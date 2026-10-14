variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "availability_zone_count" {
  description = "Number of availability zones to span."
  type        = number
  default     = 2
}

variable "flow_log_retention_days" {
  description = "Retention of VPC flow logs in CloudWatch."
  type        = number
  default     = 30
}
