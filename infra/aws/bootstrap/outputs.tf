output "state_bucket_name" {
  description = "Pass this to tofu init as -backend-config=bucket=<value> in every environment."
  value       = aws_s3_bucket.state.bucket
}

output "state_bucket_region" {
  description = "Region of the state bucket."
  value       = var.aws_region
}
