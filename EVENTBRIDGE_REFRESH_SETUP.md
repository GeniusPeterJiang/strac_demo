# EventBridge-Based Materialized View Refresh

## Quick Start

```bash
# 1. Apply migration to create materialized view
./migrate_database.sh 002_optimize_for_scale.sql

# 2. Deploy refresh Lambda and EventBridge
cd terraform
terraform apply

# 3. Build and deploy all Lambda functions
cd ..
./build_and_push.sh

# 4. Verify it's working
aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --follow
```

## What Was Implemented

### ✅ Replaced Cron with AWS Native Services

**Before (Old Approach):**
- ❌ Requires EC2 instance or server
- ❌ Manual cron job setup
- ❌ OS maintenance required
- ❌ ~$7.50/month cost
- ❌ Manual monitoring setup

**After (New Approach):**
- ✅ Serverless Lambda function
- ✅ EventBridge for scheduling
- ✅ No servers to maintain
- ✅ ~$0.75/month cost (90% savings!)
- ✅ Built-in CloudWatch monitoring

### 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│  AWS EventBridge (CloudWatch Events)        │
│  ┌───────────────────────────────────────┐  │
│  │  Rule: rate(1 minute)                 │  │
│  │  State: ENABLED                       │  │
│  └───────────────┬───────────────────────┘  │
└──────────────────┼──────────────────────────┘
                   │ Triggers every 60s
                   ▼
┌─────────────────────────────────────────────┐
│  Lambda Function (VPC-enabled)              │
│  ┌───────────────────────────────────────┐  │
│  │  Runtime: Python 3.11                 │  │
│  │  Memory: 256 MB                       │  │
│  │  Timeout: 60s                         │  │
│  │  Code: REFRESH MATERIALIZED VIEW      │  │
│  └───────────────┬───────────────────────┘  │
└──────────────────┼──────────────────────────┘
                   │ Connects via VPC
                   ▼
┌─────────────────────────────────────────────┐
│  RDS Postgres (via RDS Proxy)               │
│  ┌───────────────────────────────────────┐  │
│  │  job_progress materialized view       │  │
│  │  - Pre-computed job statistics        │  │
│  │  - Fast queries (<50ms)               │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  API Lambda (uses cached data)              │
│  GET /jobs/{id} → Returns job_progress data │
│  ?real_time=true → Query live data          │
└─────────────────────────────────────────────┘
```

## Components Created

### 1. Lambda Function

**Location:** `lambda_refresh/main.py`

**Key Features:**
- Connects to RDS via RDS Proxy
- Executes `REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress`
- Returns statistics (jobs, objects, findings)
- Handles errors gracefully
- Logs to CloudWatch

**Container Image:**
- Base: `public.ecr.aws/lambda/python:3.11`
- Dependencies: `psycopg2-binary==2.9.9`
- Deployment: ECR repository

### 2. EventBridge Rule

**Schedule:** `rate(1 minute)` - triggers every 60 seconds

**Target:** Refresh Lambda function

**Permissions:** Lambda permission to allow EventBridge invocation

### 3. CloudWatch Monitoring

**Log Group:** `/aws/lambda/strac-scanner-refresh-job-progress`

**Alarm:** Triggers when errors > 5 in 2 minutes

**Metrics:**
- Duration (should be <5s)
- Errors (should be 0)
- Invocations (should be ~60/hour)
- Throttles (should be 0)

### 4. Terraform Module

**Location:** `terraform/modules/refresh_lambda/`

**Resources:**
- `aws_lambda_function.refresh`
- `aws_cloudwatch_event_rule.refresh_schedule`
- `aws_cloudwatch_event_target.refresh_lambda`
- `aws_lambda_permission.allow_eventbridge`
- `aws_cloudwatch_metric_alarm.refresh_errors`
- `aws_ecr_repository.refresh_lambda`

### 5. Build Script

**File:** `build_refresh_lambda.sh`

**Actions:**
1. Gets ECR URL from Terraform
2. Logs into AWS ECR
3. Builds Docker image
4. Pushes to ECR
5. Updates Lambda function
6. Tests invocation

### 6. Updated Migration Script

**File:** `migrate_database.sh`

**Improvements:**
- ✅ Supports multiple migrations via argument
- ✅ Lists available migrations if file not found
- ✅ Migration-specific verification
- ✅ Initial refresh for 002 migration
- ✅ Better error messages and next steps

## Deployment Steps

### Step 1: Apply Migration

```bash
./migrate_database.sh 002_optimize_for_scale.sql
```

This creates:
- Materialized view `job_progress`
- Composite indexes
- Helper views
- Refresh function

### Step 2: Deploy Infrastructure

```bash
cd terraform
terraform apply
```

**New Resources:**
```
+ module.refresh_lambda.aws_lambda_function.refresh
+ module.refresh_lambda.aws_cloudwatch_event_rule.refresh_schedule
+ module.refresh_lambda.aws_cloudwatch_event_target.refresh_lambda
+ module.refresh_lambda.aws_lambda_permission.allow_eventbridge
+ module.refresh_lambda.aws_cloudwatch_metric_alarm.refresh_errors
+ module.refresh_lambda.aws_ecr_repository.refresh_lambda
```

### Step 3: Build and Deploy All Lambda Functions

```bash
cd ..
./build_and_push.sh
```

This unified script now builds and deploys:
- Scanner worker (ECS)
- API Lambda
- Refresh Lambda (if infrastructure exists)

**Expected Output:**
```
========================================
AWS S3 Scanner - Build and Deploy
========================================

✓ Scanner ECR:       ...strac-scanner-scanner:latest
✓ API Lambda ECR:    ...strac-scanner-lambda-api:latest
✓ Refresh Lambda ECR: ...strac-scanner-refresh-lambda:latest

🏗️  Building scanner Docker image...
✓ Scanner image built successfully

🏗️  Building Lambda API Docker image...
✓ Lambda API image built successfully

🏗️  Building Refresh Lambda Docker image...
✓ Refresh Lambda image built successfully

🔄 Updating ECS service...
✓ ECS service updated successfully

🔄 Updating Lambda API function...
✓ Lambda API function updated successfully

🔄 Updating Refresh Lambda function...
✓ Refresh Lambda function updated successfully
   ✓ Test invocation successful

========================================
✅ Build and Deploy Complete!
========================================
```

### Step 4: Verify

```bash
# Check logs
aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --follow

# Check EventBridge rule
aws events describe-rule --name strac-scanner-refresh-job-progress

# Manual test
aws lambda invoke \
  --function-name strac-scanner-refresh-job-progress \
  --payload '{}' \
  /tmp/test.json && cat /tmp/test.json | jq .
```

## Usage

### API Queries (Automatic)

The API Lambda automatically uses the cached data:

```bash
# Default: Fast cached data from materialized view
curl "${API_URL}/jobs/${JOB_ID}"
# Response includes:
# "data_source": "cached"
# "cache_timestamp": "2025-11-09T10:04:30Z"

# Real-time: Fresh data from database (slower)
curl "${API_URL}/jobs/${JOB_ID}?real_time=true"
# Response includes:
# "data_source": "real_time"
```

### Manual Refresh (If Needed)

```bash
# Invoke Lambda directly
aws lambda invoke \
  --function-name strac-scanner-refresh-job-progress \
  --payload '{"source":"manual"}' \
  /tmp/refresh-output.json

# View result
cat /tmp/refresh-output.json | jq .
```

### Monitor Refresh Performance

```bash
# View recent logs
aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --since 10m

# Get metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=strac-scanner-refresh-job-progress \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average,Maximum,Minimum
```

## Configuration

### Adjust Refresh Frequency

Edit `terraform/modules/refresh_lambda/main.tf`:

```hcl
resource "aws_cloudwatch_event_rule" "refresh_schedule" {
  schedule_expression = "rate(1 minute)"  # Change this
}
```

**Options:**
- `rate(30 seconds)` - High frequency (heavy load)
- `rate(1 minute)` - Default (recommended)
- `rate(5 minutes)` - Low frequency (light load)
- `cron(*/2 * * * ? *)` - Every 2 minutes (cron syntax)

Then apply:
```bash
cd terraform
terraform apply
```

### Temporarily Disable

```bash
# Disable EventBridge rule
aws events disable-rule --name strac-scanner-refresh-job-progress

# Re-enable
aws events enable-rule --name strac-scanner-refresh-job-progress
```

### Update Lambda Code

After modifying `lambda_refresh/main.py`:

```bash
./build_refresh_lambda.sh
```

## Cost Analysis

### Monthly Costs

**Lambda:**
- Invocations: 43,200 (every minute for 30 days)
- Duration: ~1 second average
- Memory: 256 MB
- Cost: **$0.72/month**

**EventBridge:**
- Events: 43,200/month
- First 1M events free
- Cost: **$0.00/month**

**Data Transfer:**
- Within VPC: Free
- Cost: **$0.00/month**

**Total: ~$0.75/month**

### Comparison

| Solution | Monthly Cost | Maintenance | Scalability |
|----------|--------------|-------------|-------------|
| **EventBridge + Lambda** | **$0.75** | **None** | **Automatic** |
| EC2 t3.micro + cron | $7.50 | Manual | Manual |
| ECS Fargate scheduled task | $5.00 | Some | Automatic |

**Savings: 90% vs EC2, 85% vs ECS**

## Monitoring

### Expected Log Output

```
[2025-11-09T10:00:00.123Z] Materialized view refresh triggered by EventBridge
[2025-11-09T10:00:00.234Z] Connecting to database: rds-proxy-xxx.proxy-xxx.us-west-2.rds.amazonaws.com:5432/scanner_db as scanner_admin
[2025-11-09T10:00:00.456Z] Refreshing job_progress materialized view...
[2025-11-09T10:00:01.234Z] ✓ Refresh completed in 0.78s (concurrent)
[2025-11-09T10:00:01.235Z]   Jobs: 150
[2025-11-09T10:00:01.236Z]   Total objects: 1,250,000
[2025-11-09T10:00:01.237Z]   Processed: 1,100,000
[2025-11-09T10:00:01.238Z]   Active jobs: 12
[2025-11-09T10:00:01.239Z] ✓ Materialized view refresh successful
```

### Key Metrics

Monitor these in CloudWatch:

| Metric | Normal Range | Alert If |
|--------|--------------|----------|
| Duration | 0.5-2 seconds | >10 seconds |
| Errors | 0 | >5 in 2 minutes |
| Throttles | 0 | >0 |
| Invocations | ~60/hour | <50/hour |

### Alarms

**Auto-created:**
- `strac-scanner-refresh-lambda-errors` - Triggers on >5 errors in 2 minutes

**Recommended to add:**
```bash
# Create alarm for high duration
aws cloudwatch put-metric-alarm \
  --alarm-name strac-scanner-refresh-high-duration \
  --alarm-description "Refresh taking too long" \
  --metric-name Duration \
  --namespace AWS/Lambda \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 10000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=strac-scanner-refresh-job-progress
```

## Troubleshooting

### Issue: Lambda Timing Out

**Check:**
```bash
aws logs filter-pattern "Task timed out" \
  --log-group-name /aws/lambda/strac-scanner-refresh-job-progress \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

**Solution:**
```hcl
# Increase timeout in terraform/modules/refresh_lambda/main.tf
timeout = 120  # 2 minutes
```

### Issue: Connection Errors

**Check VPC configuration:**
```bash
aws lambda get-function-configuration \
  --function-name strac-scanner-refresh-job-progress \
  | jq '.VpcConfig'
```

**Verify security groups:**
```bash
# Lambda should be in security group that can access RDS
aws ec2 describe-security-groups --group-ids sg-xxx
```

### Issue: High Duration

**Check database performance:**
```sql
-- Connect to database
psql -h your-rds-endpoint -U scanner_admin -d scanner_db

-- Check view size
SELECT pg_size_pretty(pg_total_relation_size('job_progress'));

-- Check refresh time
EXPLAIN ANALYZE REFRESH MATERIALIZED VIEW job_progress;
```

**Optimize if needed:**
```sql
-- Add more indexes to source tables
CREATE INDEX CONCURRENTLY idx_job_objects_status 
ON job_objects(status) WHERE status IN ('queued', 'processing');
```

## Summary

### What Changed

**Before:**
- Manual cron job or Python script
- Requires server maintenance
- ~$7.50/month
- Manual monitoring setup

**After:**
- Automated EventBridge + Lambda
- Serverless, no maintenance
- ~$0.75/month (90% savings)
- Built-in CloudWatch monitoring

### Files Created/Modified

**New Files:**
- `lambda_refresh/main.py` - Refresh Lambda function
- `lambda_refresh/requirements.txt` - Python dependencies
- `lambda_refresh/Dockerfile` - Container image
- `terraform/modules/refresh_lambda/main.tf` - Infrastructure
- `terraform/modules/refresh_lambda/variables.tf` - Module variables
- `terraform/modules/refresh_lambda/outputs.tf` - Module outputs
- `build_refresh_lambda.sh` - Build and deploy script
- `MATERIALIZED_VIEW_REFRESH.md` - Detailed documentation
- `EVENTBRIDGE_REFRESH_SETUP.md` - This guide
- `MIGRATION_GUIDE.md` - Migration documentation

**Modified Files:**
- `migrate_database.sh` - Support for multiple migrations
- `terraform/main.tf` - Added refresh_lambda module
- `terraform/outputs.tf` - Added refresh Lambda outputs
- `lambda_api/main.py` - Uses cached data by default
- `JOB_STATUS_API.md` - Documents real_time parameter
- `CURL_EXAMPLES.md` - Shows cached vs real-time examples

### Benefits

✅ **90% cost reduction** ($7.50 → $0.75/month)
✅ **Zero maintenance** (serverless)
✅ **Automatic scaling** (AWS managed)
✅ **Built-in monitoring** (CloudWatch)
✅ **High availability** (multi-AZ)
✅ **Infrastructure as Code** (Terraform)

### Next Steps

1. Monitor logs for first few days
2. Adjust refresh frequency if needed
3. Set up SNS notifications for alarms
4. Update team documentation
5. Celebrate! 🎉

## Documentation

- **Setup Guide**: This file (`EVENTBRIDGE_REFRESH_SETUP.md`)
- **Detailed Guide**: `MATERIALIZED_VIEW_REFRESH.md`
- **Migration Guide**: `MIGRATION_GUIDE.md`
- **API Documentation**: `JOB_STATUS_API.md`
- **Database Comparison**: `DATABASE_VIEWS_COMPARISON.md`

