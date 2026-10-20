"""Prompt construction and LLM call (Amazon Bedrock Converse API, or Google Gemini as a fallback provider)."""
import json
import os
import re
import urllib.error
import urllib.request

from catalog import CATALOG

PROVIDER = os.environ.get("LLM_PROVIDER", "bedrock")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "22"))
# tried in order if the configured model name is retired (HTTP 404)
GEMINI_FALLBACKS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
# 404 = model retired, 429 = quota for that model used up, 5xx = model overloaded -> try the next model
NEXT_MODEL_CODES = {404, 429, 500, 502, 503, 504}
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_ID = os.environ.get("MODEL_ID", "amazon.nova-lite-v1:0") if PROVIDER == "bedrock" else GEMINI_MODEL
_br = None

SYSTEM = (
    "You are a senior AWS Solutions Architect advising early-stage startups. "
    "You design architectures strictly using the AWS component IDs from the provided catalog. "
    "You follow the AWS Well-Architected Framework. Answer with a single valid JSON object and nothing else."
)


def bedrock():
    global _br
    if _br is None:
        import boto3
        from botocore.config import Config
        # Fail fast (< API Gateway's 30 s limit) so the rule-based fallback can answer.
        _br = boto3.client("bedrock-runtime", config=Config(
            read_timeout=LLM_TIMEOUT, connect_timeout=4, retries={"max_attempts": 1}))
    return _br


def catalog_text():
    return "\n".join(f"- {k}: {v['name']} - {v['desc']}" for k, v in CATALOG.items())


def build_prompt(req, passages):
    ctx = ""
    if passages:
        ctx = "REFERENCE KNOWLEDGE (retrieved from the knowledge base; ground your decisions in it):\n"
        for i, p in enumerate(passages, 1):
            ctx += f"[{i}] ({p['source']}) {p['text']}\n\n"
    flags = [k.replace("needs_", "") for k in ("needs_ai", "needs_search", "needs_realtime") if req.get(k)]
    return f"""{ctx}
STARTUP REQUIREMENTS
- Application type: {req['app_type']}
- Description: {req['description'] or 'n/a'}
- Expected monthly active users: {req['monthly_users']}
- Monthly infrastructure budget (USD): {req['budget']}
- Compliance need: {req['compliance']}
- Engineering team size: {req['team_size']}
- Target availability: {req['availability']}%
- Special features: {', '.join(flags) or 'none'}

COMPONENT CATALOG (use ONLY these ids):
{catalog_text()}

TASK
Propose exactly three architectures named "Low-cost", "Balanced" and "High-availability".
For each give: "components" (list of catalog ids), "reasoning" (2-3 sentences explaining why these
services fit THIS startup, referencing Well-Architected pillars), and "tradeoffs" (1-2 sentences).
Consider the team size (small teams should prefer managed/serverless services) and the budget.
Return JSON exactly in this shape:
{{"options":[{{"name":"Low-cost","components":["id",...],"reasoning":"...","tradeoffs":"..."}},
{{"name":"Balanced",...}},{{"name":"High-availability",...}}]}}"""


def call_llm(prompt):
    return _gemini(prompt) if PROVIDER == "gemini" else _bedrock(prompt)


def _gemini(prompt):
    """Try the configured model, then fallbacks if a model is retired, over quota or overloaded.
    Thinking is switched off / set low: architecture JSON does not need long reasoning
    and thinking tokens made responses exceed the API timeout."""
    import time
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    deadline, last = time.time() + LLM_TIMEOUT, None
    for model in [GEMINI_MODEL] + [m for m in GEMINI_FALLBACKS if m != GEMINI_MODEL]:
        for thinking in (True, False):          # retry once without thinkingConfig if rejected (400)
            left = deadline - time.time()
            if left < 5:
                raise last or RuntimeError("Gemini timed out")
            try:
                return _gemini_call(model, prompt, thinking, min(left, 45))
            except TimeoutError:
                last = RuntimeError(f"Gemini {model} timed out")
                print(last)
                break
            except urllib.error.HTTPError as e:
                last = RuntimeError(f"Gemini {model} HTTP {e.code}: {e.read()[:300]!r}")
                print(last)
                if e.code == 400 and thinking:
                    continue
                if e.code in NEXT_MODEL_CODES:
                    break
                raise last
            except urllib.error.URLError as e:      # network error / connect timeout
                last = RuntimeError(f"Gemini {model} network error: {e.reason}")
                print(last)
                break
    raise last


def _gemini_call(model, prompt, thinking, timeout):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    cfg = {"temperature": 0.2, "maxOutputTokens": 3000, "responseMimeType": "application/json"}
    if thinking:
        cfg["thinkingConfig"] = ({"thinkingBudget": 0} if model.startswith("gemini-2.5-flash")
                                 else {"thinkingLevel": "low"})
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": cfg}
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        j = json.load(f)
    print(f"Gemini model used: {model}")
    return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))


def _bedrock(prompt):
    r = bedrock().converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0.2},
    )
    return r["output"]["message"]["content"][0]["text"]


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0) if m else text)
