output "lambda_function_arn" {
  description = "ARN of the refresh Lambda function"
  value       = aws_lambda_function.refresh.arn
}

output "lambda_function_name" {
  description = "Name of the refresh Lambda function"
  value       = aws_lambda_function.refresh.function_name
}

output "ecr_repository_url" {
  description = "ECR repository URL for refresh Lambda"
  value       = aws_ecr_repository.refresh_lambda.repository_url
}

output "eventbridge_rule_name" {
  description = "EventBridge rule name"
  value       = aws_cloudwatch_event_rule.refresh_schedule.name
}

output "cloudwatch_alarm_arn" {
  description = "CloudWatch alarm ARN for monitoring errors"
  value       = aws_cloudwatch_metric_alarm.refresh_errors.arn
}

