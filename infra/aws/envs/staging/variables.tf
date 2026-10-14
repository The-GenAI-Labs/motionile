variable "project" {
  description = "Project name used in resource names."
  type        = string
  default     = "motionile"
}

variable "aws_region" {
  description = "Region of every regional resource."
  type        = string
  default     = "ap-south-1"
}

variable "domain" {
  description = "Registrable domain of staging; api, mcp and cdn are created below it."
  type        = string
}

variable "web_origin" {
  description = "Origin of the staging web app on Vercel."
  type        = string
}

variable "additional_cors_origins" {
  description = "Extra https origins allowed by the API."
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "c7i.xlarge"
}

variable "data_volume_size_gb" {
  description = "Size of the data volume."
  type        = number
  default     = 100
}

variable "snapshot_retention_days" {
  description = "Daily data volume snapshots to keep."
  type        = number
  default     = 7
}

variable "ci_ssh_public_key" {
  description = "OpenSSH public key of the staging CI deploy key."
  type        = string
}

variable "cloudfront_public_key_pem" {
  description = "PEM public key that verifies signed cookies and URLs."
  type        = string
}

variable "enable_cdn" {
  description = "Create CloudFront and WAF once the certificate validation record exists."
  type        = bool
  default     = false
}

variable "manage_dns" {
  description = "Manage every record in Route 53."
  type        = bool
  default     = false
}

variable "route53_zone_id" {
  description = "Hosted zone ID when manage_dns is true."
  type        = string
  default     = null
}

variable "alert_email" {
  description = "Address that receives alarms."
  type        = string
}

variable "acme_email" {
  description = "Address registered with Let's Encrypt."
  type        = string
}

variable "github_repository" {
  description = "Repository in owner/name form."
  type        = string
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider here; exactly one environment per account does."
  type        = bool
  default     = true
}

variable "oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN when create_oidc_provider is false."
  type        = string
  default     = null
}

variable "promotion_source_repository_arns" {
  description = "ECR repositories images are promoted from."
  type        = list(string)
  default     = []
}

variable "waf_rate_limit_per_5_minutes" {
  description = "Requests per IP in 5 minutes before the CDN blocks it."
  type        = number
  default     = 2000
}

variable "log_level" {
  description = "Server log level."
  type        = string
  default     = "INFO"
}

variable "database_statement_cache_size" {
  description = "asyncpg statement cache size; 0 behind Neon's pooler, 100 with RDS."
  type        = number
  default     = 0
}

variable "enable_rds" {
  description = "Create RDS PostgreSQL instead of using Neon."
  type        = bool
  default     = false
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "rds_multi_az" {
  description = "Run RDS with a Multi-AZ standby."
  type        = bool
  default     = false
}
