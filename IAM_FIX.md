# IAM Permission Fix for Step Functions DescribeExecution

## Problem

Lambda function was getting an `AccessDeniedException` when trying to call `states:DescribeExecution`:

```
Error describing Step Functions execution: An error occurred (AccessDeniedException) 
when calling the DescribeExecution operation: User: arn:aws:sts::697547269674:
assumed-role/strac-scanner-lambda-api-role/strac-scanner-api is not authorized to 
perform: states:DescribeExecution on resource: arn:aws:states:us-west-2:697547269674:
execution:strac-scanner-s3-scanner:scan-8f9fb6a8-e736-4268-8901-4354132d0c81 
because no identity-based policy allows the states:DescribeExecution action
```

## Root Cause

The IAM policy was granting `states:DescribeExecution` permission, but the `Resource` was set to the **state machine ARN**, not the **execution ARN**.

### ARN Formats

- **State Machine ARN**: `arn:aws:states:REGION:ACCOUNT:stateMachine:NAME`
- **Execution ARN**: `arn:aws:states:REGION:ACCOUNT:execution:NAME:EXECUTION_ID`

### Key Insight

Different Step Functions actions require different ARN types:

| Action | Operates On | ARN Type |
|--------|-------------|----------|
| `states:StartExecution` | State Machine | `stateMachine` ARN |
| `states:ListExecutions` | State Machine | `stateMachine` ARN |
| `states:DescribeExecution` | Execution | `execution` ARN |
| `states:StopExecution` | Execution | `execution` ARN |
| `states:GetExecutionHistory` | Execution | `execution` ARN |

## Solution

Split the IAM policy into two statements in `terraform/modules/api/main.tf`:

### Before (Incorrect)

```hcl
{
  Effect = "Allow"
  Action = [
    "states:StartExecution",
    "states:ListExecutions",
    "states:DescribeExecution"
  ]
  Resource = var.step_function_arn  # Only stateMachine ARN
}
```

### After (Fixed)

```hcl
# Statement 1: State Machine actions
{
  Effect = "Allow"
  Action = [
    "states:StartExecution",
    "states:ListExecutions"
  ]
  Resource = var.step_function_arn
}

# Statement 2: Execution actions
{
  Effect = "Allow"
  Action = [
    "states:DescribeExecution",
    "states:StopExecution",
    "states:GetExecutionHistory"
  ]
  # Convert stateMachine ARN to execution ARN pattern
  Resource = "${replace(var.step_function_arn, ":stateMachine:", ":execution:")}:*"
}
```

## How to Apply the Fix

1. **Apply Terraform Changes**
   ```bash
   cd terraform
   terraform plan  # Review the changes
   terraform apply # Apply the IAM policy update
   ```

2. **Wait for Policy Propagation** (usually < 1 minute)
   - IAM policy changes propagate automatically
   - No need to restart the Lambda function

3. **Test the Fix**
   ```bash
   # Create an async scan job (uses Step Functions)
   curl -X POST https://your-api-url/scan \
     -H "Content-Type: application/json" \
     -d '{"bucket": "test-bucket", "prefix": "test/"}'
   
   # Check job status (should no longer show AccessDeniedException)
   curl https://your-api-url/jobs/YOUR_JOB_ID
   ```

## Verification

After applying, the Lambda function will have permissions to:

- ✅ Start Step Functions executions (`states:StartExecution`)
- ✅ List executions (`states:ListExecutions`)
- ✅ Describe execution status (`states:DescribeExecution`)
- ✅ Stop executions if needed (`states:StopExecution`)
- ✅ Get execution history (`states:GetExecutionHistory`)

## File Changed

- `terraform/modules/api/main.tf` (lines 91-109)

## No Code Changes Needed

The Lambda function code (`lambda_api/main.py`) doesn't need any changes. The issue was purely IAM permissions.

