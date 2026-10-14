variable "name" {
  description = "Prefix for resource names, for example motionile-staging."
  type        = string
}

variable "environment" {
  description = "Environment name, staging or production."
  type        = string
}

variable "vpc_id" {
  description = "VPC that holds the instance."
  type        = string
}

variable "subnet_id" {
  description = "Public subnet for the instance."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
}

variable "root_volume_size_gb" {
  description = "Size of the root volume."
  type        = number
  default     = 50
}

variable "data_volume_size_gb" {
  description = "Size of the data volume mounted at /srv/motionile/data."
  type        = number
  default     = 100
}

variable "snapshot_retention_days" {
  description = "Number of daily data volume snapshots to keep."
  type        = number
  default     = 7
}

variable "snapshot_time_utc" {
  description = "Daily snapshot start time in UTC, HH:MM."
  type        = string
  default     = "20:30"
}

variable "ci_ssh_public_key" {
  description = "Public key of the CI deploy key, installed for the deploy user."
  type        = string
}

variable "ecr_repository_arns" {
  description = "ECR repositories the instance pulls from."
  type        = list(string)
}

variable "media_bucket_arn" {
  description = "ARN of the media bucket."
  type        = string
}

variable "backup_bucket_arn" {
  description = "ARN of the backup bucket."
  type        = string
}

variable "ses_identity_arn" {
  description = "ARN of the SES identity the instance sends from."
  type        = string
}

variable "ses_configuration_set_arn" {
  description = "ARN of the SES configuration set used for sending."
  type        = string
}

variable "log_group_arn" {
  description = "ARN of the environment log group."
  type        = string
}

variable "parameter_path" {
  description = "SSM parameter path holding the environment configuration, for example /motionile/staging."
  type        = string
}

variable "cloudwatch_agent_parameter_name" {
  description = "Name of the SSM parameter holding the CloudWatch agent configuration."
  type        = string
}

variable "alert_topic_arn" {
  description = "SNS topic notified when the instance is recovered."
  type        = string
}

variable "systemd_units" {
  description = "Systemd unit files installed by cloud-init, keyed by file name."
  type        = map(string)
}

variable "docker_log_max_size" {
  description = "Maximum size of one Docker log file before rotation."
  type        = string
  default     = "20m"
}

variable "docker_log_max_files" {
  description = "Number of rotated Docker log files kept per container."
  type        = number
  default     = 5
}
