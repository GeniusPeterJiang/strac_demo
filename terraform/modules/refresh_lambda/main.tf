# Terraform module for materialized view refresh Lambda + EventBridge

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "refresh_lambda" {
  name              = "/aws/lambda/${var.project_name}-refresh-job-progress"
  retention_in_days = 7
}

# IAM Role for Lambda
resource "aws_iam_role" "refresh_lambda" {
  name = "${var.project_name}-refresh-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "refresh_lambda" {
  name = "${var.project_name}-refresh-lambda-policy"
  role = aws_iam_role.refresh_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # CloudWatch Logs
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      # VPC permissions (if Lambda is in VPC)
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DeleteNetworkInterface"
        ]
        Resource = "*"
      }
    ]
  })
}

# ECR Repository for refresh Lambda
resource "aws_ecr_repository" "refresh_lambda" {
  name                 = "${var.project_name}-refresh-lambda"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = false
  }

  lifecycle {
    prevent_destroy = false
  }
}

# Lambda Function
resource "aws_lambda_function" "refresh" {
  function_name = "${var.project_name}-refresh-job-progress"
  role          = aws_iam_role.refresh_lambda.arn

  # Using container image
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.refresh_lambda.repository_url}:latest"

  # VPC configuration (to access RDS)
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  environment {
    variables = {
      RDS_PROXY_ENDPOINT = var.rds_proxy_endpoint
      RDS_DBNAME         = var.rds_dbname
      RDS_USERNAME       = var.rds_username
      RDS_PASSWORD       = var.rds_password
      RDS_PORT           = "5432"
    }
  }

  timeout     = 60  # 1 minute timeout (refresh should be fast)
  memory_size = 256 # Small memory footprint

  depends_on = [
    aws_cloudwatch_log_group.refresh_lambda,
    aws_iam_role_policy.refresh_lambda
  ]

  lifecycle {
    ignore_changes = [
      image_uri  # Allow updates without Terraform detecting changes
    ]
  }
}

# EventBridge Rule - Trigger every 1 minute
resource "aws_cloudwatch_event_rule" "refresh_schedule" {
  name                = "${var.project_name}-refresh-job-progress"
  description         = "Trigger materialized view refresh every 1 minute"
  schedule_expression = "rate(1 minute)"
}

# EventBridge Target - Invoke Lambda
resource "aws_cloudwatch_event_target" "refresh_lambda" {
  rule      = aws_cloudwatch_event_rule.refresh_schedule.name
  target_id = "RefreshLambda"
  arn       = aws_lambda_function.refresh.arn
}

# Lambda Permission - Allow EventBridge to invoke
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.refresh.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.refresh_schedule.arn
}

# CloudWatch Alarm - Monitor Lambda errors
resource "aws_cloudwatch_metric_alarm" "refresh_errors" {
  alarm_name          = "${var.project_name}-refresh-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "60"
  statistic           = "Sum"
  threshold           = "5"
  alarm_description   = "Alert when refresh Lambda has too many errors"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.refresh.function_name
  }
}

