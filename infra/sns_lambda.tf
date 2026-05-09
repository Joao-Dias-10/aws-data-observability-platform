# ── SNS Topic ───────────────────────────────────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts-${var.environment}"
}

# Subscription de email — confirmação manual necessária após apply
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Subscription da Lambda — processa e enriquece o evento
resource "aws_sns_topic_subscription" "lambda" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alert_handler.arn
}

# ── Lambda ───────────────────────────────────────────────────────────────────
resource "aws_lambda_function" "alert_handler" {
  function_name = "${var.project}-alert-handler-${var.environment}"
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  role          = aws_iam_role.lambda.arn
  filename      = "${path.module}/../lambda/lambda.zip"
  timeout       = 30
  memory_size   = 128

  environment {
    variables = {
      CLOUDWATCH_NAMESPACE = "SLAPlatform/${var.environment}"
      ENVIRONMENT          = var.environment
      SLACK_WEBHOOK_URL    = var.slack_webhook_url
    }
  }
}

# Permissão para o SNS invocar a Lambda
resource "aws_lambda_permission" "sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert_handler.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

# ── CloudWatch Alarm ─────────────────────────────────────────────────────────
# Alarme automático quando issues_count > 500 — sem custo de DB extra
resource "aws_cloudwatch_metric_alarm" "high_issues" {
  alarm_name          = "${var.project}-high-issues-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "IssuesCount"
  namespace           = "SLAPlatform/${var.environment}"
  period              = 300
  statistic           = "Sum"
  threshold           = 500
  alarm_description   = "Alto volume de inconsistências detectadas"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ── Athena Workgroup ─────────────────────────────────────────────────────────
# Limite de custo por query — evita scans acidentais caros
resource "aws_athena_workgroup" "sla" {
  name = "${var.project}-${var.environment}"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/athena-results/"
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    # Limite por query: máximo $5 de scan — protege contra queries sem WHERE
    bytes_scanned_cutoff_per_query = 5368709120  # 5 GB
  }
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "athena_workgroup" {
  value = aws_athena_workgroup.sla.name
}
