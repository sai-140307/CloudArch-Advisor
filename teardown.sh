#!/usr/bin/env bash
# Deletes everything this project created (stops all charges).
set -uo pipefail
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
STACK="cloudarch-advisor"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBucketName'].OutputValue" --output text 2>/dev/null)
[ -n "${BUCKET:-}" ] && aws s3 rm "s3://$BUCKET" --recursive --region "$REGION"
aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION"
ART="cloudarch-artifacts-${ACCOUNT}-${REGION}"
aws s3 rb "s3://$ART" --force --region "$REGION" 2>/dev/null
echo "Everything deleted."
