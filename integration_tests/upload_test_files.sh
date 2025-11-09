#!/bin/bash
# upload_test_files.sh - Upload 500+ test files to S3

set -e

# Get bucket name from Terraform
BUCKET=$(cd ../terraform && terraform output -raw s3_bucket_name)
REGION="us-west-2"
PREFIX="test/"

echo "=== Uploading Test Files ==="
echo "Bucket: s3://${BUCKET}/${PREFIX}"
echo ""

# Generate 500 files with various sensitive data
echo "Generating 500 test files..."
for i in $(seq 1 500); do
  cat > /tmp/test_${i}.txt <<EOF
Test file number $i
Generated: $(date)

Sample sensitive data:
- SSN: $(printf "%03d-%02d-%04d" $((RANDOM%900+100)) $((RANDOM%90+10)) $((RANDOM%9000+1000)))
- Credit Card: 4532-1234-5678-9010
- Email: user${i}@example.com
- Phone: (555) $(printf "%03d-%04d" $((RANDOM%900+100)) $((RANDOM%9000+1000)))
- AWS Access Key: AKIAIOSFODNN7EXAMPLE${i}

Random data: $(openssl rand -hex 20)
EOF
  
  aws s3 cp /tmp/test_${i}.txt s3://${BUCKET}/${PREFIX}test_${i}.txt --region ${REGION} --only-show-errors
  
  # Progress indicator
  if [ $((i % 100)) -eq 0 ]; then
    echo "  Uploaded $i files..."
  fi
done

echo ""
echo "✓ Upload complete! Uploaded 500 files to s3://${BUCKET}/${PREFIX}"
echo "  Total size: ~$(aws s3 ls s3://${BUCKET}/${PREFIX} --recursive --summarize 2>/dev/null | grep "Total Size" | awk '{print $3}') bytes"

