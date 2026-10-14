output "repository_urls" {
  description = "Repository URLs keyed by image name."
  value       = { for name, repository in aws_ecr_repository.this : name => repository.repository_url }
}

output "repository_arns" {
  description = "Repository ARNs keyed by image name."
  value       = { for name, repository in aws_ecr_repository.this : name => repository.arn }
}

output "registry" {
  description = "Registry host shared by every repository."
  value       = split("/", values(aws_ecr_repository.this)[0].repository_url)[0]
}
