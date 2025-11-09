variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for Lambda VPC"
  type        = list(string)
}

variable "lambda_security_group_id" {
  description = "Security group ID for Lambda"
  type        = string
}

variable "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint"
  type        = string
}

variable "rds_dbname" {
  description = "RDS database name"
  type        = string
}

variable "rds_username" {
  description = "RDS username"
  type        = string
  sensitive   = true
}

variable "rds_password" {
  description = "RDS password"
  type        = string
  sensitive   = true
}

