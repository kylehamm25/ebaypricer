# ECS deployment

`task-definition.json` + `deploy.sh` handle building the image and rolling out new
revisions. The one-time setup below (cluster, secrets, networking) isn't scripted here
since it depends on your existing AWS account layout (VPC, subnets, whether you already
have an ALB, etc.) - do it once via console or CLI, then `deploy.sh` is all you need
for every deploy after that.

## One-time setup

1. **Secrets Manager** - create one secret per entry under `secrets` in
   `task-definition.json`, named `ebaypricer/<NAME>` (e.g. `ebaypricer/DATABASE_URL`),
   holding the same values as your local `.env`:
   `DATABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `EBAY_APP_ID`,
   `EBAY_SECRET`, `RUNAME`, `EBAY_TOKEN_ENCRYPTION_KEY`.

2. **IAM** - an `ecsTaskExecutionRole` (AWS-managed
   `AmazonECSTaskExecutionRolePolicy` is enough) plus `secretsmanager:GetSecretValue`
   on the secrets above.

3. **Networking** - an ALB with an HTTPS listener and a target group forwarding to
   container port `8000`, health check path `/`. Security group on the ECS task should
   only allow inbound `8000` from the ALB's security group.

4. **Cluster + Service** - create the ECS cluster, then a Fargate service
   (`desiredCount: 1` to start) using the target group above. The task definition
   itself gets registered by `deploy.sh`, not created manually here.

5. **`EBAY_EXCEL_PATH` is deliberately not set** in `task-definition.json` - leave it
   out. The backend checks whether that path exists before running the legacy
   Excel-based pipeline round and skips it cleanly when it doesn't (see
   `dashboard/backend/services/ebay_data.py`), so nothing needs to point at a
   Google-Drive-synced file that won't exist in the container.

## Every deploy after that

```bash
cp deploy/.env.deploy.example deploy/.env.deploy   # once - then fill in real values
source deploy/.env.deploy
./deploy/deploy.sh
```

This builds the image (passing the `VITE_*` build args), pushes it to ECR tagged with
the current git short SHA, registers a new task definition revision from
`task-definition.json` with the placeholder tokens substituted, and forces the ECS
service to roll out to it.
