import copy
import hashlib
import json
from datetime import timedelta, timezone
from app.domain import (Error, ExternalConfiguration, TransientError, TERMINAL, PROFILES, now, uid, digest,
                        corpus_access, precondition, PIPELINE_VERSION, PROMPT_VERSION, RULES_VERSION, quote_normalize, UNITS, normalize_value)
from app.profiles import GRAPHS
from app.schemas.graphs import Classification
from app.services.catalog import document, publication, save_revision, touch
from app.services.validation import typed_graph, structural, source_checks, validate


def aggregate(repo, job_id):
    job = repo.get('jobs', job_id, lock=True)
    items = repo.find('job_items', job_id=job_id)
    states = [i['status'] for i in items]
    if job['status'] == 'cancel_requested':
        status = 'cancelled' if all(s in TERMINAL for s in states) else 'cancel_requested'
    elif 'running' in states:
        status = 'running'
    elif 'waiting_review' in states:
        status = 'waiting_review'
    elif 'queued' in states:
        status = 'queued'
    elif all(s == 'succeeded' for s in states):
        status = 'succeeded'
    elif 'succeeded' in states:
        status = 'partially_succeeded'
    elif 'blocked_external_configuration' in states:
        status = 'blocked_external_configuration'
    elif all(s == 'cancelled' for s in states):
        status = 'cancelled'
    else:
        status = 'failed'
    repo.update('jobs', job_id, status=status)
    return status


def snapshot(repo, docs, profiles, strict):
    entries, omissions = [], []
    for doc in docs:
        cls = repo.get('classification_revisions', doc['classification_id']) if doc['classification_id'] else None
        accepted = cls and cls['decision']['outcome'] in ('resolved', 'outside') and all(cls['decision'][label]['in_scope'] is not None for label in cls['decision']['labels'])
        if not accepted:
            omissions.append({'document_id': doc['id'], 'reason': 'classification_not_accepted'})
        pub = repo.find('publications', document_id=doc['id'])[0]
        graphs = {}
        for p in profiles:
            label = p.split('-')[0]
            expected = cls['decision'][label]['in_scope'] if cls else None
            rid = pub['current'].get(p)
            rev = repo.get('publication_revisions', rid) if rid else None
            if rev:
                graphs[p] = rev
                errors = structural(rev['graph'], doc['page_count'])
                if errors:
                    omissions.append({'document_id': doc['id'], 'profile': p, 'reason': 'structural_errors', 'errors': errors})
                if accepted and expected is not None and rev['graph']['scope']['in_scope'] != expected:
                    omissions.append({'document_id': doc['id'], 'profile': p, 'reason': 'classification_graph_scope_mismatch'})
            if expected is True and (not rev or rev['graph']['scope']['in_scope'] is not True):
                omissions.append({'document_id': doc['id'], 'profile': p, 'reason': 'missing_active_in_scope_graph'})
        entries.append({'document': doc, 'publication_id': pub['id'], 'classification': cls, 'graphs': graphs,
                        'pages': repo.find('pages', document_id=doc['id']), 'artifacts': repo.find('artifacts', document_id=doc['id'])})
    if strict and omissions:
        raise Error(409, 'incomplete_snapshot', 'Strict export requires accepted classifications and valid active graphs', omissions)
    # JSON round-trip detaches mutable ORM/DTO values and fixes UTC values at enqueue.
    return json.loads(json.dumps({'entries': entries, 'omissions': omissions, 'created_at': now().isoformat()}, default=str))


class Jobs:
    def __init__(self, uow):
        self.uow = uow

    def enqueue(self, actor, corpus_id, payload, key=None, parent=None):
        key = key or uid()
        if len(key) > 200:
            raise Error(422, 'invalid_idempotency_key', 'Idempotency-Key exceeds 200 characters')
        with self.uow() as u:
            corpus_access(u.repo.get('corpora', corpus_id, lock=True), actor, True)
            existing = u.repo.find('jobs', corpus_id=corpus_id, idempotency_key=key)
            hashed = digest(payload)
            if existing:
                if existing[0]['payload_hash'] != hashed:
                    raise Error(409, 'idempotency_conflict', 'Idempotency-Key was used for another payload')
                return existing[0]
            docs = u.repo.find('documents', corpus_id=corpus_id)
            if not payload.get('all_documents'):
                ids = set(payload['document_ids'])
                docs = [d for d in docs if d['id'] in ids]
                if {d['id'] for d in docs} != ids:
                    raise Error(404, 'not_found', 'Document not found')
            if not docs:
                raise Error(422, 'empty_job', 'No documents selected')
            job_input = {**payload, 'selected_document_ids': [d['id'] for d in docs]}
            if payload['kind'] in ('validate', 'export'):
                job_input['snapshot'] = snapshot(u.repo, docs, payload.get('target_profiles') or list(PROFILES),
                    strict=payload['kind'] == 'export' and not payload.get('allow_incomplete', False))
            job = u.repo.add('jobs', corpus_id=corpus_id, author_id=actor['id'], kind=payload['kind'],
                             idempotency_key=key, payload_hash=hashed, input=job_input, parent_id=parent)
            for doc in docs if payload['kind'] in ('process', 'classify') else [None]:
                item = u.repo.add('job_items', job_id=job['id'], document_id=doc['id'] if doc else None)
                u.repo.add('outbox', item_id=item['id'], task_id=uid())
            u.commit()
            return job

    def cancel(self, actor, job_id):
        with self.uow() as u:
            job = u.repo.get('jobs', job_id)
            if not job:
                raise Error(404, 'not_found', 'Job not found')
            corpus_access(u.repo.get('corpora', job['corpus_id'], lock=True), actor, True)
            job = u.repo.get('jobs', job_id, lock=True)
            if job['status'] in TERMINAL:
                return job
            u.repo.update('jobs', job_id, status='cancel_requested')
            for item in u.repo.find('job_items', job_id=job_id):
                if item['status'] in ('queued', 'waiting_review'):
                    u.repo.update('job_items', item['id'], status='cancelled')
            aggregate(u.repo, job_id)
            u.commit()
            return u.repo.get('jobs', job_id)

    def retry(self, actor, job_id, key=None):
        with self.uow() as u:
            job = u.repo.get('jobs', job_id)
            if not job:
                raise Error(404, 'not_found', 'Job not found')
            corpus_access(u.repo.get('corpora', job['corpus_id']), actor, True)
            if job['status'] not in TERMINAL:
                raise Error(409, 'job_not_terminal', 'Only a terminal job can be retried')
            failed = [i['document_id'] for i in u.repo.find('job_items', job_id=job_id) if i['status'] != 'succeeded']
            if not failed:
                raise Error(409, 'nothing_to_retry', 'No failed/cancelled items')
            payload = {k:v for k,v in job['input'].items() if k not in ('snapshot', 'selected_document_ids')}
            if job['kind'] in ('process', 'classify'):
                payload.update(document_ids=failed, all_documents=False)
        return self.enqueue(actor, job['corpus_id'], payload, key, parent=job_id)

    def review(self, actor, doc_id, expected, decision, reason, replace_reviewed):
        decision = copy.deepcopy(decision)
        for label in ('solar', 'rag'):
            if decision[label]['in_scope'] is False and not decision[label]['exclusion_reason']:
                decision[label]['exclusion_reason'] = reason
        with self.uow() as u:
            doc = document(u.repo, doc_id, actor, True)
            precondition(expected, doc['classification_id'] or 'none')
            current = u.repo.get('classification_revisions', doc['classification_id']) if doc['classification_id'] else None
            if current and current['reviewed'] and not replace_reviewed:
                raise Error(409, 'reviewed_classification', 'Explicit replace_reviewed is required')
            if decision['outcome'] not in ('resolved', 'outside'):
                raise Error(422, 'unresolved_review', 'Review must resolve classification')
            if decision['labels'] and any(decision[label]['in_scope'] is None for label in decision['labels']):
                raise Error(422, 'scope_required', 'Review must resolve profile scope')
            if any(e['source_page'] > doc['page_count'] for e in decision['evidence']):
                raise Error(422, 'invalid_page', 'Evidence page out of range')
            invalid_sources = [i for i in source_checks({'evidence':decision['evidence'], 'results':[]},
                u.repo.find('pages', document_id=doc_id), u.repo.find('artifacts', document_id=doc_id)) if i['severity']=='error']
            if invalid_sources:
                raise Error(422, 'invalid_source', 'Invalid classification source', invalid_sources)
            revs = u.repo.find('classification_revisions', document_id=doc_id)
            cls = u.repo.add('classification_revisions', document_id=doc_id, number=max([r['number'] for r in revs], default=0)+1,
                             decision=decision, reviewed=True, author_id=actor['id'], reason=reason)
            u.repo.update('documents', doc_id, classification_id=cls['id'])
            pub = u.repo.find('publications', document_id=doc_id)[0]
            # Reviewed scope changes create new graphs, leaving prior revisions intact.
            for p, rid in pub['current'].items():
                label = p.split('-')[0]
                if label not in decision['labels'] or decision[label]['in_scope'] is False:
                    empty = GRAPHS[p](domain_profile=p, bibliography=decision['bibliography'],
                                      scope={'in_scope': False, 'exclusion_reason': decision[label]['exclusion_reason'] or reason}).model_dump(mode='json')
                    save_revision(u.repo, pub, empty, actor, reason)
                    pub = u.repo.get('publications', pub['id'])
            u.repo.add('audit_entries', corpus_id=doc['corpus_id'], document_id=doc_id, publication_id=pub['id'],
                       author_id=actor['id'], action='classification_review', reason=reason, details={'revision_id': cls['id']})
            for item in u.repo.find('job_items', document_id=doc_id, status='waiting_review'):
                job = u.repo.get('jobs', item['job_id'])
                if job['status'] == 'cancel_requested':
                    continue
                u.repo.update('job_items', item['id'], status='queued', stage='extract')
                out = u.repo.find('outbox', item_id=item['id'])[0]
                u.repo.update('outbox', out['id'], dispatched=False, lease_until=None, task_id=uid())
                aggregate(u.repo, job['id'])
            touch(u.repo, doc['corpus_id'])
            u.commit()
            return cls


class Cancelled(Exception):
    pass


def normalize_results(graph):
    for result in graph['results']:
        target = (UNITS.get(result['metric_name']) if graph['domain_profile']=='solar-v1' else None) or result['normalized_unit'] or result['raw_unit']
        value = normalize_value(result['raw_value'], result['raw_unit'], target)
        result.update(normalized_value=str(value) if value is not None else None, normalized_unit=target if value is not None else None,
                      metric_value=str(value) if value is not None else None, metric_unit=target if value is not None else None)
    return graph


def machine_evidence(value):
    for source in value['evidence']:
        if source['method']=='manual':
            raise Error(422,'invalid_candidate','Model output cannot claim a manual source')
        if source['review'] not in ('open','needs_review'):
            source['review']='open'
        source['review_reason']=None
    return value


class Runner:
    def __init__(self, uow, storage, model, config):
        self.uow, self.storage, self.model, self.config = uow, storage, model, config

    def load(self, item_id):
        with self.uow() as u:
            item = u.repo.get('job_items', item_id)
            job = u.repo.get('jobs', item['job_id'])
            return item, job

    def checkpoint(self, item_id, token, progress, stage, check_cancel=True):
        with self.uow() as u:
            item = u.repo.get('job_items', item_id, lock=True)
            if item['lease_token'] != token:
                raise Cancelled()
            job = u.repo.get('jobs', item['job_id'])
            u.repo.update('job_items', item_id, progress=copy.deepcopy(progress), stage=stage,
                          lease_until=now()+timedelta(seconds=max(self.config.lease_seconds, (self.config.model_timeout+15)*(self.config.max_retries+1))))
            u.commit()
            if check_cancel and job['status'] == 'cancel_requested':
                raise Cancelled()

    def model_call(self, item_id, token, progress, key, purpose, schema, pages, context):
        outputs = progress.setdefault('outputs', {})
        if key in outputs:
            return outputs[key]['output']
        if len(outputs) >= self.config.model_max_calls:
            raise Error(422, 'model_budget_exceeded', 'Model call budget exhausted; coverage is partial')
        self.checkpoint(item_id, token, progress, purpose)
        result = self.model.call(purpose, schema, pages, context)
        outputs[key] = result
        progress['usage'] = {field:sum(out.get('usage',{}).get(field,0) for out in outputs.values())
                             for field in ('input_tokens','output_tokens','total_tokens')}
        progress.update(model=result['model'], pipeline_version=PIPELINE_VERSION, prompt_version=PROMPT_VERSION,
                        schema_version='1.0.0', rules_version=RULES_VERSION)
        self.checkpoint(item_id, token, progress, purpose, check_cancel=False)
        # Raw output is persisted before observing cancellation after a provider call.
        self.checkpoint(item_id, token, progress, purpose)
        return result['output']

    def process(self, item, job, token):
        doc_id = item['document_id']
        progress = copy.deepcopy(item['progress'])
        with self.uow() as u:
            doc = u.repo.get('documents', doc_id)
        data = self.storage.get(doc['storage_key'])
        if hashlib.sha256(data).hexdigest() != doc['sha256']:
            raise Error(422, 'source_hash_mismatch', 'Stored PDF differs from the uploaded original')
        manifest = progress.setdefault('pages', {})
        for number in range(1, doc['page_count']+1):
            self.checkpoint(item['id'], token, progress, 'prepare')
            with self.uow() as u:
                p = u.repo.find('pages', document_id=doc_id, number=number)[0]
            if p['coverage'] == 'complete':
                manifest[str(number)] = {'status': 'complete', 'engine': p['engine'], 'reused': True}
                continue
            prepared = self.storage.prepare_page(data, number)
            key = f'documents/{doc_id}/pages/{number}.png'
            self.storage.put(key, prepared['png'], 'image/png')
            artifacts = [('page', 'render', prepared['png'], 'image/png', {})]
            artifacts += [('crop', c['name'], c['data'], 'image/png', {'bbox': c['bbox']}) for c in prepared['crops']]
            artifacts.append(('table', 'tables', json.dumps(prepared['tables']).encode(), 'application/json', {}))
            if prepared['ocr']:
                artifacts.append(('ocr', 'text', prepared['text'].encode(), 'text/plain', {}))
            for kind, name, blob, content_type, details in artifacts:
                artifact_key = f'documents/{doc_id}/runs/{item["id"]}/{number}/{kind}-{name}'
                self.storage.put(artifact_key, blob, content_type)
                with self.uow() as u:
                    if not u.repo.find('artifacts', document_id=doc_id, run_id=item['id'], page=number, kind=kind, name=name):
                        u.repo.add('artifacts', document_id=doc_id, run_id=item['id'], page=number, kind=kind,
                                   name=name, storage_key=artifact_key, content_type=content_type, details=details)
                    u.commit()
            with self.uow() as u:
                u.repo.update('pages', p['id'], text=prepared['text'], blocks=prepared['blocks'], engine=prepared['engine'],
                              ocr=prepared['ocr'], coverage='complete', image_key=key, run_id=item['id'])
                u.commit()
            manifest[str(number)] = {'status': 'complete', 'engine': prepared['engine']}
        progress['coverage'] = {'prepared': len(manifest), 'total': doc['page_count'], 'complete': len(manifest) == doc['page_count']}
        self.checkpoint(item['id'], token, progress, 'classify')
        with self.uow() as u:
            pages = u.repo.find('pages', document_id=doc_id)
            artifacts = u.repo.find('artifacts', document_id=doc_id)
            doc = u.repo.get('documents', doc_id)
            cls = u.repo.get('classification_revisions', doc['classification_id']) if doc['classification_id'] else None
        # Reviewed classifications survive reprocessing and resume waiting jobs.
        preserve = cls and cls['reviewed'] and (not job['input'].get('force') or item['stage'] == 'extract')
        if not preserve:
            observations = []
            for start in range(0, len(pages), self.config.page_batch_size):
                batch = self.batch(pages[start:start+self.config.page_batch_size], artifacts)
                obs = self.model_call(item['id'], token, progress, f'classify-{start}', 'classify', Classification.model_json_schema(), batch,
                                      {'total_pages': doc['page_count'], 'batch_only': True})
                observations.append(Classification.model_validate(obs).model_dump(mode='json'))
            decision = self.model_call(item['id'], token, progress, 'classify-final', 'classify', Classification.model_json_schema(), [],
                                      {'observations': observations, 'total_pages': doc['page_count'], 'coverage': progress['coverage'], 'aggregate_all_observations': True})
            decision = machine_evidence(Classification.model_validate(decision).model_dump(mode='json'))
            verified = bool(decision['evidence']) and all(
                e['source_page'] <= doc['page_count'] and e.get('fragment') and quote_normalize(e['fragment']) and
                any(p['number'] == e['source_page'] and quote_normalize(e['fragment']) in quote_normalize(p['text']) for p in pages)
                for e in decision['evidence'])
            if decision['outcome'] in ('resolved', 'outside') and (decision['confidence'] < .85 or not verified or
                    any(decision[label]['in_scope'] is None for label in decision['labels'])):
                decision['outcome'] = 'needs_review'
            with self.uow() as u:
                u.repo.get('corpora', doc['corpus_id'], lock=True)
                existing = u.repo.find('classification_revisions', document_id=doc_id, run_id=item['id'])
                if existing:
                    cls = existing[0]
                else:
                    revisions = u.repo.find('classification_revisions', document_id=doc_id)
                    cls = u.repo.add('classification_revisions', document_id=doc_id, number=max([r['number'] for r in revisions], default=0)+1,
                                     decision=decision, reason=job['input'].get('reason') or 'Model classification', run_id=item['id'],
                                     provenance={'model':progress.get('model'), 'pipeline_version':PIPELINE_VERSION, 'prompt_version':PROMPT_VERSION,
                                                 'schema_version':'1.0.0', 'coverage':progress['coverage'],
                                                 'calls':[{k:v for k,v in out.items() if k!='output'} for name,out in progress.get('outputs',{}).items() if name.startswith('classify')]})
                current_doc = u.repo.get('documents', doc_id)
                current = u.repo.get('classification_revisions', current_doc['classification_id']) if current_doc['classification_id'] else None
                if not current or not current['reviewed'] or job['input'].get('force'):
                    u.repo.update('documents', doc_id, classification_id=cls['id'])
                    touch(u.repo, doc['corpus_id'])
                else:
                    cls = current
                u.commit()
        decision = cls['decision']
        progress['classification_revision_id'] = cls['id']
        if decision['outcome'] == 'needs_review':
            self.finish(item['id'], token, 'waiting_review', progress)
            return
        if decision['outcome'] == 'unreadable':
            raise Error(422, 'unreadable_document', 'All pages inspected but scientific content is unreadable')
        if job['kind'] == 'classify':
            self.finish(item['id'], token, 'succeeded', progress)
            return
        candidates = {}
        for profile in PROFILES:
            label = profile.split('-')[0]
            scope = decision[label] if label in decision['labels'] else {'in_scope': False, 'exclusion_reason': 'not_target_domain'}
            if scope['in_scope'] is False and not scope.get('exclusion_reason'):
                scope = {**scope, 'exclusion_reason': 'Excluded by classification'}
            graph = GRAPHS[profile](domain_profile=profile, bibliography=decision['bibliography'], scope=scope).model_dump(mode='json')
            if scope['in_scope'] is True:
                for start in range(0, len(pages), self.config.page_batch_size):
                    batch = self.batch(pages[start:start+self.config.page_batch_size], artifacts)
                    output = self.model_call(item['id'], token, progress, f'{profile}-{start}', 'extract', GRAPHS[profile].model_json_schema(), batch,
                         {'domain_profile': profile, 'total_pages': doc['page_count'], 'existing_graph': graph, 'classification': decision})
                    updated_graph = typed_graph(output)
                    # Later batches may add/refine entities but cannot silently drop earlier facts.
                    from app.profiles import ENTITIES
                    for p, collection, id_field, dto in ENTITIES.values():
                        if p == profile and not {r[id_field] for r in graph[collection]} <= {r[id_field] for r in updated_graph[collection]}:
                            raise Error(422, 'partial_model_output', 'Later extraction batch dropped earlier records')
                    graph = updated_graph
                    if graph['domain_profile'] != profile or graph['scope']['in_scope'] is not True:
                        raise Error(422, 'profile_mismatch', 'Extraction changed accepted profile/scope')
            graph = machine_evidence(normalize_results(graph))
            errors = structural(graph, doc['page_count'])
            if errors:
                raise Error(422, 'invalid_candidate', 'Extracted graph has structural errors', errors)
            progress.setdefault('profile_coverage', {})[profile] = {'pages': doc['page_count'], 'complete': True}
            candidates[profile] = graph
        # Publish both profiles in one transaction after all calls and cancellation checks.
        self.checkpoint(item['id'], token, progress, 'candidate')
        with self.uow() as u:
            u.repo.get('corpora', doc['corpus_id'], lock=True)
            latest_job = u.repo.get('jobs', job['id'], lock=True)
            latest_item = u.repo.get('job_items', item['id'], lock=True)
            latest_doc = u.repo.get('documents', doc_id)
            if latest_item['lease_token'] != token or latest_job['status'] == 'cancel_requested':
                raise Cancelled()
            if latest_doc['classification_id'] != cls['id']:
                raise Error(409, 'classification_changed', 'Classification changed during extraction; retry required')
            for profile, graph in candidates.items():
                pub = u.repo.find('publications', document_id=doc_id)[0]
                auto = profile not in pub['current'] and decision['outcome'] in ('resolved', 'outside')
                rev = save_revision(u.repo, pub, graph, None, 'Model extraction candidate', 'machine', item['id'], activate=auto)
                progress.setdefault('revisions', {})[profile] = rev['id']
                validation = validate(graph, doc['page_count'], pages, artifacts)
                progress.setdefault('validation', {})[profile] = {'structural_errors': validation['structural_errors'], 'issues': len(validation['issues'])}
                if not u.repo.find('issues', revision_id=rev['id'], run_id=job['id']):
                    for finding in validation['issues']:
                        u.repo.add('issues', corpus_id=doc['corpus_id'], publication_id=pub['id'], revision_id=rev['id'], run_id=job['id'],
                                   profile=profile, rule=finding['rule'], severity=finding['severity'], details=finding)
            # Full raw model outputs and usage stay in private object storage as well as progress.
            manifest_key = f'documents/{doc_id}/runs/{item["id"]}/manifest.json'
            self.storage.put(manifest_key, json.dumps(progress, ensure_ascii=False).encode(), 'application/json')
            if not u.repo.find('artifacts', document_id=doc_id, run_id=item['id'], kind='run_manifest', page=None, name='manifest'):
                u.repo.add('artifacts', document_id=doc_id, run_id=item['id'], kind='run_manifest', page=None, name='manifest',
                           storage_key=manifest_key, content_type='application/json',
                           details={k:progress.get(k) for k in ('model','pipeline_version','schema_version','prompt_version','coverage','profile_coverage','usage')})
            u.commit()
        self.finish(item['id'], token, 'succeeded', progress)

    def batch(self, pages, artifacts):
        return [{'number': p['number'], 'text': p['text'], 'png': self.storage.get(p['image_key']),
                 'artifacts': [{'artifact_ref': a['id'], 'kind': a['kind'], 'details': a['details']} for a in artifacts if a['page'] == p['number']]} for p in pages]

    def finish(self, id, token, status, progress=None, error=None):
        with self.uow() as u:
            original = u.repo.get('job_items', id)
            job = u.repo.get('jobs', original['job_id'], lock=True)
            item = u.repo.get('job_items', id, lock=True)
            if item['lease_token'] != token:
                return
            if job['status'] == 'cancel_requested' and status != 'failed':
                status = 'cancelled'
            u.repo.update('job_items', id, status=status, progress=progress if progress is not None else item['progress'],
                          error=error, lease_until=None, lease_token=None)
            aggregate(u.repo, item['job_id'])
            u.commit()

    def run(self, item_id):
        token = uid()
        with self.uow() as u:
            item = u.repo.get('job_items', item_id)
            if not item:
                return
            job = u.repo.get('jobs', item['job_id'], lock=True)
            item = u.repo.get('job_items', item_id, lock=True)
            if not item or item['status'] in TERMINAL or item['status'] == 'waiting_review':
                return
            if item['status'] == 'running' and item['lease_until'] and item['lease_until'].replace(tzinfo=timezone.utc) > now():
                return
            if job['status'] == 'cancel_requested':
                u.repo.update('job_items', item_id, status='cancelled')
                aggregate(u.repo, job['id'])
                u.commit()
                return
            item = u.repo.update('job_items', item_id, status='running', attempts=item['attempts']+1,
                                 lease_token=token, lease_until=now()+timedelta(seconds=self.config.lease_seconds))
            aggregate(u.repo, job['id'])
            u.commit()
        try:
            if job['kind'] in ('process', 'classify'):
                self.process(item, job, token)
            else:
                from app.services.export import Exporter
                self.checkpoint(item_id, token, item['progress'], 'snapshot')
                result = Exporter(self.storage, self.config).run(job)
                with self.uow() as u:
                    u.repo.get('corpora', job['corpus_id'], lock=True)
                    latest = u.repo.get('jobs', job['id'], lock=True)
                    current = u.repo.get('job_items', item_id, lock=True)
                    if current['lease_token'] != token or latest['status'] == 'cancel_requested':
                        raise Cancelled()
                    u.repo.update('jobs', job['id'], result=result, expires_at=now()+timedelta(days=self.config.export_retention_days))
                    for entry in result['report']['publications']:
                        for finding in entry['validation']['issues']:
                            u.repo.add('issues', corpus_id=job['corpus_id'], publication_id=entry['publication_id'],
                                       revision_id=entry['revision_id'], profile=entry['profile'], run_id=job['id'],
                                       rule=finding['rule'], severity=finding['severity'], details=finding)
                    u.commit()
                self.finish(item_id, token, 'succeeded')
        except Cancelled:
            self.finish(item_id, token, 'cancelled')
        except ExternalConfiguration as exc:
            self.finish(item_id, token, 'blocked_external_configuration', error=str(exc))
        except TransientError:
            if item['attempts'] >= self.config.max_retries+1:
                self.finish(item_id, token, 'failed', error='transient_retry_exhausted')
                raise Error(502, 'transient_retry_exhausted', 'Transient retry budget exhausted')
            self.finish(item_id, token, 'queued', error='Transient provider failure')
            # PostgreSQL schedules retries even if publishing a Celery retry would fail.
            with self.uow() as u:
                current_job = u.repo.get('jobs', job['id'], lock=True)
                current_item = u.repo.get('job_items', item_id, lock=True)
                if current_item['status'] == 'queued' and current_job['status'] != 'cancel_requested':
                    out = u.repo.find('outbox', item_id=item_id)[0]
                    u.repo.update('outbox', out['id'], dispatched=False, task_id=uid(),
                                  lease_until=now()+timedelta(seconds=min(2 ** item['attempts'], 30)))
                u.commit()
        except Exception as exc:
            code = exc.code if isinstance(exc, Error) else type(exc).__name__
            current, _ = self.load(item_id)
            progress = current['progress']
            progress['diagnostic'] = {'code':code, 'message':exc.message if isinstance(exc,Error) else type(exc).__name__,
                                      'details':exc.details if isinstance(exc,Error) else None}
            self.finish(item_id, token, 'failed', progress=progress, error=code)
            raise
