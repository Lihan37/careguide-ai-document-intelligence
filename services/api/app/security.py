import base64
import binascii
import hashlib
import hmac
import os
import time
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .db import User, get_db
from .config import settings


def password_hash(password):
    salt = os.urandom(16).hex()
    return salt + ':' + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def password_check(password, hashed):
    salt, expected = hashed.split(':')
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(expected, actual)


def token(user_id):
    body = base64.urlsafe_b64encode(f'{user_id}:{int(time.time()) + 28800}'.encode()).decode()
    return body + '.' + hmac.new(settings().session_secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def current_user(request: Request, db=Depends(get_db)):
    value = request.cookies.get('careguide_session', '')
    try:
        body, signature = value.split('.')
        expected = hmac.new(settings().session_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        user_id, expires = base64.urlsafe_b64decode(body).decode().split(':')
        if int(expires) < time.time():
            raise ValueError()
        user = db.get(User, user_id)
        if not user:
            raise ValueError()
        return user
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(401, 'Authentication required')


def reviewer(user=Depends(current_user)):
    if user.role not in {'reviewer', 'admin'}:
        raise HTTPException(403, 'Reviewer role required')
    return user
