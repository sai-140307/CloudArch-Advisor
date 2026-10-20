# Compliance guidance for regulated startups

AWS provides compliance programs but responsibility is shared: AWS secures the cloud, the customer secures what they put in it.

## HIPAA (health data in the US)
Sign a Business Associate Addendum with AWS and use only HIPAA-eligible services. Encrypt all protected health information at rest with KMS and in transit with TLS, enable CloudTrail audit logging, GuardDuty threat detection, WAF, Secrets Manager for credentials, and backups. Use Multi-AZ databases and restrict access with least-privilege IAM.

## PCI DSS (payment card data)
Prefer to keep card data out of scope by using a payment processor. If card data is handled, isolate it in a dedicated network segment, encrypt with KMS, log with CloudTrail, protect with WAF and monitor with GuardDuty.

## GDPR (personal data of people in the EU)
Know where personal data is stored, support deletion and export requests, encrypt data, keep audit logs and take backups. Choose Regions according to data-residency needs.

## SOC 2
Needs evidence of access control, change management, monitoring and backups: IAM, CloudTrail, CloudWatch, AWS Backup and infrastructure as code help produce that evidence.
