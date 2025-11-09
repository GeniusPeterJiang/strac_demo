# Variables for Step Functions module

variable "project_name" {
  description = "Project name prefix for resources"
  type        = string
}

variable "lambda_function_arn" {
  description = "ARN of the Lambda function to invoke"
  type        = string
}

