#!/bin/bash
# build_and_push.sh
# Automated script to build and push Docker images to ECR, then update ECS and Lambda

set -e  # Exit on error

echo "========================================"
echo "AWS S3 Scanner - Build and Deploy"
echo "========================================"
echo ""

# Get current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Get ECR repository URLs and AWS region from Terraform outputs
echo "📋 Getting infrastructure details from Terraform..."
cd "$SCRIPT_DIR/terraform"

SCANNER_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
if [ -z "$SCANNER_REPO" ]; then
    echo "❌ Error: Could not get ECR repository URL from Terraform."
    echo "   Make sure you've run 'terraform apply' first."
    exit 1
fi

LAMBDA_REPO=$(echo $SCANNER_REPO | sed 's/scanner/lambda-api/')
AWS_REGION=$(echo $SCANNER_REPO | cut -d'.' -f4)

echo "✓ Scanner ECR: $SCANNER_REPO"
echo "✓ Lambda ECR:  $LAMBDA_REPO"
echo "✓ Region:      $AWS_REGION"
echo ""

# Login to ECR
echo "🔐 Logging into AWS ECR..."
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin $SCANNER_REPO

if [ $? -ne 0 ]; then
    echo "❌ Error: ECR login failed. Check your AWS credentials."
    exit 1
fi
echo "✓ ECR login successful"
echo ""

# Build and push scanner image
echo "🏗️  Building scanner Docker image..."
cd "$SCRIPT_DIR/scanner"
docker build -t s3-scanner:latest .

if [ $? -ne 0 ]; then
    echo "❌ Error: Scanner image build failed."
    exit 1
fi
echo "✓ Scanner image built"

echo "📤 Pushing scanner image to ECR..."
docker tag s3-scanner:latest $SCANNER_REPO:latest
docker push $SCANNER_REPO:latest

if [ $? -ne 0 ]; then
    echo "❌ Error: Scanner image push failed."
    exit 1
fi
echo "✓ Scanner image pushed: $SCANNER_REPO:latest"
echo ""

# Build and push Lambda API image
echo "🏗️  Building Lambda API Docker image..."
cd "$SCRIPT_DIR/lambda_api"
docker build -t lambda-api:latest .

if [ $? -ne 0 ]; then
    echo "❌ Error: Lambda API image build failed."
    exit 1
fi
echo "✓ Lambda API image built"

echo "📤 Pushing Lambda API image to ECR..."
docker tag lambda-api:latest $LAMBDA_REPO:latest
docker push $LAMBDA_REPO:latest

if [ $? -ne 0 ]; then
    echo "❌ Error: Lambda API image push failed."
    exit 1
fi
echo "✓ Lambda API image pushed: $LAMBDA_REPO:latest"
echo ""

# Update ECS service
echo "🔄 Updating ECS service..."
cd "$SCRIPT_DIR/terraform"
CLUSTER=$(terraform output -raw ecs_cluster_name 2>/dev/null)
SERVICE=$(terraform output -raw ecs_service_name 2>/dev/null)

if [ -z "$CLUSTER" ] || [ -z "$SERVICE" ]; then
    echo "⚠️  Warning: Could not get ECS details. Skipping ECS update."
else
    aws ecs update-service \
        --cluster $CLUSTER \
        --service $SERVICE \
        --force-new-deployment \
        --region $AWS_REGION \
        --no-cli-pager > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo "✓ ECS service updated: $SERVICE"
    else
        echo "⚠️  Warning: ECS service update failed (may not be critical)"
    fi
fi
echo ""

# Update Lambda function
echo "🔄 Updating Lambda function..."
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name 2>/dev/null)

if [ -z "$LAMBDA_FUNC" ]; then
    echo "⚠️  Warning: Could not get Lambda function name. Skipping Lambda update."
else
    aws lambda update-function-code \
        --function-name $LAMBDA_FUNC \
        --image-uri $LAMBDA_REPO:latest \
        --region $AWS_REGION \
        --no-cli-pager > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo "✓ Lambda function updated: $LAMBDA_FUNC"
    else
        echo "⚠️  Warning: Lambda function update failed (may not be critical)"
    fi
fi
echo ""

echo "========================================"
echo "✅ Deployment Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Monitor ECS tasks: aws ecs list-tasks --cluster $CLUSTER"
echo "2. Check Lambda logs: aws logs tail /aws/lambda/$LAMBDA_FUNC --follow"
echo "3. Test the API: curl \$(cd terraform && terraform output -raw api_gateway_url)"
echo ""

