# Deployment Guide

This guide covers deploying the S3 Scanner application.

## Automated Deployment Script

The easiest way to deploy is using the provided script:

```bash
./build_and_push.sh
```

This script will:
1. ✅ Get ECR repository URLs from Terraform
2. ✅ Login to AWS ECR
3. ✅ Build the scanner Docker image
4. ✅ Push scanner image to ECR
5. ✅ Build the Lambda API Docker image
6. ✅ Push Lambda API image to ECR
7. ✅ Update ECS service (force new deployment)
8. ✅ Update Lambda function with new image

## Prerequisites

Before running the script, ensure you have:

- [x] Terraform infrastructure deployed (`terraform apply` completed)
- [x] AWS CLI configured with proper credentials
- [x] Docker installed and running
- [x] Permissions to push to ECR and update ECS/Lambda

## Manual Deployment

If you prefer to deploy manually, follow these steps:

### 1. Get ECR Repository URLs

```bash
cd terraform
SCANNER_REPO=$(terraform output -raw ecr_repository_url)
LAMBDA_REPO=$(echo $SCANNER_REPO | sed 's/scanner/lambda-api/')
REGION=$(echo $SCANNER_REPO | cut -d'.' -f4)
```

### 2. Login to ECR

```bash
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $SCANNER_REPO
```

### 3. Build and Push Scanner Image

```bash
cd ../scanner
docker build -t s3-scanner:latest .
docker tag s3-scanner:latest $SCANNER_REPO:latest
docker push $SCANNER_REPO:latest
```

### 4. Build and Push Lambda API Image

```bash
cd ../lambda_api
docker build -t lambda-api:latest .
docker tag lambda-api:latest $LAMBDA_REPO:latest
docker push $LAMBDA_REPO:latest
```

### 5. Update ECS Service

```bash
cd ../terraform
CLUSTER=$(terraform output -raw ecs_cluster_name)
SERVICE=$(terraform output -raw ecs_service_name)

aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --force-new-deployment \
  --region $REGION
```

### 6. Update Lambda Function

```bash
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name)

aws lambda update-function-code \
  --function-name $LAMBDA_FUNC \
  --image-uri $LAMBDA_REPO:latest \
  --region $REGION
```

## Verification

### Check ECS Tasks

```bash
cd terraform
CLUSTER=$(terraform output -raw ecs_cluster_name)

# List running tasks
aws ecs list-tasks --cluster $CLUSTER --desired-status RUNNING

# Get task details
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN
```

### Check Lambda Function

```bash
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name)

# Get function configuration
aws lambda get-function-configuration --function-name $LAMBDA_FUNC

# Check recent logs
aws logs tail /aws/lambda/$LAMBDA_FUNC --follow
```

### Test API Endpoint

```bash
API_URL=$(terraform output -raw api_gateway_url)

# Test health (should return 404 or OPTIONS response)
curl -v $API_URL

# Test scan endpoint
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "your-test-bucket",
    "prefix": "test/"
  }'
```

## Troubleshooting

### ECR Login Issues

**Error**: `Error saving credentials: error storing credentials`

**Solution**:
```bash
# Install credential helper
sudo apt-get install pass gnupg2  # Ubuntu/Debian
brew install pass                  # macOS

# Or use basic auth
docker login -u AWS -p $(aws ecr get-login-password --region us-west-2) $SCANNER_REPO
```

### Docker Build Fails

**Error**: `failed to solve with frontend dockerfile.v0`

**Solution**:
```bash
# Clear Docker cache
docker system prune -a

# Rebuild with no cache
docker build --no-cache -t s3-scanner:latest .
```

### ECS Service Won't Start

**Check task logs**:
```bash
CLUSTER=$(cd terraform && terraform output -raw ecs_cluster_name)

# Get latest task ARN
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --query 'taskArns[0]' --output text)

# Check why task stopped
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN \
  --query 'tasks[0].stoppedReason' --output text

# Check CloudWatch logs
aws logs tail /ecs/s3-scanner-scanner --follow
```

### Lambda Function Update Fails

**Error**: `InvalidParameterValueException: The image manifest or layer media type for the source image is not supported`

**Solution**:
```bash
# Rebuild with correct base image
cd lambda_api
docker build --platform linux/amd64 -t lambda-api:latest .
docker push $LAMBDA_REPO:latest
```

## CI/CD Integration

For production deployments, integrate with your CI/CD pipeline:

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

## Rollback

If you need to rollback to a previous version:

```bash
# Tag and push the old image version
docker tag s3-scanner:previous $SCANNER_REPO:latest
docker push $SCANNER_REPO:latest

# Update ECS service
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --force-new-deployment
```

## Blue/Green Deployment

For zero-downtime deployments, use ECS blue/green:

1. Create a new task definition revision
2. Update the service with the new task definition
3. ECS gradually replaces old tasks with new ones
4. Monitor task health during deployment
5. Rollback automatically if health checks fail

This is handled automatically by the `--force-new-deployment` flag.

## Monitoring Deployment

```bash
# Watch ECS deployment progress
watch -n 5 "aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
  --query 'services[0].deployments' --output table"

# Monitor task count
watch -n 5 "aws ecs list-tasks --cluster $CLUSTER --desired-status RUNNING | jq '.taskArns | length'"

# Check Lambda version
aws lambda get-function --function-name $LAMBDA_FUNC \
  --query 'Configuration.LastModified' --output text
```

