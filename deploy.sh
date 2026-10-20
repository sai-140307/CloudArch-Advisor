#!/usr/bin/env bash
# Deploys CloudArch Advisor. Works in AWS CloudShell, the AWS Academy lab terminal,
# or any shell with the AWS CLI (v1 or v2) and credentials.
set -eo pipefail
cd "$(dirname "$0")"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}"
REGION="${REGION:-us-east-1}"
STACK="cloudarch-advisor"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
CALLER=$(aws sts get-caller-identity --query Arn --output text)
ART="cloudarch-artifacts-${ACCOUNT}-${REGION}"
echo ">> Region: $REGION   Account: $ACCOUNT"

# AWS CLI v2 needs this flag to send a raw JSON payload; v1 does not know it.
BINFMT=""
aws --version 2>&1 | grep -q "aws-cli/2" && BINFMT="--cli-binary-format raw-in-base64-out"

# Artifact bucket for the packaged Lambda code
if ! aws s3api head-bucket --bucket "$ART" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$ART" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$ART" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
fi

echo ">> Packaging Lambda code"
aws cloudformation package --template-file template.yaml --s3-bucket "$ART" \
  --output-template-file packaged.yaml --region "$REGION" >/dev/null

# AWS Academy accounts cannot create IAM roles -> reuse the lab's LabRole.
OVERRIDES=""
ROLE_ARN=$(aws iam get-role --role-name LabRole --query Role.Arn --output text 2>/dev/null || true)
if [ -z "$ROLE_ARN" ] && echo "$CALLER" | grep -qi "voclabs\|LabRole"; then
  ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/LabRole"
fi
if [ -n "$ROLE_ARN" ] && [ "$ROLE_ARN" != "None" ]; then
  echo ">> AWS Academy detected: using existing role $ROLE_ARN"
  OVERRIDES="ExistingRoleArn=$ROLE_ARN HistoryStore=s3 ApiType=functionurl LlmProvider=gemini Retriever=bm25"
  echo "   Lab mode: Lambda Function URL, Gemini LLM, BM25 retrieval, S3 history"
  case " $* " in *GeminiApiKey=*) ;; *) echo "   !! No GeminiApiKey given: run  bash deploy.sh GeminiApiKey=YOUR_KEY  (AI falls back to rules without it)";; esac
fi

# A stack left in a failed/rolled-back state cannot be updated: remove it first.
STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo NONE)
case "$STATUS" in
  ROLLBACK_COMPLETE|ROLLBACK_FAILED|CREATE_FAILED|DELETE_FAILED)
    echo ">> Removing previous failed stack ($STATUS)"
    aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
    aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION" ;;
esac

# Extra KEY=VALUE arguments (e.g. ./deploy.sh EnableDashboard=false) become stack parameters.
OVERRIDES="$OVERRIDES $*"
OVERRIDES="$(echo $OVERRIDES)"

echo ">> Deploying CloudFormation stack (about 2 minutes)"
if [ -n "$OVERRIDES" ]; then
  aws cloudformation deploy --template-file packaged.yaml --stack-name "$STACK" \
    --capabilities CAPABILITY_IAM --region "$REGION" --parameter-overrides $OVERRIDES || FAILED=1
else
  aws cloudformation deploy --template-file packaged.yaml --stack-name "$STACK" \
    --capabilities CAPABILITY_IAM --region "$REGION" || FAILED=1
fi
if [ -n "${FAILED:-}" ]; then
  echo; echo "!! Stack failed. Reason(s):"
  aws cloudformation describe-stack-events --stack-name "$STACK" --region "$REGION" \
    --query "StackEvents[?contains(ResourceStatus,'FAILED')].[LogicalResourceId,ResourceStatusReason]" --output text | head -5
  exit 1
fi

out() { aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET=$(out KnowledgeBucketName); FN=$(out FunctionName); URL=$(out AppUrl)

echo ">> Uploading knowledge base documents to s3://$BUCKET/kb/"
aws s3 sync kb/ "s3://$BUCKET/kb/" --region "$REGION" --delete >/dev/null

echo ">> Building the RAG vector index"
aws lambda invoke --function-name "$FN" --region "$REGION" --cli-read-timeout 150 $BINFMT \
  --payload '{"action":"reindex"}' /tmp/reindex.json >/dev/null
echo "   $(cat /tmp/reindex.json)"

echo ">> Self-test: can the function reach Bedrock?"
aws lambda invoke --function-name "$FN" --region "$REGION" --cli-read-timeout 110 $BINFMT \
  --payload '{"action":"selftest"}' /tmp/selftest.json >/dev/null
echo "   $(cat /tmp/selftest.json)"
if grep -q '"llm": "ok"' /tmp/selftest.json; then
  echo "   Bedrock LLM: OK"
else
  echo "   !! Bedrock LLM not reachable. The app will still run using rule-based fallback."
  echo "   !! Enable model access in Bedrock (Model catalog) or redeploy with another ModelId."
fi

echo
echo "=================================================================="
echo " DONE.  Open this URL in your browser:"
echo "   $URL"
echo "=================================================================="
