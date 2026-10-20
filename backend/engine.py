"""Deterministic parts of the advisor: validation, guardrails, cost, scoring, diagram.

The LLM only *chooses* components and *explains* the choice. Everything that has to
be correct (prices, scores, compliance rules, diagram syntax) is computed here, so
a hallucinating model cannot produce an invalid or unsafe architecture.
"""
import iac
from catalog import (CATALOG, BLUEPRINTS, COMPLIANCE_REQUIRED, FEATURE_COMPONENTS,
                     tier_for)

PILLARS = [
    ("ops", "Operational Excellence"),
    ("sec", "Security"),
    ("rel", "Reliability"),
    ("perf", "Performance Efficiency"),
    ("cost", "Cost Optimization"),
    ("sus", "Sustainability"),
]


def normalise_req(r: dict) -> dict:
    users = int(float(r.get("monthly_users") or 1000))
    return {
        "app_type": (r.get("app_type") or "web application").strip()[:80],
        "description": (r.get("description") or "").strip()[:800],
        "monthly_users": max(users, 1),
        "budget": max(float(r.get("budget") or 200), 1.0),
        "compliance": (r.get("compliance") or "none").lower(),
        "team_size": int(float(r.get("team_size") or 3)),
        "availability": (r.get("availability") or "99.9").strip(),
        "needs_ai": bool(r.get("needs_ai")),
        "needs_search": bool(r.get("needs_search")),
        "needs_realtime": bool(r.get("needs_realtime")),
        "use_rag": r.get("use_rag", True) not in (False, "false", "0", 0),
    }


def required_components(req: dict) -> list:
    out = list(COMPLIANCE_REQUIRED.get(req["compliance"], []))
    for flag, comps in FEATURE_COMPONENTS.items():
        if req.get(flag):
            out += comps
    return out


def validate(ids):
    """Split LLM-proposed ids into (valid, invalid). Invalid = hallucinated services."""
    valid, invalid, seen = [], [], set()
    for i in ids or []:
        i = str(i).strip().lower()
        if i in seen:
            continue
        seen.add(i)
        (valid if i in CATALOG else invalid).append(i)
    return valid, invalid


def apply_guardrails(ids, req):
    """Enforce compliance/feature requirements and sanity rules.

    Returns (final_ids, added_by_guardrail, notes)."""
    final, added, notes = list(ids), [], []
    for c in required_components(req):
        if c not in final:
            final.append(c)
            added.append(c)
    if added:
        notes.append("Guardrail added required components for compliance/features: "
                     + ", ".join(CATALOG[a]["name"] for a in added))
    # sanity: compute option must exist
    compute = {"lambda", "ecs_fargate", "ec2_asg", "eks"}
    if not compute & set(final):
        final.append("lambda")
        added.append("lambda")
        notes.append("Guardrail added AWS Lambda because no compute service was chosen.")
    # sanity: relational db implies only one flavour
    if "rds_single" in final and "rds_multi_az" in final:
        final.remove("rds_single")
        notes.append("Guardrail removed single-AZ RDS (Multi-AZ already selected).")
    # sanity: NAT gateway only makes sense with VPC-based compute
    if "nat_gateway" in final and not ({"ecs_fargate", "ec2_asg", "eks"} & set(final)):
        final.remove("nat_gateway")
        notes.append("Guardrail removed NAT Gateway (no VPC-based compute selected).")
    # HIPAA/PCI: single-AZ database is not acceptable
    if req["compliance"] in ("hipaa", "pci") and "rds_single" in final:
        final.remove("rds_single")
        final.append("rds_multi_az")
        added.append("rds_multi_az")
        notes.append("Guardrail replaced single-AZ RDS with Multi-AZ for regulated workload.")
    return final, added, notes


def monthly_cost(ids, users):
    t = tier_for(users)
    items = [{"id": i, "name": CATALOG[i]["name"], "cost": CATALOG[i]["cost"][t],
              "layer": CATALOG[i]["layer"], "tiers": list(CATALOG[i]["cost"])} for i in ids]
    return round(sum(x["cost"] for x in items), 2), items


def cost_score(total, budget):
    r = total / budget
    return 5.0 if r <= 0.5 else 4.0 if r <= 0.8 else 3.0 if r <= 1.0 else 2.0 if r <= 1.5 else 1.0


def pillar_scores(ids, total, budget):
    scores = {}
    for key, label in PILLARS:
        if key == "cost":
            scores[key] = cost_score(total, budget)
            continue
        # 0.75 damping keeps scores from saturating at 5 for every large stack
        s = 1.0 + 0.75 * sum(CATALOG[i]["pillars"].get(key, 0) for i in ids)
        scores[key] = round(max(1.0, min(5.0, s)) * 2) / 2   # nearest 0.5
    scores["overall"] = round(sum(scores[k] for k, _ in PILLARS) / len(PILLARS), 2)
    return scores


def mermaid(ids):
    """Generate a Mermaid flowchart from the chosen components."""
    s = set(ids)
    L = ["flowchart LR", "  user([Users])"]
    layers = {"edge": "Edge & Network", "security": "Identity & Security",
              "compute": "Compute", "data": "Data & Messaging", "ops": "Operations"}
    for lk, title in layers.items():
        members = [i for i in ids if CATALOG[i]["layer"] == lk]
        if not members:
            continue
        L.append(f'  subgraph {lk}["{title}"]')
        for m in members:
            L.append(f'    {m}["{CATALOG[m]["name"]}"]')
        L.append("  end")

    def e(a, b):
        if a in s and b in s:
            L.append(f"  {a} --> {b}")

    first = next((x for x in ("route53", "cloudfront", "waf", "s3_static", "apigw", "alb") if x in s), None)
    if first:
        L.append(f"  user --> {first}")
    e("route53", "cloudfront"); e("route53", "alb")
    e("cloudfront", "waf"); e("cloudfront", "s3_static"); e("cloudfront", "apigw"); e("cloudfront", "alb")
    e("waf", "apigw"); e("waf", "alb")
    e("cognito", "apigw"); e("cognito", "alb")
    compute = [c for c in ("lambda", "ecs_fargate", "ec2_asg", "eks") if c in s]
    for c in compute:
        e("apigw", c); e("alb", c)
        for d in ("dynamodb", "rds_single", "rds_multi_az", "elasticache", "s3_storage",
                  "sqs", "opensearch", "bedrock", "kinesis", "secrets_manager"):
            if d in s:
                L.append(f"  {c} --> {d}")
        if "nat_gateway" in s:
            L.append(f"  {c} -.-> nat_gateway")
    e("sqs", "sns")
    e("kms", "s3_storage"); e("kms", "dynamodb"); e("kms", "rds_multi_az")
    e("rds_multi_az", "multi_region_dr"); e("s3_storage", "backup")
    if "cloudwatch" in s:
        for c in compute:
            L.append(f"  {c} -.-> cloudwatch")
    e("cloudwatch", "xray")
    e("codepipeline", "cloudwatch")
    return "\n".join(L)


def build_option(name, ids, req, reasoning="", tradeoffs="", source="llm",
                 invalid=None, raw_ids=None):
    final, added, notes = apply_guardrails(ids, req)
    total, items = monthly_cost(final, req["monthly_users"])
    scores = pillar_scores(final, total, req["budget"])
    if total > req["budget"]:
        notes.append(f"Estimated cost ${total:,.0f}/month exceeds the stated budget of ${req['budget']:,.0f}.")
    opt = {
        "name": name,
        "components": items,
        "monthly_cost": total,
        "within_budget": total <= req["budget"],
        "scores": scores,
        "diagram": mermaid(final),
        "reasoning": reasoning,
        "tradeoffs": tradeoffs,
        "source": source,
        "raw_llm_components": raw_ids or [],
        "invalid_components": invalid or [],
        "guardrail_added": added,
        "notes": notes,
    }
    opt["cloudformation"] = iac.generate(opt, req)
    return opt


def fallback_option(name, req):
    ids = list(BLUEPRINTS[name])
    reason = {
        "Low-cost": "Fully serverless stack: you pay almost nothing when idle and there are no servers to manage. Best for validating an idea with a small team.",
        "Balanced": "Serverless core plus security hardening (WAF, KMS, Secrets Manager), tracing, backups and a CI/CD pipeline. Good default for a growing startup.",
        "High-availability": "Containers across multiple AZs behind a load balancer, Multi-AZ database, cache, threat detection and cross-region DR. For strict uptime or regulated workloads.",
    }[name]
    return build_option(name, ids, req, reasoning=reason,
                        tradeoffs="Rule-based fallback blueprint (LLM unavailable).", source="fallback")
