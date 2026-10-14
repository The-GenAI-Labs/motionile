output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs ordered by availability zone."
  value       = [for zone in local.zones : aws_subnet.public[zone].id]
}

output "private_subnet_ids" {
  description = "Private subnet IDs ordered by availability zone, reserved for RDS, ElastiCache and ECS."
  value       = [for zone in local.zones : aws_subnet.private[zone].id]
}

output "s3_endpoint_id" {
  description = "ID of the S3 gateway endpoint."
  value       = aws_vpc_endpoint.s3.id
}
