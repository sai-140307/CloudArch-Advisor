# Cost Optimization pillar

Cost Optimization is the ability to run systems to deliver business value at the lowest price point.

## Design principles
Implement cloud financial management, adopt a consumption model, measure overall efficiency, stop spending money on undifferentiated heavy lifting, and analyse and attribute expenditure.

## Services and practices
Serverless services (Lambda, API Gateway, DynamoDB on-demand, S3) cost almost nothing when idle, which suits startups with unpredictable traffic. Always-on resources such as NAT Gateways, Application Load Balancers, EKS control planes, OpenSearch domains and Multi-AZ databases carry fixed monthly costs even with no traffic. Use AWS Budgets and Cost Explorer alerts, tag resources, use Savings Plans or Reserved Instances only once usage is steady, and right-size instances. Use the AWS Pricing Calculator to estimate cost before building. Delete unused resources, especially after demos and experiments.
