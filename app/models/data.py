from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, ForeignKey, UniqueConstraint, Uuid, JSON, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.domain import now, uid

J = JSON().with_variant(JSONB(), 'postgresql')


class Identified:
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class Corpus(Identified, Base):
    __tablename__ = 'corpora'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    split: Mapped[str] = mapped_column(String(32), default='custom')
    classification_mode: Mapped[str] = mapped_column(String(16), default='auto')
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class Document(Identified, Base):
    __tablename__ = 'documents'
    __table_args__ = (UniqueConstraint('corpus_id', 'publication_code'),)
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.id'), index=True)
    publication_code: Mapped[str] = mapped_column(String(80))
    original_filename: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    note: Mapped[str] = mapped_column(Text, default='')
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    classification_id: Mapped[str | None] = mapped_column(ForeignKey('classification_revisions.id', use_alter=True), nullable=True)


class Page(Identified, Base):
    __tablename__ = 'pages'
    __table_args__ = (UniqueConstraint('document_id', 'number'), CheckConstraint('number > 0'))
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text, default='')
    blocks: Mapped[list] = mapped_column(J, default=list)
    engine: Mapped[str] = mapped_column(String(64), default='pending')
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage: Mapped[str] = mapped_column(String(32), default='pending')
    image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    run_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)


class Artifact(Identified, Base):
    __tablename__ = 'artifacts'
    __table_args__ = (UniqueConstraint('document_id', 'run_id', 'kind', 'page', 'name'),)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(J, default=dict)


class Job(Identified, Base):
    __tablename__ = 'jobs'
    __table_args__ = (UniqueConstraint('corpus_id', 'idempotency_key'),)
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.id'), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(48), default='queued')
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64))
    input: Mapped[dict] = mapped_column(J)
    result: Mapped[dict] = mapped_column(J, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobItem(Identified, Base):
    __tablename__ = 'job_items'
    __table_args__ = (UniqueConstraint('job_id', 'document_id'),)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey('documents.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(48), default='queued')
    stage: Mapped[str] = mapped_column(String(32), default='inspect')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    progress: Mapped[dict] = mapped_column(J, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Outbox(Identified, Base):
    __tablename__ = 'outbox'
    item_id: Mapped[str] = mapped_column(ForeignKey('job_items.id'), unique=True)
    task_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), unique=True)
    dispatched: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Publication(Identified, Base):
    __tablename__ = 'publications'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), unique=True)
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.id'), index=True)
    current: Mapped[dict] = mapped_column(J, default=dict)


class PublicationRevision(Identified, Base):
    __tablename__ = 'publication_revisions'
    __table_args__ = (UniqueConstraint('publication_id', 'profile', 'number'), UniqueConstraint('publication_id', 'profile', 'run_id'))
    publication_id: Mapped[str] = mapped_column(ForeignKey('publications.id'), index=True)
    profile: Mapped[str] = mapped_column(String(16))
    number: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict] = mapped_column(J)
    origin: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    reason: Mapped[str] = mapped_column(Text)


class ClassificationRevision(Identified, Base):
    __tablename__ = 'classification_revisions'
    __table_args__ = (UniqueConstraint('document_id', 'number'), UniqueConstraint('document_id', 'run_id'))
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    decision: Mapped[dict] = mapped_column(J)
    provenance: Mapped[dict] = mapped_column(J, default=dict)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)


class Issue(Identified, Base):
    __tablename__ = 'issues'
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.id'), index=True)
    publication_id: Mapped[str] = mapped_column(ForeignKey('publications.id'))
    revision_id: Mapped[str] = mapped_column(ForeignKey('publication_revisions.id'))
    run_id: Mapped[str | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    profile: Mapped[str] = mapped_column(String(16))
    rule: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(J)
    review: Mapped[str] = mapped_column(String(16), default='open')


class AuditEntry(Identified, Base):
    __tablename__ = 'audit_entries'
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.id'), index=True)
    publication_id: Mapped[str | None] = mapped_column(ForeignKey('publications.id'), nullable=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey('documents.id'), nullable=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(J, default=dict)
