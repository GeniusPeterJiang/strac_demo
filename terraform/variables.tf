variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-west-2"
}

variable "aws_account_id" {
  description = "AWS account ID"
  type        = string
  default     = "697547269674"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name prefix for resources"
  type        = string
  default     = "strac-scanner"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-west-2a", "us-west-2b"]
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "rds_allocated_storage" {
  description = "RDS initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "RDS maximum allocated storage in GB"
  type        = number
  default     = 200
}

variable "rds_master_username" {
  description = "RDS master username"
  type        = string
  default     = "scanner_admin"
  sensitive   = true
}

variable "rds_master_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

variable "ecs_task_cpu" {
  description = "CPU units for ECS Fargate task (1024 = 1 vCPU)"
  type        = number
  default     = 2048
}

variable "ecs_task_memory" {
  description = "Memory for ECS Fargate task in MB"
  type        = number
  default     = 4096
}

variable "ecs_min_capacity" {
  description = "Minimum number of ECS tasks"
  type        = number
  default     = 1
}

variable "ecs_max_capacity" {
  description = "Maximum number of ECS tasks"
  type        = number
  default     = 5  # Default per requirements, but configurable via tfvars
}

variable "sqs_visibility_timeout" {
  description = "SQS visibility timeout in seconds"
  type        = number
  default     = 300
}

variable "sqs_message_retention" {
  description = "SQS message retention period in seconds"
  type        = number
  default     = 1209600 # 14 days
}

variable "sqs_max_receive_count" {
  description = "Maximum number of receives before moving to DLQ"
  type        = number
  default     = 3
}

variable "scanner_batch_size" {
  description = "Number of files to process per batch"
  type        = number
  default     = 10
}

variable "enable_bastion" {
  description = "Enable bastion host for debugging"
  type        = bool
  default     = true
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to access bastion and API"
  type        = list(string)
  default     = ["0.0.0.0/0"] # Restrict in production
}

