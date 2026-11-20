# Назначение файла: весь PDF coverage, review continuation, кандидаты, idempotency/cancel/snapshot.
import copy
import io
import json
import zipfile
import pytest
from app.db import Uow
from app.domain import Error, ExternalConfiguration
from app.schemas.requests import JobCreate
from app.services.pipeline import Runner
from app.provider import ResponsesModel, strict_schema
from tests.conftest import ModelDouble
from tests.fixtures import pdf_bytes,classification,rag_graph,solar_graph
from tests.test_graphs import seed_graph


def enqueue(env,corpus,kind='process',key=None,**extra):
    body=JobCreate(kind=kind,all_documents=True,**extra)
    job=env.rt.jobs.enqueue(env.actors['editor'],corpus.corpus['id'],body.model_dump(),key)
    with Uow() as u:items=u.repo.find('job_items',job_id=job['id'])
    return job,items


def test_complete_pipeline_idempotent_delivery_and_candidates(env,corpus):
    model=ModelDouble();runner=Runner(Uow,env.storage,model,env.config)
    job,items=enqueue(env,corpus)
    runner.run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs',job['id'])['status']=='succeeded'
        current=u.repo.get('publications',corpus.pub['id'])['current']
        assert set(current)=={'solar-v1','rag-v1'}
        assert len(u.repo.find('publication_revisions',publication_id=corpus.pub['id']))==2
        assert any(a['kind']=='crop' for a in u.repo.find('artifacts',document_id=corpus.doc['id']))
    count=len(model.calls);runner.run(items[0]['id'])
    assert len(model.calls)==count
    changed=env.rt.catalog.mutate(env.actors['editor'],corpus.pub['id'],'rag-v1',current['rag-v1'],'human title',lambda g:{**g,'bibliography':{**g['bibliography'],'title':'Human corrected'}})
    second,new=enqueue(env,corpus);runner.run(new[0]['id'])
    with Uow() as u:
        pub=u.repo.get('publications',corpus.pub['id'])
        assert pub['current']['rag-v1']==changed['revision_id']
        assert len(u.repo.find('publication_revisions',publication_id=pub['id']))==5
        revisions=u.repo.find('publication_revisions',publication_id=pub['id'],run_id=new[0]['id'])
        assert len(revisions)==2 and not any(r['id'] in pub['current'].values() for r in revisions)


def test_every_page_and_review_resumes_without_ocr(env,corpus,monkeypatch):
    doc,_=env.rt.documents.upload(env.actors['editor'],corpus.corpus['id'],'D002','five-pages.pdf',pdf_bytes(pages=5))
    model=ModelDouble(classification(['solar','rag'],confidence=.5))
    runner=Runner(Uow,env.storage,model,env.config)
    job=env.rt.jobs.enqueue(env.actors['editor'],corpus.corpus['id'],JobCreate(kind='process',document_ids=[doc['id']]).model_dump())
    with Uow() as u:item=u.repo.find('job_items',job_id=job['id'])[0]
    runner.run(item['id'])
    with Uow() as u:
        assert u.repo.get('jobs',job['id'])['status']=='waiting_review'
        current=u.repo.get('documents',doc['id'])['classification_id']
    seen=[n for purpose,pages,_ in model.calls if purpose=='classify' for n in pages]
    assert seen==[1,2,3,4,5]
    def no_ocr(*args):raise AssertionError('Review must reuse OCR artifacts')
    monkeypatch.setattr(env.storage,'prepare_page',no_ocr)
    env.rt.jobs.review(env.actors['editor'],doc['id'],current,classification(['solar','rag']),'human resolved',False)
    runner.run(item['id'])
    with Uow() as u:assert u.repo.get('jobs',job['id'])['status']=='succeeded'


def test_outside_has_bibliography_but_no_subjects(env,corpus):
    model=ModelDouble(classification([],outcome='outside'))
    job,items=enqueue(env,corpus)
    Runner(Uow,env.storage,model,env.config).run(items[0]['id'])
    with Uow() as u:
        for rev in u.repo.find('publication_revisions',publication_id=corpus.pub['id']):
            assert rev['graph']['bibliography']['title'] and not rev['graph']['results']
            assert rev['graph']['scope']['in_scope'] is False
    assert not any(p=='extract' for p,_,_ in model.calls)


def test_unreadable_is_not_outside(env,corpus):
    model=ModelDouble(classification([],outcome='unreadable',confidence=0))
    job,items=enqueue(env,corpus)
    with pytest.raises(Error):Runner(Uow,env.storage,model,env.config).run(items[0]['id'])
    with Uow() as u:
        doc=u.repo.get('documents',corpus.doc['id']);cls=u.repo.get('classification_revisions',doc['classification_id'])
        assert cls['decision']['outcome']=='unreadable' and u.repo.get('jobs',job['id'])['status']=='failed'


def test_missing_api_key_is_blocked_not_fake_success(env,corpus):
    job,items=enqueue(env,corpus)
    Runner(Uow,env.storage,ResponsesModel(env.config),env.config).run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs',job['id'])['status']=='blocked_external_configuration'
        assert not u.repo.find('publication_revisions',publication_id=corpus.pub['id'])


def test_job_idempotency_payload_and_broker_outage(env,corpus):
    first,items=enqueue(env,corpus,key='same')
    second,_=enqueue(env,corpus,key='same')
    assert first['id']==second['id']
    with pytest.raises(Error) as exc:enqueue(env,corpus,'classify',key='same')
    assert exc.value.status==409
    from app.worker import dispatch_once
    class BrokenPublisher:
        def publish(self,*args):raise ConnectionError('offline')
    assert dispatch_once(BrokenPublisher()) is False
    with Uow() as u:
        assert u.repo.get('jobs',first['id'])['status']=='queued'
        assert u.repo.find('outbox',item_id=items[0]['id'])[0]['dispatched'] is False


def test_cancel_then_retry_new_job(env,corpus):
    job,items=enqueue(env,corpus)
    assert env.rt.jobs.cancel(env.actors['editor'],job['id'])['status']=='cancelled'
    Runner(Uow,env.storage,ModelDouble(),env.config).run(items[0]['id'])
    new=env.rt.jobs.retry(env.actors['editor'],job['id'])
    assert new['id']!=job['id'] and new['parent_id']==job['id']


def test_cancel_during_provider_preserves_output_without_graph_activation(env,corpus):
    job,items=enqueue(env,corpus)
    class CancellingModel(ModelDouble):
        def call(self,*args):
            response=super().call(*args)
            env.rt.jobs.cancel(env.actors['editor'],job['id'])
            return response
    Runner(Uow,env.storage,CancellingModel(),env.config).run(items[0]['id'])
    with Uow() as u:
        item=u.repo.get('job_items',items[0]['id'])
        assert item['status']=='cancelled' and item['progress']['outputs']
        assert not u.repo.get('publications',corpus.pub['id'])['current']


def test_export_snapshot_remains_immutable(env,corpus):
    current=seed_graph(env,corpus)
    env.rt.catalog.create(env.actors['editor'],corpus.corpus['id'],corpus.doc['id'],solar_graph(),'solar fixture')
    job,items=enqueue(env,corpus,'export',run_external_checker=False)
    env.rt.catalog.mutate(env.actors['editor'],corpus.pub['id'],'rag-v1',current['revision_id'],'after snapshot',lambda g:{**g,'bibliography':{**g['bibliography'],'title':'Changed after enqueue'}})
    Runner(Uow,env.storage,ModelDouble(),env.config).run(items[0]['id'])
    with Uow() as u:
        completed=u.repo.get('jobs',job['id'])
        assert completed['status']=='succeeded'
    blob=env.storage.get(completed['result']['storage_key'])
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert sum(n.endswith('.csv') for n in archive.namelist())==14
        assert 'SYNTHETIC RAG fixture' in archive.read('rag-v1/submission/publications.csv').decode()
        assert 'Changed after enqueue' not in archive.read('rag-v1/submission/publications.csv').decode()
        assert 'false' in archive.read('solar-v1/submission/measurements.csv').decode()
        assert completed['result']['report']['external_checkers']['rag-v1']['status']=='not_available_for_profile'


def test_strict_export_rejects_missing_classification(env,corpus):
    with pytest.raises(Error) as exc:enqueue(env,corpus,'export')
    assert exc.value.code=='incomplete_snapshot'
    job,_=enqueue(env,corpus,'export',allow_incomplete=True)
    assert job['input']['snapshot']['omissions']


def test_request_forbids_model_override_and_inapplicable_fields():
    for payload in ({'kind':'process','all_documents':True,'model_id':'custom'},
                    {'kind':'classify','all_documents':True,'target_profiles':['solar-v1']},
                    {'kind':'process','all_documents':True,'force':True}):
        with pytest.raises(Exception):JobCreate.model_validate(payload)
    schema=strict_schema(ClassificationSchema())
    assert schema['additionalProperties'] is False


def ClassificationSchema():
    from app.schemas.graphs import Classification
    return Classification.model_json_schema()


def test_transient_retry_uses_durable_outbox_and_is_bounded(env,corpus):
    from app.domain import TransientError
    class OfflineModel:
        def call(self,*args):raise TransientError('provider unavailable')
    job,items=enqueue(env,corpus)
    runner=Runner(Uow,env.storage,OfflineModel(),env.config)
    runner.run(items[0]['id'])
    with Uow() as u:
        out=u.repo.find('outbox',item_id=items[0]['id'])[0]
        assert not out['dispatched'] and out['lease_until'] is not None
        assert u.repo.get('jobs',job['id'])['status']=='queued'
    for _ in range(2):runner.run(items[0]['id'])
    with pytest.raises(Error) as exc:runner.run(items[0]['id'])
    assert exc.value.code=='transient_retry_exhausted'
    with Uow() as u:assert u.repo.get('jobs',job['id'])['status']=='failed'


def test_excluding_one_profile_preserves_other_and_history(env,corpus):
    first=seed_graph(env,corpus)
    solar=env.rt.catalog.create(env.actors['editor'],corpus.corpus['id'],corpus.doc['id'],solar_graph(),'second profile')
    empty=__import__('app.profiles',fromlist=['GRAPHS']).GRAPHS['rag-v1'](domain_profile='rag-v1',bibliography=first['graph']['bibliography'],scope={'in_scope':False,'exclusion_reason':'Manual exclusion'}).model_dump(mode='json')
    new=env.rt.catalog.mutate(env.actors['editor'],corpus.pub['id'],'rag-v1',first['revision_id'],'excluded',lambda g:empty)
    with Uow() as u:
        pub=u.repo.get('publications',corpus.pub['id'])
        cls=u.repo.get('classification_revisions',u.repo.get('documents',corpus.doc['id'])['classification_id'])
        assert pub['current']['solar-v1']==solar['revision_id']
        assert cls['decision']['rag']['in_scope'] is False
    assert env.rt.catalog.read(env.actors['editor'],corpus.pub['id'],'rag-v1',first['revision_id'])['graph']['results']
    job,items=enqueue(env,corpus,'export',run_external_checker=False)
    Runner(Uow,env.storage,ModelDouble(),env.config).run(items[0]['id'])
    with Uow() as u:assert u.repo.get('jobs',job['id'])['status']=='succeeded'


def test_responses_transport_contract_and_partial_output(env,monkeypatch):
    import httpx,json
    from app.schemas.graphs import Classification
    captured=[]
    def respond(url,**kwargs):
        captured.append((url,kwargs))
        return httpx.Response(200,json={'status':'completed','model':'actual-api-model','usage':{'input_tokens':2,'output_tokens':3},
                                      'output':[{'content':[{'type':'output_text','text':json.dumps(classification())}]}]})
    monkeypatch.setattr('app.provider.httpx.post',respond)
    config=env.config.model_copy(update={'openai_api_key':__import__('pydantic').SecretStr('test-key')})
    result=ResponsesModel(config).call('classify',Classification.model_json_schema(),[{'number':7,'text':'article data','png':b'PNG'}],{})
    url,request=captured[0]
    assert url=='https://api.openai.com/v1/responses' and request['json']['model']==config.model_id
    assert request['json']['store'] is False and request['json']['text']['format']['strict'] is True
    assert any(c['type']=='input_image' and c['image_url'].startswith('data:image/png;base64,') for c in request['json']['input'][0]['content'])
    assert result['model']=='actual-api-model'
    monkeypatch.setattr('app.provider.httpx.post',lambda *a,**k:httpx.Response(200,json={'status':'incomplete','output':[]}))
    with pytest.raises(Error) as exc:ResponsesModel(config).call('classify',Classification.model_json_schema(),[],{})
    assert exc.value.code=='partial_model_output'


def test_model_cannot_confirm_its_own_sources():
    from app.services.pipeline import machine_evidence
    graph=rag_graph()
    graph['evidence']=[{'method':'text','review':'confirmed','review_reason':'model asserts verified'}]
    source=machine_evidence(graph)['evidence'][0]
    assert source['review']=='open' and source['review_reason'] is None
    graph['evidence'][0]['method']='manual'
    with pytest.raises(Error):machine_evidence(graph)
