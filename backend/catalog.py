"""Catalog of AWS building blocks the advisor can recommend.

Each component has:
  name, layer (for the diagram), desc (shown to the LLM),
  cost = approx monthly USD for (small, medium, large) workload tiers
         (us-east-1, on-demand, rounded; ESTIMATES - verify in AWS Pricing Calculator),
  pillars = score contribution to each Well-Architected pillar.

Pillar keys: ops, sec, rel, perf, cost (computed from budget, not here), sus
"""

TIERS = ("small", "medium", "large")


def C(name, layer, desc, cost, ops=0, sec=0, rel=0, perf=0, sus=0):
    return dict(name=name, layer=layer, desc=desc, cost=cost,
                pillars=dict(ops=ops, sec=sec, rel=rel, perf=perf, sus=sus))


CATALOG = {
    # ---- Edge / network
    "route53": C("Amazon Route 53", "edge", "Managed DNS with health checks and failover routing", (1, 1, 3), rel=0.5),
    "cloudfront": C("Amazon CloudFront", "edge", "Global CDN: caches content close to users, TLS, DDoS absorption", (1, 15, 120), perf=1.0, sec=0.25, sus=0.25),
    "waf": C("AWS WAF", "edge", "Web application firewall (OWASP rules, rate limiting, bot control)", (6, 12, 40), sec=1.0),
    "s3_static": C("Amazon S3 (static site)", "edge", "Static website / SPA hosting, 11 nines durability", (1, 3, 15), rel=0.5, sus=0.5, perf=0.25),
    "alb": C("Application Load Balancer", "edge", "Layer-7 load balancer across multiple AZs", (20, 30, 90), rel=1.0, perf=0.5),
    "apigw": C("Amazon API Gateway", "edge", "Managed REST/HTTP API front door with throttling and auth", (1, 35, 350), sec=0.5, ops=0.25, rel=0.25),
    "nat_gateway": C("NAT Gateway", "edge", "Outbound internet for private subnets (per-AZ, adds fixed cost)", (33, 66, 130), sec=0.25),
    # ---- Identity / security
    "cognito": C("Amazon Cognito", "security", "Managed user sign-up/sign-in, MFA, social login", (0, 0, 250), sec=0.75, ops=0.25),
    "kms": C("AWS KMS", "security", "Managed encryption keys for data at rest", (1, 2, 5), sec=0.75),
    "secrets_manager": C("AWS Secrets Manager", "security", "Store and rotate DB credentials and API keys", (1, 2, 5), sec=0.5),
    "guardduty": C("Amazon GuardDuty", "security", "Threat detection from CloudTrail, VPC flow and DNS logs", (3, 10, 40), sec=0.75),
    "cloudtrail": C("AWS CloudTrail", "security", "Audit log of every API call (needed for compliance)", (0, 2, 10), sec=0.5, ops=0.5),
    # ---- Compute
    "lambda": C("AWS Lambda", "compute", "Serverless functions; scales to zero, pay per request", (1, 20, 200), ops=0.75, rel=1.0, perf=0.25, sus=1.0),
    "ecs_fargate": C("Amazon ECS on Fargate", "compute", "Serverless containers, no servers to patch", (35, 150, 700), ops=0.5, rel=1.0, perf=0.5, sus=0.5),
    "ec2_asg": C("EC2 Auto Scaling group", "compute", "Virtual servers that scale in/out across AZs; most control, most ops work", (30, 120, 600), rel=0.75, perf=0.5),
    "eks": C("Amazon EKS", "compute", "Managed Kubernetes; powerful but heavy for small startup teams", (110, 300, 1200), perf=0.75, rel=0.75),
    "stepfunctions": C("AWS Step Functions", "compute", "Serverless workflow orchestration with retries", (1, 5, 50), ops=0.5, rel=0.5),
    # ---- Data
    "dynamodb": C("Amazon DynamoDB", "data", "Serverless NoSQL, single-digit-ms latency, multi-AZ by default", (2, 25, 250), rel=1.25, perf=1.0, ops=0.5, sus=0.5),
    "rds_single": C("Amazon RDS (single-AZ)", "data", "Managed relational DB in one Availability Zone; cheapest SQL option", (15, 60, 250), ops=0.25),
    "rds_multi_az": C("Amazon Aurora / RDS Multi-AZ", "data", "Managed relational DB with automatic failover across AZs", (45, 150, 600), rel=1.75, ops=0.5, sec=0.25),
    "elasticache": C("Amazon ElastiCache", "data", "In-memory cache (Redis/Valkey) to offload the database", (13, 50, 200), perf=1.25, sus=0.25),
    "s3_storage": C("Amazon S3 (object storage)", "data", "Durable object storage for uploads, media, backups", (2, 10, 80), rel=0.75, sus=0.25),
    "opensearch": C("Amazon OpenSearch Service", "data", "Full-text search and log analytics", (50, 150, 500), perf=0.5),
    "sqs": C("Amazon SQS", "data", "Message queue to decouple services and absorb spikes", (0, 2, 15), rel=0.75, perf=0.25),
    "sns": C("Amazon SNS", "data", "Pub/sub notifications (email, SMS, push, fan-out)", (0, 1, 5), ops=0.25),
    "eventbridge": C("Amazon EventBridge", "data", "Serverless event bus for event-driven designs", (0, 1, 5), ops=0.25, rel=0.25),
    "kinesis": C("Amazon Kinesis Data Streams", "data", "Real-time streaming ingestion", (15, 40, 200), perf=0.5),
    "bedrock": C("Amazon Bedrock", "data", "Managed foundation models for AI/GenAI features", (5, 40, 300), perf=0.25),
    # ---- Operations / delivery
    "cloudwatch": C("Amazon CloudWatch", "ops", "Metrics, logs, dashboards and alarms", (3, 15, 80), ops=1.25, rel=0.25),
    "xray": C("AWS X-Ray", "ops", "Distributed tracing to find latency bottlenecks", (0, 3, 15), ops=0.5, perf=0.25),
    "codepipeline": C("AWS CodePipeline", "ops", "Automated CI/CD pipeline", (1, 2, 5), ops=1.0),
    "backup": C("AWS Backup", "ops", "Centralised, policy-based backups", (2, 8, 40), rel=0.75, sec=0.25),
    "multi_region_dr": C("Multi-region disaster recovery", "ops", "Cross-region replication + warm standby (pilot light)", (20, 100, 500), rel=1.25, sec=0.0),
}

# ---------------------------------------------------------------- blueprints
# Used (a) as fallback when the LLM is unreachable and (b) as the "expected"
# reference when evaluating LLM output.
BLUEPRINTS = {
    "Low-cost": [
        "s3_static", "cloudfront", "apigw", "lambda", "dynamodb", "cognito",
        "cloudwatch", "cloudtrail",
    ],
    "Balanced": [
        "s3_static", "cloudfront", "waf", "cognito", "apigw", "lambda", "dynamodb",
        "s3_storage", "sqs", "cloudwatch", "xray", "cloudtrail", "secrets_manager",
        "kms", "codepipeline", "backup",
    ],
    "High-availability": [
        "route53", "cloudfront", "waf", "cognito", "alb", "ecs_fargate",
        "rds_multi_az", "elasticache", "s3_storage", "sqs", "sns", "nat_gateway",
        "cloudwatch", "xray", "cloudtrail", "guardduty", "kms", "secrets_manager",
        "backup", "multi_region_dr", "codepipeline",
    ],
}

# Components that MUST be present when a compliance need is declared (guardrail).
COMPLIANCE_REQUIRED = {
    "hipaa": ["kms", "cloudtrail", "guardduty", "waf", "secrets_manager", "backup"],
    "pci": ["kms", "cloudtrail", "guardduty", "waf", "secrets_manager"],
    "gdpr": ["kms", "cloudtrail", "backup"],
    "soc2": ["kms", "cloudtrail", "cloudwatch", "backup"],
    "none": [],
}

# Feature flags -> components that should be present.
FEATURE_COMPONENTS = {
    "needs_ai": ["bedrock"],
    "needs_search": ["opensearch"],
    "needs_realtime": ["kinesis"],
}


def tier_for(monthly_users: int) -> int:
    """Index into the (small, medium, large) cost tuples."""
    if monthly_users < 5_000:
        return 0
    if monthly_users < 100_000:
        return 1
    return 2
