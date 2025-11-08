# SQS Queue for scan jobs
resource "aws_sqs_queue" "scan_jobs" {
  name                       = "${var.project_name}-scan-jobs"
  visibility_timeout_seconds = var.visibility_timeout
  message_retention_seconds   = var.message_retention
  receive_wait_time_seconds   = 20 # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = {
    Name = "${var.project_name}-scan-jobs"
  }
}

# Dead Letter Queue
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project_name}-scan-jobs-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Name = "${var.project_name}-scan-jobs-dlq"
  }
}

# CloudWatch Metric Alarm for queue depth
resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${var.project_name}-sqs-queue-depth"
  alarm_description   = "Alert when SQS queue depth is high"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1000
  comparison_operator = "GreaterThanThreshold"

  dimensions = {
    QueueName = aws_sqs_queue.scan_jobs.name
  }

  tags = {
    Name = "${var.project_name}-sqs-queue-depth-alarm"
  }
}

# CloudWatch Metric Alarm for message age
resource "aws_cloudwatch_metric_alarm" "message_age" {
  alarm_name          = "${var.project_name}-sqs-message-age"
  alarm_description   = "Alert when oldest message age is high"
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 1
  threshold           = 600 # 10 minutes
  comparison_operator = "GreaterThanThreshold"

  dimensions = {
    QueueName = aws_sqs_queue.scan_jobs.name
  }

  tags = {
    Name = "${var.project_name}-sqs-message-age-alarm"
  }
}

# Outputs
output "scan_jobs_queue_url" {
  value       = aws_sqs_queue.scan_jobs.url
  description = "SQS scan jobs queue URL"
}

output "scan_jobs_queue_arn" {
  value       = aws_sqs_queue.scan_jobs.arn
  description = "SQS scan jobs queue ARN"
}

output "dlq_url" {
  value       = aws_sqs_queue.dlq.url
  description = "SQS dead letter queue URL"
}

output "dlq_arn" {
  value       = aws_sqs_queue.dlq.arn
  description = "SQS dead letter queue ARN"
}

