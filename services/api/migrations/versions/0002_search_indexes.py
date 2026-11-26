"""Support multiple embedding dimensions and index common owner-scoped lookups."""
from alembic import op

revision = '0002'
down_revision = '0001'


def upgrade():
    if op.get_context().dialect.name == 'postgresql':
        # Dropping the typmod keeps existing 1536-dimensional vectors intact.
        op.execute('ALTER TABLE document_embeddings ALTER COLUMN vector TYPE vector')
    op.create_index('ix_documents_owner_uploaded', 'documents', ['owner_id', 'uploaded_at'])
    op.create_index('ix_source_units_document_position', 'source_units', ['document_id', 'position'])
    op.create_index('ix_document_embeddings_model_document', 'document_embeddings', ['model', 'document_id'])


def downgrade():
    if op.get_context().dialect.name == 'postgresql':
        # Refuse to drop or truncate non-legacy vectors during a downgrade.
        op.execute('ALTER TABLE document_embeddings ALTER COLUMN vector TYPE vector(1536)')
    op.drop_index('ix_document_embeddings_model_document', table_name='document_embeddings')
    op.drop_index('ix_source_units_document_position', table_name='source_units')
    op.drop_index('ix_documents_owner_uploaded', table_name='documents')
