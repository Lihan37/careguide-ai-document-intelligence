import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, ForeignKey, String, Text, JSON, DateTime, Integer, Float, Boolean, Index, event, false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default='reviewer')


class Document(Base):
    __tablename__ = 'documents'
    __table_args__ = (Index('ix_documents_owner_uploaded', 'owner_id', 'uploaded_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    status: Mapped[str] = mapped_column(String(30), default='QUEUED', index=True)
    text: Mapped[str] = mapped_column(Text, default='')
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    corrected: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    extraction_method: Mapped[str] = mapped_column(String(60), default='pending')
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    sheet_count: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    invoice_number: Mapped[str | None] = mapped_column(String(255), index=True)
    supplier: Mapped[str | None] = mapped_column(String(255), index=True)
    review_status: Mapped[str] = mapped_column(String(30), default='pending')


class SourceUnit(Base):
    __tablename__ = 'source_units'
    __table_args__ = (Index('ix_source_units_document_position', 'document_id', 'position'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class Job(Base):
    __tablename__ = 'processing_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    status: Mapped[str] = mapped_column(String(30), default='QUEUED', index=True)
    stage: Mapped[str] = mapped_column(String(100), default='Queued')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    pages_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    preserves_current: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    worker_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    candidate_status: Mapped[str | None] = mapped_column(String(20))
    candidate: Mapped[dict | None] = mapped_column(JSON, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    error: Mapped[str | None] = mapped_column(Text)


class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str | None] = mapped_column(ForeignKey('documents.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Comparison(Base):
    __tablename__ = 'document_comparisons'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    document_ids: Mapped[list] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Embedding(Base):
    __tablename__ = 'document_embeddings'
    __table_args__ = (Index('ix_document_embeddings_model_document', 'model', 'document_id'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    source: Mapped[dict] = mapped_column(JSON)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    from pgvector.sqlalchemy import Vector
    vector = mapped_column(Vector().with_variant(Vector(1536), 'sqlite'))


engine = create_engine(settings().database_url, **({'connect_args': {'check_same_thread': False, 'timeout': 30}} if settings().database_url.startswith('sqlite') else {'pool_pre_ping': True}))
if settings().database_url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_setup(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
Session = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with Session() as session:
        yield session
