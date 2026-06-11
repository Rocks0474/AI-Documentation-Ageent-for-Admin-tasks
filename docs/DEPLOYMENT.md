# Deployment Runbook — AI Global HR Agent Team

This runbook walks through deploying the system to **GCP Cloud Run** and **AWS
ECS Fargate**. The same Docker image runs on both clouds; only `CLOUD_TARGET`
(and the target-specific environment variables) differ.

> All Terraform here was authored but **not** applied in the build environment.
> Run `terraform validate` / `plan` before `apply` in your own environment with
> real credentials. No live cloud calls are made by the code itself outside the
> adapters.

---

## 0. Prerequisites (both clouds)

- Docker, Terraform >= 1.5, and the relevant cloud CLI (`gcloud` / `aws`).
- An Anthropic API key.
- A VPC with private subnets in your target region (Tokyo by default:
  `asia-northeast1` / `ap-northeast-1`).

### The single image (build once, deploy to both)

The image bundles **both** cloud SDK extras so one artifact runs anywhere; the
factory selects the implementation at runtime from `CLOUD_TARGET`.

```bash
# From the repo root. Includes both [gcp,aws] extras => one image for both clouds.
docker build --build-arg INSTALL_EXTRAS="[gcp,aws]" -t ai-hr-agent-team:latest .
```

The container serves a health endpoint on `$PORT` (default 8080) and runs the
startup self-check (validates config, wires adapters via the factory, seeds the
JP statutory calendar when `DEFAULT_JURISDICTION=JP`). `RUN_MODE=check` runs the
self-check and exits 0 (useful as a smoke test / CI gate).

---

## 1. GCP — Cloud Run

### 1.1 Enable APIs

```bash
gcloud services enable \
  run.googleapis.com storage.googleapis.com pubsub.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com \
  aiplatform.googleapis.com artifactregistry.googleapis.com \
  --project "$PROJECT_ID"
```

### 1.2 Push the image to Artifact Registry

```bash
REGION=asia-northeast1
gcloud artifacts repositories create hr --repository-format=docker \
  --location="$REGION" --project "$PROJECT_ID"
gcloud auth configure-docker "${REGION}-docker.pkg.dev"

IMG="${REGION}-docker.pkg.dev/${PROJECT_ID}/hr/ai-hr-agent-team:$(git rev-parse --short HEAD)"
docker tag ai-hr-agent-team:latest "$IMG"
docker push "$IMG"
```

### 1.3 Terraform variables (`infra/gcp/terraform/terraform.tfvars`)

```hcl
project_id        = "your-project"
region            = "asia-northeast1"
image             = "asia-northeast1-docker.pkg.dev/your-project/hr/ai-hr-agent-team:abc1234"
bucket_prefix     = "acme-hr"            # buckets become acme-hr-zone2/-zone3/-audit
vertex_network    = "projects/PROJECT_NUMBER/global/networks/your-vpc"
vertex_subnetwork = "https://www.googleapis.com/compute/v1/projects/your-project/regions/asia-northeast1/subnetworks/your-subnet"
```

### 1.4 Apply (order of operations)

```bash
cd infra/gcp/terraform
terraform init
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

Terraform creates: the three GCS buckets (Zone 2/3 + versioned, 7yr-retention
audit), Pub/Sub topics + the routing subscription, Secret Manager containers,
the runtime service account + IAM, the Vertex AI indexes + **private** index
endpoint with deployed indexes, the Cloud Run service, and the **five Japan
statutory `google_cloud_scheduler_job` resources**.

### 1.5 Post-apply

1. **Add secret values** (Terraform only creates empty containers):

   ```bash
   printf '%s' "$ANTHROPIC_API_KEY" | gcloud secrets versions add anthropic-api-key --data-file=- --project "$PROJECT_ID"
   printf '%s' "$HRIS_KEY"          | gcloud secrets versions add hris-api-key      --data-file=- --project "$PROJECT_ID"
   # ...repeat for any connected integrations (greenhouse/goodtime/deel/panalyt/arize)
   ```

2. **Roll the Cloud Run revision** so it picks up the secret version (or it will
   on next deploy): `gcloud run services update ai-hr-agent-team --region "$REGION"`.

3. The Vertex deployed-index ids default to `zone2` / `zone3` (matching
   `VERTEX_DEPLOYED_INDEX_ID_ZONE2/3`). Override the env on the service only if
   you changed them.

### 1.6 Verify

```bash
terraform output cloud_run_url
gcloud run services describe ai-hr-agent-team --region "$REGION" --format='value(status.url)'
gcloud scheduler jobs list --location "$REGION"   # expect the 5 jp_* jobs
```

The container logs should show `startup.ready cloud_target=GCP` and
`startup.statutory_calendar_seeded`.

---

## 2. AWS — ECS Fargate

### 2.1 Push the image to ECR

```bash
AWS_REGION=ap-northeast-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --repository-name ai-hr-agent-team --region "$AWS_REGION"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

IMG="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/ai-hr-agent-team:$(git rev-parse --short HEAD)"
docker tag ai-hr-agent-team:latest "$IMG"
docker push "$IMG"
```

### 2.2 Terraform variables (`infra/aws/terraform/terraform.tfvars`)

```hcl
aws_region         = "ap-northeast-1"
image              = "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/ai-hr-agent-team:abc1234"
bucket_prefix      = "acme-hr"
vpc_id             = "vpc-0abc..."
private_subnet_ids = ["subnet-0aaa...", "subnet-0bbb..."]
```

### 2.3 Apply

```bash
cd infra/aws/terraform
terraform init
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

Terraform creates: S3 (Zone 2/3 + Object-Lock audit bucket), SQS routing queue,
SNS topics, Secrets Manager containers, CloudWatch immutable audit log group +
Athena workgroup/Glue DB, the **VPC-isolated** OpenSearch Serverless collection,
IAM roles, the ECS cluster/task/service, and the **five Japan statutory
`aws_scheduler_schedule` resources**.

### 2.4 Post-apply

1. **Add secret values:**

   ```bash
   aws secretsmanager put-secret-value --secret-id anthropic-api-key --secret-string "$ANTHROPIC_API_KEY" --region "$AWS_REGION"
   aws secretsmanager put-secret-value --secret-id hris-api-key      --secret-string "$HRIS_KEY"          --region "$AWS_REGION"
   # ...repeat for connected integrations
   ```

2. **Create the OpenSearch k-NN indexes** (the collection is empty on creation).
   From a host with network access to the VPC endpoint, create `zone2` and
   `zone3` indexes with a `knn_vector` field, e.g.:

   ```json
   PUT zone2
   {
     "settings": { "index.knn": true },
     "mappings": {
       "properties": {
         "content":  { "type": "text" },
         "metadata": { "type": "object" },
         "vector":   { "type": "knn_vector", "dimension": 1024 }
       }
     }
   }
   ```

   (Titan `amazon.titan-embed-text-v2:0` is 1024-dim; adjust to your model.)

3. **Force a new deployment** to pick up secret values:
   `aws ecs update-service --cluster ai-hr-agent-team --service ai-hr-agent-team --force-new-deployment --region "$AWS_REGION"`.

4. **(Optional) Athena over the audit trail** — register a table over the audit
   S3 bucket in the Glue DB to query the trail with SQL.

### 2.5 Verify

```bash
terraform output ecs_service_name
aws ecs describe-services --cluster ai-hr-agent-team --services ai-hr-agent-team --region "$AWS_REGION" \
  --query 'services[0].deployments'
aws scheduler list-schedules --region "$AWS_REGION"   # expect the 5 jp_* schedules
```

App logs in CloudWatch (`/ai-hr-agent-team/app`) should show
`startup.ready cloud_target=AWS`.

---

## 3. Environment variable reference

| Variable | LOCAL | GCP | AWS | Notes |
|---|---|---|---|---|
| `CLOUD_TARGET` | `LOCAL` | `GCP` | `AWS` | **The only switch** between clouds |
| `ANTHROPIC_API_KEY` | env/secret file | Secret Manager | Secrets Manager | injected as env on the service |
| `LOG_LEVEL` | `INFO` | `INFO` | `INFO` | |
| `DEFAULT_JURISDICTION` | `JP` | `JP` | `JP` | drives statutory calendar seeding |
| `DEFAULT_OUTPUT_LANGUAGE` | `EN` | `EN` | `EN` | |
| `MINIMUM_COHORT_SIZE` | `10` | `10` | `10` | analytics privacy floor |
| `HRIS_SYSTEM`, `HRIS_API_BASE_URL`, `HRIS_API_KEY_SECRET` | ✓ | ✓ | ✓ | |
| `PORT` | — | set by Cloud Run | `8080` | health server port |
| `GCP_PROJECT_ID`, `GCP_REGION` | — | ✓ | — | |
| `GCS_BUCKET_ZONE2/ZONE3/AUDIT` | — | ✓ | — | |
| `PUBSUB_TOPIC_ROUTING`, `PUBSUB_TOPIC_NOTIFICATIONS` | — | ✓ | — | |
| `VERTEX_INDEX_ID_ZONE2/ZONE3`, `VERTEX_INDEX_ENDPOINT_ID` | — | ✓ | — | |
| `VERTEX_DEPLOYED_INDEX_ID_ZONE2/ZONE3` | — | optional | — | default `zone2`/`zone3` |
| `AWS_REGION`, `AWS_ACCOUNT_ID` | — | — | ✓ | |
| `S3_BUCKET_ZONE2/ZONE3/AUDIT` | — | — | ✓ | |
| `SQS_QUEUE_URL_ROUTING` | — | — | ✓ | |
| `SNS_TOPIC_ARN_STATUTORY/WORKFLOW/NOTIFICATIONS` | — | — | ✓ | |
| `EVENTBRIDGE_SCHEDULER_ROLE_ARN` | — | — | ✓ | |
| `OPENSEARCH_ENDPOINT_ZONE2/ZONE3` | — | — | ✓ | collection endpoint |
| `CLOUDWATCH_AUDIT_LOG_GROUP/STREAM` | — | — | ✓ | immutable WORM mirror |
| `LOCAL_STORAGE_ROOT`, `LOCAL_SECRETS_FILE` | ✓ | — | — | |

All of the per-target env vars above are wired by Terraform onto the Cloud Run
service / ECS task definition — you do not set them by hand.

---

## 4. Order of operations (summary)

1. Build the single image (`[gcp,aws]` extras).
2. Push to Artifact Registry (GCP) and/or ECR (AWS).
3. `terraform apply` the target module.
4. Populate Secret Manager / Secrets Manager values.
5. **AWS only:** create the OpenSearch `zone2`/`zone3` k-NN indexes.
6. Roll the service revision (Cloud Run) / force new deployment (ECS).
7. Verify startup logs + scheduler jobs.

---

## 5. Teardown

```bash
# GCP
cd infra/gcp/terraform && terraform destroy
# AWS — the audit bucket uses Object Lock (GOVERNANCE); object versions are
# retained until their retention expires. Remove the lock / versions first if a
# full destroy is required (this is intentional WORM protection).
cd infra/aws/terraform && terraform destroy
```

---

## 6. Notes & known differences

- **Single image guarantee.** Agents never import a cloud SDK (enforced by the
  `check-layer-1-purity` CI gate). The factory selects GCP/AWS/LOCAL adapters
  from `CLOUD_TARGET` at startup, so the identical artifact runs on both clouds.
- **Vector store content.** Vertex AI Vector Search returns ids + scores only;
  OpenSearch returns the stored content too. Resolve content by id from Zone 2/3
  storage on GCP if you need the text back from a query.
- **Audit immutability.** GCP uses a versioned + retention-locked GCS bucket;
  AWS uses an Object-Lock (GOVERNANCE) S3 bucket plus a CloudWatch immutable log
  group (queryable via Athena). Approval provenance is written by the workflow
  system via `record_approval` — never by an agent (architectural Constraint #5).
- **HITL.** MANDATORY results suspend the orchestration graph
  (`interrupt_after`); the external workflow posts the approval to resume.
