#!/usr/bin/env python3
# generate_large_dataset.py - Generate 10,000+ files for load testing

import boto3
import random
import string
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Get bucket from Terraform
try:
    bucket = subprocess.check_output(
        "cd ../terraform && terraform output -raw s3_bucket_name",
        shell=True
    ).decode().strip()
except subprocess.CalledProcessError as e:
    print(f"Error getting bucket name from Terraform: {e}")
    sys.exit(1)

s3 = boto3.client('s3', region_name='us-west-2')
prefix = 'load-test/'

def upload_file(i):
    """Upload a single test file"""
    content = f"""Load test file {i}
SSN: {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(1000,9999)}
Credit Card: 4532-{random.randint(1000,9999)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}
Email: user{i}@example.com
Phone: ({random.randint(200,999)}) {random.randint(100,999)}-{random.randint(1000,9999)}
"""
    
    key = f"{prefix}file_{i:06d}.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=content.encode())
    return i

# Upload files in parallel
print(f"=== Generating Large Dataset ===")
print(f"Bucket: s3://{bucket}/{prefix}")
print("Uploading 10,000 files (parallel upload)...")
print()

with ThreadPoolExecutor(max_workers=50) as executor:
    futures = [executor.submit(upload_file, i) for i in range(1, 10001)]
    
    for i, future in enumerate(as_completed(futures), 1):
        if i % 1000 == 0:
            print(f"  Uploaded {i} files...")

print(f"\n✓ Upload complete! 10,000 files in s3://{bucket}/{prefix}")

