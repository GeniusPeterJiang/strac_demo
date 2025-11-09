output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "rds_endpoint" {
  description = "RDS endpoint"
  value       = module.rds.rds_endpoint
  sensitive   = true
}

output "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint"
  value       = module.rds.rds_proxy_endpoint
  sensitive   = true
}

output "sqs_queue_url" {
  description = "SQS scan jobs queue URL"
  value       = module.sqs.scan_jobs_queue_url
}

output "sqs_dlq_url" {
  description = "SQS dead letter queue URL"
  value       = module.sqs.dlq_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = module.ecs.service_name
}

output "api_gateway_url" {
  description = "API Gateway endpoint URL"
  value       = module.api.api_gateway_url
}

output "bastion_public_ip" {
  description = "Bastion host public IP"
  value       = var.enable_bastion ? module.bastion[0].public_ip : null
}

output "ecr_repository_url" {
  description = "ECR repository URL for scanner image"
  value       = aws_ecr_repository.scanner.repository_url
}

output "lambda_api_function_name" {
  description = "Lambda API function name"
  value       = module.api.lambda_function_name
}

output "s3_bucket_name" {
  description = "S3 bucket name for test data"
  value       = aws_s3_bucket.demo.id
}

output "step_function_arn" {
  description = "Step Functions state machine ARN"
  value       = module.step_functions.state_machine_arn
}

output "step_function_name" {
  description = "Step Functions state machine name"
  value       = module.step_functions.state_machine_name
}

output "refresh_lambda_arn" {
  description = "Refresh Lambda function ARN"
  value       = module.refresh_lambda.lambda_function_arn
}

output "refresh_lambda_ecr_url" {
  description = "ECR repository URL for refresh Lambda"
  value       = module.refresh_lambda.ecr_repository_url
}

output "refresh_eventbridge_rule" {
  description = "EventBridge rule name for refresh schedule"
  value       = module.refresh_lambda.eventbridge_rule_name
}
