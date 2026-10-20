# Security pillar

The Security pillar covers protecting data, systems and assets using cloud technologies.

## Design principles
Implement a strong identity foundation with least privilege, enable traceability, apply security at all layers, automate security best practices, protect data in transit and at rest, keep people away from data, and prepare for security events.

## Services and practices
Use IAM roles with least-privilege policies and never embed access keys in code. Use Amazon Cognito for end-user authentication with MFA. Encrypt data at rest with AWS KMS and in transit with TLS. Store credentials in AWS Secrets Manager. Put AWS WAF in front of CloudFront, API Gateway or an Application Load Balancer to block common web exploits and rate-limit abusive clients. Enable AWS CloudTrail for an audit log of every API call, and Amazon GuardDuty for threat detection. Place databases in private subnets.
