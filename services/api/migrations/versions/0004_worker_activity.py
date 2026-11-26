"""Track worker activity until document processing and source reads finish."""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'


def upgrade():
    op.add_column('processing_jobs', sa.Column('worker_active', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('processing_jobs', 'worker_active')
