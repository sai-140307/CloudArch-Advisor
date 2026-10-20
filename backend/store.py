"""Tiny key-value store used for user accounts and saved designs.

If Upstash Redis (Vercel Marketplace -> Storage -> Upstash Redis) is connected, its REST
API is used and data survives restarts. Otherwise an in-memory store is used, which is
fine for a demo but is lost when the serverless instance is recycled.
"""
import json
import os
import time
import urllib.request

def _env(*suffixes):
    """Vercel's Upstash integration may add a custom prefix (e.g. STORAGE_KV_REST_API_URL)."""
    for s in suffixes:
        if os.environ.get(s):
            return os.environ[s]
    for k, v in os.environ.items():
        if v and any(k.endswith(s) for s in suffixes) and "READ_ONLY" not in k:
            return v
    return ""


URL = _env("KV_REST_API_URL", "UPSTASH_REDIS_REST_URL").rstrip("/")
TOKEN = _env("KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_TOKEN")
PERSISTENT = bool(URL and TOKEN)

_mem, _exp = {}, {}


def _redis(*args):
    req = urllib.request.Request(URL, json.dumps([str(a) for a in args]).encode(),
                                 {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as f:
        out = json.load(f)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out.get("result")


def _alive(k):
    if k in _exp and _exp[k] < time.time():
        _mem.pop(k, None)
        _exp.pop(k, None)
    return k in _mem


def get(key):
    if PERSISTENT:
        v = _redis("GET", key)
        return json.loads(v) if v else None
    return json.loads(_mem[key]) if _alive(key) else None


def set(key, value, ttl=None):
    v = json.dumps(value, default=str)
    if PERSISTENT:
        return _redis("SET", key, v, "EX", int(ttl)) if ttl else _redis("SET", key, v)
    _mem[key] = v
    if ttl:
        _exp[key] = time.time() + ttl


def exists(key):
    if PERSISTENT:
        return bool(_redis("EXISTS", key))
    return _alive(key)


def push_recent(key, value, keep=20):
    """Prepend to a list and keep only the newest `keep` entries."""
    v = json.dumps(value, default=str)
    if PERSISTENT:
        _redis("LPUSH", key, v)
        _redis("LTRIM", key, 0, keep - 1)
        return
    lst = json.loads(_mem.get(key, "[]"))
    lst.insert(0, value)
    _mem[key] = json.dumps(lst[:keep], default=str)


def recent(key, n=20):
    if PERSISTENT:
        return [json.loads(x) for x in (_redis("LRANGE", key, 0, n - 1) or [])]
    return json.loads(_mem.get(key, "[]"))[:n]


def incr_window(key, window_s):
    """Fixed-window counter: increment `key` and return (count, seconds_left_in_window)."""
    if PERSISTENT:
        n = int(_redis("INCR", key))
        if n == 1:
            _redis("EXPIRE", key, int(window_s))
        ttl = int(_redis("TTL", key) or window_s)
        return n, max(ttl, 1)
    now = time.time()
    if not _alive(key):
        _mem[key] = "0"
        _exp[key] = now + window_s
    n = int(_mem[key]) + 1
    _mem[key] = str(n)
    return n, max(int(_exp[key] - now), 1)
