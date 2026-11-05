#!/usr/bin/env bash
# Deploy the stack from this machine: state bucket, ECR, image build and push, Terraform plan and apply.
#
# Usage:
#   export AWS_PROFILE=<profile>
#   cp infra/terraform/workshop.tfvars.example infra/terraform/workshop.tfvars   # then edit it
#   make deploy
#
# Optional environment variables:
#   AWS_REGION           default us-west-2
#   TFVARS               default infra/terraform/workshop.tfvars
#   DEPLOY_ALLOW_DIRTY   set to 1 to build from a working tree with uncommitted changes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
PLAN_FILE="deployment.tfplan"
REGION="${AWS_REGION:-us-west-2}"
export AWS_REGION="$REGION"
cd "$ROOT"

fail() { echo "ERROR: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }
confirm() {
  local answer
  read -r -p "$1 Type yes to continue: " answer
  [ "$answer" = "yes" ] || fail "Stopped. Nothing further was changed."
}

for tool in terraform aws docker git curl; do
  command -v "$tool" >/dev/null || fail "$tool is not installed."
done

TFVARS="${TFVARS:-$TF_DIR/workshop.tfvars}"
[ -f "$TFVARS" ] || fail "$TFVARS not found. Copy infra/terraform/workshop.tfvars.example to it and edit it."
TFVARS="$(cd "$(dirname "$TFVARS")" && pwd)/$(basename "$TFVARS")"
if grep -q 'REPLACE_WITH' "$TFVARS"; then
  fail "$TFVARS still has a REPLACE_WITH placeholder. Set a model, or use llm_backend = \"mock\" with bedrock_model_id = \"\"."
fi

step "Checking AWS credentials"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)" \
  || fail "AWS credentials are missing or expired. Set AWS_PROFILE and refresh them."
CALLER="$(aws sts get-caller-identity --query Arn --output text)"

TAG="$(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain)" ]; then
  [ "${DEPLOY_ALLOW_DIRTY:-0}" = "1" ] \
    || fail "The working tree has uncommitted changes. Commit them, or set DEPLOY_ALLOW_DIRTY=1 to build them anyway."
  # ECR tags are immutable, so an uncommitted build needs its own tag.
  TAG="$TAG-dirty-$(date +%Y%m%d%H%M%S)"
fi

BUCKET="resource-engine-tfstate-$ACCOUNT-$REGION"
cat <<EOF

Account:  $ACCOUNT
Identity: $CALLER
Region:   $REGION
Branch:   $(git branch --show-current)
Image:    $TAG
Settings: $TFVARS
State:    s3://$BUCKET

EOF
confirm "This creates the state bucket and ECR repository if needed, then pushes the image. You review the plan before anything else changes."

step "Preparing the Terraform state bucket"
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "Using existing bucket $BUCKET"
else
  aws s3 mb "s3://$BUCKET" --region "$REGION"
  aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

step "Initializing Terraform"
terraform -chdir="$TF_DIR" init -input=false -reconfigure \
  -backend-config="bucket=$BUCKET" \
  -backend-config="key=resource-engine.tfstate" \
  -backend-config="region=$REGION"

step "Creating the ECR repository"
terraform -chdir="$TF_DIR" apply -input=false -auto-approve -target=aws_ecr_repository.app \
  -var-file="$TFVARS" -var="region=$REGION" -var="image_tag=bootstrap"
REPO="$(terraform -chdir="$TF_DIR" output -raw ecr_repository_url)"

step "Building and pushing $REPO:$TAG"
if aws ecr describe-images --repository-name "${REPO#*/}" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
  echo "Image $TAG is already in ECR, so the build is skipped."
else
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
  # ECS tasks run on x86, so this is required when building on Apple Silicon.
  docker buildx build --platform linux/amd64 -t "$REPO:$TAG" --push .
fi

step "Planning the deployment"
trap 'rm -f "$TF_DIR/$PLAN_FILE"' EXIT
terraform -chdir="$TF_DIR" plan -input=false -var-file="$TFVARS" -var="region=$REGION" \
  -var="image_tag=$TAG" -out="$PLAN_FILE"

echo
confirm "Review the plan above. Applying it creates or changes billable AWS resources."

step "Applying the plan"
terraform -chdir="$TF_DIR" apply -input=false "$PLAN_FILE"

step "Waiting for the ECS service to stabilize"
aws ecs wait services-stable \
  --cluster "$(terraform -chdir="$TF_DIR" output -raw cluster_name)" \
  --services "$(terraform -chdir="$TF_DIR" output -raw service_name)"

ALB="$(terraform -chdir="$TF_DIR" output -raw alb_dns_name)"
step "Checking http://$ALB/api/health"
curl --fail --silent --show-error --retry 10 --retry-delay 6 "http://$ALB/api/health"
printf '\n\nDeployed: http://%s\n' "$ALB"
echo "Next: import the sample data, then run make demo-accounts. See docs/deployment.md."
