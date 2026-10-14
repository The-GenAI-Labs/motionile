variable "project" {
  description = "Project name used as a prefix for every resource."
  type        = string
  default     = "motionile"
}

variable "aws_region" {
  description = "Region that holds the state bucket."
  type        = string
  default     = "ap-south-1"
}

variable "state_bucket_name" {
  description = "Globally unique name of the OpenTofu state bucket. Leave empty to derive one from the project and account ID."
  type        = string
  default     = ""
}

variable "noncurrent_version_retention_days" {
  description = "Days to keep superseded state versions."
  type        = number
  default     = 90
}
