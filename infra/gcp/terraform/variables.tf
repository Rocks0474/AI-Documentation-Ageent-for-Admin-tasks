variable "project_id" {
  type        = string
  description = "GCP project ID to deploy into."
}

variable "region" {
  type        = string
  description = "GCP region. Tokyo by default for JP clients."
  default     = "asia-northeast1"
}

variable "image" {
  type        = string
  description = "Container image for Cloud Run (e.g. REGION-docker.pkg.dev/PROJECT/REPO/ai-hr-agent-team:TAG). The same image deploys to AWS — only CLOUD_TARGET differs."
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
  default     = "ai-hr-agent-team"
}

variable "bucket_prefix" {
  type        = string
  description = "Prefix for globally-unique GCS bucket names (e.g. acme-hr). Buckets are <prefix>-zone2 / -zone3 / -audit."
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
  type        = number
  description = "People Analytics cohort privacy floor."
  default     = 10
}

variable "hris_system" {
  type    = string
  default = "SMARTHR"
}

variable "hris_api_base_url" {
  type    = string
  default = ""
}

variable "enable_vertex" {
  type        = bool
  description = "Provision Vertex AI Vector Search + Cloud Run VPC egress. Set false to stage the rest of the stack first (no VPC/peering required); the app runs with a disabled vector backend."
  default     = true
}

variable "vertex_network" {
  type        = string
  description = "Full VPC network resource path for the PRIVATE Vertex AI index endpoint and Cloud Run egress, e.g. projects/PROJECT_NUMBER/global/networks/NETWORK. Required only when enable_vertex = true."
  default     = ""
}

variable "vertex_subnetwork" {
  type        = string
  description = "Subnetwork self-link for Cloud Run direct VPC egress (must be in var.region). Required only when enable_vertex = true."
  default     = ""
}

variable "vertex_index_dimensions" {
  type        = number
  description = "Embedding dimensionality (text-embedding-004 => 768)."
  default     = 768
}

variable "secret_names" {
  type        = list(string)
  description = "Secret Manager secret containers to create (values are added out-of-band)."
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

variable "labels" {
  type    = map(string)
  default = { app = "ai-hr-agent-team", managed-by = "terraform" }
}
