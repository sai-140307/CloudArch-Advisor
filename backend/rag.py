"""Minimal, transparent RAG pipeline.

  S3 (markdown docs) -> chunk -> embed (Amazon Titan Text Embeddings v2) -> index.json in S3
  query -> embed -> cosine similarity -> top-k chunks -> prompt

Why not Bedrock Knowledge Bases? They need a vector store whose minimum cost is
too high for a student project (OpenSearch Serverless). Doing retrieval ourselves
keeps cost ~ $0 and makes every RAG step visible for the report.
If Titan is unreachable (or RETRIEVER=bm25), retrieval falls back to Okapi BM25
lexical ranking over the same chunks, so RAG still works in accounts where Bedrock
is blocked. The index records which retriever built it.
"""
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor

KB_BUCKET = os.environ.get("KB_BUCKET", "")
KB_PREFIX = os.environ.get("KB_PREFIX", "kb/")
INDEX_KEY = os.environ.get("INDEX_KEY", "index/index.json")
KB_DIR = os.environ.get("KB_DIR", "")            # local dir for tests
EMBED_MODEL = os.environ.get("EMBED_MODEL", "amazon.titan-embed-text-v2:0")
RETRIEVER = os.environ.get("RETRIEVER", "auto")
DIM = 512

_index = None        # in-memory cache across warm invocations
_s3 = _br = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def bedrock():
    global _br
    if _br is None:
        import boto3
        _br = boto3.client("bedrock-runtime")
    return _br


# ------------------------------------------------------------------ chunking
def chunk_markdown(title, text, max_words=140):
    """Split on headings, then pack paragraphs up to ~max_words."""
    sections = re.split(r"\n(?=#{1,3} )", text)
    chunks = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        paras, cur, n = re.split(r"\n\s*\n", sec), [], 0
        for p in paras:
            w = len(p.split())
            if cur and n + w > max_words:
                chunks.append("\n\n".join(cur))
                cur, n = [], 0
            cur.append(p)
            n += w
        if cur:
            chunks.append("\n\n".join(cur))
    return [{"source": title, "text": c} for c in chunks if len(c.split()) >= 8]


# ---------------------------------------------------------------- embeddings
STOP = set("a an the and or of to in for on with by is are be as at it this that from use your you can when".split())


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def bm25_scores(query, chunks, df, avgdl, k1=1.5, b=0.75):
    n = len(chunks)
    q = tokens(query)
    out = []
    for c in chunks:
        tf, dl, s = c["tf"], c["len"], 0.0
        for w in q:
            f = tf.get(w, 0)
            if f:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / avgdl))
        out.append(s)
    return out


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _titan_embed(text):
    body = json.dumps({"inputText": text[:8000], "dimensions": DIM, "normalize": True})
    r = bedrock().invoke_model(modelId=EMBED_MODEL, body=body,
                               contentType="application/json", accept="application/json")
    return json.loads(r["body"].read())["embedding"]


def embed_many(texts):
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(_titan_embed, texts))


def pick_embedder():
    if RETRIEVER == "bm25" or os.environ.get("FORCE_HASH_EMBED"):
        return "bm25"
    try:
        _titan_embed("test")
        return "titan"
    except Exception as e:  # no creds / no model access
        print("Titan embeddings unavailable, using BM25 retrieval:", repr(e)[:200])
        return "bm25"


# ------------------------------------------------------------------- loading
def load_docs():
    docs = []
    if KB_DIR:
        for fn in sorted(os.listdir(KB_DIR)):
            if fn.endswith((".md", ".txt")):
                with open(os.path.join(KB_DIR, fn), encoding="utf-8") as f:
                    docs.append((fn, f.read()))
        return docs
    paginator = s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=KB_BUCKET, Prefix=KB_PREFIX):
        for o in page.get("Contents", []):
            k = o["Key"]
            if k.endswith((".md", ".txt")):
                body = s3().get_object(Bucket=KB_BUCKET, Key=k)["Body"].read().decode("utf-8")
                docs.append((k.split("/")[-1], body))
    return docs


def build_index():
    """(Re)build the vector index. Called by the 'reindex' action after docs are uploaded."""
    global _index
    chunks = []
    for name, text in load_docs():
        chunks += chunk_markdown(name, text)
    embedder = pick_embedder()
    idx = {"embedder": embedder, "model": EMBED_MODEL if embedder == "titan" else "okapi-bm25",
           "n_chunks": len(chunks), "chunks": chunks}
    if embedder == "titan":
        for c, v in zip(chunks, embed_many([c["text"] for c in chunks])):
            c["vec"] = [round(x, 5) for x in v]
    else:
        df = {}
        for c in chunks:
            toks = tokens(c["source"].replace("_", " ") + " " + c["text"])
            c["len"] = len(toks)
            c["tf"] = {}
            for w in toks:
                c["tf"][w] = c["tf"].get(w, 0) + 1
            for w in c["tf"]:
                df[w] = df.get(w, 0) + 1
        idx["df"] = df
        idx["avgdl"] = sum(c["len"] for c in chunks) / max(len(chunks), 1)
    if KB_DIR:
        with open(os.path.join("/tmp", "index.json"), "w") as f:
            json.dump(idx, f)
    else:
        s3().put_object(Bucket=KB_BUCKET, Key=INDEX_KEY, Body=json.dumps(idx).encode(),
                        ContentType="application/json")
    _index = idx
    return {"embedder": embedder, "chunks": len(chunks), "docs": len(set(c["source"] for c in chunks))}


def get_index():
    global _index
    if _index is not None:
        return _index
    try:
        if KB_DIR:
            with open("/tmp/index.json") as f:
                _index = json.load(f)
        else:
            _index = json.loads(s3().get_object(Bucket=KB_BUCKET, Key=INDEX_KEY)["Body"].read())
    except Exception:
        build_index()      # first request after deploy: build lazily
    return _index


# ----------------------------------------------------------------- retrieval
def retrieve(query, k=6):
    idx = get_index()
    if idx["embedder"] == "titan":
        qv = _titan_embed(query)
        scored = [(sum(a * b for a, b in zip(qv, c["vec"])), c) for c in idx["chunks"]]
    else:
        s = bm25_scores(query, idx["chunks"], idx["df"], idx["avgdl"])
        scored = list(zip(s, idx["chunks"]))
    scored.sort(key=lambda x: -x[0])
    return [{"source": c["source"], "score": round(s, 3), "text": c["text"]} for s, c in scored[:k]]
