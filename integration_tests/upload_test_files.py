#!/usr/bin/env python3
# upload_test_files.py - Upload 500+ test files to S3 (faster than bash)
import boto3
import subprocess
import random
import sys

# Get bucket from Terraform
try:
    bucket = subprocess.check_output(
        "cd ../terraform && terraform output -raw s3_bucket_name",
        shell=True
    ).decode().strip()
except subprocess.CalledProcessError as e:
    print(f"Error getting bucket name from Terraform: {e}")
    sys.exit(1)

prefix = 'test/'
s3 = boto3.client('s3', region_name='us-west-2')

print(f"=== Uploading Test Files ===")
print(f"Bucket: s3://{bucket}/{prefix}\n")

# Generate 500 files with sensitive data
print("Generating 500 test files...")
for i in range(1, 501):
    content = f"""Test file number {i}
Generated for S3 scanner testing

Sample sensitive data:
- SSN: {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(1000,9999)}
- Credit Card: 4532-1234-5678-9010
- Email: user{i}@example.com
- Phone: (555) {random.randint(100,999)}-{random.randint(1000,9999)}
- AWS Access Key: AKIAIOSFODNN7EXAMPLE{i}

Random data: {''.join(random.choices('0123456789abcdef', k=40))}
"""
    
    key = f"{prefix}test_{i:04d}.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=content.encode())
    
    if i % 100 == 0:
        print(f"  Uploaded {i} files...")

print(f"\n✓ Upload complete! Uploaded 500 files to s3://{bucket}/{prefix}")

