# Назначение файла: реальные hashes/JWT, rotation/reuse, блокировка, роли и fail-closed limiter.
import json
from datetime import timedelta
import jwt
import pytest
from app.db import Uow
from app.domain import Error, now
from app.security import Issuer, Hasher, Limiter, create_keys
from app.services.auth import AuthService


def login(env,role='editor'):
    return env.rt.auth.login(role+'@example.org','test-password-long','127.0.0.1')


def test_password_and_jwt(env):
    pair=login(env)
    jwk=json.loads(env.config.jwt_public_path.read_text())['keys'][0]
    claims=jwt.decode(pair['access_token'],jwt.PyJWK.from_dict(jwk).key,algorithms=['RS256'],audience=env.config.jwt_audience,issuer=env.config.jwt_issuer)
    assert claims['exp']-claims['iat']==900
    assert claims['sub']==env.actors['editor']['id'] and claims['roles']==['editor']
    assert {'nbf','jti','role'} <= claims.keys()
    assert 'd' not in jwk and 'p' not in jwk
    assert env.people['editor']['password_hash'].startswith('$argon2id$')
    assert 'password_hash' not in env.auth.get('/api/v1/auth/me',headers=env.headers()).json()
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(pair['access_token'],jwt.PyJWK.from_dict(jwk).key,algorithms=['RS256'],audience='wrong')


def test_refresh_reuse_revokes_new_token(env):
    first=login(env); second=env.rt.auth.refresh(first['refresh_token'])
    assert first['refresh_token']!=second['refresh_token']
    with pytest.raises(Error,match='family revoked'):
        env.rt.auth.refresh(first['refresh_token'])
    with pytest.raises(Error):
        env.rt.auth.refresh(second['refresh_token'])
    with Uow() as u:
        rows=u.repo.find('refresh_sessions',user_id=env.actors['editor']['id'])
    assert all(row['token_hash'] not in (first['refresh_token'],second['refresh_token']) and row['revoked_at'] for row in rows)


def test_logout_password_block_and_last_admin(env):
    pair=login(env)
    env.rt.auth.logout(pair['refresh_token']);env.rt.auth.logout(pair['refresh_token'])
    with pytest.raises(Error): env.rt.auth.refresh(pair['refresh_token'])
    pair=login(env)
    env.rt.auth.password(env.actors['editor'],'test-password-long','replacement-password')
    with pytest.raises(Error): env.rt.auth.refresh(pair['refresh_token'])
    with pytest.raises(Error): login(env)
    pair=env.rt.auth.login('editor@example.org','replacement-password','local')
    env.rt.auth.patch_user(env.actors['editor']['id'],{'is_active':False})
    with pytest.raises(Error): env.rt.auth.refresh(pair['refresh_token'])
    with pytest.raises(Error): env.rt.auth.login('editor@example.org','replacement-password','local')
    with pytest.raises(Error,match='last active'): env.rt.auth.patch_user(env.actors['admin']['id'],{'role':'viewer'})


def test_logout_all_and_invalid_credentials(env):
    first=login(env); second=login(env)
    env.rt.auth.logout_all(env.actors['editor'])
    for token in (first,second):
        with pytest.raises(Error): env.rt.auth.refresh(token['refresh_token'])
    response=env.auth.post('/api/v1/auth/login',json={'email':'missing@example.org','password':'wrong'})
    assert response.status_code==401 and response.json()['error']['code']=='invalid_credentials'
    assert 'wrong' not in response.text


def test_gateway_and_admin_role(env):
    assert env.backend.get('/api/v1/corpora',headers={'X-User-ID':env.actors['admin']['id'],'X-User-Role':'admin'}).status_code==401
    assert env.auth.get('/api/v1/users',headers=env.headers('viewer')).status_code==403
    assert env.auth.get('/api/v1/users',headers=env.headers('admin')).status_code==200


def test_login_fails_closed_if_redis_unavailable(env):
    auth=AuthService(Uow,Hasher(),Issuer(env.config),Limiter('redis://127.0.0.1:1/0'))
    with pytest.raises(Error) as exc: auth.login('editor@example.org','test-password-long','local')
    assert exc.value.status==503


def test_key_rotation_overlap(env):
    first=login(env)['access_token'];before=env.config.jwt_key_path.read_bytes()
    create_keys(env.config)
    assert env.config.jwt_key_path.read_bytes()==before
    create_keys(env.config,rotate=True)
    keys=json.loads(env.config.jwt_public_path.read_text())['keys']
    assert len(keys)==2
    key=next(k for k in keys if k['kid']==jwt.get_unverified_header(first)['kid'])
    jwt.decode(first,jwt.PyJWK.from_dict(key).key,algorithms=['RS256'],audience=env.config.jwt_audience)
