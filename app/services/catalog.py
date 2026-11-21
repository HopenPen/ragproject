import copy
import re
from decimal import Decimal
from app.domain import Error, corpus_access, require_editor, precondition, uid, decimal_value, digest, TERMINAL
from app.profiles import ENTITIES, GRAPHS
from app.schemas.graphs import Evidence, Bibliography, Scope
from app.services.validation import enforce_graph, structural, comparison_key, source_checks


def paginate(items, page=1, page_size=50):
    return {'items': items[(page-1)*page_size:page*page_size], 'total': len(items), 'page': page, 'page_size': page_size}


def document(repo, id, actor, write=False):
    obj = repo.get('documents', id)
    if not obj:
        raise Error(404, 'not_found', 'Document not found')
    corpus_access(repo.get('corpora', obj['corpus_id'], lock=write), actor, write)
    return obj


def publication(repo, id, actor, write=False):
    obj = repo.get('publications', id)
    if not obj:
        raise Error(404, 'not_found', 'Publication not found')
    corpus_access(repo.get('corpora', obj['corpus_id'], lock=write), actor, write)
    return repo.get('publications', id, lock=write)


def selected_revision(repo, pub, profile=None, revision=None):
    if profile is None:
        if len(pub['current']) != 1:
            raise Error(422, 'profile_required', 'Specify a domain profile')
        profile = next(iter(pub['current']))
    if profile not in GRAPHS:
        raise Error(422, 'unknown_profile', 'Unknown profile')
    rid = revision or pub['current'].get(profile)
    if not revision and not rid and pub['current']:
        raise Error(409, 'profile_not_active', 'Requested profile has no active graph')
    rev = repo.get('publication_revisions', rid) if rid else None
    if not rev or rev['publication_id'] != pub['id']:
        raise Error(404, 'not_found', 'Revision not found')
    if rev['profile'] != profile:
        raise Error(409, 'profile_mismatch', 'Revision belongs to a different profile')
    return rev


def touch(repo, corpus_id):
    corpus = repo.get('corpora', corpus_id, lock=True)
    repo.update('corpora', corpus_id, revision=corpus['revision'] + 1)


def audit(repo, pub, actor, action, reason, details=None):
    repo.add('audit_entries', corpus_id=pub['corpus_id'], publication_id=pub.get('id'),
             document_id=pub.get('document_id'), author_id=actor['id'] if actor else None,
             action=action, reason=reason, details=details or {})


def save_revision(repo, pub, graph, actor, reason, origin='manual', run_id=None, activate=True):
    doc = repo.get('documents', pub['document_id'])
    graph = enforce_graph(graph, doc['page_count'])
    source_errors = [i for i in source_checks(graph, repo.find('pages', document_id=doc['id']), repo.find('artifacts', document_id=doc['id'])) if i['severity'] == 'error']
    if source_errors:
        raise Error(422, 'invalid_source', 'Invalid source reference', source_errors)
    profile = graph['domain_profile']
    previous = repo.find('publication_revisions', publication_id=pub['id'], profile=profile)
    if run_id:
        existing = [r for r in previous if r['run_id'] == run_id]
        if existing:
            return existing[0]
    revision = repo.add('publication_revisions', publication_id=pub['id'], profile=profile,
                         number=max([r['number'] for r in previous], default=0)+1, graph=graph,
                         origin=origin, run_id=run_id, author_id=actor['id'] if actor else None, reason=reason)
    if activate:
        repo.update('publications', pub['id'], current={**pub['current'], profile: revision['id']})
        synchronize_scope(repo, pub, graph, actor, reason) if origin == 'manual' else None
    audit(repo, pub, actor, 'revision_created' if activate else 'candidate_created', reason, {'revision_id': revision['id'], 'domain_profile': profile})
    touch(repo, pub['corpus_id'])
    return revision


def synchronize_scope(repo, pub, graph, actor, reason):
    doc = repo.get('documents', pub['document_id'])
    cls = repo.get('classification_revisions', doc['classification_id']) if doc['classification_id'] else None
    label = graph['domain_profile'].split('-')[0]
    if cls and cls['decision'][label] != graph['scope']:
        decision = copy.deepcopy(cls['decision'])
        decision[label] = graph['scope']
        revisions = repo.find('classification_revisions', document_id=doc['id'])
        new = repo.add('classification_revisions', document_id=doc['id'], number=max(r['number'] for r in revisions)+1,
                       decision=decision, reviewed=True, author_id=actor['id'], reason=reason)
        repo.update('documents', doc['id'], classification_id=new['id'])
        audit(repo, pub, actor, 'scope_review', reason, {'classification_revision_id': new['id'], 'domain_profile': graph['domain_profile']})


class Documents:
    def __init__(self, uow, storage):
        self.uow, self.storage = uow, storage

    def corpora(self, actor):
        with self.uow() as u:
            return [self.summary(u.repo, row) for row in u.repo.find('corpora', **({} if actor['role'] == 'admin' else {'owner_id': actor['id']}))]

    @staticmethod
    def summary(repo, row):
        pubs = repo.find('publications', corpus_id=row['id'])
        active = {rid for pub in pubs for rid in pub['current'].values()}
        graphs = [repo.get('publication_revisions', rid)['graph'] for rid in active]
        return {**row, 'stats': {
            'documents': len(repo.find('documents', corpus_id=row['id'])),
            'records': sum(len(g['results']) for g in graphs),
            'issues_open': sum(i['review'] == 'open' and i['revision_id'] in active for i in repo.find('issues', corpus_id=row['id']))}}

    def corpus_details(self, actor, id):
        with self.uow() as u:
            return self.summary(u.repo, corpus_access(u.repo.get('corpora', id), actor))

    def create_corpus(self, actor, values):
        require_editor(actor)
        with self.uow() as u:
            result = u.repo.add('corpora', owner_id=actor['id'], **values)
            u.commit()
            return result

    def patch_corpus(self, actor, id, values):
        with self.uow() as u:
            corpus = corpus_access(u.repo.get('corpora', id, lock=True), actor, True)
            if 'split' in values and values['split'] != corpus['split'] and u.repo.find('documents', corpus_id=id):
                raise Error(409, 'split_immutable', 'Split cannot change after upload')
            if values.get('archived'):
                from app.services.pipeline import aggregate
                for job in u.repo.find('jobs',corpus_id=id):
                    job=u.repo.get('jobs',job['id'],lock=True)
                    if job['status'] in TERMINAL:
                        continue
                    u.repo.update('jobs',job['id'],status='cancel_requested')
                    for item in u.repo.find('job_items',job_id=job['id']):
                        if item['status'] in ('queued','waiting_review','paused'):
                            u.repo.update('job_items',item['id'],status='cancelled')
                    aggregate(u.repo,job['id'])
            result = u.repo.update('corpora', id, **values, revision=corpus['revision']+1)
            u.commit()
            return result

    def upload(self, actor, corpus_id, code, filename, data):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', code):
            raise Error(422, 'invalid_code', 'Use an explicit safe publication code/alias')
        with self.uow() as u:
            corpus_access(u.repo.get('corpora', corpus_id, lock=True), actor, True)
            info = self.storage.inspect_pdf(data)
            existing = u.repo.find('documents', corpus_id=corpus_id, publication_code=code)
            if existing:
                if existing[0]['sha256'] == info['sha256']:
                    return existing[0], False
                raise Error(409, 'code_hash_conflict', 'This publication code has a different PDF; use an explicit alias')
            id = uid()
            key = f'corpora/{corpus_id}/documents/{id}/original.pdf'
            self.storage.put(key, data, 'application/pdf')
            result = u.repo.add('documents', id=id, corpus_id=corpus_id, publication_code=code,
                                original_filename=filename, display_name=filename, sha256=info['sha256'],
                                storage_key=key, byte_size=len(data), page_count=info['page_count'])
            for p in info['pages']:
                u.repo.add('pages', document_id=id, **p)
            u.repo.add('publications', corpus_id=corpus_id, document_id=id)
            touch(u.repo, corpus_id)
            u.commit()
            return result, True


class Catalog:
    def __init__(self, uow, cache=None):
        self.uow, self.cache = uow, cache

    def get(self, actor, table, id, write=False):
        with self.uow() as u:
            return self.authorize(u.repo, actor, table, id, write)

    def authorize(self, repo, actor, table, id, write=False):
        if table == 'corpora':
            return corpus_access(repo.get(table, id, lock=write), actor, write)
        if table == 'documents':
            return document(repo, id, actor, write)
        if table == 'publications':
            return publication(repo, id, actor, write)
        obj = repo.get(table, id)
        if not obj:
            raise Error(404, 'not_found', 'Object not found')
        if 'corpus_id' in obj:
            corpus_access(repo.get('corpora', obj['corpus_id'], lock=write), actor, write)
        elif 'document_id' in obj:
            document(repo, obj['document_id'], actor, write)
        elif 'publication_id' in obj:
            publication(repo, obj['publication_id'], actor, write)
        elif table == 'job_items':
            self.authorize(repo, actor, 'jobs', obj['job_id'], write)
        else:
            raise Error(422, 'invalid_resource', 'Unsupported resource')
        return obj

    def related(self, actor, parent_table, id, table, **filters):
        with self.uow() as u:
            self.authorize(u.repo, actor, parent_table, id)
            parent_key = {'corpora': 'corpus_id', 'documents': 'document_id', 'publications': 'publication_id', 'jobs': 'job_id'}[parent_table]
            return u.repo.find(table, **{parent_key: id}, **{k:v for k,v in filters.items() if v is not None})

    def patch_document(self, actor, id, values):
        with self.uow() as u:
            doc = document(u.repo, id, actor, True)
            result = u.repo.update('documents', id, **values)
            touch(u.repo, doc['corpus_id'])
            u.commit()
            return result

    def job_details(self, actor, id):
        with self.uow() as u:
            job = self.authorize(u.repo, actor, 'jobs', id)
            items = u.repo.find('job_items', job_id=id)
            outbox = [u.repo.find('outbox', item_id=i['id'])[0] for i in items]
            return {**job, 'dispatch_pending': any(not o['dispatched'] for o in outbox),
                    'counters': {state: sum(i['status'] == state for i in items) for state in {i['status'] for i in items}},
                    'coverage': {i['document_id'] or 'snapshot': i['progress'].get('coverage') for i in items}}

    def search(self, actor, corpus_id, q, scope, profile):
        with self.uow() as u:
            corpus = corpus_access(u.repo.get('corpora', corpus_id), actor)
            key = f'search:{corpus_id}:{corpus["revision"]}:'+digest([q,scope,profile])
            cached = self.cache.get(key) if self.cache else None
            if cached is not None:
                return cached
            result = u.repo.search(corpus_id, q, scope)
            if profile:
                ids = set()
                for doc in u.repo.find('documents', corpus_id=corpus_id):
                    cls = u.repo.get('classification_revisions',doc['classification_id']) if doc['classification_id'] else None
                    if cls and profile.split('-')[0] in cls['decision']['labels']:
                        ids.add(doc['id'])
                result = [r for r in result if r['document_id'] in ids]
            if self.cache:
                self.cache.put(key, result)
            return result

    def review_items(self, actor, corpus_id):
        with self.uow() as u:
            corpus_access(u.repo.get('corpora', corpus_id), actor)
            items = []
            for doc in u.repo.find('documents', corpus_id=corpus_id):
                cls = u.repo.get('classification_revisions', doc['classification_id']) if doc['classification_id'] else None
                if not cls or cls['decision']['outcome'] in ('needs_review', 'unreadable'):
                    items.append({'kind': 'classification', 'document_id': doc['id'], 'revision_id': cls['id'] if cls else None})
                elif any(cls['decision'][label]['in_scope'] is None for label in cls['decision']['labels']):
                    items.append({'kind': 'scope', 'document_id': doc['id'], 'revision_id': cls['id']})
            for pub in u.repo.find('publications', corpus_id=corpus_id):
                for rev in u.repo.find('publication_revisions', publication_id=pub['id']):
                    if rev['id'] not in pub['current'].values() and rev['origin'] == 'machine':
                        items.append({'kind': 'candidate', 'publication_id': pub['id'], 'revision_id': rev['id'], 'profile': rev['profile']})
                    if rev['id'] in pub['current'].values():
                        items += [{'kind': 'source', 'publication_id': pub['id'], 'revision_id': rev['id'], 'evidence_id': e['evidence_id']} for e in rev['graph']['evidence'] if e['review'] in ('open', 'needs_review')]
            items += [{'kind': 'issue', 'issue_id': i['id'], 'profile': i['profile']} for i in u.repo.find('issues', corpus_id=corpus_id, review='open')]
            return items

    def read(self, actor, id, profile=None, revision=None):
        with self.uow() as u:
            pub = publication(u.repo, id, actor)
            rev = selected_revision(u.repo, pub, profile, revision)
            return {'publication_id': id, 'domain_profile': rev['profile'], 'revision_id': rev['id'], 'revision_number': rev['number'], 'graph': rev['graph']}

    def create(self, actor, corpus_id, document_id, graph, reason):
        with self.uow() as u:
            doc = document(u.repo, document_id, actor, True)
            if doc['corpus_id'] != corpus_id:
                raise Error(404, 'not_found', 'Document not found')
            classification = u.repo.get('classification_revisions', doc['classification_id']) if doc['classification_id'] else None
            label = graph.get('domain_profile', '').split('-')[0]
            if not classification or classification['decision']['outcome'] not in ('resolved', 'outside') or label not in classification['decision']['labels']:
                raise Error(409, 'classification_required', 'Accepted matching classification is required')
            pub = u.repo.find('publications', document_id=document_id)[0]
            if graph['domain_profile'] in pub['current']:
                raise Error(409, 'profile_exists', 'Use graph replacement with If-Match')
            rev = save_revision(u.repo, pub, graph, actor, reason)
            u.commit()
            return {'publication_id': pub['id'], 'domain_profile': rev['profile'], 'revision_id': rev['id'], 'revision_number': rev['number'], 'graph': rev['graph']}

    def mutate(self, actor, id, profile, expected, reason, transform):
        with self.uow() as u:
            pub = publication(u.repo, id, actor, True)
            rev = selected_revision(u.repo, pub, profile)
            precondition(expected, rev['id'])
            graph = copy.deepcopy(rev['graph'])
            result = transform(graph)
            graph = graph if result is None else result
            if graph.get('domain_profile') != rev['profile']:
                raise Error(409, 'profile_mismatch', 'Graph profile cannot change')
            new = save_revision(u.repo, pub, graph, actor, reason)
            u.commit()
            return {'publication_id': id, 'domain_profile': new['profile'], 'revision_id': new['id'], 'revision_number': new['number'], 'graph': new['graph']}

    def entity(self, actor, id, entity_type, entity_id=None, operation='read', record=None, expected=None, reason=None):
        if entity_type not in ENTITIES:
            raise Error(422, 'unknown_entity_type', 'Unknown entity type')
        profile, collection, key, model = ENTITIES[entity_type]
        if operation == 'read':
            result = self.read(actor, id, profile)
            rows = result['graph'][collection]
            if entity_id:
                row = next((r for r in rows if r[key] == entity_id), None)
                if row is None:
                    raise Error(404, 'not_found', 'Entity not found')
                return {**{k:v for k,v in result.items() if k != 'graph'}, 'record': row}
            return {**{k:v for k,v in result.items() if k != 'graph'}, 'items': rows}
        def change(graph):
            rows = graph[collection]
            found = next((r for r in rows if r[key] == entity_id), None)
            if operation == 'create':
                rows.append(model.model_validate(record).model_dump(mode='json'))
            else:
                if found is None:
                    raise Error(404, 'not_found', 'Entity not found')
                if operation == 'delete':
                    rows.remove(found)
                else:
                    if key in record and record[key] != entity_id:
                        raise Error(422, 'immutable_id', 'Entity id cannot change')
                    rows[rows.index(found)] = model.model_validate({**found, **record}).model_dump(mode='json')
        return self.mutate(actor, id, profile, expected, reason, change)

    def activate(self, actor, id, revision_id, profile, expected, reason):
        with self.uow() as u:
            pub = publication(u.repo, id, actor, True)
            target = selected_revision(u.repo, pub, profile, revision_id)
            precondition(expected, pub['current'].get(target['profile'], 'none'))
            doc = u.repo.get('documents', pub['document_id'])
            enforce_graph(target['graph'], doc['page_count'])
            u.repo.update('publications', id, current={**pub['current'], target['profile']: target['id']})
            synchronize_scope(u.repo, pub, target['graph'], actor, reason)
            audit(u.repo, pub, actor, 'revision_activated', reason, {'revision_id': target['id']})
            touch(u.repo, pub['corpus_id'])
            u.commit()
            return {'domain_profile': target['profile'], 'revision_id': target['id']}

    def results(self, actor, corpus_id, profile=None, **filters):
        with self.uow() as u:
            corpus = corpus_access(u.repo.get('corpora', corpus_id), actor)
            cache_key = f'results:{corpus_id}:{corpus["revision"]}:'+digest([profile,filters])
            cached = self.cache.get(cache_key) if self.cache else None
            if cached is not None:
                return cached
            rows = []
            for pub in u.repo.find('publications', corpus_id=corpus_id):
                for p, rid in pub['current'].items():
                    if profile and profile != p:
                        continue
                    rev = u.repo.get('publication_revisions', rid)
                    graph = rev['graph']
                    flagged = {record_id for i in u.repo.find('issues', revision_id=rid) for record_id in i['details'].get('record_ids',[])}
                    for record in graph['results']:
                        context = {}
                        if p == 'solar-v1':
                            device = next((d for d in graph['devices'] if d['device_id']==record['device_id']),{})
                            material = next((m for m in graph['materials'] if m['material_id']==(record['material_id'] or device.get('absorber_material_id'))),{})
                            measurement = next((m for m in graph['measurements'] if m['measurement_id']==record['measurement_id']),{})
                            for entity,fields in ((device,('device_type','architecture','active_area','area_definition')),
                                                  (material,('material_class','formula_normalized')),
                                                  (measurement,('scan_direction','certified','spectrum'))):
                                context.update({field:entity.get(field) for field in fields})
                        else:
                            for collection,key,fields in (
                                ('configurations','config_id',('rag_variant','retrieval_method','embedding_model','generator_model','top_k')),
                                ('datasets','dataset_id',('dataset_name','dataset_version','data_split','language')),
                                ('tasks','task_id',('task_type',))):
                                entity = next((e for e in graph[collection] if e[key]==record[key]),{})
                                context.update({field:entity.get(field) for field in fields})
                        rows.append({**context, **record, 'publication_id': pub['id'], 'domain_profile': p, 'revision_id': rid,
                                     'year': graph['bibliography']['year'],
                                     'has_issues': record['result_id'] in flagged})
            for key, value in filters.items():
                if value is None:
                    continue
                if key in ('value_min', 'value_max'):
                    op = (lambda x: x >= Decimal(str(value))) if key == 'value_min' else (lambda x: x <= Decimal(str(value)))
                    rows = [r for r in rows if r['normalized_value'] is not None and op(Decimal(r['normalized_value']))]
                else:
                    rows = [r for r in rows if r.get(key) == value]
            result = sorted(rows, key=lambda r: (r['publication_id'], r['domain_profile'], r['result_id']))
            if self.cache:
                self.cache.put(cache_key,result)
            return result

    def comparisons(self, actor, corpus_id, profile, refs, area_tolerance=None):
        with self.uow() as u:
            corpus_access(u.repo.get('corpora', corpus_id), actor)
            groups, excluded = {}, []
            tolerance = decimal_value(area_tolerance) if area_tolerance is not None else None
            if area_tolerance is not None and (profile != 'solar-v1' or tolerance is None or tolerance < 0):
                raise Error(422, 'invalid_tolerance', 'Area tolerance must be a nonnegative explicit solar value')
            for ref in refs:
                if set(ref) != {'publication_id', 'result_id'}:
                    raise Error(422, 'invalid_reference', 'Use publication_id/result_id')
                pub = publication(u.repo, ref['publication_id'], actor)
                if pub['corpus_id'] != corpus_id:
                    raise Error(404, 'not_found', 'Publication not found')
                rev = selected_revision(u.repo, pub, profile)
                graph = rev['graph']
                r = next((r for r in graph['results'] if r['result_id'] == ref['result_id']), None)
                if r is None:
                    raise Error(404, 'not_found', 'Result not found')
                key = comparison_key(graph, r)
                required = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15) if profile == 'solar-v1' else (0, 1, 2, 3, 4, 5, 6, 8)
                reasons = [f'Unknown comparability field {i}' for i in required if key[i] is None]
                if profile == 'solar-v1' and (key[2] != 'AM1.5G' or decimal_value(key[3]) != Decimal(100) or key[4] != 'mW/cm2'):
                    reasons.append('Illumination is not explicitly AM1.5G / 100 mW/cm2')
                if r['result_origin'] != 'primary':
                    reasons.append('Cited results are not comparable to local experiments')
                if reasons:
                    excluded.append({'ref': ref, 'status': 'needs_review', 'reasons': reasons})
                else:
                    group_key = key
                    if tolerance is not None:
                        for existing in groups:
                            if key[:5]+key[6:] == existing[:5]+existing[6:] and abs(Decimal(key[5])-Decimal(existing[5])) <= tolerance:
                                group_key = existing
                                break
                    groups.setdefault(group_key, []).append(ref)
            return {'domain_profile': profile, 'groups': [{'conditions': list(k), 'results': v} for k,v in groups.items()], 'excluded': excluded,
                    'area_policy': 'exact' if tolerance is None else {'project_defined_absolute_cm2_tolerance': str(tolerance)}}

    def review_issue(self, actor, id, review, reason, expected):
        with self.uow() as u:
            obj = u.repo.get('issues', id)
            if not obj:
                raise Error(404, 'not_found', 'Issue not found')
            pub = publication(u.repo, obj['publication_id'], actor, True)
            obj = u.repo.get('issues', id, lock=True)
            precondition(expected, obj['details'].get('review_revision', obj['id']))
            if review not in ('confirmed', 'dismissed', 'open'):
                raise Error(422, 'invalid_review', 'Invalid issue review')
            result = u.repo.update('issues', id, review=review, details={**obj['details'], 'review_revision': uid()})
            audit(u.repo, pub, actor, 'issue_review', reason, {'issue_id': id, 'review': review})
            touch(u.repo, pub['corpus_id'])
            u.commit()
            return result
