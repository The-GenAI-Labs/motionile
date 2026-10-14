module "environment" {
  source = "../../modules/environment"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  project                          = var.project
  environment                      = "production"
  domain                           = var.domain
  web_origin                       = var.web_origin
  additional_cors_origins          = var.additional_cors_origins
  vpc_cidr                         = var.vpc_cidr
  instance_type                    = var.instance_type
  data_volume_size_gb              = var.data_volume_size_gb
  snapshot_retention_days          = var.snapshot_retention_days
  ci_ssh_public_key                = var.ci_ssh_public_key
  cloudfront_public_key_pem        = var.cloudfront_public_key_pem
  enable_cdn                       = var.enable_cdn
  manage_dns                       = var.manage_dns
  route53_zone_id                  = var.route53_zone_id
  alert_email                      = var.alert_email
  acme_email                       = var.acme_email
  github_repository                = var.github_repository
  create_oidc_provider             = var.create_oidc_provider
  oidc_provider_arn                = var.oidc_provider_arn
  promotion_source_repository_arns = var.promotion_source_repository_arns
  waf_rate_limit_per_5_minutes     = var.waf_rate_limit_per_5_minutes
  log_level                        = var.log_level
  database_statement_cache_size    = var.database_statement_cache_size
  enable_rds                       = var.enable_rds
  rds_instance_class               = var.rds_instance_class
  rds_multi_az                     = var.rds_multi_az
  parameter_catalog_path           = "${path.root}/../../../../deploy/parameters.csv"
  systemd_unit_directory           = "${path.root}/../../../../deploy/systemd"
}
