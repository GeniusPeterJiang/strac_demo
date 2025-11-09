# Development Guide

Comprehensive guide for deploying, developing, and maintaining the S3 Sensitive Data Scanner.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Deployment](#deployment)
- [Database Migrations](#database-migrations)
- [Local Development](#local-development)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [CI/CD Integration](#cicd-integration)

## Prerequisites

**Required:**
- AWS Account (configured via AWS CLI)
- Terraform >= 1.6
- Docker
- PostgreSQL client (`psql`)
- Python 3.12+ (for local testing)

**Installation:**
```bash
# macOS
brew install terraform awscli postgresql docker python@3.12

# Ubuntu/Debian
sudo apt-get update
sudo apt-get install terraform awscli postgresql-client docker.io python3.12
```

## Initial Setup

### 1. Configure Terraform Variables

Create `terraform/terraform.tfvars`:

```hcl
aws_region      = "us-west-2"
aws_account_id  = "697547269674"
environment     = "dev"
project_name    = "strac-scanner"

rds_master_username = "scanner_admin"
rds_master_password = "ChangeMe123!"  # Use a secure password!

# Optional: Adjust scaling
ecs_min_capacity = 1
ecs_max_capacity = 50
scanner_batch_size = 10
```

### 2. Create EC2 Key Pair (for Bastion Host)

```bash
aws ec2 create-key-pair \
  --key-name strac-scanner-bastion-key \
  --query 'KeyMaterial' \
  --output text > ~/.ssh/strac-scanner-bastion-key.pem

chmod 400 ~/.ssh/strac-scanner-bastion-key.pem
```

### 3. Deploy Infrastructure

**Stage 1: Core Infrastructure + ECR**
```bash
cd terraform
terraform init

# Deploy core infrastructure (includes ECR repos)
terraform apply -target=aws_ecr_repository.scanner \
                -target=aws_ecr_repository.lambda_api \
                -target=module.vpc \
                -target=module.rds \
                -target=module.sqs \
                -target=module.ecs \
                -target=module.bastion
```

**Stage 2: Build and Push Container Images**
```bash
cd ..
./build_and_push.sh
```

**Stage 3: Complete Deployment**
```bash
cd terraform
terraform apply  # Deploys Lambda, Step Functions, and remaining resources
```

### 4. Initialize Database

```bash
./init_database.sh  # Automated script
```

Or manually:
```bash
cd terraform
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint | cut -d: -f1)
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db -f database_schema.sql
```

### 5. Apply Database Optimizations (Optional)

For production or large-scale deployments, apply migrations manually:

```bash
cd terraform
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint | cut -d: -f1)

# Migration 001: Step Functions tracking
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db \
  -f migrations/001_add_execution_arn.sql

# Migration 002: Performance optimizations (6000× faster queries)
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db \
  -f migrations/002_optimize_for_scale.sql
```

Migration 002 adds:
- Materialized views for 6000× faster queries
- Composite indexes for efficient lookups
- Auto-refresh Lambda (EventBridge trigger every 1 minute)

## Deployment

### Automated Deployment

The `build_and_push.sh` script handles everything:

```bash
./build_and_push.sh
```

**What it does:**
1. Gets ECR repository URLs from Terraform
2. Logs into AWS ECR
3. Builds Docker images (scanner, API Lambda, refresh Lambda)
4. Pushes images to ECR
5. Updates ECS service (force new deployment)
6. Updates all Lambda functions
7. Tests refresh Lambda invocation

### Manual Deployment

If you prefer step-by-step control:

```bash
# 1. Get repository URLs
cd terraform
SCANNER_REPO=$(terraform output -raw ecr_repository_url)
API_REPO=$(echo $SCANNER_REPO | sed 's/scanner/lambda-api/')
REFRESH_REPO=$(echo $SCANNER_REPO | sed 's/scanner/lambda-refresh/')
REGION=$(echo $SCANNER_REPO | cut -d'.' -f4)

# 2. Login to ECR
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $SCANNER_REPO

# 3. Build and push scanner
cd ../scanner
docker build -t s3-scanner:latest .
docker tag s3-scanner:latest $SCANNER_REPO:latest
docker push $SCANNER_REPO:latest

# 4. Build and push API Lambda
cd ../lambda_api
docker build -t lambda-api:latest .
docker tag lambda-api:latest $API_REPO:latest
docker push $API_REPO:latest

# 5. Build and push refresh Lambda
cd ../lambda_refresh
docker build -t lambda-refresh:latest .
docker tag lambda-refresh:latest $REFRESH_REPO:latest
docker push $REFRESH_REPO:latest

# 6. Update ECS service
cd ../terraform
aws ecs update-service \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --service $(terraform output -raw ecs_service_name) \
  --force-new-deployment

# 7. Update Lambda functions
aws lambda update-function-code \
  --function-name $(terraform output -raw lambda_api_function_name) \
  --image-uri $API_REPO:latest

aws lambda update-function-code \
  --function-name strac-scanner-refresh-job-progress \
  --image-uri $REFRESH_REPO:latest
```

### Verification

```bash
cd terraform

# Check ECS service
aws ecs describe-services \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --services $(terraform output -raw ecs_service_name) \
  --query 'services[0].deployments'

# Check Lambda status
aws lambda get-function \
  --function-name $(terraform output -raw lambda_api_function_name) \
  --query 'Configuration.[LastModified,State]'

# Test API endpoint
API_URL=$(terraform output -raw api_gateway_url)
curl -v "${API_URL}/scan" -X POST \
  -H "Content-Type: application/json" \
  -d '{"bucket": "test-bucket", "prefix": "test/"}'
```

## Database Migrations

### Available Migrations

**001_add_execution_arn.sql**
- Adds Step Functions tracking to jobs table
- Enables fast execution status queries
- Required for async processing

**002_optimize_for_scale.sql**
- Materialized views for cached statistics
- Composite indexes for performance
- EventBridge auto-refresh setup
- **Result: 6000× faster queries for large jobs**

### Applying Migrations

```bash
cd terraform
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint | cut -d: -f1)

# Apply migration 001
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db \
  -f migrations/001_add_execution_arn.sql

# Apply migration 002
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db \
  -f migrations/002_optimize_for_scale.sql

# Via bastion (if RDS is in private subnet)
ssh -i ~/.ssh/strac-scanner-bastion-key.pem -L 5432:RDS_ENDPOINT:5432 ubuntu@BASTION_IP
psql -h localhost -U scanner_admin -d scanner_db -f migrations/002_optimize_for_scale.sql
```

### Verification

```bash
# Check materialized view exists
psql -h localhost -U scanner_admin -d scanner_db -c "\d+ job_progress"

# Test query performance
time psql -h localhost -U scanner_admin -d scanner_db -c "
  SELECT * FROM job_progress LIMIT 10;
"
# Should be <50ms even with millions of objects
```

## Local Development

### Local Scanner Testing

```bash
cd scanner/tests
./run_tests.sh  # Runs 72 pytest tests
```

**Test categories:**
- Pattern detection (SSN, credit cards, AWS keys, etc.)
- Database operations (inserts, queries, transactions)
- Batch processing (SQS message handling)
- Integration tests (end-to-end workflows)

### Running Scanner Locally

```bash
# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/scanner_db"
export SQS_QUEUE_URL="https://sqs.us-west-2.amazonaws.com/123456/queue"
export AWS_REGION="us-west-2"

cd scanner
python main.py
```

### Testing Lambda Locally

```bash
cd lambda_api
pip install -r requirements.txt

# Run with Docker (simulates Lambda environment)
docker build -t lambda-api:test .
docker run -p 9000:8080 \
  -e DATABASE_URL="postgresql://..." \
  -e SQS_QUEUE_URL="https://..." \
  lambda-api:test

# Invoke
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"httpMethod": "POST", "path": "/scan", "body": "{\"bucket\":\"test\"}"}'
```

## Testing

### Integration Testing

```bash
cd terraform
API_URL=$(terraform output -raw api_gateway_url)
BUCKET=$(terraform output -raw s3_bucket_name)

# 1. Upload test file
echo "SSN: 123-45-6789" | aws s3 cp - s3://$BUCKET/test/file.txt

# 2. Trigger scan
JOB_ID=$(curl -s -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\":\"$BUCKET\",\"prefix\":\"test/\"}" | jq -r '.job_id')

# 3. Wait for processing
sleep 10

# 4. Check status
curl -s "${API_URL}/jobs/${JOB_ID}" | jq .

# 5. Get results
curl -s "${API_URL}/results?job_id=${JOB_ID}" | jq .
```

### Load Testing

```bash
# Test with 1K objects
for i in {1..1000}; do
  echo "Test data SSN: 123-45-$((6000+i))" | \
    aws s3 cp - s3://$BUCKET/load-test/file-$i.txt &
done
wait

# Trigger scan
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\":\"$BUCKET\",\"prefix\":\"load-test/\"}"
```

### Monitoring During Tests

```bash
# Watch ECS task count
watch -n 5 "aws ecs describe-services \
  --cluster strac-scanner-cluster \
  --services strac-scanner-scanner \
  --query 'services[0].[runningCount,desiredCount]'"

# Monitor SQS queue depth
watch -n 5 "aws sqs get-queue-attributes \
  --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages"

# Tail logs
aws logs tail /ecs/strac-scanner-scanner --follow
```

## Troubleshooting

### ECS Tasks Not Starting

**Symptoms:** Desired count > 0, running count = 0

**Check:**
```bash
# Get stopped task
CLUSTER=strac-scanner-cluster
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --desired-status STOPPED --query 'taskArns[0]' --output text)

# See why it stopped
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN \
  --query 'tasks[0].[stoppedReason,containers[0].reason]'

# Common issues:
# - "CannotPullContainerError" → Check ECR permissions
# - "Essential container exited" → Check CloudWatch logs
# - "ResourceInitializationError" → Check VPC/security groups
```

**Solutions:**
1. Verify ECR image exists: `aws ecr describe-images --repository-name strac-scanner-scanner`
2. Check task execution role permissions
3. Review CloudWatch logs: `aws logs tail /ecs/strac-scanner-scanner`
4. Verify security groups allow outbound HTTPS (for ECR pull)

### Lambda Function Errors

**Symptoms:** API returns 500 errors

**Check:**
```bash
# Get recent errors
aws logs tail /aws/lambda/strac-scanner-api --since 5m --filter-pattern "ERROR"

# Common issues:
# - "Unable to import module" → Check dependencies in requirements.txt
# - "Connection timeout" → Check VPC/security groups (for RDS access)
# - "Task timed out" → Increase timeout or optimize code
```

**Solutions:**
1. Check Lambda configuration: `aws lambda get-function-configuration --function-name strac-scanner-api`
2. Verify environment variables are set correctly
3. Test database connectivity from Lambda VPC
4. Review IAM permissions for Lambda execution role

### Step Functions Stuck

**Symptoms:** Job status shows "listing" indefinitely

**Check:**
```bash
# Get execution details
EXEC_ARN="arn:aws:states:..."  # From job status API
aws stepfunctions describe-execution --execution-arn $EXEC_ARN

# Check execution history
aws stepfunctions get-execution-history --execution-arn $EXEC_ARN --max-results 10

# View logs
aws logs tail /aws/stepfunctions/strac-scanner-s3-scanner --since 10m
```

**Solutions:**
1. Verify Lambda has permission to be invoked by Step Functions
2. Check for Lambda errors in CloudWatch
3. Ensure continuation tokens are being handled correctly
4. Review S3 bucket permissions for ListObjects

### Slow Query Performance

**Symptoms:** GET /jobs/{job_id} takes >5 seconds

**Check:**
```bash
# Check if materialized view exists
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db -c "
  SELECT matviewname FROM pg_matviews WHERE matviewname = 'job_progress';
"

# Check refresh Lambda status
aws lambda get-function --function-name strac-scanner-refresh-job-progress

# Check EventBridge rule
aws events describe-rule --name strac-scanner-refresh-job-progress
```

**Solutions:**
1. Apply migration 002: `./migrate_database.sh 002_optimize_for_scale.sql`
2. Verify refresh Lambda is running: `aws logs tail /aws/lambda/strac-scanner-refresh-job-progress`
3. Manually refresh: `psql -c "REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;"`
4. Enable EventBridge rule: `aws events enable-rule --name strac-scanner-refresh-job-progress`

### Database Connection Pool Exhausted

**Symptoms:** "Too many connections" errors

**Check:**
```bash
# Check current connections
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db -c "
  SELECT count(*) FROM pg_stat_activity WHERE datname = 'scanner_db';
"

# Check RDS Proxy metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=strac-scanner-db \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Maximum
```

**Solutions:**
1. Ensure RDS Proxy is configured (handled by Terraform)
2. Reduce ECS max_capacity if necessary
3. Increase RDS max_connections: Modify parameter group
4. Optimize scanner code to use connection pooling

### High Costs

**Symptoms:** Unexpected AWS bill

**Check:**
```bash
# Most expensive services
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=SERVICE

# Common culprits:
# - NAT Gateway: Use VPC endpoints instead
# - RDS: Use smaller instance or Reserved Instances
# - ECS: Reduce max_capacity or use Spot Fargate
```

**Solutions:**
1. Enable VPC endpoints for S3, SQS, ECR (eliminates NAT costs)
2. Use RDS Reserved Instances for production (40% savings)
3. Enable ECS Fargate Spot pricing (up to 70% savings)
4. Scale down during off-hours with scheduled actions
5. Use S3 Inventory instead of ListObjects for very large buckets

## CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/deploy.yml
name: Deploy to AWS
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2
      
      - name: Build and deploy
        run: ./build_and_push.sh
```

### GitLab CI

```yaml
# .gitlab-ci.yml
deploy:
  image: docker:latest
  services:
    - docker:dind
  script:
    - apk add --no-cache aws-cli bash
    - ./build_and_push.sh
  only:
    - main
```

## Rollback Procedures

### Rollback ECS Deployment

```bash
# Find previous task definition
aws ecs list-task-definitions --family-prefix strac-scanner-scanner --sort DESC

# Update service to use previous version
aws ecs update-service \
  --cluster strac-scanner-cluster \
  --service strac-scanner-scanner \
  --task-definition strac-scanner-scanner:PREVIOUS_VERSION
```

### Rollback Lambda Deployment

```bash
# List previous versions
aws lambda list-versions-by-function --function-name strac-scanner-api

# Publish previous version as $LATEST
aws lambda update-function-code \
  --function-name strac-scanner-api \
  --image-uri PREVIOUS_IMAGE_URI:latest
```

### Rollback Database Migration

```sql
-- For migration 002
DROP MATERIALIZED VIEW IF EXISTS job_progress CASCADE;
DROP VIEW IF EXISTS active_jobs_progress;
DROP VIEW IF EXISTS job_statistics;
DROP INDEX IF EXISTS idx_job_objects_job_status;

-- For migration 001
ALTER TABLE jobs DROP COLUMN execution_arn;
```

## Development Best Practices

1. **Always test migrations on staging first**
2. **Use feature flags for gradual rollouts**
3. **Monitor CloudWatch metrics during deployments**
4. **Keep Terraform state in S3 with locking (DynamoDB)**
5. **Use separate AWS accounts for dev/staging/production**
6. **Tag all resources for cost tracking**
7. **Enable CloudTrail for audit logging**
8. **Use Secrets Manager for credentials (never commit to git)**
9. **Run `terraform plan` before `apply`**
10. **Create RDS snapshots before major changes**

## Useful Commands Reference

```bash
# Get all Terraform outputs
cd terraform && terraform output

# Force ECS service update
aws ecs update-service --cluster CLUSTER --service SERVICE --force-new-deployment

# Drain SQS queue (for testing)
aws sqs purge-queue --queue-url $QUEUE_URL

# Manually trigger refresh Lambda
aws lambda invoke --function-name strac-scanner-refresh-job-progress /tmp/out.json

# Check Step Functions execution
aws stepfunctions describe-execution --execution-arn $EXEC_ARN

# Scale ECS manually
aws ecs update-service --cluster CLUSTER --service SERVICE --desired-count 10

# Connect to RDS via bastion
ssh -i ~/.ssh/key.pem -L 5432:RDS_ENDPOINT:5432 ubuntu@BASTION_IP
psql -h localhost -U scanner_admin -d scanner_db
```

## Next Steps

- Review [SCALING.md](SCALING.md) for capacity planning and optimization strategies
- Set up CloudWatch dashboards for monitoring
- Configure SNS alarms for critical metrics
- Implement automated backups with retention policies
- Consider multi-region deployment for HA

