# Назначение файла: factories auth/backend, OpenAPI, CORS, request IDs/errors/logs и dispatcher lifespan.
import json
import logging
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.db import Uow
from app.domain import Error, uid
from app.security import Hasher, Issuer, Limiter
from app.storage import Storage, ReadCache
from app.services.auth import AuthService
from app.services.catalog import Catalog, Documents
from app.services.pipeline import Jobs
from app.routes import auth, documents, jobs, catalog, health

counters = {'requests': 0, 'errors': 0}
log = logging.getLogger('science_extract')


class JsonLog(logging.Formatter):
    def format(self, record):
        value = {'level': record.levelname, 'event': record.getMessage()}
        for field in ('request_id', 'job_id', 'item_id', 'corpus_id', 'elapsed_ms', 'status', 'error_code'):
            if hasattr(record, field):
                value[field] = getattr(record, field)
        return json.dumps(value, ensure_ascii=False)


def create_app(config=None, runtime=None):
    config = config or settings()
    if runtime is None:
        storage = Storage(config) if config.app_mode == 'backend' else None
        runtime = SimpleNamespace(config=config, uow=Uow, storage=storage, catalog=Catalog(Uow, ReadCache(config.redis_url)),
            documents=Documents(Uow, storage), jobs=Jobs(Uow))
        if config.app_mode == 'auth':
            runtime.auth = AuthService(Uow, Hasher(), Issuer(config), Limiter(config.redis_url))

    @asynccontextmanager
    async def lifespan(app):
        stop = thread = None
        if config.app_mode == 'backend' and config.dispatcher_enabled:
            from app.worker import start_dispatcher
            stop, thread = start_dispatcher()
        yield
        if stop:
            stop.set()
            thread.join(timeout=5)

    app = FastAPI(title='Science Extract '+config.app_mode, version='3.0.0', lifespan=lifespan,
        description='JWT via public gateway. Source pages start at 1. Unknown = null; scientific/source review requires a human. '
                    'Use login → Authorize → upload → process job → poll → If-Match corrections → validate/export snapshot → download ZIP.')
    app.state.runtime = runtime
    app.add_middleware(CORSMiddleware, allow_origins=config.allowed_origins, allow_credentials=False,
        allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Authorization', 'Content-Type', 'If-Match', 'Idempotency-Key'],
        expose_headers=['ETag', 'Idempotency-Key', 'Content-Disposition', 'X-Request-ID'])

    @app.middleware('http')
    async def trace(request, call_next):
        incoming = request.headers.get('x-request-id', '')
        try:
            request.state.request_id = str(UUID(incoming))
        except (ValueError, TypeError):
            request.state.request_id = uid()
        start = time.monotonic()
        counters['requests'] += 1
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        if response.status_code >= 400:
            counters['errors'] += 1
        # Never log request bodies, Authorization or provider contents.
        log.info('http_request', extra={'request_id': request.state.request_id, 'status': response.status_code, 'elapsed_ms': round(1000*(time.monotonic()-start))})
        return response

    def error_response(request, status, code, message, details=None):
        return JSONResponse({'error': {'code': code, 'message': message, 'details': details, 'request_id': getattr(request.state, 'request_id', None)}}, status_code=status)

    @app.exception_handler(Error)
    async def domain_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def input_error(request, exc):
        # Drop input/context to avoid reflecting password or token values.
        return error_response(request, 422, 'validation_error', 'Invalid input', [{k:e[k] for k in ('loc', 'msg', 'type')} for e in exc.errors()])

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return error_response(request, 409, 'conflict', 'Conflicting unique value or reference')

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        log.error('request_failure', extra={'request_id': getattr(request.state, 'request_id', None), 'error_code': type(exc).__name__})
        return error_response(request, 503, 'dependency_unavailable', 'Request failed; see request ID in private operator logs')

    app.include_router(health.router)
    if config.app_mode == 'auth':
        app.include_router(auth.router)
        app.include_router(auth.jwks_router)
    elif config.app_mode == 'backend':
        for router in (documents.router, jobs.router, catalog.router):
            app.include_router(router)
        def openapi():
            if not app.openapi_schema:
                app.openapi_schema = get_openapi(title=app.title, version=app.version, description=app.description,
                    routes=app.routes + auth.router.routes)
                examples = {'/api/v1/auth/login': {'email': 'admin@example.org', 'password': 'your configured password'},
                            '/api/v1/corpora/{id}/jobs': {'kind': 'process', 'all_documents': True},
                            '/api/v1/publications/{id}/graph': {'graph': GRAPHS['rag-v1'](domain_profile='rag-v1', bibliography={'title': 'Corrected title'}, scope={'in_scope': False, 'exclusion_reason': 'Survey'}).model_dump(mode='json'), 'reason': 'Reviewed source'}}
                for path, body in examples.items():
                    for method in ('post', 'put'):
                        op = app.openapi_schema['paths'].get(path, {}).get(method)
                        if op and 'requestBody' in op:
                            op['requestBody']['content']['application/json']['example'] = body
                content = app.openapi_schema['paths']['/api/v1/corpora/{id}/jobs']['post']['requestBody']['content']['application/json']
                content.pop('example',None)
                content['examples'] = {kind:{'value':{'kind':kind,'all_documents':True,**({'target_profiles':['solar-v1','rag-v1']} if kind in ('validate','export') else {})}} for kind in ('process','classify','validate','export')}
            return app.openapi_schema
        from app.profiles import GRAPHS
        app.openapi = openapi
    else:
        raise ValueError('APP_MODE must be auth or backend')
    return app


handler = logging.StreamHandler()
handler.setFormatter(JsonLog())
logging.basicConfig(level=settings().log_level, handlers=[handler])
# ASGI factory is used by uvicorn --factory; importing modules does not open connections.
