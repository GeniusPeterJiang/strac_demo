variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs"
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to access bastion"
  type        = list(string)
}

variable "rds_security_group_id" {
  description = "RDS security group ID to allow access from bastion"
  type        = string
}

variable "key_pair_name" {
  description = "EC2 Key Pair name for bastion host"
  type        = string
  default     = "strac-scanner-bastion-key"
}

