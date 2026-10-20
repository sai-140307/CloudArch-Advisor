#!/usr/bin/env python3
"""Run CloudArch Advisor on your own computer (no AWS, no Vercel needed).

    export GEMINI_API_KEY=your_key      # Windows PowerShell:  $env:GEMINI_API_KEY="your_key"
    python3 scripts/run_local.py
    -> open http://localhost:8000

Uses the same Vercel entry point (api/index.py) and the same backend code.
"""
import importlib.util
import os
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vercel_entry", os.path.join(ROOT, "api", "index.py"))
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)

port = int(os.environ.get("PORT", "8000"))
print(f"CloudArch Advisor running on http://localhost:{port}  (Ctrl+C to stop)")
if not os.environ.get("GEMINI_API_KEY"):
    print("Note: GEMINI_API_KEY not set - recommendations will use the rule-based fallback.")
ThreadingHTTPServer(("0.0.0.0", port), entry.handler).serve_forever()
