import hashlib
import secrets
from datetime import timedelta, timezone
from app.domain import Error, now, uid


def safe_user(user):
    return {k: v for k, v in user.items() if k != 'password_hash'}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, uow_factory, hasher, issuer, limiter):
        self.uow, self.hasher, self.issuer, self.limiter = uow_factory, hasher, issuer, limiter
        self.dummy = hasher.hash(secrets.token_hex(20))

    def pair(self, repo, user, family=None):
        refresh = secrets.token_urlsafe(32)
        repo.add('refresh_sessions', user_id=user['id'], family_id=family or uid(),
                 token_hash=token_hash(refresh), expires_at=now() + timedelta(days=7))
        return {'access_token': self.issuer.issue(user), 'refresh_token': refresh,
                'expires_in': 900, 'token_type': 'bearer'}

    def login(self, email, password, ip):
        self.limiter.check(ip + ':' + email.casefold())
        self.limiter.check('ip:' + ip)
        with self.uow() as u:
            users = u.repo.find('users', email=email.casefold())
            user = users[0] if users else None
            valid = self.hasher.verify(user['password_hash'] if user else self.dummy, password)
            if not user or not valid or not user['is_active']:
                raise Error(401, 'invalid_credentials', 'Invalid email or password')
            result = self.pair(u.repo, user)
            u.commit()
            return result

    def revoke(self, repo, user_id=None, family_id=None):
        for session in repo.find('refresh_sessions', **({'user_id': user_id} if user_id else {'family_id': family_id})):
            repo.update('refresh_sessions', session['id'], revoked_at=now())

    def refresh(self, token):
        with self.uow() as u:
            sessions = u.repo.find('refresh_sessions', token_hash=token_hash(token))
            if not sessions:
                raise Error(401, 'invalid_refresh', 'Invalid refresh token')
            # Every refresh/revocation locks the user first, then reloads the session.
            # This serializes concurrent rotation, reuse, password change and logout-all.
            user = u.repo.get('users', sessions[0]['user_id'], lock=True)
            session = u.repo.get('refresh_sessions', sessions[0]['id'], lock=True)
            if session['used_at'] or session['revoked_at']:
                self.revoke(u.repo, family_id=session['family_id'])
                u.commit()
                raise Error(401, 'refresh_reuse', 'Refresh family revoked')
            expires = session['expires_at'].replace(tzinfo=timezone.utc)
            if expires <= now() or not user['is_active']:
                raise Error(401, 'invalid_refresh', 'Invalid refresh token')
            u.repo.update('refresh_sessions', session['id'], used_at=now())
            result = self.pair(u.repo, user, session['family_id'])
            u.commit()
            return result

    def logout(self, token):
        with self.uow() as u:
            sessions = u.repo.find('refresh_sessions', token_hash=token_hash(token))
            if sessions:
                u.repo.get('users', sessions[0]['user_id'], lock=True)
                self.revoke(u.repo, family_id=sessions[0]['family_id'])
            u.commit()

    def logout_all(self, actor):
        with self.uow() as u:
            u.repo.get('users', actor['id'], lock=True)
            self.revoke(u.repo, user_id=actor['id'])
            u.commit()

    def password(self, actor, old, new):
        with self.uow() as u:
            user = u.repo.get('users', actor['id'], lock=True)
            if not user or not self.hasher.verify(user['password_hash'], old):
                raise Error(401, 'invalid_credentials', 'Invalid password')
            u.repo.update('users', actor['id'], password_hash=self.hasher.hash(new))
            self.revoke(u.repo, user_id=actor['id'])
            u.commit()

    def create_user(self, values):
        with self.uow() as u:
            email = str(values['email']).casefold()
            if u.repo.find('users', email=email):
                raise Error(409, 'email_exists', 'Email already exists')
            user = u.repo.add('users', email=email, password_hash=self.hasher.hash(values['password']),
                              display_name=values['display_name'], role=values['role'])
            u.commit()
            return safe_user(user)

    def patch_user(self, id, changes):
        with self.uow() as u:
            u.repo.lock_admins()
            user = u.repo.get('users', id, lock=True)
            if not user:
                raise Error(404, 'not_found', 'User not found')
            updated = {**user, **changes}
            if user['role'] == 'admin' and user['is_active'] and (updated['role'] != 'admin' or not updated['is_active']):
                if len(u.repo.find('users', role='admin', is_active=True)) <= 1:
                    raise Error(409, 'last_admin', 'Cannot disable the last active administrator')
            result = u.repo.update('users', id, **changes)
            if not result['is_active']:
                self.revoke(u.repo, user_id=id)
            u.commit()
            return safe_user(result)
