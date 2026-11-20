import json
from fastapi import APIRouter, Depends, Request, Response
from app.schemas.auth import Login, Refresh, PasswordChange, UserCreate, UserPatch
from app.routes.dependencies import actor, admin, runtime, paging
from app.domain import Error
from app.services.auth import safe_user
from app.services.catalog import paginate

router = APIRouter(prefix='/api/v1', tags=['Authentication'])
jwks_router = APIRouter()


@router.post('/auth/login', summary='Login; access token lasts 15 minutes', responses={401: {}, 429: {}, 503: {}})
def login(body: Login, request: Request, rt=Depends(runtime)):
    return rt.auth.login(str(body.email), body.password.get_secret_value(), request.headers.get('x-real-ip', request.client.host))


@router.post('/auth/refresh')
def refresh(body: Refresh, rt=Depends(runtime)):
    return rt.auth.refresh(body.refresh_token)


@router.post('/auth/logout', status_code=204, description='Revokes the refresh family. Existing access JWT remains valid until exp, at most 15 minutes.')
def logout(body: Refresh, rt=Depends(runtime)):
    rt.auth.logout(body.refresh_token)


@router.post('/auth/logout-all', status_code=204, description='Revokes every refresh family. Existing access JWT remains valid until exp, at most 15 minutes.')
def logout_all(identity=Depends(actor), rt=Depends(runtime)):
    rt.auth.logout_all(identity)


@router.post('/auth/change-password', status_code=204, description='Checks the old password and revokes every refresh family. Existing access JWT remains valid until exp.')
def password(body: PasswordChange, identity=Depends(actor), rt=Depends(runtime)):
    rt.auth.password(identity, body.old_password.get_secret_value(), body.new_password.get_secret_value())


@router.get('/auth/me')
def me(identity=Depends(actor), rt=Depends(runtime)):
    with rt.uow() as u:
        user = u.repo.get('users', identity['id'])
        if not user:
            raise Error(404, 'not_found', 'User not found')
        return safe_user(user)


@router.get('/users')
def users(identity=Depends(admin), pagination=Depends(paging), rt=Depends(runtime)):
    with rt.uow() as u:
        return paginate([safe_user(user) for user in u.repo.find('users')], **pagination)


@router.post('/users', status_code=201)
def create_user(body: UserCreate, identity=Depends(admin), rt=Depends(runtime)):
    return rt.auth.create_user({**body.model_dump(exclude={'password'}), 'password': body.password.get_secret_value()})


@router.get('/users/{id}')
def user(id: str, identity=Depends(admin), rt=Depends(runtime)):
    with rt.uow() as u:
        user = u.repo.get('users', id)
        if not user:
            raise Error(404, 'not_found', 'User not found')
        return safe_user(user)


@router.patch('/users/{id}')
def patch_user(id: str, body: UserPatch, identity=Depends(admin), rt=Depends(runtime)):
    return rt.auth.patch_user(id, body.model_dump(exclude_none=True))


@jwks_router.get('/.well-known/jwks.json', include_in_schema=False)
def jwks(rt=Depends(runtime)):
    return json.loads(rt.config.jwt_public_path.read_text(encoding='utf-8'))
