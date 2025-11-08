# AWS S3 Sensitive Data Scanner

A scalable AWS-based service that scans S3 files (up to hundreds of terabytes, millions of objects) for sensitive data patterns including SSN, credit card numbers, AWS keys, emails, and US phone numbers.

## Architecture Overview

The system is designed for massive scale and consists of:

- **API Layer**: API Gateway + Lambda for triggering scans and retrieving results
- **Queue**: SQS for job distribution with dead-letter queue for failed messages
- **Workers**: ECS Fargate tasks that consume SQS messages and scan S3 objects
- **Database**: RDS PostgreSQL with RDS Proxy for connection pooling
- **Infrastructure**: Terraform-managed AWS resources with VPC, subnets, and security groups

### Message Flow

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /scan {bucket, prefix}
       ▼
┌─────────────────┐
│  API Gateway    │
│  (HTTP API)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────────┐
│  Lambda Handler │─────▶│  RDS (jobs)      │
│  (POST /scan)   │      │  Create job_id   │
└────────┬────────┘      └──────────────────┘
         │
         │ Enumerate S3 objects
         │ Create job_objects records
         │
         ▼
┌─────────────────┐
│  SQS Queue      │◀─────┐
│  scan-jobs      │      │
│  (Long polling) │      │
└────────┬────────┘      │
         │                │ Visibility timeout
         │ Messages:      │ (300s default)
         │ {job_id,       │
         │  bucket,       │
         │  key, etag}     │
         │                │
         ▼                │
┌─────────────────┐       │
│  ECS Fargate    │       │
│  Worker Tasks   │       │
│  (Auto-scaling) │       │
└────────┬────────┘       │
         │                │
         │ Receive message│
         │ (10 at a time) │
         │                │
         ▼                │
┌─────────────────┐       │
│  Download from  │       │
│  S3             │       │
└────────┬────────┘       │
         │                │
         ▼                │
┌─────────────────┐       │
│  Detectors      │       │
│  (SSN, CC, etc) │       │
└────────┬────────┘       │
         │                │
         │ Luhn validation│
         │ for credit cards│
         │                │
         ▼                │
┌─────────────────┐       │
│  RDS            │       │
│  - findings     │       │
│  - job_objects  │       │
│    (status)     │       │
└────────┬────────┘       │
         │                │
         │ Delete message │
         │ from SQS       │
         └────────────────┘
                │
                │ If processing fails > 3 times
                ▼
         ┌──────────────┐
         │  SQS DLQ      │
         │  scan-jobs-dlq│
         └──────────────┘

GET /jobs/{job_id} and GET /results:
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  API Gateway    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│  Lambda Handler │─────▶│  RDS          │
│  (GET endpoints)│      │  Query data  │
└─────────────────┘      └──────────────┘
```

**Key Points:**
- **Visibility Timeout**: 300 seconds (5 minutes) - messages are hidden from other consumers during processing
- **Retries**: Messages are retried up to 3 times before moving to DLQ
- **Auto-scaling**: ECS tasks scale based on `ApproximateNumberOfMessagesVisible` metric (min 1, max 5 by default)
- **Idempotency**: Findings use unique constraint on (bucket, key, etag, detector, byte_offset) to prevent duplicates
- **Long Polling**: SQS receive wait time is 20 seconds to reduce empty responses

## Project Structure

```
aws-strac-scanner/
├── terraform/              # Infrastructure as Code
│   ├── main.tf            # Main Terraform configuration
│   ├── provider.tf        # AWS provider configuration
│   ├── variables.tf       # Variable definitions
│   ├── outputs.tf         # Output values
│   ├── database_schema.sql # Database schema
│   └── modules/           # Terraform modules
│       ├── vpc/           # VPC, subnets, NAT, endpoints
│       ├── rds/           # RDS PostgreSQL + Proxy
│       ├── sqs/           # SQS queues + DLQ
│       ├── ecs/           # ECS Fargate cluster + service
│       ├── api/           # API Gateway + Lambda
│       └── bastion/       # EC2 bastion host
├── scanner/               # ECS Fargate worker application
│   ├── main.py           # Main worker loop
│   ├── batch_processor.py # Batch processing logic
│   ├── Dockerfile         # Container image
│   ├── requirements.txt   # Python dependencies
│   └── utils/
│       ├── detectors.py   # Pattern detection logic
│       └── db.py          # Database utilities
├── lambda_api/            # Lambda API handler
│   ├── main.py           # API endpoints
│   ├── Dockerfile        # Container image
│   └── requirements.txt   # Python dependencies
└── docs/                  # Documentation
    ├── README.md         # This file
    └── TESTING.md        # Testing guide
```

## Prerequisites

- AWS Account (Account ID: 697547269674)
- AWS CLI configured with appropriate credentials
- Terraform >= 1.6
- Docker (for building container images)
- Python 3.12 (for local development)
- PostgreSQL client (for database access)

## Quick Start

### 1. Configure Terraform Variables

Create a `terraform/terraform.tfvars` file:

```hcl
aws_region      = "us-west-2"
aws_account_id  = "697547269674"
environment     = "dev"
project_name    = "strac-scanner"

rds_master_username = "scanner_admin"
rds_master_password = "YourSecurePassword123!" # Change this!

# Optional: Adjust scaling parameters
ecs_min_capacity = 1
ecs_max_capacity = 50
scanner_batch_size = 10
```

### 2. Initialize and Apply Terraform

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

This will create:
- VPC with public/private subnets
- RDS PostgreSQL instance with RDS Proxy
- SQS queues (main + DLQ)
- ECS Fargate cluster and service
- API Gateway + Lambda
- ECR repositories for container images
- Security groups and IAM roles

### 3. Initialize Database

After Terraform completes, connect to the database and run the schema:

```bash
# Get RDS endpoint from Terraform output
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint)

# Connect and run schema
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db -f database_schema.sql
```

### 4. Build and Push Container Images

```bash
# Build scanner image
cd ../scanner
docker build -t strac-scanner:latest .
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <ECR_REPO_URL>
docker tag strac-scanner:latest <ECR_REPO_URL>:latest
docker push <ECR_REPO_URL>:latest

# Build Lambda API image
cd ../lambda_api
docker build -t lambda-api:latest .
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <LAMBDA_ECR_REPO_URL>
docker tag lambda-api:latest <LAMBDA_ECR_REPO_URL>:latest
docker push <LAMBDA_ECR_REPO_URL>:latest
```

### 5. Update ECS Service and Lambda

After pushing images, update the ECS service and Lambda function to use the new images.

## API Endpoints

### POST /scan

Trigger a new scan job.

**Request:**
```json
{
  "bucket": "my-bucket",
  "prefix": "documents/"  // Optional
}
```

**Response:**
```json
{
  "job_id": "uuid",
  "bucket": "my-bucket",
  "prefix": "documents/",
  "total_objects": 1234,
  "messages_enqueued": 1234,
  "status": "queued"
}
```

### GET /jobs/{job_id}

Get job status and progress.

**Response:**
```json
{
  "job_id": "uuid",
  "bucket": "my-bucket",
  "prefix": "documents/",
  "status": "processing",
  "total_objects": 1234,
  "queued": 100,
  "processing": 50,
  "succeeded": 1000,
  "failed": 84,
  "total_findings": 234,
  "progress_percent": 87.5
}
```

### GET /results

Retrieve scan findings with pagination (supports cursor or offset).

**Query Parameters:**
- `job_id` (optional): Filter by job ID
- `bucket` (optional): Filter by bucket
- `key` (optional): Filter by object key (can be used as prefix filter)
- `limit` (default: 100): Results per page
- `cursor` (optional): Cursor for pagination (ID of last item from previous page)
- `offset` (optional): Offset for pagination (fallback if cursor not provided)

**Response:**
```json
{
  "findings": [
    {
      "id": 1,
      "job_id": "uuid",
      "bucket": "my-bucket",
      "key": "documents/file.txt",
      "detector": "ssn",
      "masked_match": "XXX-XX-6789",
      "context": "My SSN is XXX-XX-6789 and I need to keep it secure.",
      "byte_offset": 42,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 234,
  "limit": 100,
  "cursor": "12345",  // or "offset": 0 if using offset-based
  "next_cursor": "12245",  // Use this for next page
  "has_more": true
}
```
```

## Scalability Features

### S3 Listing

- **Prefix Fan-out**: For large buckets, use prefix-based parallel listing (a-z, 0-9)
- **S3 Inventory**: For extremely large buckets (millions of objects), use S3 Inventory
- **S3 Batch Operations**: For massive scale, consider S3 Batch Operations

### SQS Scaling

- **Auto-scaling**: ECS tasks scale based on `ApproximateNumberOfMessagesVisible`
- **Message Age**: Also scales based on `ApproximateAgeOfOldestMessage`
- **Dead Letter Queue**: Failed messages (>3 retries) go to DLQ for investigation
- **Batch Processing**: Process 10-20 files per task invocation

### ECS Fargate

- **Auto-scaling**: 1-50 tasks (configurable)
- **Target Tracking**: CPU utilization and SQS queue depth
- **Spot Pricing**: Can use Spot Fargate for cost optimization
- **Connection Pooling**: RDS Proxy handles database connections

### RDS

- **RDS Proxy**: Connection pooling for many concurrent ECS tasks
- **Auto-scaling Storage**: 20GB initial, up to 200GB
- **Batch Inserts**: 100-1000 rows per transaction
- **Partitioning**: Optional table partitioning for >100M rows

## Monitoring

### CloudWatch Metrics

- **SQS**: `ApproximateNumberOfMessagesVisible`, `ApproximateAgeOfOldestMessage`
- **ECS**: `CPUUtilization`, `MemoryUtilization`, `RunningTaskCount`
- **RDS**: `DatabaseConnections`, `WriteLatency`, `ReadLatency`
- **Lambda**: `Invocations`, `Duration`, `Errors`

### CloudWatch Dashboards

Create dashboards to monitor:
- Queue depth and message age
- ECS task concurrency
- RDS write latency
- Error rate per detector type
- Processing throughput (files/sec, bytes/sec)

### Alarms

- High queue depth (>1000 messages)
- High message age (>10 minutes)
- High RDS connection count
- High error rate

## Cost Optimization

1. **VPC Endpoints**: Use VPC endpoints for S3 and SQS to avoid NAT Gateway costs
2. **Spot Fargate**: Use Spot pricing for ECS tasks (up to 70% savings)
3. **RDS Reserved Instances**: For production, use Reserved Instances
4. **S3 Inventory**: Use S3 Inventory instead of ListObjects for very large buckets
5. **Auto-scaling**: Scale down during low usage periods

## Security

- **VPC**: All resources in private subnets except API Gateway and bastion
- **Encryption**: S3, RDS, and EBS volumes encrypted at rest
- **SSL/TLS**: All connections use SSL/TLS
- **IAM Roles**: Least privilege IAM roles for each service
- **Secrets**: RDS credentials stored in Secrets Manager
- **Network**: Security groups restrict access to necessary ports only

## Multi-Region Support

The infrastructure supports multiple AWS regions. To deploy to additional regions:

1. Update `aws_region` variable in `terraform.tfvars`
2. Update `availability_zones` to match the region
3. Re-run `terraform apply`

The application code automatically uses the configured AWS region from environment variables.

## Troubleshooting

### ECS Tasks Not Processing

1. Check CloudWatch Logs: `/ecs/strac-scanner-scanner`
2. Verify SQS queue has messages: `aws sqs get-queue-attributes --queue-url <URL>`
3. Check ECS service desired count matches running tasks
4. Verify IAM roles have correct permissions

### High Error Rate

1. Check DLQ for failed messages
2. Review CloudWatch Logs for error patterns
3. Verify RDS connection limits and proxy configuration
4. Check S3 bucket permissions

### Slow Processing

1. Increase ECS task count (max_capacity)
2. Increase task CPU/memory
3. Check RDS write latency
4. Verify VPC endpoints are working (no NAT Gateway usage)
5. Consider increasing batch size

## Next Steps

- [ ] Add more detector patterns (passwords, API keys, etc.)
- [ ] Implement S3 Inventory integration for very large buckets
- [ ] Add CloudWatch dashboards
- [ ] Set up automated testing
- [ ] Add CI/CD pipeline
- [ ] Implement result export (CSV, JSON)
- [ ] Add notification system (SNS) for job completion

## License

[Your License Here]

