"""
Optional admin password. With ADMIN_TOKEN set, every dashboard and settings endpoint requires
"Authorization: Bearer <token>"; without it the admin API is open, which is fine for the
default setup where the app only listens on this machine (see docker-compose.yml).
"""

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException


def admin_token() -> str:
    return os.getenv("ADMIN_TOKEN", "").strip()


def require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    """Dependency for the admin routers: refuse requests without the token, when one is set"""
    expected = admin_token()
    if not expected:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.strip().encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Admin token required",
                            headers={"WWW-Authenticate": "Bearer"})
