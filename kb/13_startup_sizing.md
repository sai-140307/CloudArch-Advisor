# Sizing guidance for startups

## Under 5,000 monthly users
Use a fully serverless stack. Monthly infrastructure cost can stay under about 25 dollars and the AWS Free Tier covers much of it. Avoid NAT Gateways, load balancers, EKS and OpenSearch because their fixed costs dominate.

## 5,000 to 100,000 monthly users
Serverless still works well; add CloudFront caching, WAF, a queue for background jobs, tracing and automated backups. Move to containers when you need long-running processes or relational data with complex queries. Expect costs in the low hundreds of dollars.

## Over 100,000 monthly users
Add caching with ElastiCache, a Multi-AZ relational database or provisioned DynamoDB capacity, auto scaling, and deeper observability. Review Savings Plans once usage is predictable. Plan multi-Region disaster recovery if downtime is costly.

## Team size
Teams of one to five engineers should prefer managed and serverless services, because every self-managed component adds on-call burden. Larger teams can justify Kubernetes or custom platforms.
