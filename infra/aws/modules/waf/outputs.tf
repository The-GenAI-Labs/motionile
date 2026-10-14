output "web_acl_arn" {
  description = "ARN of the CloudFront-scoped web ACL."
  value       = aws_wafv2_web_acl.cdn.arn
}

output "log_group_name" {
  description = "CloudWatch log group in us-east-1 that receives WAF logs."
  value       = aws_cloudwatch_log_group.waf.name
}
