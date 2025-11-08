# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ECR Repository for scanner Docker image
resource "aws_ecr_repository" "scanner" {
  name                 = "${var.project_name}-scanner"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project_name}-scanner"
  }
}

# ECR Repository for Lambda API Docker image (if using container image)
resource "aws_ecr_repository" "lambda_api" {
  name                 = "${var.project_name}-lambda-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project_name}-lambda-api"
  }
}

# S3 bucket for demo/test files
resource "aws_s3_bucket" "demo" {
  bucket = "${var.project_name}-demo-${var.aws_account_id}"

  tags = {
    Name = "${var.project_name}-demo"
  }
}

resource "aws_s3_bucket_versioning" "demo" {
  bucket = aws_s3_bucket.demo.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "demo" {
  bucket = aws_s3_bucket.demo.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "scanner" {
  name              = "/ecs/${var.project_name}-scanner"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-scanner-logs"
  }
}

# Note: Lambda log group is created in the API module to set retention
# Lambda auto-creates it, but we manage it explicitly to avoid infinite retention costs

# IAM Role for ECS Task Execution
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ecs-task-execution"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# IAM Role for ECS Task (scanner worker)
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ecs-task"
  }
}

resource "aws_iam_role_policy" "ecs_task" {
  name = "${var.project_name}-ecs-task-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${aws_s3_bucket.demo.bucket}",
          "arn:aws:s3:::${aws_s3_bucket.demo.bucket}/*",
          "arn:aws:s3:::*" # Allow scanning any bucket (restrict in production)
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = module.sqs.scan_jobs_queue_arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.scanner.arn}:*"
      }
    ]
  })
}

# Modules
module "vpc" {
  source = "./modules/vpc"

  project_name      = var.project_name
  vpc_cidr          = var.vpc_cidr
  availability_zones = var.availability_zones
}

# Security Group for ECS Tasks (created early for RDS dependency)
resource "aws_security_group" "ecs" {
  name        = "${var.project_name}-ecs-sg"
  description = "Security group for ECS tasks"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.project_name}-ecs-sg"
  }
}

module "rds" {
  source = "./modules/rds"

  project_name            = var.project_name
  vpc_id                  = module.vpc.vpc_id
  private_subnet_ids      = module.vpc.private_subnet_ids
  instance_class          = var.rds_instance_class
  allocated_storage       = var.rds_allocated_storage
  max_allocated_storage   = var.rds_max_allocated_storage
  master_username         = var.rds_master_username
  master_password         = var.rds_master_password
  # Allow connections from ECS tasks and bastion host (if enabled)
  allowed_security_groups = concat(
    [aws_security_group.ecs.id],
    var.enable_bastion ? [module.bastion[0].security_group_id] : []
  )
}

module "sqs" {
  source = "./modules/sqs"

  project_name          = var.project_name
  visibility_timeout     = var.sqs_visibility_timeout
  message_retention      = var.sqs_message_retention
  max_receive_count      = var.sqs_max_receive_count
}

module "ecs" {
  source = "./modules/ecs"

  project_name       = var.project_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = aws_security_group.ecs.id
  ecr_repository_url = aws_ecr_repository.scanner.repository_url
  log_group_name     = aws_cloudwatch_log_group.scanner.name
  task_execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn
  sqs_queue_url      = module.sqs.scan_jobs_queue_url
  sqs_queue_arn      = module.sqs.scan_jobs_queue_arn
  rds_proxy_endpoint = module.rds.rds_proxy_endpoint
  rds_master_username = var.rds_master_username
  rds_master_password = var.rds_master_password
  task_cpu           = var.ecs_task_cpu
  task_memory        = var.ecs_task_memory
  min_capacity       = var.ecs_min_capacity
  max_capacity       = var.ecs_max_capacity
  scanner_batch_size = var.scanner_batch_size

  depends_on = [aws_security_group.ecs]
}

module "api" {
  source = "./modules/api"

  project_name        = var.project_name
  sqs_queue_url       = module.sqs.scan_jobs_queue_url
  sqs_queue_arn       = module.sqs.scan_jobs_queue_arn
  rds_proxy_endpoint  = module.rds.rds_proxy_endpoint
  rds_master_username = var.rds_master_username
  rds_master_password = var.rds_master_password
  log_group_name      = "/aws/lambda/${var.project_name}-api"
  ecr_repository_url  = aws_ecr_repository.lambda_api.repository_url
  subnet_ids          = module.vpc.private_subnet_ids
  security_group_ids  = [aws_security_group.ecs.id]
}

module "bastion" {
  source = "./modules/bastion"
  count  = var.enable_bastion ? 1 : 0

  project_name       = var.project_name
  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  allowed_cidr_blocks = var.allowed_cidr_blocks
  rds_security_group_id = module.rds.security_group_id
  key_pair_name      = "strac-scanner-bastion-key" # Create this key pair first
}

