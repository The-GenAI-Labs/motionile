output "certificate_arn" {
  description = "ARN of the us-east-1 certificate for the CDN host."
  value       = aws_acm_certificate.cdn.arn
}

output "certificate_validation_records" {
  description = "DNS record that validates the CDN certificate, keyed by a stable label."
  value = {
    cdn-certificate-validation = {
      name  = tolist(aws_acm_certificate.cdn.domain_validation_options)[0].resource_record_name
      type  = tolist(aws_acm_certificate.cdn.domain_validation_options)[0].resource_record_type
      value = tolist(aws_acm_certificate.cdn.domain_validation_options)[0].resource_record_value
    }
  }
}

output "distribution_id" {
  description = "ID of the CloudFront distribution, or null while the CDN is disabled."
  value       = var.enabled ? aws_cloudfront_distribution.this[0].id : null
}

output "distribution_arn" {
  description = "ARN of the CloudFront distribution, or null while the CDN is disabled."
  value       = var.enabled ? aws_cloudfront_distribution.this[0].arn : null
}

output "distribution_domain_name" {
  description = "CloudFront domain the CDN CNAME points to, or null while the CDN is disabled."
  value       = var.enabled ? aws_cloudfront_distribution.this[0].domain_name : null
}

output "distribution_hosted_zone_id" {
  description = "Route 53 zone ID for alias records to the distribution."
  value       = var.enabled ? aws_cloudfront_distribution.this[0].hosted_zone_id : null
}

output "key_group_id" {
  description = "ID of the trusted key group that signs cookies and URLs."
  value       = aws_cloudfront_key_group.signing.id
}

output "public_key_id" {
  description = "ID of the active CloudFront public key; signed cookies send it as CloudFront-Key-Pair-Id."
  value       = aws_cloudfront_public_key.signing[var.active_public_key].id
}
