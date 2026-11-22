# Назначение файла: изолированная SQLite/ASGI и только тестовые storage/model/limiter doubles.
import copy
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.config import settings, Settings
from app.db import Base, engine, Uow
from app.security import Hasher, Issuer, create_keys
from app.storage import Storage
from app.services.auth import AuthService
from app.services.catalog import Catalog, Documents
from app.services.pipeline import Jobs, Runner
from app.main import create_app
from tests.fixtures import classification, solar_graph, rag_graph


class MemoryStorage(Storage):
    def __init__(self, config):
        self.config, self.files = config, {}

    def put(self, key, data, content_type):
        self.files[key] = data

    def get(self, key):
        return self.files[key]

    def delete(self, key):
        if key.endswith('/'):
            for stored in list(self.files):
                if stored.startswith(key):
                    self.files.pop(stored, None)
        else:
            self.files.pop(key, None)


class TestLimiter:
    def check(self, identity):
        pass


class ModelDouble:
    def __init__(self, decision=None):
        self.calls=[]
        self.decision=decision or classification(['solar','rag'])

    def call(self, purpose, schema, pages, context):
        self.calls.append((purpose, [p['number'] for p in pages], copy.deepcopy(context)))
        if purpose=='classify':
            output=copy.deepcopy(self.decision)
        else:
            output=solar_graph() if context['domain_profile']=='solar-v1' else rag_graph()
            if context.get('output_mode') == 'repair_delta':
                output = {'graph': output, 'removed_entities': [], 'removed_evidence': []}
        return {'output':output,'model':'TEST-DOUBLE-NOT-REAL','usage':{'input_tokens':1,'output_tokens':1},'response_id':'test'}


@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('DISPATCHER_ENABLED','false')
    settings.cache_clear(); engine.cache_clear()
    config=Settings(database_url='sqlite:///'+str(tmp_path/'test.sqlite'),dispatcher_enabled=False,
                    gateway_secret='test-gateway-secret-with-at-least-32-chars',
                    jwt_key_path=tmp_path/'keys'/'private.pem',jwt_public_path=tmp_path/'public'/'jwks.json',
                    external_checker_path=None, openai_api_key='', runtime_path=tmp_path)
    import app.models.auth,app.models.data
    Base.metadata.create_all(engine())
    create_keys(config)
    hasher=Hasher()
    with Uow() as u:
        people={role:u.repo.add('users',email=role+'@example.org',password_hash=hasher.hash('test-password-long'),role=role,display_name=role) for role in ('admin','editor','viewer')}
        u.commit()
    actors={k:{'id':v['id'],'role':v['role']} for k,v in people.items()}
    store=MemoryStorage(config)
    rt=SimpleNamespace(config=config,uow=Uow,storage=store,catalog=Catalog(Uow),documents=Documents(Uow,store),jobs=Jobs(Uow),
                       auth=AuthService(Uow,hasher,Issuer(config),TestLimiter()))
    backend=TestClient(create_app(config,rt),raise_server_exceptions=False)
    auth_config=config.model_copy(update={'app_mode':'auth'})
    auth_client=TestClient(create_app(auth_config,rt),raise_server_exceptions=False)
    def headers(role='editor'):
        return {'X-Gateway-Credential':config.gateway_secret.get_secret_value(),'X-User-ID':actors[role]['id'],'X-User-Role':role}
    result=SimpleNamespace(config=config,rt=rt,actors=actors,people=people,storage=store,backend=backend,auth=auth_client,headers=headers,tmp=tmp_path)
    yield result
    backend.close();auth_client.close()
    engine().dispose();engine.cache_clear();settings.cache_clear()


@pytest.fixture
def corpus(env):
    from tests.fixtures import pdf_bytes
    corpus=env.rt.documents.create_corpus(env.actors['editor'],{'name':'Test corpus','split':'synthetic'})
    doc,_=env.rt.documents.upload(env.actors['editor'],corpus['id'],'D001','fixture.pdf',pdf_bytes('mixed'))
    with Uow() as u:
        pub=u.repo.find('publications',document_id=doc['id'])[0]
    return SimpleNamespace(corpus=corpus,doc=doc,pub=pub)
