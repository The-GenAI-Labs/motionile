output "deploy_role_arn" {
  description = "Role assumed by GitHub Actions; store it as the AWS_DEPLOY_ROLE_ARN environment variable."
  value       = aws_iam_role.deploy.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider, passed to the other environment."
  value       = local.oidc_provider_arn
}
