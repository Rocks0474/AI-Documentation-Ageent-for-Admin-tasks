terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  bucket_zone2 = "${var.bucket_prefix}-zone2"
  bucket_zone3 = "${var.bucket_prefix}-zone3"
  bucket_audit = "${var.bucket_prefix}-audit"

  audit_log_group  = "/${var.name_prefix}/audit"
  audit_log_stream = "audit-events"

  # Japan statutory filing calendar — mirrors
  # config/japan_statutory_calendar.py:JAPAN_STATUTORY_JOBS. EventBridge cron
  # form (day-of-week => ? when day-of-month is set).
  statutory_jobs = {
    jp_rodo_hoken_renewal = {
      cron     = "cron(0 9 1 6 ? *)" # June 1 — 労働保険年度更新
      topic    = aws_sns_topic.statutory.arn
      payload  = { filing_type = "労働保険年度更新", deadline_days = 50 }
    }
    jp_santei_kiso_todoke = {
      cron     = "cron(0 9 1 7 ? *)" # July 1 — 算定基礎届
      topic    = aws_sns_topic.statutory.arn
      payload  = { filing_type = "算定基礎届", deadline_days = 10 }
    }
    jp_nenmatsuchosei_prep = {
      cron     = "cron(0 9 1 11 ? *)" # November 1 — 年末調整
      topic    = aws_sns_topic.statutory.arn
      payload  = { filing_type = "年末調整", deadline_days = 60 }
    }
    jp_36kyotei_check = {
      cron     = "cron(0 9 1 * ? *)" # 1st of every month — 36協定更新確認
      topic    = aws_sns_topic.statutory.arn
      payload  = { filing_type = "36協定更新確認", deadline_days = 30 }
    }
    jp_merit_cycle_trigger = {
      cron     = "cron(0 9 1 2 ? *)" # February 1 — MERIT_CYCLE_PREP
      topic    = aws_sns_topic.workflow.arn
      payload  = { workflow_type = "MERIT_CYCLE_PREP", jurisdiction = "JP" }
    }
  }
}

# ---------------------------------------------------------------------------
# S3 — Zone 2, Zone 3, and an Object-Lock (WORM) audit bucket.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "zone2" {
  bucket = local.bucket_zone2
  tags   = var.tags
}

resource "aws_s3_bucket" "zone3" {
  bucket = local.bucket_zone3
  tags   = var.tags
}

resource "aws_s3_bucket" "audit" {
  bucket              = local.bucket_audit
  object_lock_enabled = true
  tags                = var.tags
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.audit_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each = {
    zone2 = aws_s3_bucket.zone2.id
    zone3 = aws_s3_bucket.zone3.id
    audit = aws_s3_bucket.audit.id
  }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = {
    zone2 = aws_s3_bucket.zone2.id
    zone3 = aws_s3_bucket.zone3.id
    audit = aws_s3_bucket.audit.id
  }
  bucket = each.value
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
    bucket_key_enabled = true
  }
}

# ---------------------------------------------------------------------------
# SQS (routing) + SNS (statutory / workflow / notifications).
# ---------------------------------------------------------------------------
resource "aws_sqs_queue" "routing" {
  name                       = "${var.name_prefix}-routing"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 60
  sqs_managed_sse_enabled    = true
  tags                       = var.tags
}

resource "aws_sns_topic" "statutory" {
  name = "${var.name_prefix}-statutory-filing-alerts"
  tags = var.tags
}

resource "aws_sns_topic" "workflow" {
  name = "${var.name_prefix}-hr-workflow-triggers"
  tags = var.tags
}

resource "aws_sns_topic" "notifications" {
  name = "${var.name_prefix}-hr-notifications"
  tags = var.tags
}

# ---------------------------------------------------------------------------
# Secrets Manager — containers only; values added out-of-band.
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "secrets" {
  for_each = toset(var.secret_names)
  name     = each.value
  tags     = var.tags
}

# ---------------------------------------------------------------------------
# CloudWatch Logs (immutable audit WORM) + Athena for querying.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "audit" {
  name              = local.audit_log_group
  retention_in_days = 0 # never expire — audit trail
  tags              = var.tags
}

resource "aws_cloudwatch_log_stream" "audit" {
  name           = local.audit_log_stream
  log_group_name = aws_cloudwatch_log_group.audit.name
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name_prefix}/app"
  retention_in_days = 90
  tags              = var.tags
}

resource "aws_s3_bucket" "athena_results" {
  bucket = "${var.bucket_prefix}-athena-results"
  tags   = var.tags
}

resource "aws_athena_workgroup" "audit" {
  name = "${var.name_prefix}-audit"
  configuration {
    enforce_workgroup_configuration = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/results/"
    }
  }
  tags = var.tags
}

resource "aws_glue_catalog_database" "audit" {
  name = replace("${var.name_prefix}_audit", "-", "_")
}

# ---------------------------------------------------------------------------
# OpenSearch Serverless — VECTORSEARCH collection, VPC-isolated.
# ---------------------------------------------------------------------------
resource "aws_security_group" "opensearch" {
  name_prefix = "${var.name_prefix}-aoss-"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}

resource "aws_opensearchserverless_vpc_endpoint" "this" {
  name               = "${var.name_prefix}-aoss-vpce"
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [aws_security_group.opensearch.id]
}

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${var.name_prefix}-enc"
  type = "encryption"
  policy = jsonencode({
    Rules = [{
      ResourceType = "collection"
      Resource     = ["collection/${var.name_prefix}"]
    }]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.name_prefix}-net"
  type = "network"
  policy = jsonencode([{
    Rules = [
      { ResourceType = "collection", Resource = ["collection/${var.name_prefix}"] },
      { ResourceType = "dashboard", Resource = ["collection/${var.name_prefix}"] },
    ]
    AllowFromPublic = false
    SourceVPCEs     = [aws_opensearchserverless_vpc_endpoint.this.id]
  }])
}

resource "aws_opensearchserverless_collection" "vectors" {
  name       = var.name_prefix
  type       = "VECTORSEARCH"
  tags       = var.tags
  depends_on = [aws_opensearchserverless_security_policy.encryption]
}

resource "aws_opensearchserverless_access_policy" "data" {
  name = "${var.name_prefix}-data"
  type = "data"
  policy = jsonencode([{
    Rules = [
      {
        ResourceType = "index"
        Resource     = ["index/${var.name_prefix}/*"]
        Permission   = ["aoss:*"]
      },
      {
        ResourceType = "collection"
        Resource     = ["collection/${var.name_prefix}"]
        Permission   = ["aoss:*"]
      },
    ]
    Principal = [aws_iam_role.task.arn]
  }])
}

# ---------------------------------------------------------------------------
# IAM — EventBridge Scheduler role, ECS task + execution roles.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "scheduler_publish" {
  name = "publish"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sns:Publish"]
      Resource = [aws_sns_topic.statutory.arn, aws_sns_topic.workflow.arn]
    }]
  })
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "exec_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "exec_secrets" {
  name = "read-secrets"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [for s in aws_secretsmanager_secret.secrets : s.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "task_permissions" {
  name = "runtime"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.zone2.arn, "${aws_s3_bucket.zone2.arn}/*",
          aws_s3_bucket.zone3.arn, "${aws_s3_bucket.zone3.arn}/*",
          aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = [aws_sqs_queue.routing.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.statutory.arn, aws_sns_topic.workflow.arn, aws_sns_topic.notifications.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [for s in aws_secretsmanager_secret.secrets : s.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:PutLogEvents", "logs:CreateLogStream", "logs:DescribeLogStreams"]
        Resource = ["${aws_cloudwatch_log_group.audit.arn}:*"]
      },
      {
        Effect   = "Allow"
        Action   = ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule", "scheduler:GetSchedule", "scheduler:ListSchedules"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.scheduler.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["aoss:APIAccessAll"]
        Resource = [aws_opensearchserverless_collection.vectors.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["*"]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# ECS Fargate — the single Docker image, configured for AWS via env vars.
# ---------------------------------------------------------------------------
resource "aws_security_group" "ecs" {
  name_prefix = "${var.name_prefix}-ecs-"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix
  tags = var.tags
}

resource "aws_ecs_task_definition" "app" {
  family                   = var.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = var.name_prefix
    image     = var.image
    essential = true
    environment = [
      { name = "CLOUD_TARGET", value = "AWS" },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "AWS_ACCOUNT_ID", value = local.account_id },
      { name = "LOG_LEVEL", value = "INFO" },
      { name = "DEFAULT_JURISDICTION", value = var.default_jurisdiction },
      { name = "DEFAULT_OUTPUT_LANGUAGE", value = var.default_output_language },
      { name = "MINIMUM_COHORT_SIZE", value = tostring(var.minimum_cohort_size) },
      { name = "HRIS_SYSTEM", value = var.hris_system },
      { name = "HRIS_API_BASE_URL", value = var.hris_api_base_url },
      { name = "HRIS_API_KEY_SECRET", value = "hris-api-key" },
      { name = "S3_BUCKET_ZONE2", value = aws_s3_bucket.zone2.bucket },
      { name = "S3_BUCKET_ZONE3", value = aws_s3_bucket.zone3.bucket },
      { name = "S3_BUCKET_AUDIT", value = aws_s3_bucket.audit.bucket },
      { name = "SQS_QUEUE_URL_ROUTING", value = aws_sqs_queue.routing.url },
      { name = "SNS_TOPIC_ARN_STATUTORY", value = aws_sns_topic.statutory.arn },
      { name = "SNS_TOPIC_ARN_WORKFLOW", value = aws_sns_topic.workflow.arn },
      { name = "SNS_TOPIC_ARN_NOTIFICATIONS", value = aws_sns_topic.notifications.arn },
      { name = "EVENTBRIDGE_SCHEDULER_ROLE_ARN", value = aws_iam_role.scheduler.arn },
      { name = "OPENSEARCH_ENDPOINT_ZONE2", value = aws_opensearchserverless_collection.vectors.collection_endpoint },
      { name = "OPENSEARCH_ENDPOINT_ZONE3", value = aws_opensearchserverless_collection.vectors.collection_endpoint },
      { name = "CLOUDWATCH_AUDIT_LOG_GROUP", value = aws_cloudwatch_log_group.audit.name },
      { name = "CLOUDWATCH_AUDIT_LOG_STREAM", value = aws_cloudwatch_log_stream.audit.name },
    ]
    secrets = [
      { name = "ANTHROPIC_API_KEY", valueFrom = var.anthropic_secret_arn != "" ? var.anthropic_secret_arn : aws_secretsmanager_secret.secrets["anthropic-api-key"].arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "app"
      }
    }
  }])

  tags = var.tags
}

resource "aws_ecs_service" "app" {
  name            = var.name_prefix
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  tags = var.tags
}

# ---------------------------------------------------------------------------
# EventBridge Scheduler — Japan statutory filing calendar.
# ---------------------------------------------------------------------------
resource "aws_scheduler_schedule" "statutory" {
  for_each = local.statutory_jobs

  name = each.key
  flexible_time_window { mode = "OFF" }
  schedule_expression          = each.value.cron
  schedule_expression_timezone = "Asia/Tokyo"

  target {
    arn      = each.value.topic
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode(each.value.payload)
  }
}
