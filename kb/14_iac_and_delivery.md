# Infrastructure as code and delivery

Define infrastructure in AWS CloudFormation templates or the AWS Cloud Development Kit (CDK) so environments are repeatable, reviewable in version control and easy to delete. Use separate stacks or accounts for development and production. Deploy through a pipeline in AWS CodePipeline with automated tests, and use AWS Organizations with budgets and guardrails for multi-account setups.

## Good practice
Use least-privilege IAM roles generated per resource, parameterise stack inputs, enable stack termination protection in production, detect drift using CloudFormation drift detection, and tag every resource with an owner and project for cost allocation.
