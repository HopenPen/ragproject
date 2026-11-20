# Назначение файла: ASGI binary/ACL/revision contracts и реальные infrastructure roundtrips по opt-in.
import io
import json
import os
import secrets
from pathlib import Path
import pytest
from app.domain import Error
from tests.fixtures import pdf_bytes,classification,rag_graph


def test_api_binary_upload_acl_and_archive(env):
    api=env.backend;headers=env.headers()
    corpus=api.post('/api/v1/corpora',headers=headers,json={'name':'Corpus'}).json()
    path=f'/api/v1/corpora/{corpus["id"]}'
    data=pdf_bytes()
    uploaded=api.post(path+'/documents',headers=headers,data={'publication_code':'D001'},files={'file':('fixture.pdf',data,'application/pdf')})
    assert uploaded.status_code==201
    doc=uploaded.json()
    assert 'storage_key' not in doc
    assert api.get(f'/api/v1/documents/{doc["id"]}/file',headers=headers).content==data
    assert api.get(path,headers=env.headers('viewer')).status_code==404
    assert api.get(path,headers=env.headers('admin')).status_code==200
    assert api.patch(path,headers=headers,json={'split':'changed'}).status_code==409
    assert api.post(path+'/archive',headers=headers).status_code==200
    assert api.patch(path,headers=headers,json={'name':'new'}).status_code==409


def test_api_graph_etag_and_pagination(env,corpus):
    from tests.test_graphs import seed_graph
    seed_graph(env,corpus)
    api=env.backend;headers=env.headers();path=f'/api/v1/publications/{corpus.pub["id"]}/graph?profile=rag-v1'
    current=api.get(path,headers=headers)
    assert current.status_code==200 and current.headers['etag']
    body={'graph':current.json()['graph'],'reason':'API correction'}
    assert api.put(path,headers=headers,json=body).status_code==428
    updated=api.put(path,headers={**headers,'If-Match':current.headers['etag']},json=body)
    assert updated.status_code==200 and updated.headers['etag']!=current.headers['etag']
    assert api.put(path,headers={**headers,'If-Match':current.headers['etag']},json=body).status_code==412
    assert api.get('/api/v1/corpora?page_size=201',headers=headers).status_code==422
    assert api.get('/api/v1/corpora?page_size=1',headers=headers).json()['total']==1
    assert api.get('/api/v1/domain-profiles/rag-v1',headers=headers).json()['status']=='project_defined_recommended'


def test_pdf_signature_page_limit_and_model_strict_input(env):
    with pytest.raises(Error) as exc:env.storage.inspect_pdf(b'bad')
    assert exc.value.status==415
    env.config.max_pdf_pages=1
    with pytest.raises(Error):env.storage.inspect_pdf(pdf_bytes(pages=2))
    assert len(env.storage.prepare_page(pdf_bytes('mixed'),1)['crops'])==1


def test_evaluate_one_to_one_ignores_random_ids(tmp_path):
    from app.profiles import csv_columns
    from app.services.export import csv_bytes
    from tools.manage import evaluate
    a,b=tmp_path/'pred',tmp_path/'gold';a.mkdir();b.mkdir()
    for directory in (a,b):
        graph=rag_graph()
        if directory==b:
            graph['configurations'][0]['config_id']='different'
            graph['results'][0]['config_id']='different'
            graph['results'][0]['result_id']='different-result'
        for table,columns in csv_columns('rag-v1').items():
            rows=graph.get(table,[]) if table!='publications' else [{'title':'fixture','in_scope':True}]
            (directory/(table+'.csv')).write_bytes(csv_bytes(columns,[{'publication_id':'D001',**r} for r in rows]))
    result=evaluate(a,b,'rag-v1')
    assert result['f1']==1 and not result['official_scorer']
    with (a/'results.csv').open('ab') as stream:
        import csv,io
        original=(a/'results.csv').read_text().splitlines()[1]
        stream.write((original+'\n').encode())
    assert evaluate(a,b,'rag-v1')['precision']==.5


def test_real_tesseract_scan_and_mixed(env):
    import shutil
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is installed in the app image; not available on this host')
    prepared=env.storage.prepare_page(pdf_bytes('scan'),1)
    assert prepared['ocr'] and '10' in prepared['text'] and prepared['coverage']=='complete'
    mixed=env.storage.prepare_page(pdf_bytes('mixed'),1)
    assert not mixed['ocr'] and mixed['crops'] and mixed['png']


@pytest.mark.infrastructure
@pytest.mark.skipif(os.environ.get('RUN_INFRA_TESTS')!='1',reason='Real Compose infrastructure not configured')
def test_real_postgres_redis_rabbitmq_s3_and_gateway():
    import httpx
    import redis
    from kombu import Connection, Queue, Exchange
    from sqlalchemy import create_engine,text
    from app.config import Settings
    from app.storage import Storage
    from app.security import Issuer
    from app.domain import now
    from datetime import timedelta
    import jwt
    config=Settings()
    db=create_engine(config.database_url)
    with db.connect() as conn:
        assert conn.execute(text('SELECT 1')).scalar()==1
        assert 'jsonb'==conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name='publication_revisions' AND column_name='graph'")).scalar()
    cache=redis.Redis.from_url(config.redis_url);assert cache.ping()
    marker=secrets.token_hex(8)
    store=Storage(config);store.put('integration/'+marker,b'%PDF-binary-roundtrip','application/pdf')
    assert store.get('integration/'+marker)==b'%PDF-binary-roundtrip'
    with Connection(config.rabbitmq_url.get_secret_value(),transport_options={'confirm_publish':True}) as broker:
        q=Queue('integration-'+marker,exchange=Exchange('integration',type='direct',durable=True),routing_key=marker,auto_delete=True)(broker)
        q.declare()
        broker.Producer(serializer='json').publish({'marker':marker},exchange='integration',routing_key=marker,delivery_mode=2)
        message=q.get();assert message.payload['marker']==marker;message.ack();q.delete()
    with httpx.Client(base_url='http://nginx',timeout=30) as client:
        assert client.get('/api/v1/corpora',headers={'X-User-Role':'admin','X-User-ID':marker}).status_code in (401,403)
        assert client.get('/metrics').status_code==404
        assert client.get('/health/ready').status_code==404
        tokens=client.post('/api/v1/auth/login',json={'email':config.admin_email,'password':config.admin_password.get_secret_value()}).json()
        assert 'access_token' in tokens
        assert client.get('/api/v1/corpora',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==200
        # Tampered signature, incorrect audience and expired token are never accepted.
        token=tokens['access_token']
        for invalid in (token[:-5]+'AAAAA','invalid'):
            assert client.get('/api/v1/corpora',headers={'Authorization':'Bearer '+invalid}).status_code in (401,403)
        assert client.get('/docs').status_code==200
    db.dispose()


@pytest.mark.infrastructure
@pytest.mark.skipif(os.environ.get('RUN_SIGNING_TESTS')!='1',reason='Run in auth container with its private signing key')
def test_real_gateway_expired_wrong_issuer_audience_and_spoofing():
    import httpx,jwt
    from datetime import timedelta
    from app.config import Settings
    from app.domain import now,uid
    from app.security import Issuer
    config=Settings()
    with httpx.Client(base_url='http://nginx',timeout=30) as client:
        pair=client.post('/api/v1/auth/login',json={'email':config.admin_email,'password':config.admin_password.get_secret_value()}).json()
        claims=jwt.decode(pair['access_token'],options={'verify_signature':False})
        header=jwt.get_unverified_header(pair['access_token'])
        key=config.jwt_key_path.read_bytes()
        expired={**claims,'iat':int((now()-timedelta(hours=1)).timestamp()),'nbf':int((now()-timedelta(hours=1)).timestamp()),'exp':int((now()-timedelta(minutes=5)).timestamp())}
        for invalid_claims in (expired,{**claims,'aud':'wrong-audience'},{**claims,'iss':'wrong-issuer'}):
            token=jwt.encode(invalid_claims,key,algorithm='RS256',headers=header)
            assert client.get('/api/v1/corpora',headers={'Authorization':'Bearer '+token}).status_code in (401,403)
        me=client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+pair['access_token'],'X-User-ID':uid(),'X-User-Role':'viewer','X-Gateway-Credential':'spoof'})
        assert me.status_code==200 and me.json()['id']==claims['sub'] and me.json()['role']=='admin'
