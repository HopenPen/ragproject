# Назначение файла: схемы/ссылки/revisions/physics/CSV обоих профилей и semantic evaluation.
import copy
import csv
import io
from decimal import Decimal
import pytest
from pydantic import ValidationError
from app.db import Uow
from app.domain import Error, normalize_value, quote_normalize
from app.profiles import csv_columns, passport
from app.services.validation import enforce_graph, scientific, structural, source_checks
from app.services.export import csv_bytes
from tests.fixtures import solar_graph,rag_graph,classification


@pytest.mark.parametrize('factory',[solar_graph,rag_graph])
def test_typed_graph_and_links(factory):
    graph=enforce_graph(factory(),1)
    assert not structural(graph,1)
    graph['unexpected']='bad'
    with pytest.raises(Error):enforce_graph(graph,1)
    graph=factory();graph['results'][0]['duplicate_of']=graph['results'][0]['result_id']
    assert any(i['rule']=='duplicate_cycles' for i in structural(graph,1))
    graph=factory();graph['scope']['in_scope']=False
    assert any(i['rule']=='excluded_graph' for i in structural(graph,1))


def test_solar_rules_and_no_assumed_pin():
    graph=solar_graph();graph['results'][-1].update(metric_value='20',raw_value='20',normalized_value='20')
    assert 'jv_consistency' in {i['rule'] for i in scientific(graph) if i['severity']=='warning'}
    graph['measurements'][0]['light_intensity']=None
    assert not any(i['rule']=='jv_consistency' and i['severity']=='warning' for i in scientific(graph))
    assert any(i.get('definition_status')=='awaiting_definition' for i in scientific(graph))
    eqe=copy.deepcopy(graph['results'][1]);eqe.update(result_id='EQE',metric_name='Jsc_EQE',normalized_value='23',metric_value='23',raw_value='23')
    graph['results'].append(eqe)
    assert any(i['rule']=='eqe_consistency' for i in scientific(graph))


def test_rag_scales_k_and_protocol():
    graph=rag_graph();r=graph['results'][0]
    assert r['metric_k']==0 and graph['configurations'][0]['top_k']==0
    r.update(metric_value='2',normalized_value='2',raw_value='2',metric_name='Recall@10')
    rules={i['rule'] for i in scientific(graph)}
    assert {'metric_k','metric_scale'}<=rules
    r.update(metric_unit=None,normalized_unit=None,metric_name='F1')
    assert not any(i['rule']=='metric_scale' for i in scientific(graph))
    r.update(metric_unit='fraction',normalized_unit='fraction')
    graph['experiments'].append({**graph['experiments'][0],'experiment_id':'E2','evaluation_protocol':'different protocol'})
    graph['results'].append({**r,'result_id':'R2','experiment_id':'E2'})
    assert any(i['rule']=='protocol_mismatch' for i in scientific(graph))


def test_units_raw_ranges_and_quote_signs():
    assert normalize_value('1123','mV','V')==Decimal('1.123')
    assert normalize_value('0.49','fraction','%')==49
    assert normalize_value('~0.49','fraction','%') is None
    assert normalize_value('1-2','V','V') is None
    assert normalize_value('NaN','V','V') is None
    assert quote_normalize('Эффек-\nтивность -1.20%')=='эффективность -1.20%'
    assert quote_normalize('-1.20')!=quote_normalize('1.20')
    assert quote_normalize('1.20')!=quote_normalize('1.2')


def test_csv_exact_order_null_zero_false():
    columns=csv_columns('solar-v1')
    assert columns['results'][1:5]==['result_id','device_id','measurement_id','material_id']
    data=csv_bytes(['a','b','c','d','e'],[{'a':None,'b':0,'c':False,'d':['A','B'],'e':'comma,\nquote"'}])
    row=list(csv.DictReader(io.StringIO(data.decode())))[0]
    assert row=={'a':'','b':'0','c':'false','d':'A;B','e':'comma,\nquote"'}
    assert len(csv_columns('rag-v1'))==7
    assert passport('rag-v1')['status']=='project_defined_recommended'


def seed_graph(env,corpus,profile='rag-v1'):
    decision=classification(['solar','rag'])
    env.rt.jobs.review(env.actors['editor'],corpus.doc['id'],'none',decision,'known synthetic fixture',False)
    return env.rt.catalog.create(env.actors['editor'],corpus.corpus['id'],corpus.doc['id'],rag_graph() if profile=='rag-v1' else solar_graph(),'manual data')


def test_atomic_revision_stale_delete_and_acl(env,corpus):
    initial=seed_graph(env,corpus)
    pid=corpus.pub['id'];actor=env.actors['editor']
    with pytest.raises(Error) as exc:
        env.rt.catalog.mutate(actor,pid,'rag-v1',None,'missing',lambda g:g)
    assert exc.value.status==428
    changed=env.rt.catalog.mutate(actor,pid,'rag-v1',initial['revision_id'],'title fix',lambda g:{**g,'bibliography':{**g['bibliography'],'title':'Correction'}})
    with pytest.raises(Error) as exc: env.rt.catalog.mutate(actor,pid,'rag-v1',initial['revision_id'],'stale',lambda g:g)
    assert exc.value.status==412
    with pytest.raises(Error):env.rt.catalog.entity(actor,pid,'configuration','C1','delete',expected=changed['revision_id'],reason='would break link')
    assert env.rt.catalog.read(actor,pid,'rag-v1')['revision_id']==changed['revision_id']
    assert env.rt.catalog.read(actor,pid,'rag-v1',initial['revision_id'])['graph']['bibliography']['title']=='SYNTHETIC RAG fixture'
    with pytest.raises(Error) as exc:env.rt.catalog.read(env.actors['viewer'],pid,'rag-v1')
    assert exc.value.status==404
    with pytest.raises(Error): env.rt.catalog.entity(actor,pid,'unknown')


def test_cross_profile_links_and_source_sign(env,corpus):
    graph=rag_graph();graph['results'][0]['config_id']='D1'
    with pytest.raises(Error):enforce_graph(graph,1)
    graph=rag_graph();graph['results'][0]['source_fragment']='RAG F1 = -0.5 fraction.'
    report=source_checks(graph,[{'number':1,'text':'RAG F1 = 0.5 fraction.','width':600,'height':800}])
    assert any(i['severity']=='needs_review' for i in report)


def test_profile_filters_cache_invalidation_and_acl(env,corpus):
    from app.services.catalog import Catalog
    seed_graph(env,corpus)
    class Cache:
        def __init__(self):self.values={}
        def get(self,key):return copy.deepcopy(self.values.get(key))
        def put(self,key,value,ttl=30):self.values[key]=copy.deepcopy(value)
    catalog=Catalog(Uow,Cache())
    args=(env.actors['editor'],corpus.corpus['id'],'rag-v1')
    assert len(catalog.results(*args,top_k=0,generator_model='reported-generator'))==1
    assert catalog.results(*args,top_k=1)==[]
    current=catalog.read(env.actors['editor'],corpus.pub['id'],'rag-v1')
    catalog.entity(env.actors['editor'],corpus.pub['id'],'configuration','C1','patch',{'top_k':1},current['revision_id'],'changed retrieval')
    assert catalog.results(*args,top_k=0)==[]
    assert len(catalog.results(*args,top_k=1))==1
    with pytest.raises(Error) as exc:catalog.results(env.actors['viewer'],corpus.corpus['id'],'rag-v1',top_k=1)
    assert exc.value.status==404


def test_visual_source_requires_location_and_correct_artifact():
    from app.schemas.graphs import Evidence
    source={'evidence_id':'E1','entity_id':'R1','field_path':'metric_value','source_page':1,'method':'vision','artifact_ref':'artifact','reading_method':'chart axis reading'}
    with pytest.raises(ValidationError):Evidence.model_validate(source)
    source=Evidence.model_validate({**source,'bbox':[0,0,100,100]}).model_dump(mode='json')
    graph=rag_graph();graph['evidence']=[source]
    report=source_checks(graph,[{'number':1,'text':'RAG F1 = 0.5 fraction.','width':600,'height':800}],
                         [{'id':'artifact','page':2,'content_type':'application/json'}])
    assert sum(i['severity']=='error' for i in report)==2
