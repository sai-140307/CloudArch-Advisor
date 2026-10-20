"""AWS Lambda entry point (behind API Gateway HTTP API).

Routes
  GET  /                -> web UI (index.html)
  POST /api/recommend   -> run the full pipeline
  GET  /api/history     -> last requests from DynamoDB
  GET  /api/health      -> config / status
  (direct invoke) {"action": "reindex"} -> rebuild the vector index
"""
import base64
import json
import os
import time
import uuid
from decimal import Decimal

import engine
import llm
import rag

TABLE = os.environ.get("TABLE_NAME", "")
HERE = os.path.dirname(os.path.abspath(__file__))
MOCK = bool(os.environ.get("MOCK_LLM"))
_ddb = None
_mem_history = []   # used when neither DynamoDB nor S3 is configured (e.g. Vercel)


def table():
    global _ddb
    if _ddb is None:
        import boto3
        _ddb = boto3.resource("dynamodb").Table(TABLE)
    return _ddb


def resp(code, body, ctype="application/json"):
    return {"statusCode": code,
            "headers": {"Content-Type": ctype, "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "no-store"},
            "body": body if isinstance(body, str) else json.dumps(body, default=str)}


def recommend(raw):
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

    # 3. Validate + guardrails + cost + score + diagram (deterministic)
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

    result = {
        "id": uuid.uuid4().hex[:12],
        "requirements": req,
        "options": options,
        "sources": [{"source": p["source"], "score": p["score"], "text": p["text"][:300]} for p in passages],
        "model": llm.MODEL_ID,
        "provider": llm.PROVIDER,
        "retriever": (rag._index or {}).get("model"),
        "llm_error": llm_error,
        "timings": {**timings, "total_s": round(time.time() - t0, 2)},
    }
    rec = {"id": result["id"], "ts": int(time.time()),
           "app_type": req["app_type"], "users": req["monthly_users"],
           "budget": req["budget"], "compliance": req["compliance"],
           "use_rag": req["use_rag"],
           "summary": [{"name": o["name"], "cost": o["monthly_cost"], "overall": o["scores"]["overall"]}
                       for o in options]}
    try:
        if TABLE:
            table().put_item(Item=json.loads(json.dumps(rec), parse_float=Decimal))
        elif rag.KB_BUCKET:
            # History store fallback for accounts without DynamoDB: one JSON object per request in S3.
            rag.s3().put_object(Bucket=rag.KB_BUCKET, Key=f"history/{9999999999 - rec['ts']}-{rec['id']}.json",
                                Body=json.dumps(rec).encode(), ContentType="application/json")
        else:
            _mem_history.insert(0, rec)
            del _mem_history[10:]
    except Exception as e:
        print("History write failed:", repr(e))
    return result


def history():
    if TABLE:
        items = table().scan(Limit=50).get("Items", [])
        items.sort(key=lambda x: -int(x.get("ts", 0)))
        return items[:10]
    if not rag.KB_BUCKET:
        return list(_mem_history)
    # keys are reverse-timestamped, so the first 10 listed are the newest
    objs = rag.s3().list_objects_v2(Bucket=rag.KB_BUCKET, Prefix="history/", MaxKeys=10).get("Contents", [])
    return [json.loads(rag.s3().get_object(Bucket=rag.KB_BUCKET, Key=o["Key"])["Body"].read()) for o in objs]


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
    try:
        if method == "OPTIONS":
            return resp(204, "")
        if method == "GET" and path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                return resp(200, f.read(), "text/html; charset=utf-8")
        if method == "GET" and path == "/api/health":
            return resp(200, {"ok": True, "provider": llm.PROVIDER, "model": llm.MODEL_ID,
                              "retriever": rag.RETRIEVER, "kb_bucket": rag.KB_BUCKET or None,
                              "gemini_key_set": bool(llm.GEMINI_KEY)})
        if method == "GET" and path == "/api/history":
            return resp(200, history())
        if method == "POST" and path == "/api/recommend":
            body = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode()
            return resp(200, recommend(json.loads(body)))
        return resp(404, {"error": "not found"})
    except Exception as e:
        print("ERROR", repr(e))
        return resp(500, {"error": str(e)[:300]})
