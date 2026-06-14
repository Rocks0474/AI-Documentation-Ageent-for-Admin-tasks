output "cloud_run_url" {
  description = "URL of the deployed Cloud Run service."
  value       = google_cloud_run_v2_service.app.uri
}

output "service_account_email" {
  description = "Runtime service account email."
  value       = google_service_account.run_sa.email
}

output "bucket_zone2" {
  value = google_storage_bucket.zone2.name
}

output "bucket_zone3" {
  value = google_storage_bucket.zone3.name
}

output "bucket_audit" {
  value = google_storage_bucket.audit.name
}

output "topic_routing" {
  value = google_pubsub_topic.routing.name
}

output "topic_statutory" {
  value = google_pubsub_topic.statutory.name
}

output "topic_workflow_triggers" {
  value = google_pubsub_topic.workflow.name
}

output "topic_notifications" {
  value = google_pubsub_topic.notifications.name
}

output "vertex_index_id_zone2" {
  value = google_vertex_ai_index.zone2.id
}

output "vertex_index_id_zone3" {
  value = google_vertex_ai_index.zone3.id
}

output "vertex_index_endpoint_id" {
  value = google_vertex_ai_index_endpoint.private.id
}

output "statutory_job_names" {
  description = "Cloud Scheduler job names for the Japan statutory calendar."
  value       = [for j in google_cloud_scheduler_job.statutory : j.name]
}
