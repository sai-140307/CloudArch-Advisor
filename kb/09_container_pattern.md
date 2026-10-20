# Reference architecture: containers on ECS Fargate behind a load balancer

Users reach Amazon CloudFront and AWS WAF, then an Application Load Balancer in public subnets that forwards to ECS tasks on AWS Fargate in private subnets across at least two Availability Zones. State lives in Amazon Aurora (Multi-AZ) with an ElastiCache layer for hot reads, and files in Amazon S3. NAT Gateways give private subnets outbound access. CloudWatch and X-Ray provide observability.

## When to choose it
Applications that already run in Docker, need long-running processes or WebSockets, steady traffic where always-on containers are cheaper than per-request pricing, or a relational database. Fargate removes server management. Choose EKS only if the team already knows Kubernetes, because the control plane costs extra and the operational load is much higher.

## Cost notes
The ALB, NAT Gateways and Multi-AZ database add fixed monthly cost. Use one NAT Gateway in non-production environments.
