variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "environment" {
  description = "Environment name, staging or production."
  type        = string
}

variable "log_retention_days" {
  description = "Retention of the environment log group."
  type        = number
  default     = 30
}

variable "alert_email" {
  description = "Email address subscribed to the alert topic."
  type        = string
}

variable "instance_id" {
  description = "ID of the application instance."
  type        = string
}

variable "data_mount_path" {
  description = "Mount path of the data volume."
  type        = string
  default     = "/srv/motionile/data"
}

variable "cpu_threshold_percent" {
  description = "CPU utilisation that raises an alarm."
  type        = number
  default     = 80
}

variable "memory_threshold_percent" {
  description = "Memory use that raises an alarm."
  type        = number
  default     = 80
}

variable "disk_threshold_percent" {
  description = "Disk use on the root and data volumes that raises an alarm."
  type        = number
  default     = 80
}

variable "server_error_rate_threshold_percent" {
  description = "Share of API responses with status 5xx that raises an alarm."
  type        = number
  default     = 5
}

variable "server_error_minimum_requests" {
  description = "Requests needed in a period before the 5xx rate is evaluated."
  type        = number
  default     = 20
}

variable "task_failure_threshold" {
  description = "Failed worker tasks in 15 minutes that raise an alarm."
  type        = number
  default     = 5
}
