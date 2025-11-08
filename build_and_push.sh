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

# Check if Docker daemon is accessible
echo "🔍 Checking Docker availability..."
if ! docker ps >/dev/null 2>&1; then
    echo "❌ Error: Cannot connect to Docker daemon."
    echo ""
    echo "Possible fixes:"
    echo "  1. Start Docker: sudo systemctl start docker"
    echo "  2. Add your user to docker group: sudo usermod -aG docker \$USER"
    echo "  3. Run this script with sudo (preserves env): sudo -E ./build_and_push.sh"
    echo ""
    exit 1
fi
echo "✓ Docker is accessible"
echo ""

# Get ECR repository URLs and AWS region from Terraform outputs
echo "📋 Getting infrastructure details from Terraform..."
cd "$SCRIPT_DIR/terraform"

SCANNER_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
if [ -z "$SCANNER_REPO" ]; then
    echo "❌ Error: Could not get ECR repository URL from Terraform."
    echo "   Make sure you've run 'terraform apply' first."
    exit 1
fi

# Fix: Properly construct Lambda repo URL
LAMBDA_REPO=$(echo $SCANNER_REPO | sed 's/strac-scanner-scanner/strac-scanner-lambda-api/')
AWS_REGION=$(echo $SCANNER_REPO | cut -d'.' -f4)

echo "✓ Scanner ECR: $SCANNER_REPO"
echo "✓ Lambda ECR:  $LAMBDA_REPO"
echo "✓ Region:      $AWS_REGION"
echo ""

# Login to ECR
echo "🔐 Logging into AWS ECR..."
echo "   Using region: $AWS_REGION"
echo "   Repository: $SCANNER_REPO"

if ! aws ecr get-login-password --region $AWS_REGION 2>/dev/null | \
    docker login --username AWS --password-stdin $SCANNER_REPO 2>&1; then
    echo ""
    echo "❌ Error: ECR login failed."
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check AWS credentials: aws sts get-caller-identity"
    echo "  2. Verify ECR access: aws ecr describe-repositories --region $AWS_REGION"
    echo "  3. If using sudo, try: sudo -E ./build_and_push.sh"
    echo ""
    exit 1
fi
echo "✓ ECR login successful"
echo ""

# Build and push scanner image
echo "🏗️  Building scanner Docker image..."
echo "   Directory: $SCRIPT_DIR/scanner"
cd "$SCRIPT_DIR/scanner"

if ! docker build -t s3-scanner:latest . 2>&1 | tail -10; then
    echo "❌ Error: Scanner image build failed."
    echo "   Check Dockerfile in: $SCRIPT_DIR/scanner"
    exit 1
fi
echo "✓ Scanner image built successfully"
echo ""

echo "📤 Pushing scanner image to ECR..."
echo "   Target: $SCANNER_REPO:latest"
docker tag s3-scanner:latest $SCANNER_REPO:latest

if ! docker push $SCANNER_REPO:latest 2>&1 | grep -E "(Pushed|digest:)"; then
    echo "❌ Error: Scanner image push failed."
    exit 1
fi
echo "✓ Scanner image pushed: $SCANNER_REPO:latest"
echo ""

# Build and push Lambda API image
echo "🏗️  Building Lambda API Docker image..."
echo "   Directory: $SCRIPT_DIR/lambda_api"
cd "$SCRIPT_DIR/lambda_api"

if ! docker build -t lambda-api:latest . 2>&1 | tail -10; then
    echo "❌ Error: Lambda API image build failed."
    echo "   Check Dockerfile in: $SCRIPT_DIR/lambda_api"
    exit 1
fi
echo "✓ Lambda API image built successfully"
echo ""

echo "📤 Pushing Lambda API image to ECR..."
echo "   Target: $LAMBDA_REPO:latest"
docker tag lambda-api:latest $LAMBDA_REPO:latest

if ! docker push $LAMBDA_REPO:latest 2>&1 | grep -E "(Pushed|digest:)"; then
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
    echo "   (This is normal if Lambda hasn't been created yet)"
else
    echo "   Cluster: $CLUSTER"
    echo "   Service: $SERVICE"
    
    if aws ecs update-service \
        --cluster $CLUSTER \
        --service $SERVICE \
        --force-new-deployment \
        --region $AWS_REGION \
        --no-cli-pager 2>&1; then
        echo "✓ ECS service updated successfully"
    else
        echo "⚠️  Warning: ECS service update failed (may not be critical if service doesn't exist yet)"
    fi
fi
echo ""

# Update Lambda function
echo "🔄 Updating Lambda function..."
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name 2>/dev/null)

if [ -z "$LAMBDA_FUNC" ]; then
    echo "⚠️  Warning: Could not get Lambda function name. Skipping Lambda update."
    echo "   (This is normal - Lambda doesn't exist yet. Run 'terraform apply' next)"
else
    echo "   Function: $LAMBDA_FUNC"
    echo "   Image: $LAMBDA_REPO:latest"
    
    if aws lambda update-function-code \
        --function-name $LAMBDA_FUNC \
        --image-uri $LAMBDA_REPO:latest \
        --region $AWS_REGION \
        --no-cli-pager 2>&1; then
        echo "✓ Lambda function updated successfully"
    else
        echo "⚠️  Warning: Lambda function update failed"
        echo "   This is expected if the Lambda function doesn't exist yet"
        echo "   Run 'cd terraform && terraform apply' to create it"
    fi
fi
echo ""

echo "========================================"
echo "✅ Docker Images Pushed to ECR!"
echo "========================================"
echo ""
echo "Images successfully pushed:"
echo "  • Scanner: $SCANNER_REPO:latest"
echo "  • Lambda:  $LAMBDA_REPO:latest"
echo ""
echo "Next steps:"
if [ -z "$LAMBDA_FUNC" ]; then
    echo "1. Complete infrastructure deployment:"
    echo "   cd terraform && terraform apply"
    echo ""
    echo "2. Initialize database:"
    echo "   cd $SCRIPT_DIR && ./init_database.sh"
    echo ""
    echo "3. Test the API:"
    echo "   API_URL=\$(cd terraform && terraform output -raw api_gateway_url)"
    echo "   curl \$API_URL"
else
    echo "1. Monitor ECS tasks: aws ecs list-tasks --cluster $CLUSTER"
    echo "2. Check Lambda logs: aws logs tail /aws/lambda/$LAMBDA_FUNC --follow"
    echo "3. Test the API: API_URL=\$(cd terraform && terraform output -raw api_gateway_url) && curl \$API_URL"
fi
echo ""

