variable "name" {
  description = "Prefix for bucket names; must be globally unique, for example motionile-staging-123456789012."
  type        = string
}

variable "web_origin" {
  description = "Origin of the web app allowed by bucket CORS, for example https://motionile.com."
  type        = string
}

variable "cloudfront_distribution_arn" {
  description = "ARN of the CloudFront distribution allowed to read media. Null until the CDN is enabled."
  type        = string
  default     = null
}

variable "enable_cloudfront_reads" {
  description = "Grant the CloudFront distribution read access to media."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Days to keep objects in the backup bucket."
  type        = number
  default     = 30
}

variable "noncurrent_version_retention_days" {
  description = "Days to keep overwritten or deleted media versions."
  type        = number
  default     = 30
}

variable "work_retention_days" {
  description = "Days to keep render checkpoints and intermediate files under work/ before the lifecycle rule expires them."
  type        = number
  default     = 7
}
