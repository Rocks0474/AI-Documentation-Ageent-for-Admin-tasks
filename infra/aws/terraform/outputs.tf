output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.app.name
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "bucket_zone2" {
  value = aws_s3_bucket.zone2.bucket
}

output "bucket_zone3" {
  value = aws_s3_bucket.zone3.bucket
}

output "bucket_audit" {
  value = aws_s3_bucket.audit.bucket
}

output "sqs_queue_url_routing" {
  value = aws_sqs_queue.routing.url
}

output "sns_topic_arn_statutory" {
  value = aws_sns_topic.statutory.arn
}

output "sns_topic_arn_workflow" {
  value = aws_sns_topic.workflow.arn
}

output "sns_topic_arn_notifications" {
  value = aws_sns_topic.notifications.arn
}

output "opensearch_endpoint" {
  value = aws_opensearchserverless_collection.vectors.collection_endpoint
}

output "eventbridge_scheduler_role_arn" {
  value = aws_iam_role.scheduler.arn
}

output "audit_log_group" {
  value = aws_cloudwatch_log_group.audit.name
}

output "athena_workgroup" {
  value = aws_athena_workgroup.audit.name
}

output "statutory_schedule_names" {
  value = [for s in aws_scheduler_schedule.statutory : s.name]
}
