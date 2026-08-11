#!/usr/bin/env bash
# Builds the image, pushes it to ECR, registers a new task definition revision
# from deploy/task-definition.json, and rolls the ECS service to it.
#
# Required env vars (export before running, or put in deploy/.env.deploy and
# `source` it - that file is gitignored, see deploy/README.md):
#   AWS_ACCOUNT_ID, AWS_REGION, ECS_CLUSTER, ECS_SERVICE
#   VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY   (frontend build args)
#   SUPABASE_URL, SUPABASE_ANON_KEY             (backend runtime env)
#   DEFAULT_USER_ID, ALLOWED_ORIGINS            (backend runtime env)
set -euo pipefail

: "${AWS_ACCOUNT_ID:?Set AWS_ACCOUNT_ID}"
: "${AWS_REGION:?Set AWS_REGION}"
: "${ECS_CLUSTER:?Set ECS_CLUSTER}"
: "${ECS_SERVICE:?Set ECS_SERVICE}"
: "${VITE_SUPABASE_URL:?Set VITE_SUPABASE_URL}"
: "${VITE_SUPABASE_ANON_KEY:?Set VITE_SUPABASE_ANON_KEY}"
: "${SUPABASE_URL:?Set SUPABASE_URL}"
: "${SUPABASE_ANON_KEY:?Set SUPABASE_ANON_KEY}"
: "${DEFAULT_USER_ID:?Set DEFAULT_USER_ID}"
: "${ALLOWED_ORIGINS:?Set ALLOWED_ORIGINS}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ECR_REPO="ebaypricer"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${ECR_REPO}"
TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"

echo "==> Ensuring ECR repo exists"
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" >/dev/null

echo "==> Logging in to ECR"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> Building image ${IMAGE_URI}:${TAG}"
docker build \
  --build-arg VITE_SUPABASE_URL="$VITE_SUPABASE_URL" \
  --build-arg VITE_SUPABASE_ANON_KEY="$VITE_SUPABASE_ANON_KEY" \
  -t "${IMAGE_URI}:${TAG}" -t "${IMAGE_URI}:latest" \
  "$REPO_ROOT"

echo "==> Pushing image"
docker push "${IMAGE_URI}:${TAG}"
docker push "${IMAGE_URI}:latest"

echo "==> Registering task definition revision"
TASK_DEF_FILE="$(mktemp)"
sed \
  -e "s|<ACCOUNT_ID>|${AWS_ACCOUNT_ID}|g" \
  -e "s|<REGION>|${AWS_REGION}|g" \
  -e "s|ebaypricer:latest|ebaypricer:${TAG}|" \
  -e "s|<SUPABASE_URL>|${SUPABASE_URL}|g" \
  -e "s|<SUPABASE_ANON_KEY>|${SUPABASE_ANON_KEY}|g" \
  -e "s|<DEFAULT_USER_ID>|${DEFAULT_USER_ID}|g" \
  -e "s|<ALLOWED_ORIGINS>|${ALLOWED_ORIGINS}|g" \
  "$SCRIPT_DIR/task-definition.json" > "$TASK_DEF_FILE"

aws ecs register-task-definition --cli-input-json "file://$TASK_DEF_FILE" --region "$AWS_REGION" >/dev/null
rm -f "$TASK_DEF_FILE"

echo "==> Updating service"
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition ebaypricer \
  --force-new-deployment \
  --region "$AWS_REGION" >/dev/null

echo "==> Rollout started. Watch it with:"
echo "    aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION --query 'services[0].deployments'"
