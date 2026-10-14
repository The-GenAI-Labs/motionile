resource "aws_db_subnet_group" "this" {
  name        = var.name
  description = "Private subnets for ${var.name}"
  subnet_ids  = var.subnet_ids
}

resource "aws_security_group" "database" {
  name        = "${var.name}-database"
  description = "PostgreSQL from the application instance only"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  for_each = toset(var.client_security_group_ids)

  security_group_id            = aws_security_group.database.id
  description                  = "PostgreSQL from the application"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = each.value
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name}-postgres${var.engine_version}"
  family      = "postgres${var.engine_version}"
  description = "Motionile settings with the vector, citext and pgcrypto extensions allowed"

  parameter {
    name  = "rds.allowed_extensions"
    value = "vector,citext,pgcrypto"
  }

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  identifier                            = var.name
  engine                                = "postgres"
  engine_version                        = var.engine_version
  instance_class                        = var.instance_class
  db_name                               = var.database_name
  username                              = var.master_username
  manage_master_user_password           = true
  allocated_storage                     = var.allocated_storage_gb
  max_allocated_storage                 = var.max_allocated_storage_gb
  storage_type                          = "gp3"
  storage_encrypted                     = true
  multi_az                              = var.multi_az
  db_subnet_group_name                  = aws_db_subnet_group.this.name
  vpc_security_group_ids                = [aws_security_group.database.id]
  parameter_group_name                  = aws_db_parameter_group.this.name
  publicly_accessible                   = false
  backup_retention_period               = var.backup_retention_days
  backup_window                         = "19:00-20:00"
  maintenance_window                    = "sun:20:30-sun:21:30"
  copy_tags_to_snapshot                 = true
  deletion_protection                   = true
  skip_final_snapshot                   = false
  final_snapshot_identifier             = "${var.name}-final"
  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  iam_database_authentication_enabled   = true
  auto_minor_version_upgrade            = true
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]
}
