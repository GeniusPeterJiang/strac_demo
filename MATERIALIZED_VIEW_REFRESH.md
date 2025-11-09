# Materialized View Auto-Refresh Setup

## Overview

The `job_progress` materialized view provides cached, fast queries for job status but needs periodic refresh to stay current. We use **AWS EventBridge + Lambda** for serverless, automated refreshes.

## Architecture

```
┌─────────────────────┐
│  EventBridge Rule   │  ← Triggers every 1 minute
│   (Cron Schedule)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Refresh Lambda     │  ← Executes REFRESH MATERIALIZED VIEW
│   (VPC-enabled)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│    RDS Postgres     │  ← Updates job_progress view
│ (via RDS Proxy)     │
└─────────────────────┘
```

## Components

### 1. Lambda Function (`lambda_refresh/main.py`)

- **Function**: Connects to RDS and executes `REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress`
- **Runtime**: Python 3.11 with psycopg2
- **VPC**: Deployed in private subnets to access RDS
- **Timeout**: 60 seconds
- **Memory**: 256 MB

### 2. EventBridge Rule

- **Schedule**: `rate(1 minute)` - triggers every 60 seconds
- **Target**: Refresh Lambda function
- **State**: Enabled by default

### 3. CloudWatch Monitoring

- **Logs**: `/aws/lambda/strac-scanner-refresh-job-progress`
- **Alarm**: Triggers if >5 errors in 2 minutes
- **Metrics**: Duration, invocations, errors

## Deployment

### Prerequisites

1. Terraform infrastructure deployed
2. Migration `002_optimize_for_scale.sql` applied
3. Docker installed locally

### Step-by-Step

```bash
# 1. Apply Terraform to create Lambda and EventBridge
cd terraform
terraform apply

# Expected output:
#   + module.refresh_lambda.aws_lambda_function.refresh
#   + module.refresh_lambda.aws_cloudwatch_event_rule.refresh_schedule
#   + module.refresh_lambda.aws_cloudwatch_event_target.refresh_lambda

# 2. Build and deploy all Lambda functions
cd ..
./build_and_push.sh
```

### What `build_and_push.sh` Does

The unified build script now handles all components:

1. ✅ Gets ECR repository URLs from Terraform
2. ✅ Logs into AWS ECR
3. ✅ Builds Docker images:
   - Scanner worker (ECS)
   - API Lambda
   - Refresh Lambda (if infrastructure exists)
4. ✅ Pushes images to ECR
5. ✅ Updates ECS service and Lambda functions
6. ✅ Tests refresh Lambda with sample invocation

## Verification

### Check Deployment Status

```bash
# List Lambda functions
aws lambda list-functions | grep refresh-job-progress

# Get EventBridge rule
aws events list-rules --name-prefix strac-scanner-refresh

# Check rule targets
aws events list-targets-by-rule --rule strac-scanner-refresh-job-progress
```

### Monitor Logs

```bash
# Tail logs in real-time
aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --follow

# Get recent logs
aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --since 10m
```

### Expected Log Output

```
[2025-11-09 10:00:00] Connecting to database...
[2025-11-09 10:00:01] Refreshing job_progress materialized view...
[2025-11-09 10:00:02] ✓ Refresh completed in 0.85s (concurrent)
  Jobs: 150
  Total objects: 1,250,000
  Processed: 1,100,000
  Active jobs: 12
```

### Test Manual Invocation

```bash
# Invoke Lambda directly
aws lambda invoke \
  --function-name strac-scanner-refresh-job-progress \
  --payload '{"source":"manual-test"}' \
  /tmp/refresh-test.json

# Check response
cat /tmp/refresh-test.json | jq .
```

**Expected Response:**
```json
{
  "statusCode": 200,
  "body": "{\"success\": true, \"duration_seconds\": 0.85, \"refresh_type\": \"concurrent\", \"statistics\": {\"total_jobs\": 150, \"total_objects\": 1250000, ...}}"
}
```

## Configuration

### Adjust Refresh Frequency

Edit `terraform/modules/refresh_lambda/main.tf`:

```hcl
resource "aws_cloudwatch_event_rule" "refresh_schedule" {
  name                = "${var.project_name}-refresh-job-progress"
  description         = "Trigger materialized view refresh"
  
  # Options:
  # - rate(30 seconds)  ← For heavy load
  # - rate(1 minute)    ← Default
  # - rate(5 minutes)   ← For light load
  schedule_expression = "rate(1 minute)"
}
```

Then apply:
```bash
cd terraform
terraform apply
```

### Recommended Frequencies

| Workload | Objects/min | Refresh Interval | Staleness |
|----------|-------------|------------------|-----------|
| Light | <10K | Every 5 minutes | Up to 5 min old |
| Medium | 10K-100K | Every 1 minute | Up to 1 min old |
| Heavy | >100K | Every 30 seconds | Up to 30s old |

### Disable Auto-Refresh (Temporarily)

```bash
# Disable EventBridge rule
aws events disable-rule --name strac-scanner-refresh-job-progress

# Re-enable later
aws events enable-rule --name strac-scanner-refresh-job-progress
```

## Monitoring & Alerts

### CloudWatch Alarm

The Terraform configuration includes an alarm that triggers when:
- **Condition**: Lambda errors > 5 in 2 consecutive periods (2 minutes)
- **Action**: Sends notification (configure SNS topic in Terraform)

### Key Metrics to Monitor

```bash
# View Lambda metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=strac-scanner-refresh-job-progress \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average,Maximum
```

**What to watch:**
- ✅ **Duration**: Should be <5 seconds for most refreshes
- ⚠️ **Errors**: Should be 0
- ⚠️ **Throttles**: Should be 0
- ℹ️ **Invocations**: Should match schedule (60/hour for 1-minute interval)

### Dashboard

Create a CloudWatch dashboard:

```bash
# Get dashboard JSON template
cat > /tmp/refresh-dashboard.json <<'EOF'
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/Lambda", "Duration", {"FunctionName": "strac-scanner-refresh-job-progress"}],
          [".", "Errors", {"FunctionName": "."}],
          [".", "Invocations", {"FunctionName": "."}]
        ],
        "period": 60,
        "stat": "Sum",
        "region": "us-west-2",
        "title": "Refresh Lambda Metrics"
      }
    }
  ]
}
EOF

# Create dashboard
aws cloudwatch put-dashboard \
  --dashboard-name strac-scanner-refresh \
  --dashboard-body file:///tmp/refresh-dashboard.json
```

## Troubleshooting

### Issue: Lambda Timing Out

**Symptom**: Logs show "Task timed out after 60.00 seconds"

**Solutions:**
1. Increase Lambda timeout:
   ```hcl
   # In terraform/modules/refresh_lambda/main.tf
   timeout = 120  # Increase to 2 minutes
   ```

2. Check materialized view size:
   ```sql
   SELECT pg_size_pretty(pg_total_relation_size('job_progress'));
   ```

3. Optimize refresh (if > 1M jobs):
   ```sql
   -- Add more indexes
   CREATE INDEX CONCURRENTLY idx_job_objects_job_id_status 
   ON job_objects(job_id, status);
   ```

### Issue: Connection Errors

**Symptom**: Logs show "could not connect to server"

**Solutions:**
1. Check Lambda VPC configuration:
   ```bash
   aws lambda get-function-configuration \
     --function-name strac-scanner-refresh-job-progress \
     --query 'VpcConfig'
   ```

2. Verify security group allows access to RDS:
   ```bash
   # Check RDS security group
   aws ec2 describe-security-groups --group-ids sg-xxxxx
   ```

3. Test connectivity from Lambda VPC:
   ```bash
   # Deploy test Lambda in same VPC
   # Try connecting to RDS endpoint
   ```

### Issue: "Materialized View Does Not Exist"

**Symptom**: Lambda returns error about missing view

**Solution**: Run migration:
```bash
./migrate_database.sh 002_optimize_for_scale.sql
```

### Issue: Concurrent Refresh Failing

**Symptom**: Logs show "falling back to regular refresh"

**Solution**: Create unique index (first-time setup):
```sql
-- Connect to database
psql -h your-rds-endpoint -U scanner_admin -d scanner_db

-- Create unique index for concurrent refresh
CREATE UNIQUE INDEX CONCURRENTLY job_progress_job_id_idx 
ON job_progress (job_id);
```

## Cost Analysis

### Lambda Costs

**Assumptions:**
- Refresh every 1 minute = 43,200 invocations/month
- Average duration: 1 second
- Memory: 256 MB

**Monthly Cost:**
```
Compute: 43,200 × 1s × $0.0000166667 = $0.72
Requests: 43,200 × $0.20/1M = $0.01
Total: ~$0.73/month
```

### EventBridge Costs

**Free tier**: 1 million events/month

Our usage: 43,200 events/month → **FREE**

### Total Monthly Cost

**~$0.75/month** for automatic materialized view refresh

Compare to EC2 t3.micro running cron: **~$7.50/month**

**Savings: 90%** 🎉

## Alternative: Manual Refresh Script

If you prefer manual control, use the Python script:

```bash
# Set environment variables
export RDS_PROXY_ENDPOINT="your-rds-proxy.rds.amazonaws.com"
export RDS_USERNAME="scanner_admin"
export RDS_PASSWORD="your-password"

# Run refresh
python3 refresh_job_progress.py
```

Or SQL directly:
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;
```

## Comparison: EventBridge vs Cron

| Feature | EventBridge + Lambda | Traditional Cron |
|---------|---------------------|------------------|
| **Cost** | ~$0.75/month | ~$7.50/month (EC2) |
| **Maintenance** | None (serverless) | OS updates, monitoring |
| **Scaling** | Automatic | Manual |
| **Monitoring** | CloudWatch built-in | Setup required |
| **Deployment** | Terraform IaC | Manual setup |
| **HA** | AWS managed | Need multiple servers |
| **Cold starts** | ~500ms (VPC) | None |

**Recommendation**: Use EventBridge + Lambda for production

## Summary

✅ **Deployed**: EventBridge triggers Lambda every 1 minute
✅ **Fast**: <1 second refresh time for most datasets
✅ **Cheap**: ~$0.75/month
✅ **Monitored**: CloudWatch logs and alarms
✅ **Serverless**: No servers to maintain

Your materialized view stays fresh automatically! 🎉

