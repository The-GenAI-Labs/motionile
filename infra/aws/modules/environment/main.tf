data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  name          = "${var.project}-${var.environment}"
  bucket_prefix = "${local.name}-${data.aws_caller_identity.current.account_id}"
  api_domain    = "api.${var.domain}"
  mcp_domain    = "mcp.${var.domain}"
  cdn_domain    = "cdn.${var.domain}"
  web_host      = trimprefix(var.web_origin, "https://")
  cors_origins  = distinct(concat([var.web_origin], var.additional_cors_origins))
  catalog       = csvdecode(file(var.parameter_catalog_path))
  systemd_units = { for file_name in fileset(var.systemd_unit_directory, "*.{service,timer}") : file_name => file("${var.systemd_unit_directory}/${file_name}") }

  infra_parameters = merge(
    {
      APP_ENV                       = var.environment
      PROVIDERS_MODE                = "live"
      LOG_LEVEL                     = var.log_level
      AWS_REGION                    = data.aws_region.current.region
      API_DOMAIN                    = local.api_domain
      MCP_DOMAIN                    = local.mcp_domain
      CDN_DOMAIN                    = local.cdn_domain
      ACME_EMAIL                    = var.acme_email
      CORS_ALLOWED_ORIGINS          = join(",", local.cors_origins)
      TURNSTILE_EXPECTED_HOSTNAMES  = local.web_host
      STORAGE_BUCKET                = module.storage.media_bucket_name
      STORAGE_REGION                = data.aws_region.current.region
      STORAGE_FORCE_PATH_STYLE      = "false"
      BACKUP_BUCKET                 = module.storage.backup_bucket_name
      IMAGE_REPOSITORY_API          = module.registry.repository_urls["motionile-api"]
      IMAGE_REPOSITORY_WORKER       = module.registry.repository_urls["motionile-worker"]
      ECR_REGISTRY                  = module.registry.registry
      CLOUDWATCH_LOG_GROUP          = module.observability.log_group_name
      SES_CONFIGURATION_SET         = module.email.configuration_set_name
      EMAIL_FROM_DOMAIN             = var.domain
      DATABASE_STATEMENT_CACHE_SIZE = tostring(var.database_statement_cache_size)
    },
    var.enable_cdn ? { CLOUDFRONT_KEY_PAIR_ID = module.cdn.public_key_id } : {},
  )

  host_records = {
    api = { name = local.api_domain, type = "A", value = module.compute.elastic_ip }
    mcp = { name = local.mcp_domain, type = "A", value = module.compute.elastic_ip }
  }
  cdn_records = var.enable_cdn ? {
    cdn = { name = local.cdn_domain, type = "CNAME", value = module.cdn.distribution_domain_name }
  } : {}
  validation_records = merge(module.cdn.certificate_validation_records, module.email.dns_records)
  dns_records        = merge(local.host_records, local.cdn_records, local.validation_records)
}

module "network" {
  source = "../network"

  name     = local.name
  vpc_cidr = var.vpc_cidr
}

module "registry" {
  source = "../registry"

  environment = var.environment
}

module "storage" {
  source = "../storage"

  name                        = local.bucket_prefix
  web_origin                  = var.web_origin
  backup_retention_days       = var.backup_retention_days
  enable_cloudfront_reads     = var.enable_cdn
  cloudfront_distribution_arn = module.cdn.distribution_arn
}

module "observability" {
  source = "../observability"

  name               = local.name
  environment        = var.environment
  alert_email        = var.alert_email
  log_retention_days = var.log_retention_days
  instance_id        = module.compute.instance_id
}

module "email" {
  source = "../email"

  name        = local.name
  domain      = var.domain
  kms_key_arn = module.observability.kms_key_arn
}

module "secrets" {
  source = "../secrets"

  project           = var.project
  environment       = var.environment
  parameter_catalog = local.catalog
}

module "compute" {
  source = "../compute"

  name                            = local.name
  environment                     = var.environment
  vpc_id                          = module.network.vpc_id
  subnet_id                       = module.network.public_subnet_ids[0]
  instance_type                   = var.instance_type
  root_volume_size_gb             = var.root_volume_size_gb
  data_volume_size_gb             = var.data_volume_size_gb
  snapshot_retention_days         = var.snapshot_retention_days
  ci_ssh_public_key               = var.ci_ssh_public_key
  ecr_repository_arns             = values(module.registry.repository_arns)
  media_bucket_arn                = module.storage.media_bucket_arn
  backup_bucket_arn               = module.storage.backup_bucket_arn
  ses_identity_arn                = module.email.identity_arn
  ses_configuration_set_arn       = module.email.configuration_set_arn
  log_group_arn                   = module.observability.log_group_arn
  parameter_path                  = module.secrets.path
  cloudwatch_agent_parameter_name = module.observability.agent_config_parameter_name
  alert_topic_arn                 = module.observability.alert_topic_arn
  systemd_units                   = local.systemd_units
}

module "waf" {
  source = "../waf"
  count  = var.enable_cdn ? 1 : 0

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name                     = local.name
  web_origin               = var.web_origin
  rate_limit_per_5_minutes = var.waf_rate_limit_per_5_minutes
}

module "cdn" {
  source = "../cdn"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name                              = local.name
  domain_name                       = local.cdn_domain
  web_origin                        = var.web_origin
  enabled                           = var.enable_cdn
  media_bucket_regional_domain_name = module.storage.media_bucket_regional_domain_name
  log_bucket_arn                    = module.storage.backup_bucket_arn
  public_key_pem                    = var.cloudfront_public_key_pem
  web_acl_arn                       = var.enable_cdn ? module.waf[0].web_acl_arn : null
}

module "iam_github" {
  source = "../iam-github"

  name                 = local.name
  environment          = var.environment
  github_repository    = var.github_repository
  create_oidc_provider = var.create_oidc_provider
  oidc_provider_arn    = var.oidc_provider_arn
  push_repository_arns = values(module.registry.repository_arns)
  pull_repository_arns = var.promotion_source_repository_arns
  security_group_arn   = module.compute.security_group_arn
}

module "dns" {
  source = "../dns"

  enabled = var.manage_dns
  zone_id = var.route53_zone_id
  records = local.dns_records
}

module "database" {
  source = "../database"
  count  = var.enable_rds ? 1 : 0

  name                      = local.name
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.private_subnet_ids
  client_security_group_ids = [module.compute.security_group_id]
  instance_class            = var.rds_instance_class
  multi_az                  = var.rds_multi_az
  allocated_storage_gb      = var.rds_allocated_storage_gb
}

resource "aws_ssm_parameter" "infra" {
  for_each = toset(keys(local.infra_parameters))

  name        = "${module.secrets.path}/${each.key}"
  description = "Managed by OpenTofu from infrastructure outputs"
  type        = "String"
  tier        = "Standard"
  value       = local.infra_parameters[each.key]

  lifecycle {
    precondition {
      condition     = contains(module.secrets.infra_parameter_names, "${module.secrets.path}/${each.key}")
      error_message = "Every infrastructure parameter must be listed in deploy/parameters.csv with source infra."
    }
  }
}

check "infra_parameters_cover_catalog" {
  assert {
    condition = alltrue([
      for name in module.secrets.infra_parameter_names :
      contains([for key in keys(local.infra_parameters) : "${module.secrets.path}/${key}"], name) || name == "${module.secrets.path}/CLOUDFRONT_KEY_PAIR_ID"
    ])
    error_message = "deploy/parameters.csv lists an infrastructure parameter that OpenTofu does not write."
  }
}
