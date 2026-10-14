output "endpoint" {
  description = "Host and port of the database."
  value       = aws_db_instance.this.endpoint
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret that RDS keeps the master password in."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  description = "Security group of the database."
  value       = aws_security_group.database.id
}
