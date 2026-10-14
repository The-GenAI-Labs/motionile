output "media_bucket_name" {
  description = "Name of the private media bucket."
  value       = aws_s3_bucket.this["media"].bucket
}

output "media_bucket_arn" {
  description = "ARN of the media bucket."
  value       = aws_s3_bucket.this["media"].arn
}

output "media_bucket_regional_domain_name" {
  description = "Regional domain name of the media bucket, used as the CloudFront origin."
  value       = aws_s3_bucket.this["media"].bucket_regional_domain_name
}

output "backup_bucket_name" {
  description = "Name of the backup bucket."
  value       = aws_s3_bucket.this["backup"].bucket
}

output "backup_bucket_arn" {
  description = "ARN of the backup bucket."
  value       = aws_s3_bucket.this["backup"].arn
}
