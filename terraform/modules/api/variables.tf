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

variable "subnet_ids" {
  description = "Subnet IDs for Lambda VPC configuration"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs for Lambda"
  type        = list(string)
}

variable "step_function_arn" {
  description = "Step Functions state machine ARN"
  type        = string
  default     = ""
}
