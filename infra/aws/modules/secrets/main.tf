data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  path           = "/${var.project}/${var.environment}"
  owner_names    = [for row in var.parameter_catalog : row.name if row.source == "owner"]
  infra_names    = [for row in var.parameter_catalog : row.name if row.source == "infra"]
  required_names = [for row in var.parameter_catalog : row.name if row.required == "yes"]
  path_arn       = "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${local.path}"
}
