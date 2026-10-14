variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "web_origin" {
  description = "Origin that /media requests must name in their Referer, for example https://motionile.com."
  type        = string
}

variable "rate_limit_per_5_minutes" {
  description = "Requests allowed per client IP in any 5-minute window."
  type        = number
  default     = 2000
}

variable "log_retention_days" {
  description = "Retention of WAF logs."
  type        = number
  default     = 30
}
