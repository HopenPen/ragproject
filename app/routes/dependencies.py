from fastapi import Depends, Request, Query
from fastapi.security import HTTPBearer
from app.security import gateway_identity
from app.domain import Error

bearer = HTTPBearer(auto_error=False)


def runtime(request: Request):
    return request.app.state.runtime


def actor(request: Request, credentials=Depends(bearer)):
    return gateway_identity(request.app.state.runtime.config, request.headers)


def admin(identity=Depends(actor)):
    if identity['role'] != 'admin':
        raise Error(403, 'forbidden', 'Administrator required')
    return identity


def paging(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    return {'page': page, 'page_size': page_size}


def public_record(value):
    if isinstance(value, list):
        return [public_record(v) for v in value]
    if isinstance(value, dict):
        return {k: public_record(v) for k, v in value.items() if k not in ('storage_key', 'image_key', 'password_hash', 'token_hash')}
    return value
