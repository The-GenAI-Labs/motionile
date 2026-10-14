output "path" {
  description = "Parameter namespace of the environment."
  value       = local.path
}

output "path_arn" {
  description = "ARN prefix of the parameter namespace."
  value       = local.path_arn
}

output "owner_parameter_names" {
  description = "SecureString parameters the owner uploads with infra/scripts/put-parameters.sh."
  value       = [for name in local.owner_names : "${local.path}/${name}"]
}

output "infra_parameter_names" {
  description = "Plain String parameters OpenTofu writes from its own outputs."
  value       = [for name in local.infra_names : "${local.path}/${name}"]
}

output "required_parameter_names" {
  description = "Parameters render-env.sh refuses to run without."
  value       = [for name in local.required_names : "${local.path}/${name}"]
}
