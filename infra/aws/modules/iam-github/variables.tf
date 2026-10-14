variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "environment" {
  description = "GitHub environment allowed to assume the deploy role."
  type        = string
}

variable "github_repository" {
  description = "Repository in owner/name form."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

variable "create_oidc_provider" {
  description = "Create the GitHub Actions OIDC provider. Only one environment per account creates it."
  type        = bool
  default     = false
}

variable "oidc_provider_arn" {
  description = "ARN of an existing GitHub Actions OIDC provider when create_oidc_provider is false."
  type        = string
  default     = null
}

variable "push_repository_arns" {
  description = "ECR repositories the role pushes to."
  type        = list(string)
}

variable "pull_repository_arns" {
  description = "Additional ECR repositories the role reads from, such as staging repositories for promotion."
  type        = list(string)
  default     = []
}

variable "security_group_arn" {
  description = "Security group the role may open port 22 on during a deployment."
  type        = string
}
