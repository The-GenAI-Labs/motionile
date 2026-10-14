variable "environment" {
  description = "Environment name used as the repository namespace."
  type        = string
}

variable "repository_names" {
  description = "Image names to create repositories for."
  type        = list(string)
  default     = ["motionile-api", "motionile-worker"]
}

variable "tagged_images_to_keep" {
  description = "Number of tagged images kept per repository."
  type        = number
  default     = 30
}

variable "untagged_expiry_days" {
  description = "Days after which untagged images expire."
  type        = number
  default     = 7
}
