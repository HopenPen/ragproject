from sqlalchemy import String, Boolean, DateTime, ForeignKey, Uuid, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.domain import now, uid


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint("role in ('viewer','editor','admin')"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str] = mapped_column(String(200), default='')
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class RefreshSession(Base):
    __tablename__ = 'refresh_sessions'
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    family_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
