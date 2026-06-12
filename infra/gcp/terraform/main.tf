terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Locals — bucket/topic names and the Japan statutory filing calendar seed jobs.
# These mirror config/japan_statutory_calendar.py:JAPAN_STATUTORY_JOBS exactly.
# ---------------------------------------------------------------------------
locals {
  bucket_zone2 = "${var.bucket_prefix}-zone2"
  bucket_zone3 = "${var.bucket_prefix}-zone3"
  bucket_audit = "${var.bucket_prefix}-audit"

  topic_routing       = "routing"
  topic_statutory     = "statutory-filing-alerts"
  topic_workflow      = "hr-workflow-triggers"
  topic_notifications = "hr-notifications"

  statutory_jobs = {
    jp_rodo_hoken_renewal = {
      schedule = "0 9 1 6 *" # June 1 annually — 労働保険年度更新
      topic    = local.topic_statutory
      payload  = { filing_type = "労働保険年度更新", deadline_days = 50 }
    }
    jp_santei_kiso_todoke = {
      schedule = "0 9 1 7 *" # July 1 annually — 算定基礎届
      topic    = local.topic_statutory
      payload  = { filing_type = "算定基礎届", deadline_days = 10 }
    }
    jp_nenmatsuchosei_prep = {
      schedule = "0 9 1 11 *" # November 1 annually — 年末調整
      topic    = local.topic_statutory
      payload  = { filing_type = "年末調整", deadline_days = 60 }
    }
    jp_36kyotei_check = {
      schedule = "0 9 1 * *" # 1st of every month — 36協定更新確認
      topic    = local.topic_statutory
      payload  = { filing_type = "36協定更新確認", deadline_days = 30 }
    }
    jp_merit_cycle_trigger = {
      schedule = "0 9 1 2 *" # February 1 — MERIT_CYCLE_PREP
      topic    = local.topic_workflow
      payload  = { workflow_type = "MERIT_CYCLE_PREP", jurisdiction = "JP" }
    }
  }
}

# ---------------------------------------------------------------------------
# Storage — Zone 2 (controlled), Zone 3 (public knowledge), Audit (WORM-ish).
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "zone2" {
  name                        = local.bucket_zone2
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = var.labels
}

resource "google_storage_bucket" "zone3" {
  name                        = local.bucket_zone3
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = var.labels
}

resource "google_storage_bucket" "audit" {
  name                        = local.bucket_audit
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = var.labels

  # Versioning keeps every prior version of an audit object — append-only
  # history with a mutable-looking surface for approval provenance.
  versioning { enabled = true }

  # Retain audit objects for J-SOX / GDPR / APPI review windows.
  retention_policy {
    retention_period = 220752000 # ~7 years in seconds
  }
}

# ---------------------------------------------------------------------------
# Pub/Sub — routing plane, statutory alerts, workflow triggers, notifications.
# ---------------------------------------------------------------------------
resource "google_pubsub_topic" "routing" {
  name   = local.topic_routing
  labels = var.labels
}

resource "google_pubsub_topic" "statutory" {
  name   = local.topic_statutory
  labels = var.labels
}

resource "google_pubsub_topic" "workflow" {
  name   = local.topic_workflow
  labels = var.labels
}

resource "google_pubsub_topic" "notifications" {
  name   = local.topic_notifications
  labels = var.labels
}

resource "google_pubsub_subscription" "routing" {
  name                 = "${local.topic_routing}-sub"
  topic                = google_pubsub_topic.routing.id
  ack_deadline_seconds = 60
  labels               = var.labels
}

# ---------------------------------------------------------------------------
# Secret Manager — containers only; values are added out-of-band.
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(var.secret_names)
  secret_id = each.value
  labels    = var.labels
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

# ---------------------------------------------------------------------------
# Service account for Cloud Run + IAM.
# ---------------------------------------------------------------------------
resource "google_service_account" "run_sa" {
  account_id   = "${var.service_name}-sa"
  display_name = "AI HR Agent Team Cloud Run SA"
}

resource "google_storage_bucket_iam_member" "sa_buckets" {
  for_each = {
    zone2 = google_storage_bucket.zone2.name
    zone3 = google_storage_bucket.zone3.name
    audit = google_storage_bucket.audit.name
  }
  bucket = each.value
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_pubsub_topic_iam_member" "sa_publisher" {
  for_each = {
    routing       = google_pubsub_topic.routing.name
    statutory     = google_pubsub_topic.statutory.name
    workflow      = google_pubsub_topic.workflow.name
    notifications = google_pubsub_topic.notifications.name
  }
  topic  = each.value
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_pubsub_subscription_iam_member" "sa_subscriber" {
  subscription = google_pubsub_subscription.routing.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "sa_secret_accessor" {
  for_each  = google_secret_manager_secret.secrets
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_project_iam_member" "sa_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_project_iam_member" "sa_scheduler_admin" {
  project = var.project_id
  role    = "roles/cloudscheduler.admin"
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}

# ---------------------------------------------------------------------------
# Vertex AI Vector Search — Zone 2 and Zone 3 indexes on a PRIVATE endpoint.
# ---------------------------------------------------------------------------
resource "google_vertex_ai_index" "zone2" {
  region              = var.region
  display_name        = "${var.service_name}-zone2"
  index_update_method = "STREAM_UPDATE"
  labels              = var.labels
  metadata {
    config {
      dimensions                  = var.vertex_index_dimensions
      approximate_neighbors_count = 150
      distance_measure_type       = "DOT_PRODUCT_DISTANCE"
      algorithm_config {
        tree_ah_config {
          leaf_node_embedding_count    = 500
          leaf_nodes_to_search_percent = 10
        }
      }
    }
  }
}

resource "google_vertex_ai_index" "zone3" {
  region              = var.region
  display_name        = "${var.service_name}-zone3"
  index_update_method = "STREAM_UPDATE"
  labels              = var.labels
  metadata {
    config {
      dimensions                  = var.vertex_index_dimensions
      approximate_neighbors_count = 150
      distance_measure_type       = "DOT_PRODUCT_DISTANCE"
      algorithm_config {
        tree_ah_config {
          leaf_node_embedding_count    = 500
          leaf_nodes_to_search_percent = 10
        }
      }
    }
  }
}

resource "google_vertex_ai_index_endpoint" "private" {
  display_name = "${var.service_name}-endpoint"
  region       = var.region
  network      = var.vertex_network # private endpoint (VPC-peered)
  labels       = var.labels
}

resource "google_vertex_ai_index_endpoint_deployed_index" "zone2" {
  index_endpoint    = google_vertex_ai_index_endpoint.private.id
  index             = google_vertex_ai_index.zone2.id
  deployed_index_id = "zone2"
  automatic_resources {
    min_replica_count = 1
    max_replica_count = 2
  }
}

resource "google_vertex_ai_index_endpoint_deployed_index" "zone3" {
  index_endpoint    = google_vertex_ai_index_endpoint.private.id
  index             = google_vertex_ai_index.zone3.id
  deployed_index_id = "zone3"
  automatic_resources {
    min_replica_count = 1
    max_replica_count = 2
  }
}

# ---------------------------------------------------------------------------
# Cloud Run — the single Docker image, configured for GCP via env vars.
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "app" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = google_service_account.run_sa.email
    scaling { min_instance_count = 1 }

    vpc_access {
      network_interfaces {
        network    = var.vertex_network
        subnetwork = var.vertex_subnetwork
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image

      env {
        name  = "CLOUD_TARGET"
        value = "GCP"
      }
      env {
        name  = "RUN_MODE"
        value = "api" # serve the ingestion + approval API (worker runs in-process)
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "DEFAULT_JURISDICTION"
        value = var.default_jurisdiction
      }
      env {
        name  = "DEFAULT_OUTPUT_LANGUAGE"
        value = var.default_output_language
      }
      env {
        name  = "MINIMUM_COHORT_SIZE"
        value = tostring(var.minimum_cohort_size)
      }
      env {
        name  = "HRIS_SYSTEM"
        value = var.hris_system
      }
      env {
        name  = "HRIS_API_BASE_URL"
        value = var.hris_api_base_url
      }
      env {
        name  = "HRIS_API_KEY_SECRET"
        value = "hris-api-key"
      }
      env {
        name  = "GCS_BUCKET_ZONE2"
        value = google_storage_bucket.zone2.name
      }
      env {
        name  = "GCS_BUCKET_ZONE3"
        value = google_storage_bucket.zone3.name
      }
      env {
        name  = "GCS_BUCKET_AUDIT"
        value = google_storage_bucket.audit.name
      }
      env {
        name  = "PUBSUB_TOPIC_ROUTING"
        value = google_pubsub_topic.routing.name
      }
      env {
        name  = "PUBSUB_TOPIC_NOTIFICATIONS"
        value = google_pubsub_topic.notifications.name
      }
      env {
        name  = "VERTEX_INDEX_ID_ZONE2"
        value = google_vertex_ai_index.zone2.id
      }
      env {
        name  = "VERTEX_INDEX_ID_ZONE3"
        value = google_vertex_ai_index.zone3.id
      }
      env {
        name  = "VERTEX_INDEX_ENDPOINT_ID"
        value = google_vertex_ai_index_endpoint.private.id
      }
      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "anthropic-api-key"
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.sa_secret_accessor]
}

# ---------------------------------------------------------------------------
# Cloud Scheduler — Japan statutory filing calendar (one job per seed entry).
# ---------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "statutory" {
  for_each = local.statutory_jobs

  name      = each.key
  region    = var.region
  schedule  = each.value.schedule
  time_zone = "Asia/Tokyo"

  pubsub_target {
    topic_name = "projects/${var.project_id}/topics/${each.value.topic}"
    data       = base64encode(jsonencode(each.value.payload))
  }
}
