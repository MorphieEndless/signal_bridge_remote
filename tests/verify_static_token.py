"""Verify optional static Bearer authentication without network or hardware."""
import os
import sys
import tempfile
from pathlib import Path

STATIC_TOKEN = "static-test-token-that-is-at-least-32-characters"
os.environ["SB_SECRET_KEY"] = "test-secret-key-for-verification-only"
os.environ["SB_STATIC_BEARER_TOKEN"] = STATIC_TOKEN
os.environ["SB_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config  # noqa: E402
from server.auth import create_token, verify_token  # noqa: E402

config.validate()
static_user = verify_token(STATIC_TOKEN)
assert static_user == {"user_id": "static-bearer-user", "username": "static-token"}
assert verify_token("wrong-static-token") is None

jwt_token = create_token("jwt-user", "jwt-name")
assert verify_token(jwt_token) == {"user_id": "jwt-user", "username": "jwt-name"}

print("static Bearer and JWT verification checks: OK")
