variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "visibility_timeout" {
  description = "SQS visibility timeout in seconds"
  type        = number
}

variable "message_retention" {
  description = "SQS message retention period in seconds"
  type        = number
}

variable "max_receive_count" {
  description = "Maximum number of receives before moving to DLQ"
  type        = number
}

