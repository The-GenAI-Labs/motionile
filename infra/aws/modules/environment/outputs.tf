output "elastic_ip" {
  description = "Elastic IP that api and mcp point to."
  value       = module.compute.elastic_ip
}

output "instance_id" {
  description = "Application instance; connect with aws ssm start-session --target <id>."
  value       = module.compute.instance_id
}

output "security_group_id" {
  description = "Security group the deploy workflow opens port 22 on."
  value       = module.compute.security_group_id
}

output "ecr_repository_urls" {
  description = "ECR repository URLs keyed by image name."
  value       = module.registry.repository_urls
}

output "ecr_repository_arns" {
  description = "ECR repository ARNs keyed by image name; production uses staging's for promotion."
  value       = module.registry.repository_arns
}

output "ecr_registry" {
  description = "ECR registry host."
  value       = module.registry.registry
}

output "deploy_role_arn" {
  description = "Role GitHub Actions assumes for this environment."
  value       = module.iam_github.deploy_role_arn
}

output "oidc_provider_arn" {
  description = "GitHub OIDC provider ARN."
  value       = module.iam_github.oidc_provider_arn
}

output "media_bucket_name" {
  description = "Private media bucket."
  value       = module.storage.media_bucket_name
}

output "backup_bucket_name" {
  description = "Backup bucket."
  value       = module.storage.backup_bucket_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID, null until enable_cdn is true."
  value       = module.cdn.distribution_id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain the cdn record points to, null until enable_cdn is true."
  value       = module.cdn.distribution_domain_name
}

output "cloudfront_key_group_id" {
  description = "Trusted key group for signed cookies and URLs."
  value       = module.cdn.key_group_id
}

output "cloudfront_public_key_id" {
  description = "Public key ID sent as CloudFront-Key-Pair-Id."
  value       = module.cdn.public_key_id
}

output "ses_configuration_set" {
  description = "SES configuration set."
  value       = module.email.configuration_set_name
}

output "ses_feedback_topic_arn" {
  description = "SNS topic for bounces and complaints."
  value       = module.email.feedback_topic_arn
}

output "alert_topic_arn" {
  description = "SNS topic every alarm notifies."
  value       = module.observability.alert_topic_arn
}

output "log_group_name" {
  description = "CloudWatch log group of the environment."
  value       = module.observability.log_group_name
}

output "parameter_path" {
  description = "SSM namespace of the environment configuration."
  value       = module.secrets.path
}

output "owner_parameter_names" {
  description = "SecureString parameters to upload with infra/scripts/put-parameters.sh."
  value       = module.secrets.owner_parameter_names
}

output "dns_validation_records" {
  description = "Records needed before enable_cdn can be true and before SES can send: certificate validation, DKIM, MAIL FROM and DMARC."
  value       = local.validation_records
}

output "dns_records" {
  description = "Every record the environment needs at the DNS provider."
  value       = local.dns_records
}

output "database_endpoint" {
  description = "RDS endpoint when enable_rds is true."
  value       = var.enable_rds ? module.database[0].endpoint : null
}

output "database_master_secret_arn" {
  description = "Secrets Manager secret holding the RDS master password when enable_rds is true."
  value       = var.enable_rds ? module.database[0].master_user_secret_arn : null
}

output "github_environment_variables" {
  description = "Values for the GitHub environment variables, see docs/runbooks/github-setup.md."
  value = {
    AWS_REGION              = data.aws_region.current.region
    AWS_DEPLOY_ROLE_ARN     = module.iam_github.deploy_role_arn
    ECR_REGISTRY            = module.registry.registry
    EC2_SECURITY_GROUP_ID   = module.compute.security_group_id
    DEPLOY_HOST             = module.compute.elastic_ip
    API_URL                 = "https://${local.api_domain}"
    MCP_URL                 = "https://${local.mcp_domain}"
    WEB_URL                 = var.web_origin
    IMAGE_REPOSITORY_API    = module.registry.repository_urls["motionile-api"]
    IMAGE_REPOSITORY_WORKER = module.registry.repository_urls["motionile-worker"]
  }
}
