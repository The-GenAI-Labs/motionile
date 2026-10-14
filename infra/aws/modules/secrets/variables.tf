variable "project" {
  description = "Project name at the root of the parameter namespace."
  type        = string
  default     = "motionile"
}

variable "environment" {
  description = "Environment name, staging or production."
  type        = string
}

variable "parameter_catalog" {
  description = "Rows of deploy/parameters.csv: name, source, required and description."
  type = list(object({
    name        = string
    source      = string
    required    = string
    description = string
  }))
}
