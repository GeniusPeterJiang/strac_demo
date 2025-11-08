# Fresh Deployment Guide

This guide walks you through a completely clean deployment of the S3 Scanner infrastructure.

## Prerequisites

- AWS CLI configured with credentials for account `697547269674`
- Terraform >= 1.6 installed
- Docker installed
- Appropriate IAM permissions (Admin or equivalent)

## Option 1: Complete Fresh Start (Recommended)

If you have existing infrastructure with errors or want to start completely fresh:

### Step 1: Complete Cleanup

```bash
# Run the automated cleanup script
./clean_slate.sh

# When prompted, type: DELETE EVERYTHING
```

**What this does:**
- ✅ Scales down and deletes ECS services/clusters
- ✅ Deletes Lambda functions and API Gateway
- ✅ Deletes RDS databases and proxies (5-10 min)
- ✅ Deletes SQS queues
- ✅ Deletes CloudWatch log groups
- ✅ Deletes Secrets Manager secrets
- ✅ Deletes ECR repositories
- ✅ Terminates bastion hosts
- ✅ Cleans Terraform state
- ⚠️ Preserves S3 bucket data (delete manually if needed)

**Time required:** ~10-15 minutes (mostly waiting for RDS deletion)

### Step 2: Fresh Deployment

```bash
cd terraform

# Initialize Terraform
terraform init

# Review the plan
terraform plan

# Apply infrastructure
terraform apply

# Type 'yes' when prompted
```

**Time required:** ~15-20 minutes

### Step 3: Initialize Database

```bash
# Get RDS endpoint
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint | cut -d: -f1)

# Run database schema
psql -h $RDS_ENDPOINT -U strac_admin -d scanner_db -f database_schema.sql
# Password: zKDcdi5gJke#dUp6 (from terraform.tfvars)
```

### Step 4: Build and Deploy Container Images

```bash
cd ..
./build_and_push.sh
```

This will:
- Build both Docker images (scanner + lambda)
- Push to ECR
- Update ECS service and Lambda function

### Step 5: Verify Deployment

```bash
cd terraform

# Get API URL
API_URL=$(terraform output -raw api_gateway_url)
echo "API URL: $API_URL"

# Test the API
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{"bucket": "strac-scanner-demo-697547269674", "prefix": "test/"}'
```

## Option 2: Incremental Cleanup (For Specific Issues)

If you only need to fix specific issues without a full wipe:

### Fix Terraform State Issues Only

```bash
cd terraform

# Remove problematic resources from state
terraform state rm module.rds.aws_iam_service_linked_role.rds 2>/dev/null || true

# Delete log groups manually
aws logs delete-log-group --log-group-name /aws/lambda/strac-scanner-api --region us-west-2
aws logs delete-log-group --log-group-name /ecs/strac-scanner-scanner --region us-west-2

# Re-run terraform
terraform plan
terraform apply
```

### Fix RDS Version Mismatch

If you get "Cannot find upgrade path from X to Y":

```bash
# Option A: Delete and recreate
aws rds modify-db-instance \
  --db-instance-identifier strac-scanner-db \
  --no-deletion-protection \
  --apply-immediately \
  --region us-west-2

aws rds delete-db-instance \
  --db-instance-identifier strac-scanner-db \
  --skip-final-snapshot \
  --region us-west-2

# Wait for deletion
aws rds wait db-instance-deleted --db-instance-identifier strac-scanner-db --region us-west-2

# Option B: Update Terraform to match existing version
# Edit terraform/modules/rds/main.tf
# Change engine_version to match your existing database version
```

## Troubleshooting Common Errors

### Error: "Service linked role cannot be deleted"

**Fix:** The RDS database still exists. Delete it first:
```bash
aws rds delete-db-proxy --db-proxy-name strac-scanner-proxy --region us-west-2
sleep 60
aws rds modify-db-instance --db-instance-identifier strac-scanner-db --no-deletion-protection --apply-immediately --region us-west-2
aws rds delete-db-instance --db-instance-identifier strac-scanner-db --skip-final-snapshot --region us-west-2
```

### Error: "CloudWatch log group already exists"

**Fix:** Delete the log group:
```bash
aws logs delete-log-group --log-group-name /aws/lambda/strac-scanner-api --region us-west-2
```

### Error: "db_instance_identifier only allows lowercase"

**Fix:** Already fixed in `terraform/modules/rds/main.tf` (changed `.id` to `.identifier`)

### Error: "Cannot find upgrade path from 15.X to 15.Y"

**Fix:** Already fixed in `terraform/modules/rds/main.tf` (set to version `15.14`)

## Verification Checklist

After deployment, verify:

- [ ] Terraform apply completed successfully
- [ ] No errors in `terraform output`
- [ ] RDS endpoint is accessible
- [ ] ECS service is running: `aws ecs describe-services --cluster strac-scanner-cluster --services strac-scanner-service --region us-west-2`
- [ ] Lambda function exists: `aws lambda get-function --function-name strac-scanner-api --region us-west-2`
- [ ] SQS queue exists: `aws sqs list-queues --queue-name-prefix strac-scanner --region us-west-2`
- [ ] API Gateway is accessible: `curl $API_URL`

## Clean Up S3 Data (Optional)

The cleanup script preserves S3 data. To delete it:

```bash
BUCKET_NAME="strac-scanner-demo-697547269674"

# List contents
aws s3 ls s3://$BUCKET_NAME --recursive

# Delete all objects
aws s3 rm s3://$BUCKET_NAME --recursive

# Delete bucket
aws s3 rb s3://$BUCKET_NAME
```

## Post-Deployment

1. Upload test files: See [docs/TESTING.md](docs/TESTING.md)
2. Run integration tests
3. Set up CloudWatch dashboards
4. Configure alerts
5. Review security settings

## Cost Management

After testing, to minimize costs:

```bash
# Scale down ECS to 0 tasks
aws ecs update-service \
  --cluster strac-scanner-cluster \
  --service strac-scanner-service \
  --desired-count 0 \
  --region us-west-2

# Or completely destroy infrastructure
cd terraform
terraform destroy
```

## Quick Reference

```bash
# Full cleanup and redeploy
./clean_slate.sh
cd terraform && terraform init && terraform apply
cd .. && ./build_and_push.sh

# Check status
cd terraform
terraform output

# Test API
API_URL=$(terraform output -raw api_gateway_url)
curl -X POST "${API_URL}/scan" -H "Content-Type: application/json" -d '{"bucket":"strac-scanner-demo-697547269674","prefix":"test/"}'

# View logs
aws logs tail /ecs/strac-scanner-scanner --follow
aws logs tail /aws/lambda/strac-scanner-api --follow

# Destroy everything
./clean_slate.sh
```

## Support

For issues:
1. Check CloudWatch Logs
2. Review Terraform outputs
3. Verify IAM permissions
4. Check security group rules
5. Review [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (if exists)

## Important Notes

- ⚠️ The cleanup script is **destructive and irreversible**
- ⚠️ Always backup important data before cleanup
- ⚠️ RDS deletion takes 5-10 minutes
- ⚠️ S3 data is preserved by default
- ✅ Terraform state is cleaned automatically
- ✅ Service-linked roles are no longer managed by Terraform

