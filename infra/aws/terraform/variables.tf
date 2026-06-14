variable "aws_region" {
  type        = string
  description = "AWS region. Tokyo by default for JP clients."
  default     = "ap-northeast-1"
}

variable "image" {
  type        = string
  description = "Container image URI in ECR (e.g. ACCOUNT.dkr.ecr.REGION.amazonaws.com/ai-hr-agent-team:TAG). Identical image to GCP — only CLOUD_TARGET differs."
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names."
  default     = "ai-hr-agent-team"
}

variable "bucket_prefix" {
  type        = string
  description = "Prefix for globally-unique S3 bucket names. Buckets are <prefix>-zone2 / -zone3 / -audit."
}

variable "vpc_id" {
  type        = string
  description = "VPC to deploy ECS tasks and the OpenSearch VPC endpoint into."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for ECS tasks and the OpenSearch VPC endpoint."
}

variable "anthropic_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret holding ANTHROPIC_API_KEY (created below or pre-existing)."
  default     = ""
}

variable "default_jurisdiction" {
  type    = string
  default = "JP"
}

variable "default_output_language" {
  type    = string
  default = "EN"
}

variable "minimum_cohort_size" {
  type    = number
  default = 10
}

variable "hris_system" {
  type    = string
  default = "SMARTHR"
}

variable "hris_api_base_url" {
  type    = string
  default = ""
}

variable "secret_names" {
  type = list(string)
  default = [
    "anthropic-api-key",
    "hris-api-key",
    "greenhouse-api-key",
    "goodtime-api-key",
    "deel-api-key",
    "panalyt-api-key",
    "arize-api-key",
  ]
}

variable "audit_retention_days" {
  type        = number
  description = "S3 Object Lock retention (governance) for the audit bucket."
  default     = 2555 # ~7 years
}

variable "tags" {
  type    = map(string)
  default = { app = "ai-hr-agent-team", "managed-by" = "terraform" }
}
