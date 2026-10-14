variable "project" {
  description = "Project name used in resource names and the parameter namespace."
  type        = string
  default     = "motionile"
}

variable "environment" {
  description = "Environment name; must match the GitHub environment."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "domain" {
  description = "Registrable domain of the environment, for example motionile.com. api, mcp and cdn are created below it."
  type        = string
}

variable "web_origin" {
  description = "Origin of the web app on Vercel, for example https://motionile.com."
  type        = string

  validation {
    condition     = can(regex("^https://[a-z0-9.-]+$", var.web_origin))
    error_message = "web_origin must be a lowercase https origin without a path or trailing slash."
  }
}

variable "additional_cors_origins" {
  description = "Extra https origins allowed by the API, such as the www host."
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR block of the environment VPC."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
}

variable "root_volume_size_gb" {
  description = "Root volume size."
  type        = number
  default     = 50
}

variable "data_volume_size_gb" {
  description = "Data volume size."
  type        = number
  default     = 100
}

variable "snapshot_retention_days" {
  description = "Daily data volume snapshots to keep."
  type        = number
  default     = 7
}

variable "ci_ssh_public_key" {
  description = "OpenSSH public key of the CI deploy key."
  type        = string
}

variable "cloudfront_public_key_pem" {
  description = "PEM public key that CloudFront uses to verify signed cookies and URLs."
  type        = string
}

variable "enable_cdn" {
  description = "Create the CloudFront distribution and WAF. Set to true once the certificate validation record exists."
  type        = bool
  default     = false
}

variable "manage_dns" {
  description = "Create every DNS record in Route 53."
  type        = bool
  default     = false
}

variable "route53_zone_id" {
  description = "Hosted zone of the domain when manage_dns is true."
  type        = string
  default     = null
}

variable "alert_email" {
  description = "Email address that receives alarms."
  type        = string
}

variable "acme_email" {
  description = "Email address registered with Let's Encrypt by Caddy."
  type        = string
}

variable "github_repository" {
  description = "Repository in owner/name form that deploys this environment."
  type        = string
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider in this environment."
  type        = bool
  default     = false
}

variable "oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN when create_oidc_provider is false."
  type        = string
  default     = null
}

variable "promotion_source_repository_arns" {
  description = "ECR repositories this environment promotes images from."
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

variable "log_retention_days" {
  description = "Retention of the environment log group."
  type        = number
  default     = 30
}

variable "backup_retention_days" {
  description = "Retention of objects in the backup bucket."
  type        = number
  default     = 30
}

variable "database_statement_cache_size" {
  description = "asyncpg statement cache size; 0 behind a transaction-mode pooler such as Neon."
  type        = number
  default     = 0
}

variable "enable_rds" {
  description = "Create an RDS PostgreSQL instance instead of using Neon."
  type        = bool
  default     = false
}

variable "rds_instance_class" {
  description = "RDS instance class when enable_rds is true."
  type        = string
  default     = "db.t4g.medium"
}

variable "rds_multi_az" {
  description = "Run RDS with a Multi-AZ standby."
  type        = bool
  default     = false
}

variable "rds_allocated_storage_gb" {
  description = "Initial RDS storage."
  type        = number
  default     = 50
}

variable "parameter_catalog_path" {
  description = "Path of deploy/parameters.csv, the shared list of environment parameters."
  type        = string
}

variable "systemd_unit_directory" {
  description = "Directory holding the systemd units installed by cloud-init."
  type        = string
}
