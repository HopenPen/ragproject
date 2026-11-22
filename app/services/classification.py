import copy
from pydantic import ValidationError
from app.domain import Error
from app.schemas.graphs import Classification


def machine_classification(value):
    """Topic and experimental scope are independent. Manual inputs stay strict."""
    value = copy.deepcopy(value)
    if value.get('outcome') == 'outside' and value.get('labels'):
        value['outcome'] = 'needs_review'
    try:
        return Classification.model_validate(value).model_dump(mode='json')
    except ValidationError as exc:
        raise Error(422, 'invalid_classification', 'Invalid model classification',
                    exc.errors(include_context=False, include_input=False)) from exc


def automatic_decision(value, threshold):
    decision = copy.deepcopy(value)
    if decision['outcome'] == 'unreadable':
        return decision
    labels = decision['labels']
    scopes_resolved = all(decision[label]['in_scope'] is not None for label in (labels or ['solar', 'rag']))
    if decision['confidence'] >= threshold and scopes_resolved:
        decision['outcome'] = 'resolved' if labels else 'outside'
    else:
        decision['outcome'] = 'needs_review'
    return decision


def reconsider_pending(uow, threshold):
    """Accept saved model decisions under the current policy without another provider call."""
    from app.domain import uid
    from app.services.pipeline import aggregate
    with uow() as u:
        document_ids = [doc['id'] for doc in u.repo.find('documents') if doc['classification_id']]
    counts = {'accepted': 0, 'resumed_items': 0, 'paused_items': 0}
    for document_id in document_ids:
        with uow() as u:
            doc = u.repo.get('documents', document_id)
            if not doc:
                continue
            corpus = u.repo.get('corpora', doc['corpus_id'], lock=True)
            if not corpus or corpus['archived']:
                continue
            doc = u.repo.get('documents', document_id)
            current = u.repo.get('classification_revisions', doc['classification_id'])
            if not current or current['reviewed'] or current['decision']['outcome'] != 'needs_review':
                continue
            decision = automatic_decision(current['decision'], threshold)
            if decision['outcome'] not in ('resolved', 'outside'):
                continue
            pending = []
            items = u.repo.find('job_items', document_id=document_id, status=['waiting_review', 'paused'])
            for job_id in sorted({item['job_id'] for item in items}):
                job = u.repo.get('jobs', job_id, lock=True)
                if job['status'] not in ('queued', 'running', 'waiting_review', 'pause_requested', 'paused'):
                    continue
                for item in (item for item in items if item['job_id'] == job_id):
                    item = u.repo.get('job_items', item['id'], lock=True)
                    if item['status'] == 'waiting_review' or (item['status'] == 'paused' and item['progress'].get('_resume_status') == 'waiting_review'):
                        pending.append(item)
            previous = u.repo.find('classification_revisions', document_id=document_id)
            revision = u.repo.add('classification_revisions', document_id=document_id,
                number=max(r['number'] for r in previous)+1, decision=decision, reviewed=False, reason='',
                provenance={**current['provenance'], 'supersedes_revision_id': current['id'],
                            'acceptance_policy': 'confidence-threshold-v1', 'confidence_threshold': threshold})
            u.repo.update('documents', document_id, classification_id=revision['id'])
            for item in pending:
                progress = {**item['progress'], 'classification_revision_id': revision['id'], '_resuming': item['attempts'] > 0}
                if item['status'] == 'paused':
                    progress['_resume_status'] = 'queued'
                    u.repo.update('job_items', item['id'], stage='extract', progress=progress)
                    counts['paused_items'] += 1
                else:
                    u.repo.update('job_items', item['id'], status='queued', stage='extract', progress=progress,
                                  lease_token=None, lease_until=None, error=None)
                    out = u.repo.find('outbox', item_id=item['id'])[0]
                    u.repo.update('outbox', out['id'], dispatched=False, lease_until=None, task_id=uid(), last_error=None)
                    counts['resumed_items'] += 1
            for job_id in {item['job_id'] for item in pending}:
                aggregate(u.repo, job_id)
            u.repo.add('audit_entries', corpus_id=corpus['id'], document_id=document_id,
                       action='classification_auto_accepted', reason='',
                       details={'revision_id': revision['id'], 'previous_revision_id': current['id'], 'confidence_threshold': threshold})
            u.repo.update('corpora', corpus['id'], revision=corpus['revision']+1)
            u.commit()
            counts['accepted'] += 1
    return counts
