"""Explicit local operator reset from private environment configuration; never prints password."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/api'))
from sqlalchemy import select
from app.db import Session, User
from app.config import settings
from app.security import password_hash

if __name__ == '__main__':
    cfg = settings()
    if len(cfg.demo_password) < 12:
        raise SystemExit('DEMO_PASSWORD must have at least 12 characters')
    with Session() as db:
        user = db.scalar(select(User).where(User.username == cfg.demo_username))
        if not user:
            raise SystemExit('User not found; start the API first')
        user.password_hash = password_hash(cfg.demo_password)
        db.commit()
    print('Configured local user password reset. Rotate SESSION_SECRET and restart services to invalidate existing sessions.')
