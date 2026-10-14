variable "name" {
  description = "Prefix for resource names, for example motionile-production."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the database."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the database subnet group."
  type        = list(string)
}

variable "client_security_group_ids" {
  description = "Security groups allowed to connect on 5432."
  type        = list(string)
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage_gb" {
  description = "Initial storage."
  type        = number
  default     = 50
}

variable "max_allocated_storage_gb" {
  description = "Upper bound for storage autoscaling."
  type        = number
  default     = 200
}

variable "engine_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "17"
}

variable "multi_az" {
  description = "Run a synchronous standby in a second availability zone."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Automated backup retention."
  type        = number
  default     = 14
}

variable "database_name" {
  description = "Name of the application database."
  type        = string
  default     = "motionile"
}

variable "master_username" {
  description = "Master user name; the password is generated and kept in Secrets Manager by RDS."
  type        = string
  default     = "motionile_admin"
}
