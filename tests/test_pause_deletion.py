from datetime import timedelta
import pytest
from app.db import Uow
from app.domain import Error, now, uid
from app.services.pipeline import Runner, Jobs
from app.services.deletion import Deletions, cleanup_storage_once
from tests.conftest import ModelDouble
from tests.fixtures import pdf_bytes, classification
from tests.test_pipeline import enqueue
from tests.test_graphs import seed_graph


@pytest.mark.parametrize('pause_purpose', ['classify', 'extract'])
def test_pause_saves_provider_response_and_resume_reuses_it(env, corpus, pause_purpose):
    job, items = enqueue(env, corpus)
    class PauseAfterCall(ModelDouble):
        paused = False
        def call(self, purpose, *args):
            value = super().call(purpose, *args)
            if purpose == pause_purpose and not self.paused:
                self.paused = True
                assert env.rt.jobs.pause(env.actors['editor'], job['id'])['status'] == 'pause_requested'
            return value
    model = PauseAfterCall()
    runner = Runner(Uow, env.storage, model, env.config)
    runner.run(items[0]['id'])
    with Uow() as u:
        item = u.repo.get('job_items', items[0]['id'])
        assert item['status'] == 'paused'
        assert u.repo.get('jobs', job['id'])['status'] == 'paused'
        assert item['progress']['outputs']
        assert item['attempts'] == 1
        assert u.repo.get('publications', corpus.pub['id'])['current'] == {}
    count = len(model.calls)
    runner.run(items[0]['id'])
    assert len(model.calls) == count
    env.rt.jobs.resume(env.actors['editor'], job['id'])
    env.rt.jobs.resume(env.actors['editor'], job['id'])  # idempotent duplicate
    Runner(Uow, env.storage, model, env.config).run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'
        assert u.repo.get('job_items', items[0]['id'])['attempts'] == 1
        assert len(u.repo.find('classification_revisions', run_id=items[0]['id'])) == 1
        assert len(u.repo.find('publication_revisions', run_id=items[0]['id'])) == 2
    signatures = [(purpose, tuple(pages), ctx.get('domain_profile')) for purpose, pages, ctx in model.calls]
    assert len(signatures) == len(set(signatures))


def test_queued_pause_survives_redelivery_and_can_be_cancelled(env, corpus):
    job, items = enqueue(env, corpus)
    assert env.rt.jobs.pause(env.actors['editor'], job['id'])['status'] == 'paused'
    assert env.rt.jobs.pause(env.actors['editor'], job['id'])['status'] == 'paused'
    model = ModelDouble()
    Runner(Uow, env.storage, model, env.config).run(items[0]['id'])
    assert not model.calls
    assert env.rt.jobs.cancel(env.actors['editor'], job['id'])['status'] == 'cancelled'
    with pytest.raises(Error) as exc:
        env.rt.jobs.resume(env.actors['editor'], job['id'])
    assert exc.value.status == 409


def test_pause_before_first_run_preserves_first_attempt(env, corpus):
    job, items = enqueue(env, corpus)
    env.rt.jobs.pause(env.actors['editor'], job['id'])
    env.rt.jobs.resume(env.actors['editor'], job['id'])
    Runner(Uow, env.storage, ModelDouble(), env.config).run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'
        assert u.repo.get('job_items', items[0]['id'])['attempts'] == 1


def test_pause_recovery_does_not_automatically_restart_expired_worker(env, corpus):
    from app.worker import dispatch_once
    job, items = enqueue(env, corpus)
    with Uow() as u:
        u.repo.update('job_items', items[0]['id'], status='running', attempts=1, lease_token=uid(), lease_until=now()-timedelta(seconds=1))
        u.repo.update('jobs', job['id'], status='running')
        u.commit()
    env.rt.jobs.pause(env.actors['editor'], job['id'])
    class NoPublisher:
        def publish(self, *args):
            pytest.fail('Paused work must not be published')
    dispatch_once(NoPublisher())
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'paused'
        assert u.repo.get('job_items', items[0]['id'])['status'] == 'paused'
    Jobs(Uow).resume(env.actors['editor'], job['id'])
    Runner(Uow, env.storage, ModelDouble(), env.config).run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'


def test_review_while_paused_stays_paused_until_explicit_resume(env, corpus):
    job, items = enqueue(env, corpus)
    Runner(Uow, env.storage, ModelDouble(classification(confidence=.5)), env.config).run(items[0]['id'])
    env.rt.jobs.pause(env.actors['editor'], job['id'])
    with Uow() as u:
        revision = u.repo.get('documents', corpus.doc['id'])['classification_id']
    env.rt.jobs.review(env.actors['editor'], corpus.doc['id'], revision, classification(), 'Reviewed while paused', False)
    with Uow() as u:
        item = u.repo.get('job_items', items[0]['id'])
        assert item['status'] == 'paused'
        assert item['progress']['_resume_status'] == 'queued'
    env.rt.jobs.resume(env.actors['editor'], job['id'])
    Runner(Uow, env.storage, ModelDouble(), env.config).run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'


def test_delete_article_removes_scientific_history_and_durably_cleans_pdf(env, corpus):
    graph = seed_graph(env, corpus)
    orphan = f'documents/{corpus.doc["id"]}/runs/interrupted/artifact.png'
    env.storage.put(orphan, b'interrupted run', 'image/png')
    job, items = enqueue(env, corpus)
    env.rt.jobs.pause(env.actors['editor'], job['id'])
    response = env.backend.delete('/api/v1/documents/'+corpus.doc['id'], headers=env.headers())
    assert response.status_code == 204, response.text
    assert env.backend.get('/api/v1/documents/'+corpus.doc['id'], headers=env.headers()).status_code == 404
    assert env.backend.get('/api/v1/publications/'+corpus.pub['id'], headers=env.headers()).status_code == 404
    with Uow() as u:
        assert not u.repo.find('publication_revisions', publication_id=corpus.pub['id'])
        assert not u.repo.find('classification_revisions', document_id=corpus.doc['id'])
        assert u.repo.get('jobs', job['id'])['status'] == 'cancelled'
        assert not u.repo.find('job_items', document_id=corpus.doc['id'])
        assert u.repo.find('storage_deletions')
    # The original is removed only by the durable storage cleanup, not by an unsafe pre-commit delete.
    assert corpus.doc['storage_key'] in env.storage.files
    while cleanup_storage_once(env.storage):
        pass
    assert corpus.doc['storage_key'] not in env.storage.files
    assert orphan not in env.storage.files
    Runner(Uow, env.storage, ModelDouble(), env.config).run(items[0]['id'])  # stale queue delivery


def test_deleting_one_paused_article_preserves_other_article_progress(env, corpus):
    second, _ = env.rt.documents.upload(env.actors['editor'], corpus.corpus['id'], 'D002', 'second.pdf', pdf_bytes())
    job, items = enqueue(env, corpus)
    env.rt.jobs.pause(env.actors['editor'], job['id'])
    Deletions(Uow).remove(env.actors['editor'], document_id=corpus.doc['id'])
    with Uow() as u:
        remaining = u.repo.find('job_items', job_id=job['id'])
        assert len(remaining) == 1 and remaining[0]['document_id'] == second['id']
        assert remaining[0]['status'] == 'paused'
        assert u.repo.get('jobs', job['id'])['status'] == 'paused'
    env.rt.jobs.resume(env.actors['editor'], job['id'])
    Runner(Uow, env.storage, ModelDouble(), env.config).run(remaining[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'


def test_corpus_delete_requires_stopped_worker_and_respects_acl(env, corpus):
    job, items = enqueue(env, corpus)
    assert env.backend.delete('/api/v1/corpora/'+corpus.corpus['id'], headers=env.headers('viewer')).status_code == 404
    with Uow() as u:
        u.repo.update('job_items', items[0]['id'], status='running', lease_token=uid(), lease_until=now()+timedelta(seconds=60))
        u.commit()
    response = env.backend.delete('/api/v1/corpora/'+corpus.corpus['id'], headers=env.headers())
    assert response.status_code == 409 and response.json()['error']['code'] == 'processing_active'
    with Uow() as u:
        assert u.repo.get('documents', corpus.doc['id'])
        u.repo.update('job_items', items[0]['id'], status='paused', lease_token=None, lease_until=None)
        u.commit()
    env.rt.documents.patch_corpus(env.actors['editor'], corpus.corpus['id'], {'archived': True})
    response = env.backend.delete('/api/v1/corpora/'+corpus.corpus['id'], headers=env.headers())
    assert response.status_code == 204, response.text
    with Uow() as u:
        assert not u.repo.get('corpora', corpus.corpus['id'])
        assert not u.repo.find('jobs', corpus_id=corpus.corpus['id'])


def test_failed_storage_cleanup_is_retried_after_restart(env, corpus):
    Deletions(Uow).remove(env.actors['editor'], corpus_id=corpus.corpus['id'])
    class OfflineStorage:
        def delete(self, key):
            raise ConnectionError('storage unavailable')
    assert cleanup_storage_once(OfflineStorage())
    with Uow() as u:
        rows = u.repo.find('storage_deletions')
        assert rows[0]['attempts'] == 1
        u.repo.update('storage_deletions', rows[0]['id'], retry_at=now()-timedelta(seconds=1))
        u.commit()
    while cleanup_storage_once(env.storage):
        pass
    assert not env.storage.files


def test_pausing_validations_is_rejected(env, corpus):
    seed_graph(env, corpus)
    job, _ = enqueue(env, corpus, 'validate')
    response = env.backend.post('/api/v1/jobs/'+job['id']+'/pause', headers=env.headers())
    assert response.status_code == 409
