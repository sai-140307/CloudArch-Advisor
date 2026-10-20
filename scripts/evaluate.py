#!/usr/bin/env python3
"""Evaluation harness: 8 startup scenarios x {RAG on, RAG off}.

Usage:  python3 scripts/evaluate.py https://xxxx.execute-api.us-east-1.amazonaws.com
Writes: eval_results.csv and eval_summary.md  (paste the table into your report).

Metrics (per option, then averaged):
  coverage    - share of REQUIRED components (compliance/feature rules) that the LLM chose
                on its own, BEFORE the guardrail layer added anything  (higher = better)
  invalid     - number of services the LLM invented that are not in the catalog (lower = better)
  in_budget   - share of options whose estimated cost fits the budget
  overall     - mean Well-Architected score (1-5)
  latency     - end-to-end seconds
"""
import csv, json, os, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from engine import required_components, normalise_req

SCENARIOS = [
 dict(name="EdTech MVP", app_type="Online learning platform", monthly_users=3000, budget=100, team_size=3, compliance="none", availability="99.9", needs_ai=True, description="Video lessons and quizzes for school students."),
 dict(name="Fintech wallet", app_type="Payments wallet", monthly_users=60000, budget=1500, team_size=8, compliance="pci", availability="99.99", needs_realtime=True, description="Card payments and instant transfers."),
 dict(name="HealthTech", app_type="Telemedicine platform", monthly_users=15000, budget=700, team_size=5, compliance="hipaa", availability="99.95", needs_ai=True, description="Video consultations and health records."),
 dict(name="E-commerce", app_type="Fashion e-commerce store", monthly_users=40000, budget=600, team_size=4, compliance="gdpr", availability="99.9", needs_search=True, description="Catalogue search, carts and weekend flash sales."),
 dict(name="SaaS B2B", app_type="B2B project management SaaS", monthly_users=8000, budget=300, team_size=6, compliance="soc2", availability="99.9", description="Teams, tasks, reports and integrations."),
 dict(name="Gaming", app_type="Mobile multiplayer game backend", monthly_users=250000, budget=4000, team_size=10, compliance="none", availability="99.9", needs_realtime=True, description="Leaderboards and live matches."),
 dict(name="Food delivery", app_type="Food delivery marketplace", monthly_users=30000, budget=500, team_size=5, compliance="gdpr", availability="99.9", needs_search=True, description="Restaurants, live order tracking and payments."),
 dict(name="Hobby blog", app_type="Content blog with newsletter", monthly_users=800, budget=20, team_size=1, compliance="none", availability="99", description="Static posts and email signup."),
]

def call(base, payload):
    r = urllib.request.Request(base.rstrip("/") + "/api/recommend", json.dumps(payload).encode(),
                               {"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(r, timeout=90) as f:
        j = json.load(f)
    return j, time.time() - t

def main(base):
    rows = []
    for sc in SCENARIOS:
        for rag in (True, False):
            payload = {k: v for k, v in sc.items() if k != "name"}; payload["use_rag"] = rag
            req = normalise_req(payload); need = set(required_components(req))
            try:
                j, lat = call(base, payload)
            except Exception as e:
                print("FAILED", sc["name"], rag, e); continue
            for o in j["options"]:
                raw = {x.lower() for x in o["raw_llm_components"]}
                cov = (len(need & raw) / len(need)) if need and o["source"] == "llm" else None
                rows.append(dict(scenario=sc["name"], rag=rag, option=o["name"], source=o["source"],
                                 coverage=cov, invalid=len(o["invalid_components"]),
                                 in_budget=int(o["within_budget"]), cost=o["monthly_cost"],
                                 overall=o["scores"]["overall"], latency=round(lat, 1)))
            print(f"{sc['name']:15} rag={rag!s:5} done ({lat:.1f}s)")
            time.sleep(13)  # stay under the app's 5 designs/minute limit and Gemini's free-tier limit
    with open("eval_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    def avg(rs, k):
        v = [r[k] for r in rs if r[k] is not None]; return sum(v) / len(v) if v else float("nan")
    lines = ["| Metric | RAG ON | RAG OFF |", "|---|---|---|"]
    for lab, k, fmt in [("Required-component coverage (LLM only, before guardrails)", "coverage", "{:.0%}"),
                        ("Invented services per option", "invalid", "{:.2f}"),
                        ("Options within budget", "in_budget", "{:.0%}"),
                        ("Mean Well-Architected score (1-5)", "overall", "{:.2f}"),
                        ("Mean latency per request (s)", "latency", "{:.1f}")]:
        on = fmt.format(avg([r for r in rows if r["rag"]], k)); off = fmt.format(avg([r for r in rows if not r["rag"]], k))
        lines.append(f"| {lab} | {on} | {off} |")
    fb = sum(r["source"] == "fallback" for r in rows)
    lines.append(f"\nOptions served by rule-based fallback (LLM failure): {fb} of {len(rows)}")
    open("eval_summary.md", "w").write("\n".join(lines)); print("\n" + "\n".join(lines))

if __name__ == "__main__":
    main(sys.argv[1])
