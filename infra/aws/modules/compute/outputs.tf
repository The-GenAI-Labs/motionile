output "instance_id" {
  description = "ID of the application instance."
  value       = aws_instance.this.id
}

output "elastic_ip" {
  description = "Public Elastic IP of the instance."
  value       = aws_eip.this.public_ip
}

output "security_group_id" {
  description = "Security group of the instance; deployments open port 22 on it temporarily."
  value       = aws_security_group.instance.id
}

output "security_group_arn" {
  description = "ARN of the instance security group."
  value       = aws_security_group.instance.arn
}

output "instance_role_arn" {
  description = "ARN of the instance role."
  value       = aws_iam_role.instance.arn
}

output "data_volume_id" {
  description = "ID of the data volume."
  value       = aws_ebs_volume.data.id
}

output "ami_id" {
  description = "Ubuntu 24.04 AMI the instance was launched from."
  value       = aws_instance.this.ami
}
