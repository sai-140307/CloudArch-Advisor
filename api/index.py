"""Vercel entry point.

Vercel runs this file as a Python serverless function (the same idea as AWS Lambda).
It translates each HTTP request into the Lambda-style event that backend/app.py
already understands, so the SAME application code runs on AWS Lambda and on Vercel.

Vercel profile: Google Gemini (key from the GEMINI_API_KEY environment variable),
BM25 retrieval over the bundled kb/ documents, in-memory request history.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("RETRIEVER", "bm25")
os.environ.setdefault("KB_DIR", os.path.join(ROOT, "kb"))
os.environ.setdefault("LLM_TIMEOUT", "50")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import app  # noqa: E402  (backend/app.py)


class handler(BaseHTTPRequestHandler):
    def _run(self, method):
        path = self.path.split("?", 1)[0] or "/"
        if path.startswith("/api/index"):          # direct hit on the function file
            path = "/" + path[len("/api/index"):].lstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else None
        event = {"rawPath": path, "body": body, "isBase64Encoded": False,
                 "headers": {k.lower(): v for k, v in self.headers.items()},
                 "requestContext": {"http": {"method": method}}}
        result = app.handler(event, None)
        if not isinstance(result, dict) or "statusCode" not in result:   # non-HTTP action
            result = {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                      "body": json.dumps(result)}
        payload = (result.get("body") or "").encode("utf-8")
        self.send_response(result["statusCode"])
        for k, v in (result.get("headers") or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(payload)

    def do_GET(self):
        self._run("GET")

    def do_HEAD(self):
        self._run("HEAD")

    def do_POST(self):
        self._run("POST")

    def do_OPTIONS(self):
        self._run("OPTIONS")
