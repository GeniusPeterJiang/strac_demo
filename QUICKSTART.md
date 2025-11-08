# Quick Start Guide

This guide will help you get the S3 Sensitive Data Scanner up and running quickly.

## Prerequisites Checklist

- [ ] AWS Account (697547269674)
- [ ] AWS CLI installed and configured
- [ ] Terraform >= 1.6 installed
- [ ] Docker installed
- [ ] Python 3.12 installed (for local testing)
- [ ] PostgreSQL client installed (for database setup)

## Step-by-Step Deployment

### 1. Configure Terraform Variables

Create `terraform/terraform.tfvars`:

```hcl
aws_region      = "us-west-2"
aws_account_id  = "697547269674"
environment     = "dev"
project_name    = "s3-scanner"

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
  --key-name s3-scanner-bastion-key \
  --query 'KeyMaterial' \
  --output text > bastion-key.pem

chmod 400 bastion-key.pem
```

### 3. Deploy Infrastructure

```bash
cd terraform
terraform init
terraform plan  # Review the plan
terraform apply # Type 'yes' when prompted
```

**Note**: This will take 15-20 minutes to complete. Grab a coffee! ☕

### 4. Initialize Database

After Terraform completes:

```bash
# Get RDS endpoint
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint | cut -d: -f1)

# Connect and run schema
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db -f database_schema.sql
# Enter password when prompted
```

### 5. Build and Push Container Images

```bash
# Get ECR repository URLs
SCANNER_REPO=$(terraform output -raw ecr_repository_url)
LAMBDA_REPO=$(terraform output -raw ecr_repository_url | sed 's/scanner/lambda-api/')

# Login to ECR
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin $SCANNER_REPO

# Build and push scanner image
cd ../scanner
docker build -t s3-scanner:latest .
docker tag s3-scanner:latest $SCANNER_REPO:latest
docker push $SCANNER_REPO:latest

# Build and push Lambda API image
cd ../lambda_api
docker build -t lambda-api:latest .
docker tag lambda-api:latest $LAMBDA_REPO:latest
docker push $LAMBDA_REPO:latest
```

### 6. Update ECS Service

After pushing images, update the ECS service to use the new image:

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)
SERVICE=$(terraform output -raw ecs_service_name)

aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --force-new-deployment
```

### 7. Update Lambda Function

```bash
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name)

aws lambda update-function-code \
  --function-name $LAMBDA_FUNC \
  --image-uri $LAMBDA_REPO:latest
```

### 8. Test the API

```bash
# Get API URL
API_URL=$(terraform output -raw api_gateway_url)

# Create a test file in S3
BUCKET=$(terraform output -raw ecr_repository_url | cut -d/ -f1 | sed 's/697547269674.dkr.ecr.us-west-2.amazonaws.com/s3-scanner-demo-697547269674/')
echo "My SSN is 123-45-6789" | aws s3 cp - s3://$BUCKET/test/file.txt

# Trigger a scan
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\": \"$BUCKET\", \"prefix\": \"test/\"}"

# Save the job_id from the response, then check status:
# curl "${API_URL}/jobs/<job_id>"

# Get results:
# curl "${API_URL}/results?job_id=<job_id>"
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
- **Fix**: Check CloudWatch Logs: `/aws/lambda/s3-scanner-api`

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

