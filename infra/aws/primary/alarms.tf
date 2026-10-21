# CloudWatch alarms for the safety-critical paths.
#
# A personal-safety app must page a human if alert dispatch stops. Before this
# there were no alarms at all. The most important is the worker heartbeat: the
# every-60s worker dispatches overdue/SOS alerts, so "no tick completed in N
# minutes" means alerts may be silently failing.
#
# NOTE: requires `terraform plan` review before apply (alarm thresholds may need
# tuning to real traffic; the email subscription must be confirmed once).

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts-${local.env}"

  tags = {
    Name = "${local.name_prefix}-alerts-${local.env}"
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Worker heartbeat (the single most important alarm) -----------------------
# The worker logs "tick complete: {...}" once per successful tick. Count those
# and alarm when none arrive — treat missing data as breaching so a worker that
# stopped emitting entirely (service crash-loop, stopped task) fires.

resource "aws_cloudwatch_log_metric_filter" "worker_heartbeat" {
  name           = "${local.name_prefix}-worker-tick-${local.env}"
  log_group_name = aws_cloudwatch_log_group.task["worker"].name
  pattern        = "\"tick complete\""

  metric_transformation {
    name          = "WorkerTickComplete"
    namespace     = "${local.name_prefix}/${local.env}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_no_heartbeat" {
  alarm_name          = "${local.name_prefix}-worker-no-heartbeat-${local.env}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.worker_heartbeat.metric_transformation[0].name
  namespace           = "${local.name_prefix}/${local.env}"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_description   = "No worker tick completed in 5 min — overdue/SOS alert dispatch may be down."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# --- ALB health ---------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx-${local.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  alarm_description   = "Sustained 5xx from the web service."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.web.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  alarm_name          = "${local.name_prefix}-alb-unhealthy-${local.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "Web target group has unhealthy hosts."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.web.arn_suffix
    TargetGroup  = aws_lb_target_group.web.arn_suffix
  }
}

# --- RDS ----------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name_prefix}-rds-cpu-${local.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_description   = "RDS CPU sustained > 85%."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "${local.name_prefix}-rds-storage-${local.env}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 2147483648 # 2 GiB
  treat_missing_data  = "notBreaching"
  alarm_description   = "RDS free storage < 2 GiB."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_freeable_memory" {
  alarm_name          = "${local.name_prefix}-rds-memory-${local.env}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 134217728 # 128 MiB
  treat_missing_data  = "notBreaching"
  alarm_description   = "RDS freeable memory < 128 MiB."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.identifier
  }
}
