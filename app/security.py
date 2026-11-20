# Назначение файла: Argon2id, RS256/JWKS, key overlap и fail-closed Redis limiter.
import hashlib
import json
import secrets
from datetime import timedelta
from pathlib import Path
import jwt
import redis
from argon2 import PasswordHasher as ArgonHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from app.domain import now, uid, Error


class Hasher:
    def __init__(self):
        self.impl = ArgonHasher(time_cost=3, memory_cost=65536, parallelism=2)

    def hash(self, password):
        return self.impl.hash(password)

    def verify(self, hashed, password):
        try:
            return self.impl.verify(hashed, password)
        except (VerificationError, InvalidHashError):
            return False


def public_jwk(key):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    canonical = json.dumps({k: jwk[k] for k in ('e', 'kty', 'n')}, sort_keys=True, separators=(',', ':'))
    import base64
    jwk.update(kid=base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b'=').decode(), alg='RS256', use='sig')
    return jwk


def create_keys(config, rotate=False):
    path = config.jwt_key_path
    path.parent.mkdir(parents=True, exist_ok=True)
    config.jwt_public_path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not rotate:
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    previous = json.loads(config.jwt_public_path.read_text())['keys'] if config.jwt_public_path.exists() else []
    # Old public keys remain until operator runs prune after the 15-minute access TTL.
    result = {'keys': [public_jwk(key)] + previous}
    temp = path.with_suffix('.new')
    temp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    temp.chmod(0o600)
    public_temp = config.jwt_public_path.with_suffix('.new')
    public_temp.write_text(json.dumps(result), encoding='utf-8')
    public_temp.replace(config.jwt_public_path)
    temp.replace(path)


class Issuer:
    def __init__(self, config):
        self.config = config

    def issue(self, user):
        key = serialization.load_pem_private_key(self.config.jwt_key_path.read_bytes(), password=None)
        instant = now()
        return jwt.encode({'sub': user['id'], 'role': user['role'], 'roles': [user['role']],
                           'iss': self.config.jwt_issuer, 'aud': self.config.jwt_audience,
                           'iat': instant, 'nbf': instant, 'exp': instant + timedelta(minutes=15), 'jti': uid()},
                          key, algorithm='RS256', headers={'kid': public_jwk(key)['kid']})


class Limiter:
    def __init__(self, url):
        self.client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)

    def check(self, identity):
        key = 'login:' + hashlib.sha256(identity.encode()).hexdigest()
        try:
            count = self.client.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", 1, key)
        except redis.RedisError:
            raise Error(503, 'rate_limiter_unavailable', 'Login temporarily unavailable')
        if count > 10:
            raise Error(429, 'rate_limited', 'Too many login attempts')


def gateway_identity(config, headers):
    expected = config.gateway_secret.get_secret_value()
    if not expected or not secrets.compare_digest(headers.get('x-gateway-credential', ''), expected):
        raise Error(401, 'untrusted_gateway', 'Trusted gateway required')
    sub, role = headers.get('x-user-id'), headers.get('x-user-role')
    from uuid import UUID
    try:
        UUID(sub)
    except (ValueError, TypeError, AttributeError):
        raise Error(401, 'invalid_identity', 'Invalid identity')
    if role not in ('viewer', 'editor', 'admin'):
        raise Error(403, 'invalid_role', 'Invalid role')
    return {'id': sub, 'role': role}
