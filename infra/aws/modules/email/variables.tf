variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "domain" {
  description = "Domain mail is sent from, for example motionile.com."
  type        = string
}

variable "mail_from_subdomain" {
  description = "Subdomain used as the custom MAIL FROM domain."
  type        = string
  default     = "mail"
}

variable "kms_key_arn" {
  description = "Customer managed key that encrypts the feedback topic."
  type        = string
}
