data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_subnet" "this" {
  id = var.subnet_id
}

data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  region         = data.aws_region.current.region
  account_id     = data.aws_caller_identity.current.account_id
  partition      = data.aws_partition.current.partition
  parameter_arn  = "arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter${var.parameter_path}"
  snapshot_tag   = "${var.name}-data"
  data_volume_id = replace(aws_ebs_volume.data.id, "-", "")
}

resource "aws_security_group" "instance" {
  name        = "${var.name}-instance"
  description = "Public HTTP and HTTPS for ${var.name}; SSH is opened per deployment for the runner only"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name}-instance"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "web" {
  for_each = {
    http-ipv4  = { port = 80, protocol = "tcp", cidr_ipv4 = "0.0.0.0/0", cidr_ipv6 = null }
    https-ipv4 = { port = 443, protocol = "tcp", cidr_ipv4 = "0.0.0.0/0", cidr_ipv6 = null }
    http3-ipv4 = { port = 443, protocol = "udp", cidr_ipv4 = "0.0.0.0/0", cidr_ipv6 = null }
    http-ipv6  = { port = 80, protocol = "tcp", cidr_ipv4 = null, cidr_ipv6 = "::/0" }
    https-ipv6 = { port = 443, protocol = "tcp", cidr_ipv4 = null, cidr_ipv6 = "::/0" }
    http3-ipv6 = { port = 443, protocol = "udp", cidr_ipv4 = null, cidr_ipv6 = "::/0" }
  }

  security_group_id = aws_security_group.instance.id
  description       = "Public ${each.key}"
  ip_protocol       = each.value.protocol
  from_port         = each.value.port
  to_port           = each.value.port
  cidr_ipv4         = each.value.cidr_ipv4
  cidr_ipv6         = each.value.cidr_ipv6
}

resource "aws_vpc_security_group_egress_rule" "all" {
  for_each = {
    ipv4 = { cidr_ipv4 = "0.0.0.0/0", cidr_ipv6 = null }
    ipv6 = { cidr_ipv4 = null, cidr_ipv6 = "::/0" }
  }

  security_group_id = aws_security_group.instance.id
  description       = "Outbound ${each.key} to provider APIs, ECR, SSM and package mirrors"
  ip_protocol       = "-1"
  cidr_ipv4         = each.value.cidr_ipv4
  cidr_ipv6         = each.value.cidr_ipv6
}

data "aws_iam_policy_document" "instance_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name}-instance"
  assume_role_policy = data.aws_iam_policy_document.instance_assume.json
}

resource "aws_iam_role_policy_attachment" "session_manager" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "instance" {
  statement {
    sid       = "EcrAuthorization"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
    ]
    resources = var.ecr_repository_arns
  }

  statement {
    sid       = "ReadEnvironmentParameters"
    actions   = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
    resources = [local.parameter_arn, "${local.parameter_arn}/*"]
  }

  statement {
    sid       = "ReadCloudWatchAgentConfiguration"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter/${var.cloudwatch_agent_parameter_name}"]
  }

  statement {
    sid       = "DecryptEnvironmentParameters"
    actions   = ["kms:Decrypt"]
    resources = ["arn:${local.partition}:kms:${local.region}:${local.account_id}:key/*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${local.region}.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values   = ["${local.parameter_arn}/*"]
    }
  }

  statement {
    sid       = "ListBuckets"
    actions   = ["s3:ListBucket"]
    resources = [var.media_bucket_arn, var.backup_bucket_arn]
  }

  statement {
    sid = "ReadWriteObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${var.media_bucket_arn}/*", "${var.backup_bucket_arn}/*"]
  }

  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [var.ses_identity_arn, var.ses_configuration_set_arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = [var.log_group_arn, "${var.log_group_arn}:*"]
  }

  statement {
    sid       = "PublishAgentMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["CWAgent"]
    }
  }

  statement {
    sid       = "DescribeForAgentDimensions"
    actions   = ["ec2:DescribeTags", "ec2:DescribeVolumes"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "motionile-runtime"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name}-instance"
  role = aws_iam_role.instance.name
}

resource "aws_ebs_volume" "data" {
  availability_zone = data.aws_subnet.this.availability_zone
  size              = var.data_volume_size_gb
  type              = "gp3"
  encrypted         = true

  tags = {
    Name     = "${var.name}-data"
    Snapshot = local.snapshot_tag
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_instance" "this" {
  ami                         = data.aws_ssm_parameter.ubuntu_ami.insecure_value
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.instance.id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true
  disable_api_termination     = true
  ebs_optimized               = true
  monitoring                  = true
  user_data_replace_on_change = false

  user_data = templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
    region                  = local.region
    environment             = var.environment
    data_volume_device      = "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${local.data_volume_id}"
    ci_ssh_public_key       = trimspace(var.ci_ssh_public_key)
    cloudwatch_agent_config = var.cloudwatch_agent_parameter_name
    docker_log_max_size     = var.docker_log_max_size
    docker_log_max_files    = var.docker_log_max_files
    systemd_units           = var.systemd_units
    systemd_timers          = [for file_name in keys(var.systemd_units) : file_name if endswith(file_name, ".timer")]
  })

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gb
    encrypted             = true
    delete_on_termination = true

    tags = {
      Name = "${var.name}-root"
    }
  }

  maintenance_options {
    auto_recovery = "default"
  }

  tags = {
    Name = var.name
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.this.id
}

resource "aws_eip" "this" {
  domain = "vpc"

  tags = {
    Name = var.name
  }
}

resource "aws_eip_association" "this" {
  instance_id   = aws_instance.this.id
  allocation_id = aws_eip.this.id
}

resource "aws_cloudwatch_metric_alarm" "system_recovery" {
  alarm_name          = "${var.name}-system-status-recovery"
  alarm_description   = "Recover ${var.name} when the underlying host fails its system status check."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "missing"
  alarm_actions       = ["arn:${local.partition}:automate:${local.region}:ec2:recover", var.alert_topic_arn]
  ok_actions          = [var.alert_topic_arn]

  dimensions = {
    InstanceId = aws_instance.this.id
  }
}

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "${var.name}-dlm"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "data" {
  description        = "Daily snapshots of the ${var.name} data volume"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]

    target_tags = {
      Snapshot = local.snapshot_tag
    }

    schedule {
      name      = "daily"
      copy_tags = true

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = [var.snapshot_time_utc]
      }

      retain_rule {
        count = var.snapshot_retention_days
      }

      tags_to_add = {
        SnapshotCreator = "dlm"
      }
    }
  }
}
