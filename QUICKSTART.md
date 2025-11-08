# Quick Start Guide

This guide will help you get the S3 Sensitive Data Scanner up and running quickly.

## Prerequisites Checklist

- [ ] AWS Account (697547269674)
- [ ] AWS CLI installed and configured
- [ ] Terraform >= 1.6 installed
- [ ] Docker installed
- [ ] Python 3.12 installed (for local testing)
- [ ] PostgreSQL client installed (for database setup)

## Local Testing (No AWS Required)

Before deploying to AWS, you can test the scanner locally:

```bash
cd scanner/tests
./run_tests.sh
```

This runs **72 pytest tests** covering pattern detection, database operations, batch processing, and integration workflows without requiring AWS infrastructure.

## Step-by-Step Deployment

### 1. Configure Terraform Variables

Create `terraform/terraform.tfvars`:

```hcl
aws_region      = "us-west-2"
aws_account_id  = "697547269674"
environment     = "dev"
project_name    = "strac-scanner"

rds_master_username = "scanner_admin"
rds_master_password = "ChangeThisPassword123!"  # IMPORTANT: Change this!

# Optional: Adjust for your needs
ecs_min_capacity = 1
ecs_max_capacity = 50
scanner_batch_size = 10
```

### 2. Create EC2 Key Pair (for Bastion)

```bash
aws ec2 create-key-pair \
  --key-name strac-scanner-bastion-key \
  --query 'KeyMaterial' \
  --output text > ~/strac-scanner-bastion-key.pem

chmod 400 ~/strac-scanner-bastion-key.pem
```

### 3. Deploy Infrastructure (Stage 1: Core Infrastructure)

Deploy core infrastructure including ECR repositories (but skip Lambda for now):

```bash
cd terraform
terraform init

# Apply everything except Lambda (which needs Docker images first)
terraform apply -target=aws_ecr_repository.scanner \
                -target=aws_ecr_repository.lambda_api \
                -target=module.vpc \
                -target=module.rds \
                -target=module.sqs \
                -target=module.ecs \
                -target=aws_s3_bucket.demo \
                -target=module.bastion
```

**Note**: This creates ECR repositories and core infrastructure. Takes ~10-15 minutes.

### 4. Build and Push Container Images

Now that ECR repositories exist, build and push the Docker images:

```bash
cd /home/peterjiang/strac_demo

# Run the build script (it will guide you if there are permission issues)
./build_and_push.sh

# If you get Docker permission errors, use sudo with -E flag (preserves environment):
# sudo -E ./build_and_push.sh

# Or add your user to docker group (requires logout):
# sudo usermod -aG docker $USER
```

This script will:
- Build both Docker images (scanner + lambda)
- Push to ECR
- Update ECS service (if it exists)

### 5. Deploy Infrastructure (Stage 2: Complete)

Complete the deployment with Lambda function (now that images exist):

```bash
cd terraform
terraform apply  # Creates Lambda and remaining resources
```

**Note**: This final apply takes ~5 minutes. Now grab that coffee! ☕

### 6. Initialize Database

After Terraform completes successfully, initialize the database schema:

```bash
cd /home/peterjiang/strac_demo
./init_database.sh
```

This script will:
- Automatically read credentials from `terraform.tfvars`
- Get RDS endpoint from Terraform outputs
- Test database connectivity
- Create all required tables (jobs, job_objects, findings)
- Verify tables were created successfully

**Manual method** (if you prefer):
```bash
cd terraform
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint | cut -d: -f1)
psql -h $RDS_ENDPOINT -U strac_admin -d scanner_db -f database_schema.sql
# Enter password when prompted
```

### 7. Test the API

```bash
# Get infrastructure details
cd terraform
API_URL=$(terraform output -raw api_gateway_url)
BUCKET=$(terraform output -raw s3_bucket_name)

# Create a test file in S3
echo "My SSN is 123-45-6789 and my credit card is 4532-1234-5678-9010" | \
  aws s3 cp - s3://$BUCKET/test/file.txt

# Trigger a scan
JOB_RESPONSE=$(curl -s -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\": \"$BUCKET\", \"prefix\": \"test/\"}")

echo "Scan triggered:"
echo $JOB_RESPONSE | jq .

# Extract job_id and check status
JOB_ID=$(echo $JOB_RESPONSE | jq -r '.job_id')
echo ""
echo "Checking job status..."
curl -s "${API_URL}/jobs/${JOB_ID}" | jq .

# Wait a moment and get results
sleep 5
echo ""
echo "Getting scan results..."
curl -s "${API_URL}/results?job_id=${JOB_ID}" | jq .
```

## Verification Checklist

- [ ] Terraform apply completed successfully
- [ ] Database schema initialized
- [ ] Container images built and pushed
- [ ] ECS service is running (check AWS Console)
- [ ] Lambda function updated with new image
- [ ] API Gateway endpoint is accessible
- [ ] Test scan completes successfully

## Common Issues

### Terraform Apply Fails

- **Issue**: IAM permissions
- **Fix**: Ensure your AWS credentials have admin permissions or required IAM permissions

### Database Connection Fails

- **Issue**: Security group not allowing connections
- **Fix**: Verify RDS security group allows connections from ECS security group

### ECS Tasks Not Starting

- **Issue**: Container image not found
- **Fix**: Verify ECR images are pushed and ECS task definition references correct image

### API Returns 500

- **Issue**: Lambda function error
- **Fix**: Check CloudWatch Logs: `/aws/lambda/strac-scanner-api`

## Next Steps

1. Review the [README.md](README.md) for architecture details
2. Check [docs/TESTING.md](docs/TESTING.md) for testing procedures
3. Set up CloudWatch dashboards for monitoring
4. Configure alerts for production use

## Cost Estimate

For a small deployment (1-5 ECS tasks, minimal usage):
- **Monthly**: ~$150-200
- **Breakdown**:
  - NAT Gateways: ~$64/month
  - RDS (db.t3.medium): ~$60/month
  - ECS Fargate: ~$20-50/month (depends on usage)
  - Other services: ~$20/month

## Support

For issues or questions:
1. Check CloudWatch Logs
2. Review Terraform outputs
3. Verify IAM permissions
4. Check security group rules

Happy scanning! 🔍

