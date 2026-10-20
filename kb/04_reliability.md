# Reliability pillar

Reliability is the ability of a workload to perform its intended function correctly and consistently, and to recover quickly from failure.

## Design principles
Automatically recover from failure, test recovery procedures, scale horizontally to increase aggregate availability, stop guessing capacity, and manage change through automation.

## Services and practices
Deploy across multiple Availability Zones. Amazon DynamoDB, Amazon S3, AWS Lambda and Amazon SQS are replicated across AZs by the service itself. Use Amazon Aurora or RDS Multi-AZ for relational data with automatic failover. Use Application Load Balancers with Auto Scaling or ECS services spread over AZs. Decouple components with SQS and SNS so one failing part does not take down the rest. Use AWS Backup for scheduled backups. For disaster recovery choose a strategy by recovery time and recovery point objective: backup and restore (cheapest, hours), pilot light, warm standby, or multi-site active-active (most expensive, near-zero downtime).
