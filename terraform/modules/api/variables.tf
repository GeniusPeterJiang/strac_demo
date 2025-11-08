variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "sqs_queue_url" {
  description = "SQS queue URL"
  type        = string
}

variable "sqs_queue_arn" {
  description = "SQS queue ARN"
  type        = string
}

variable "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint"
  type        = string
}

variable "rds_master_username" {
  description = "RDS master username"
  type        = string
  sensitive   = true
}

variable "rds_master_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

variable "log_group_name" {
  description = "CloudWatch log group name"
  type        = string
}

variable "ecr_repository_url" {
  description = "ECR repository URL for Lambda container image"
  type        = string
}

