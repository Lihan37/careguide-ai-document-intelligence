"""Keep retry candidates and replaced extraction snapshots with their jobs."""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'


def upgrade():
    op.add_column('processing_jobs', sa.Column('preserves_current', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('processing_jobs', sa.Column('candidate_status', sa.String(20)))
    op.add_column('processing_jobs', sa.Column('candidate', sa.JSON()))


def downgrade():
    op.drop_column('processing_jobs', 'candidate')
    op.drop_column('processing_jobs', 'candidate_status')
    op.drop_column('processing_jobs', 'preserves_current')
