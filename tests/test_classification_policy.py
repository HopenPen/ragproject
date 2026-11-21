import copy
import pytest
from app.db import Uow
from app.schemas.requests import JobCreate
from app.services.classification import automatic_decision, reconsider_pending
from app.services.pipeline import Runner
from tests.conftest import ModelDouble
from tests.fixtures import classification, rag_graph
from tests.test_pipeline import enqueue


@pytest.mark.parametrize('confidence,outcome,expected', [
    (.8499, 'resolved', 'needs_review'), (.85, 'resolved', 'resolved'),
    (.99, 'needs_review', 'resolved'), (.99, 'unreadable', 'unreadable'),
])
def test_confidence_threshold_does_not_require_literal_quotes(confidence, outcome, expected):
    decision = classification(confidence=confidence, outcome=outcome)
    decision['evidence'][0]['fragment'] = 'A PDF control character changed the superscript minus'
    assert automatic_decision(decision, .85)['outcome'] == expected
    assert decision['outcome'] == outcome


def test_uncertain_scope_still_needs_review_and_outside_is_automatic():
    decision = classification(confidence=.99)
    decision['solar']['in_scope'] = None
    assert automatic_decision(decision, .85)['outcome'] == 'needs_review'
    decision = classification([], outcome='needs_review', confidence=.99)
    assert automatic_decision(decision, .85)['outcome'] == 'outside'


def test_high_confidence_classification_completes_with_unmatched_quote(env, corpus):
    decision = classification(confidence=.85, outcome='needs_review')
    decision['evidence'][0]['fragment'] = 'Missing literal source fragment'
    job = env.rt.jobs.enqueue(env.actors['editor'], corpus.corpus['id'], JobCreate(kind='classify', all_documents=True).model_dump())
    with Uow() as u:
        item = u.repo.find('job_items', job_id=job['id'])[0]
    Runner(Uow, env.storage, ModelDouble(decision), env.config).run(item['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'
        doc = u.repo.get('documents', corpus.doc['id'])
        assert u.repo.get('classification_revisions', doc['classification_id'])['decision']['outcome'] == 'resolved'


@pytest.mark.parametrize('paused', [False, True])
def test_pending_old_policy_reuses_classification_and_preserves_pause(env, corpus, paused):
    job, items = enqueue(env, corpus)
    model = ModelDouble(classification(['solar', 'rag'], confidence=.5))
    runner = Runner(Uow, env.storage, model, env.config)
    runner.run(items[0]['id'])
    # Reproduce an immutable legacy revision that was blocked solely by literal-source checking.
    with Uow() as u:
        doc = u.repo.get('documents', corpus.doc['id'])
        previous = u.repo.get('classification_revisions', doc['classification_id'])
        decision = copy.deepcopy(previous['decision'])
        decision['confidence'] = .99
        decision['evidence'][0]['fragment'] = 'PDF superscript mismatch'
        old = u.repo.add('classification_revisions', document_id=doc['id'], number=previous['number']+1,
                         decision=decision, reviewed=False, reason='Legacy source check')
        u.repo.update('documents', doc['id'], classification_id=old['id'])
        u.commit()
    if paused:
        env.rt.jobs.pause(env.actors['editor'], job['id'])
    calls = len(model.calls)
    result = reconsider_pending(Uow, .85)
    assert result['accepted'] == 1
    assert result['paused_items' if paused else 'resumed_items'] == 1
    assert reconsider_pending(Uow, .85)['accepted'] == 0  # idempotent
    with Uow() as u:
        assert u.repo.get('classification_revisions', old['id'])['decision']['outcome'] == 'needs_review'
        assert u.repo.get('jobs', job['id'])['status'] == ('paused' if paused else 'queued')
    if paused:
        runner.run(items[0]['id'])
        assert len(model.calls) == calls
        env.rt.jobs.resume(env.actors['editor'], job['id'])
    runner.run(items[0]['id'])
    assert all(purpose == 'extract' for purpose, _, _ in model.calls[calls:])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'


@pytest.mark.parametrize('reason', ['omitted', '', None])
def test_manual_topic_review_without_reason_and_exclusion_without_reason(env, corpus, reason):
    decision = classification(['rag'])
    decision['rag'] = {'in_scope': False, 'exclusion_reason': None}
    payload = {'expected_revision': 'none', 'decision': decision}
    if reason != 'omitted':
        payload['reason'] = reason
    response = env.backend.post(f'/api/v1/documents/{corpus.doc["id"]}/classifications/review', headers=env.headers(), json=payload)
    assert response.status_code == 200, response.text
    with Uow() as u:
        cls = u.repo.get('classification_revisions', response.json()['id'])
        assert cls['reviewed'] and cls['reason'] == ''
        assert cls['decision']['rag']['exclusion_reason']


def test_graph_edit_delete_and_exclude_without_reason(env, corpus):
    env.rt.jobs.review(env.actors['editor'], corpus.doc['id'], 'none', classification(['rag']), '', False)
    response = env.backend.post(f'/api/v1/corpora/{corpus.corpus["id"]}/publications', headers=env.headers(),
                                json={'document_id': corpus.doc['id'], 'graph': rag_graph()})
    assert response.status_code == 201, response.text
    pid = corpus.pub['id']
    response = env.backend.patch(f'/api/v1/publications/{pid}?profile=rag-v1',
        headers={**env.headers(), 'If-Match': response.headers['etag']}, json={'bibliography': {'title': 'Edited without a comment'}})
    assert response.status_code == 200, response.text
    response = env.backend.request('DELETE', f'/api/v1/publications/{pid}/entities/rag_result/R1',
        headers={**env.headers(), 'If-Match': response.headers['etag']}, json={})
    assert response.status_code == 200, response.text
    response = env.backend.post(f'/api/v1/publications/{pid}/exclude?profile=rag-v1',
        headers={**env.headers(), 'If-Match': response.headers['etag']}, json={})
    assert response.status_code == 200, response.text
    assert response.json()['graph']['scope']['exclusion_reason']
    with Uow() as u:
        assert all(row['reason'] == '' for row in u.repo.find('publication_revisions', publication_id=pid))
