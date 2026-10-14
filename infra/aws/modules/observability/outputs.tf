output "log_group_name" {
  description = "Environment log group; containers write to it through the awslogs driver."
  value       = aws_cloudwatch_log_group.this.name
}

output "log_group_arn" {
  description = "ARN of the environment log group."
  value       = aws_cloudwatch_log_group.this.arn
}

output "agent_config_parameter_name" {
  description = "SSM parameter that holds the CloudWatch agent configuration."
  value       = aws_ssm_parameter.agent_config.name
}

output "alert_topic_arn" {
  description = "SNS topic that receives every alarm."
  value       = aws_sns_topic.alerts.arn
}

output "kms_key_arn" {
  description = "Customer managed key that encrypts the alert and feedback topics."
  value       = aws_kms_key.alerts.arn
}

output "metric_namespace" {
  description = "Namespace of the log-based application metrics."
  value       = local.metric_namespace
}
