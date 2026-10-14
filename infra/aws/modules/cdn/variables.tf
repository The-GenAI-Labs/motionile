variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "domain_name" {
  description = "CDN host name, for example cdn.motionile.com."
  type        = string
}

variable "web_origin" {
  description = "Origin of the web app allowed by CORS, for example https://motionile.com."
  type        = string
}

variable "enabled" {
  description = "Create the distribution. Keep false until the certificate validation records exist in DNS."
  type        = bool
  default     = false
}

variable "media_bucket_regional_domain_name" {
  description = "Regional domain name of the media bucket."
  type        = string
}

variable "log_bucket_arn" {
  description = "ARN of the bucket that receives standard logs under cloudfront/."
  type        = string
}

variable "public_keys" {
  description = "PEM public keys trusted for signed cookies and URLs, keyed by a short label. Keep the old key here during a rotation. Private keys never enter OpenTofu."
  type        = map(string)

  validation {
    condition     = length(var.public_keys) > 0 && alltrue([for label in keys(var.public_keys) : can(regex("^[a-z0-9-]{1,32}$", label))])
    error_message = "public_keys needs at least one key, labelled with 1-32 lowercase letters, digits or dashes."
  }
}

variable "active_public_key" {
  description = "Label of the key whose ID the application signs with."
  type        = string
}

variable "web_acl_arn" {
  description = "ARN of the CloudFront-scoped WAF web ACL."
  type        = string
  default     = null
}

variable "price_class" {
  description = "CloudFront price class; PriceClass_200 includes India."
  type        = string
  default     = "PriceClass_200"
}

variable "default_ttl_seconds" {
  description = "Default cache lifetime for media."
  type        = number
  default     = 86400
}
