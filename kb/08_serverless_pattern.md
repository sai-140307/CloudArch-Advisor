# Reference architecture: serverless web application

A serverless web application typically uses Amazon S3 and Amazon CloudFront for the static front end, Amazon Cognito for authentication, Amazon API Gateway as the API front door, AWS Lambda for business logic and Amazon DynamoDB for data. It scales automatically from zero to thousands of requests per second, has no servers to patch, and costs very little at low traffic.

## When to choose it
Early-stage startups, MVPs, small teams of one to five engineers, spiky or unpredictable traffic, and event-driven workloads. Add SQS for background work, EventBridge for events, Step Functions for multi-step workflows, and WAF for protection.

## Limits to consider
Lambda has a 15 minute maximum run time, cold starts can add latency, and very high steady throughput can be cheaper on containers. Relational joins and complex transactions fit a relational database better than DynamoDB.
