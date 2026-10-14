output "elastic_ip" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.elastic_ip
}

output "instance_id" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.instance_id
}

output "security_group_id" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.security_group_id
}

output "ecr_repository_urls" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.ecr_repository_urls
}

output "ecr_repository_arns" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.ecr_repository_arns
}

output "ecr_registry" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.ecr_registry
}

output "deploy_role_arn" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.deploy_role_arn
}

output "oidc_provider_arn" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.oidc_provider_arn
}

output "media_bucket_name" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.media_bucket_name
}

output "backup_bucket_name" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.backup_bucket_name
}

output "cloudfront_distribution_id" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.cloudfront_distribution_id
}

output "cloudfront_domain_name" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.cloudfront_domain_name
}

output "cloudfront_key_group_id" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.cloudfront_key_group_id
}

output "cloudfront_public_key_id" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.cloudfront_public_key_id
}

output "ses_configuration_set" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.ses_configuration_set
}

output "ses_feedback_topic_arn" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.ses_feedback_topic_arn
}

output "alert_topic_arn" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.alert_topic_arn
}

output "log_group_name" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.log_group_name
}

output "parameter_path" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.parameter_path
}

output "owner_parameter_names" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.owner_parameter_names
}

output "dns_validation_records" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.dns_validation_records
}

output "dns_records" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.dns_records
}

output "database_endpoint" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.database_endpoint
}

output "database_master_secret_arn" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.database_master_secret_arn
}

output "github_environment_variables" {
  description = "See modules/environment/outputs.tf."
  value       = module.environment.github_environment_variables
}
