# Step Functions State Machine for S3 Scanner
# Handles listing and processing S3 objects with continuation tokens

# IAM Role for Step Functions
resource "aws_iam_role" "step_function" {
  name = "${var.project_name}-step-function-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-step-function-role"
  }
}

# IAM Policy for Step Functions to invoke Lambda
resource "aws_iam_role_policy" "step_function" {
  name = "${var.project_name}-step-function-policy"
  role = aws_iam_role.step_function.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = var.lambda_function_arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# CloudWatch Log Group for Step Functions
resource "aws_cloudwatch_log_group" "step_function" {
  name              = "/aws/stepfunctions/${var.project_name}-s3-scanner"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-step-function-logs"
  }
}

# Step Functions State Machine
resource "aws_sfn_state_machine" "s3_scanner" {
  name     = "${var.project_name}-s3-scanner"
  role_arn = aws_iam_role.step_function.arn

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_function.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  definition = jsonencode({
    Comment = "S3 Scanner - Incremental Listing and Processing with Continuation Tokens"
    StartAt = "ProcessBatch"
    States = {
      ProcessBatch = {
        Type     = "Task"
        Resource = var.lambda_function_arn
        Comment  = "List and process a batch of S3 objects"
        Parameters = {
          "job_id.$"              = "$.job_id"
          "bucket.$"              = "$.bucket"
          "prefix.$"              = "$.prefix"
          "continuation_token.$"  = "$.continuation_token"
          "objects_processed.$"   = "$.objects_processed"
        }
        ResultPath = "$"
        Retry = [
          {
            ErrorEquals = [
              "Lambda.ServiceException",
              "Lambda.AWSLambdaException",
              "Lambda.SdkClientException",
              "Lambda.TooManyRequestsException"
            ]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "HandleError"
          }
        ]
        Next = "CheckIfDone"
      }

      CheckIfDone = {
        Type    = "Choice"
        Comment = "Check if there are more objects to process"
        Choices = [
          {
            Variable      = "$.done"
            BooleanEquals = false
            Next          = "ProcessBatch"
          }
        ]
        Default = "JobComplete"
      }

      HandleError = {
        Type = "Pass"
        Comment = "Handle errors gracefully"
        Parameters = {
          "job_id.$"         = "$.job_id"
          "error.$"          = "$.error"
          "objects_processed.$" = "$.objects_processed"
        }
        Next = "JobFailed"
      }

      JobFailed = {
        Type = "Fail"
        Comment = "Job failed to complete"
      }

      JobComplete = {
        Type = "Succeed"
        Comment = "All objects have been listed and enqueued"
      }
    }
  })

  tags = {
    Name = "${var.project_name}-s3-scanner"
  }
}

# Outputs
output "state_machine_arn" {
  value       = aws_sfn_state_machine.s3_scanner.arn
  description = "Step Functions state machine ARN"
}

output "state_machine_name" {
  value       = aws_sfn_state_machine.s3_scanner.name
  description = "Step Functions state machine name"
}

