from alembic import context
from sqlalchemy import create_engine
from app.db import Base
from app.config import settings, guard_migration


def check_direction():
    operation = context.get_context().opts.get('fn')
    guard_migration(settings().app_env, getattr(operation, '__name__', ''))

target_metadata = Base.metadata
if context.is_offline_mode():
    context.configure(url=settings().database_url, target_metadata=target_metadata, literal_binds=True)
    check_direction()
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(settings().database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        check_direction()
        with context.begin_transaction():
            context.run_migrations()
