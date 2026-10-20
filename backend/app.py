"""HTTP entry point (AWS Lambda event format; Vercel adapts to it in api/index.py).

Routes
  GET  /                      web UI (index.html)
  POST /api/auth/signup       {name, email, password} -> {token, user}
  POST /api/auth/login        {email, password}       -> {token, user}
  GET  /api/auth/me           current user (Bearer token)
  POST /api/recommend         run the full pipeline (saved to the user's designs)
  GET  /api/history           the user's recent designs (guest designs when signed out)
  GET  /api/design/<id>       one saved design in full
  POST /api/ask               follow-up question about a design (RAG + LLM)
  GET  /api/kb                knowledge-base documents
  GET  /api/health            configuration / status
  Rate limits per visitor: 5 designs/min and 60/day, 10 questions/min, 10 sign-in attempts/min (HTTP 429)
  (direct invoke) {"action": "reindex"} | {"action": "selftest"}
"""
import base64
import json
import os
import re
import time
import uuid
from decimal import Decimal

import auth
import engine
import llm
import rag
import store

TABLE = os.environ.get("TABLE_NAME", "")
HERE = os.path.dirname(os.path.abspath(__file__))
MOCK = bool(os.environ.get("MOCK_LLM"))
DESIGN_TTL = 30 * 24 * 3600
_ddb = None

# Rate limits per visitor (signed-in user, else IP address): (requests, window in seconds).
# They protect the free AI quota and keep one visitor from slowing the service for others.
LIMITS = {
    "recommend": [(int(os.environ.get("RL_DESIGNS_PER_MIN", "5")), 60),
                  (int(os.environ.get("RL_DESIGNS_PER_DAY", "60")), 86400)],
    "ask": [(int(os.environ.get("RL_ASKS_PER_MIN", "10")), 60)],
    "auth": [(int(os.environ.get("RL_AUTH_PER_MIN", "10")), 60)],
}


class RateLimited(Exception):
    def __init__(self, msg, retry):
        super().__init__(msg)
        self.retry = retry


def client_id(event, user):
    if user:
        return "u:" + user["email"]
    h = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    ip = (h.get("x-forwarded-for", "").split(",")[0].strip() or h.get("x-real-ip", "")
          or event.get("requestContext", {}).get("http", {}).get("sourceIp", "") or "unknown")
    return "ip:" + ip


def check_rate(kind, who):
    for limit, window in LIMITS[kind]:
        try:
            n, left = store.incr_window(f"rl:{kind}:{window}:{who}:{int(time.time() // window)}", window)
        except Exception as e:          # never block users because the counter store failed
            print("Rate limit check failed:", repr(e))
            return
        if n > limit:
            what = {"recommend": "designs", "ask": "questions", "auth": "sign-in attempts"}[kind]
            per = "minute" if window == 60 else "day"
            wait = f"{left} seconds" if left < 120 else f"{round(left / 3600, 1)} hours"
            raise RateLimited(f"You have reached the limit of {limit} {what} per {per}. Try again in {wait}.", left)


def table():
    global _ddb
    if _ddb is None:
        import boto3
        _ddb = boto3.resource("dynamodb").Table(TABLE)
    return _ddb


def resp(code, body, ctype="application/json"):
    return {"statusCode": code,
            "headers": {"Content-Type": ctype, "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization",
                        "Cache-Control": "no-store"},
            "body": body if isinstance(body, str) else json.dumps(body, default=str)}


def owner_key(user):
    return f"designs:{user['email']}" if user else "designs:guest"


# ------------------------------------------------------------------ pipeline
def recommend(raw, user=None):
    t0 = time.time()
    req = engine.normalise_req(raw)
    timings = {}

    # 1. Retrieve
    passages, t = [], time.time()
    if req["use_rag"]:
        q = (f"AWS architecture for {req['app_type']} startup, {req['monthly_users']} users, "
             f"budget ${req['budget']}, compliance {req['compliance']}, team of {req['team_size']}. "
             f"{req['description']}")
        try:
            passages = rag.retrieve(q, k=6)
        except Exception as e:
            print("RAG failed:", repr(e))
    timings["retrieve_s"] = round(time.time() - t, 2)

    # 2. Generate
    llm_opts, llm_error, t = {}, None, time.time()
    if not MOCK:
        try:
            out = llm.parse_json(llm.call_llm(llm.build_prompt(req, passages)))
            for o in out.get("options", []):
                llm_opts[str(o.get("name", "")).strip().lower()] = o
        except Exception as e:
            llm_error = repr(e)[:300]
            print("LLM failed:", llm_error)
    else:
        llm_error = "MOCK_LLM enabled"
    timings["generate_s"] = round(time.time() - t, 2)

    # 3. Validate + guardrails + cost + score + diagram + IaC (deterministic)
    options = []
    for name in ("Low-cost", "Balanced", "High-availability"):
        o = llm_opts.get(name.lower())
        if o and isinstance(o.get("components"), list):
            valid, invalid = engine.validate(o["components"])
            if len(valid) >= 3:
                options.append(engine.build_option(
                    name, valid, req, str(o.get("reasoning", ""))[:900],
                    str(o.get("tradeoffs", ""))[:500], "llm", invalid, o["components"]))
                continue
        options.append(engine.fallback_option(name, req))

    # Recommended = best overall score among options that fit the budget (else the cheapest)
    fits = [o for o in options if o["within_budget"]]
    best = max(fits, key=lambda o: o["scores"]["overall"]) if fits else min(options, key=lambda o: o["monthly_cost"])

    result = {
        "id": uuid.uuid4().hex[:12],
        "created": int(time.time()),
        "owner": user["name"] if user else "Guest",
        "requirements": req,
        "options": options,
        "recommended": best["name"],
        "sources": [{"source": p["source"], "score": p["score"], "text": p["text"][:400]} for p in passages],
        "model": llm.MODEL_ID,
        "provider": llm.PROVIDER,
        "retriever": (rag._index or {}).get("model"),
        "llm_error": llm_error,
        "timings": {**timings, "total_s": round(time.time() - t0, 2)},
    }
    summary = {"id": result["id"], "ts": result["created"], "app_type": req["app_type"],
               "users": req["monthly_users"], "budget": req["budget"], "compliance": req["compliance"],
               "use_rag": req["use_rag"], "recommended": best["name"],
               "summary": [{"name": o["name"], "cost": o["monthly_cost"], "overall": o["scores"]["overall"]}
                           for o in options]}
    try:
        store.set(f"design:{result['id']}", result, ttl=DESIGN_TTL)
        store.push_recent(owner_key(user), summary)
    except Exception as e:
        print("Design save failed:", repr(e))
    try:   # AWS audit log (DynamoDB in the full profile, S3 in the Academy profile)
        if TABLE:
            table().put_item(Item=json.loads(json.dumps(summary), parse_float=Decimal))
        elif rag.KB_BUCKET:
            rag.s3().put_object(Bucket=rag.KB_BUCKET, Key=f"history/{9999999999 - summary['ts']}-{summary['id']}.json",
                                Body=json.dumps(summary).encode(), ContentType="application/json")
    except Exception as e:
        print("Audit write failed:", repr(e))
    return result


# --------------------------------------------------------------- ask the architect
ASK_SYSTEM = (
    "You are a senior AWS Solutions Architect answering follow-up questions from a startup team about an "
    "architecture you recommended. Be concrete and practical, name AWS services exactly, and stay under "
    "170 words. Use short paragraphs or a few '-' bullet lines; no markdown headings, no tables. "
    "If the question is unrelated to cloud architecture, say so in one sentence.")


def ask(body):
    q = str(body.get("question", "")).strip()[:500]
    if not q:
        return {"answer": "Type a question about this architecture first.", "sources": []}
    opt = body.get("option") or {}
    req = body.get("requirements") or {}
    comps = ", ".join(c.get("name", "") for c in (opt.get("components") or [])[:30])
    try:
        passages = rag.retrieve(q, k=4)
    except Exception:
        passages = []
    ctx = "\n".join(f"[{i}] ({p['source']}) {p['text']}" for i, p in enumerate(passages, 1))
    prompt = (f"Reference knowledge:\n{ctx}\n\n"
              f"Startup: {req.get('app_type', '')}; {req.get('monthly_users', '')} monthly users; "
              f"budget ${req.get('budget', '')}/month; compliance {req.get('compliance', 'none')}.\n"
              f"Chosen option: {opt.get('name', '')} (~${opt.get('monthly_cost', '?')}/month) with: {comps}.\n"
              f"Why it was chosen: {str(opt.get('reasoning', ''))[:600]}\n\nQuestion: {q}")
    try:
        if MOCK:
            raise RuntimeError("MOCK_LLM enabled")
        answer = llm.call_llm(prompt, json_mode=False, system=ASK_SYSTEM).strip()
    except Exception as e:
        print("Ask failed:", repr(e))
        answer = ("The AI model is not reachable right now. These knowledge-base passages are the most "
                  "relevant to your question:\n" + "\n".join(
                      "- " + re.sub(r"\s+", " ", re.sub(r"(?m)^#+.*$", "", p["text"])).strip()[:220] + "…"
                      for p in passages[:3]))
    return {"answer": answer, "sources": [{"source": p["source"], "score": p["score"]} for p in passages]}


# --------------------------------------------------------------- knowledge base
def kb_docs():
    out = []
    for name, text in rag.load_docs():
        m = re.search(r"^#\s+(.+)$", text, flags=re.M)
        out.append({"name": name, "title": m.group(1).strip() if m else name,
                    "words": len(text.split()), "text": text})
    return out


# --------------------------------------------------------------- router
def handler(event, context):
    if event.get("action") == "reindex":
        return rag.build_index()
    if event.get("action") == "selftest":
        out = {"model": llm.MODEL_ID, "embed_model": rag.EMBED_MODEL}
        try:
            llm.call_llm('Reply with the JSON {"ok": true}')
            out["llm"] = "ok"
        except Exception as e:
            out["llm"] = repr(e)[:300]
        try:
            rag._titan_embed("test")
            out["embeddings"] = "ok"
        except Exception as e:
            out["embeddings"] = repr(e)[:300]
        return out

    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    user = auth.user_from_headers(event.get("headers"))

    def body():
        b = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            b = base64.b64decode(b).decode()
        return json.loads(b)

    try:
        if method == "OPTIONS":
            return resp(204, "")
        if method == "GET" and path in ("/", "/index.html", "/login", "/app"):
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                return resp(200, f.read(), "text/html; charset=utf-8")
        if method == "GET" and path == "/api/health":
            return resp(200, {"ok": True, "provider": llm.PROVIDER, "model": llm.MODEL_ID,
                              "retriever": rag.RETRIEVER, "kb_bucket": rag.KB_BUCKET or None,
                              "gemini_key_set": bool(llm.GEMINI_KEY),
                              "persistent_store": store.PERSISTENT})
        if method == "POST" and path in ("/api/auth/signup", "/api/auth/login"):
            check_rate("auth", client_id(event, None))
        if method == "POST" and path == "/api/auth/signup":
            b = body()
            return resp(200, auth.signup(b.get("name"), b.get("email"), b.get("password")))
        if method == "POST" and path == "/api/auth/login":
            b = body()
            return resp(200, auth.login(b.get("email"), b.get("password")))
        if method == "GET" and path == "/api/auth/me":
            return resp(200, {"user": user}) if user else resp(401, {"error": "Not signed in."})
        if method == "POST" and path == "/api/recommend":
            check_rate("recommend", client_id(event, user))
            return resp(200, recommend(body(), user))
        if method == "GET" and path == "/api/history":
            return resp(200, store.recent(owner_key(user), 20))
        if method == "GET" and path.startswith("/api/design/"):
            d = store.get(f"design:{path.rsplit('/', 1)[-1][:24]}")
            return resp(200, d) if d else resp(404, {"error": "This design has expired or does not exist."})
        if method == "POST" and path == "/api/ask":
            check_rate("ask", client_id(event, user))
            return resp(200, ask(body()))
        if method == "GET" and path == "/api/kb":
            return resp(200, kb_docs())
        return resp(404, {"error": "not found"})
    except auth.AuthError as e:
        return resp(e.code, {"error": str(e)})
    except RateLimited as e:
        r = resp(429, {"error": str(e), "retry_after": e.retry})
        r["headers"]["Retry-After"] = str(e.retry)
        return r
    except Exception as e:
        print("ERROR", repr(e))
        return resp(500, {"error": str(e)[:300]})
