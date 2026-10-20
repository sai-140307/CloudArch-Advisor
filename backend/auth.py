"""Accounts and sessions.

- Passwords: PBKDF2-HMAC-SHA256, 120,000 iterations, 16-byte random salt per user.
- Sessions: stateless signed tokens (payload.signature, HMAC-SHA256), valid 7 days.
  The signing secret is AUTH_SECRET, or a value derived from other configured secrets.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

import store

_seed = (os.environ.get("AUTH_SECRET") or os.environ.get("GEMINI_API_KEY")
         or os.environ.get("KV_REST_API_TOKEN") or "cloudarch-dev-secret")
SECRET = hashlib.sha256(("cloudarch-auth:" + _seed).encode()).digest()
TOKEN_TTL = 7 * 24 * 3600
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")


class AuthError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)


def make_token(user):
    payload = _b64(json.dumps({"e": user["email"], "n": user["name"],
                               "x": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token):
    try:
        payload, sig = token.split(".", 1)
        good = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(payload))
        if data["x"] < time.time():
            return None
        return {"email": data["e"], "name": data["n"]}
    except Exception:
        return None


def user_from_headers(headers):
    h = {k.lower(): v for k, v in (headers or {}).items()}
    auth = h.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return verify_token(auth[7:].strip())
    return None


def signup(name, email, password):
    name, email = (name or "").strip()[:60], (email or "").strip().lower()
    if not name:
        raise AuthError("Enter your name.")
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if len(password or "") < 8:
        raise AuthError("Use a password of at least 8 characters.")
    key = f"user:{email}"
    if store.exists(key):
        raise AuthError("An account with this email already exists. Sign in instead.", 409)
    salt = secrets.token_bytes(16)
    store.set(key, {"name": name, "email": email, "salt": _b64(salt),
                    "hash": _b64(_hash(password, salt)), "created": int(time.time())})
    user = {"name": name, "email": email}
    return {"token": make_token(user), "user": user}


def login(email, password):
    email = (email or "").strip().lower()
    rec = store.get(f"user:{email}")
    if not rec or not hmac.compare_digest(_b64(_hash(password or "", _unb64(rec["salt"]))), rec["hash"]):
        msg = "Email or password is incorrect."
        if not store.PERSISTENT:
            msg += (" Accounts on this demo are kept in memory and reset when the server restarts."
                    " If you signed up earlier, create your account again.")
        raise AuthError(msg, 401)
    user = {"name": rec["name"], "email": rec["email"]}
    return {"token": make_token(user), "user": user}
