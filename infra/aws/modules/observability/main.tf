data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

locals {
  account_id       = data.aws_caller_identity.current.account_id
  metric_namespace = "Motionile/${var.environment}"
  host_log_files = {
    syslog     = "/var/log/syslog"
    cloud-init = "/var/log/cloud-init-output.log"
    deploy     = "/srv/motionile/logs/deploy.log"
  }
  agent_config = {
    agent = {
      metrics_collection_interval = 60
      run_as_user                 = "root"
    }
    metrics = {
      namespace = "CWAgent"
      append_dimensions = {
        InstanceId = "$${aws:InstanceId}"
      }
      aggregation_dimensions = [["InstanceId"], ["InstanceId", "path"]]
      metrics_collected = {
        mem = {
          measurement = ["mem_used_percent"]
        }
        disk = {
          measurement              = ["used_percent"]
          resources                = ["/", var.data_mount_path]
          drop_device              = true
          ignore_file_system_types = ["sysfs", "devtmpfs", "tmpfs", "overlay", "squashfs"]
        }
      }
    }
    logs = {
      logs_collected = {
        files = {
          collect_list = [
            for stream, path in local.host_log_files : {
              file_path       = path
              log_group_name  = aws_cloudwatch_log_group.this.name
              log_stream_name = "host/{instance_id}/${stream}"
            }
          ]
        }
      }
    }
  }
  log_metrics = {
    ApiRequests  = "{ $.event = \"http.request\" }"
    Api5xx       = "{ $.event = \"http.request\" && $.status >= 500 }"
    TaskFailures = "{ $.event = \"task.failed\" }"
  }
}

data "aws_iam_policy_document" "alerts_key" {
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowAlarmAndEmailPublishers"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com", "ses.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_kms_key" "alerts" {
  description             = "Encrypts ${var.name} alert and email feedback topics"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.alerts_key.json
}

resource "aws_kms_alias" "alerts" {
  name          = "alias/${var.name}-alerts"
  target_key_id = aws_kms_key.alerts.key_id
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/motionile/${var.environment}"
  retention_in_days = var.log_retention_days
}

resource "aws_ssm_parameter" "agent_config" {
  name        = "AmazonCloudWatch-${var.name}"
  description = "CloudWatch agent configuration for ${var.name}"
  type        = "String"
  tier        = "Standard"
  value       = jsonencode(local.agent_config)
}

resource "aws_cloudwatch_log_metric_filter" "this" {
  for_each = local.log_metrics

  name           = "${var.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.this.name
  pattern        = each.value

  metric_transformation {
    name          = each.key
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_sns_topic" "alerts" {
  name              = "${var.name}-alerts"
  kms_master_key_id = aws_kms_key.alerts.arn
}

data "aws_iam_policy_document" "alerts_topic" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:cloudwatch:${data.aws_region.current.region}:${local.account_id}:alarm:*"]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts_topic.json
}

resource "aws_sns_topic_subscription" "alert_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "cpu" {
  alarm_name          = "${var.name}-cpu-high"
  alarm_description   = "CPU above ${var.cpu_threshold_percent}% for 15 minutes."
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.cpu_threshold_percent
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = var.instance_id
  }
}

resource "aws_cloudwatch_metric_alarm" "memory" {
  alarm_name          = "${var.name}-memory-high"
  alarm_description   = "Memory use above ${var.memory_threshold_percent}% for 15 minutes."
  namespace           = "CWAgent"
  metric_name         = "mem_used_percent"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.memory_threshold_percent
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = var.instance_id
  }
}

resource "aws_cloudwatch_metric_alarm" "disk" {
  for_each = {
    root = "/"
    data = var.data_mount_path
  }

  alarm_name          = "${var.name}-disk-${each.key}-high"
  alarm_description   = "Disk use on ${each.value} above ${var.disk_threshold_percent}%."
  namespace           = "CWAgent"
  metric_name         = "disk_used_percent"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.disk_threshold_percent
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = var.instance_id
    path       = each.value
  }
}

resource "aws_cloudwatch_metric_alarm" "server_errors" {
  alarm_name          = "${var.name}-api-5xx-rate"
  alarm_description   = "More than ${var.server_error_rate_threshold_percent}% of API responses were 5xx in two consecutive 5-minute periods."
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.server_error_rate_threshold_percent
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "rate"
    expression  = "IF(requests >= ${var.server_error_minimum_requests}, 100 * errors / requests, 0)"
    label       = "5xx rate"
    return_data = true
  }

  metric_query {
    id = "errors"

    metric {
      namespace   = local.metric_namespace
      metric_name = "Api5xx"
      period      = 300
      stat        = "Sum"
    }
  }

  metric_query {
    id = "requests"

    metric {
      namespace   = local.metric_namespace
      metric_name = "ApiRequests"
      period      = 300
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "task_failures" {
  alarm_name          = "${var.name}-task-failures"
  alarm_description   = "At least ${var.task_failure_threshold} worker task failures in 15 minutes."
  namespace           = local.metric_namespace
  metric_name         = "TaskFailures"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.task_failure_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
