from sqlalchemy import select, text
from app.models.auth import User


class AuthRepository:
    def lock_admins(self):
        if self.session.bind.dialect.name == 'postgresql':
            self.session.execute(text('SELECT pg_advisory_xact_lock(8544321)'))
        list(self.session.scalars(select(User).where(User.role == 'admin').with_for_update()))
