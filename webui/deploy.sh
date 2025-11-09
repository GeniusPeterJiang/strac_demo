#!/bin/bash
# Deploy web UI to S3 static website hosting

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Get bucket name from Terraform output
cd "$PROJECT_ROOT/terraform"

echo "Getting S3 bucket name from Terraform..."
BUCKET_NAME=$(terraform output -raw webui_bucket_name 2>/dev/null || echo "")

if [ -z "$BUCKET_NAME" ]; then
    echo "Error: Could not get bucket name from Terraform output."
    echo "Please run 'terraform apply' first to create the S3 bucket."
    exit 1
fi

echo "Bucket name: $BUCKET_NAME"

# Upload index.html
echo "Uploading index.html..."
aws s3 cp "$SCRIPT_DIR/index.html" "s3://$BUCKET_NAME/index.html" \
    --content-type "text/html" \
    --cache-control "no-cache"

echo ""
echo "✓ Deployment complete!"
echo ""
echo "Web UI URL:"
WEBSITE_URL=$(terraform output -raw webui_website_url 2>/dev/null || echo "")
if [ -n "$WEBSITE_URL" ]; then
    echo "  http://$WEBSITE_URL"
else
    echo "  http://$BUCKET_NAME.s3-website-$(aws configure get region).amazonaws.com"
fi
echo ""
echo "Note: The URL uses HTTP. For HTTPS, consider using CloudFront."

