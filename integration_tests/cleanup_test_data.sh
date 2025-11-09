#!/bin/bash
# cleanup_test_data.sh - Remove all test files from S3

BUCKET=$(cd ../terraform && terraform output -raw s3_bucket_name)

echo "=== Cleanup Test Data ==="
echo "Bucket: $BUCKET"
echo ""

# Delete test prefixes
for PREFIX in "test/" "load-test/" "bulk/"; do
  COUNT=$(aws s3 ls s3://${BUCKET}/${PREFIX} --recursive 2>/dev/null | wc -l)
  
  if [ $COUNT -gt 0 ]; then
    echo "Deleting $COUNT files from ${PREFIX}..."
    aws s3 rm s3://${BUCKET}/${PREFIX} --recursive
    echo "  ✓ Deleted"
  else
    echo "No files found in ${PREFIX}"
  fi
done

echo ""
echo "✓ Cleanup complete!"

