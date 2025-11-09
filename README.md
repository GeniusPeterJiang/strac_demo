# AWS S3 Sensitive Data Scanner

A production-ready AWS service that scans S3 files for sensitive data patterns (SSN, credit cards, AWS keys, emails, phone numbers). Designed to scale from thousands to **millions of objects** efficiently.

## Quick Start

```bash
# 1. Configure Terraform
cd terraform
cp terraform.tfvars.example terraform.tfvars  # Edit with your AWS details

# 2. Deploy infrastructure
terraform init && terraform apply

# 3. Build and deploy containers
cd .. && ./build_and_push.sh

# 4. Initialize database
./init_database.sh

# 5. Test the API
API_URL=$(cd terraform && terraform output -raw api_gateway_url)
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{"bucket": "my-bucket", "prefix": "path/"}'
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed deployment and testing instructions.

## Architecture

### High-Level Overview

```
Client → API Gateway → Lambda (listing) → Step Functions (batches)
                           ↓
                       SQS Queue (fair queue)
                           ↓
                    ECS Fargate Workers (auto-scaling)
                           ↓
                    RDS PostgreSQL (RDS Proxy)
```

### Detailed Message Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. API REQUEST                                                              │
│    POST /scan {"bucket": "my-bucket", "prefix": "path/"}                   │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│ 2. LAMBDA API (listing)                                                     │
│    • Creates job record in RDS                                              │
│    • Invokes Step Functions for async S3 listing                           │
│    • Returns job_id immediately (no timeout)                               │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│ 3. STEP FUNCTIONS (S3 Listing)                                              │
│    • Lists S3 objects in batches (10K per iteration)                       │
│    • Uses continuation tokens (handles 50M+ objects)                       │
│    • Parallel SQS enqueueing (20 workers)                                  │
│    • Enqueues scan tasks to SQS                                            │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│ 4. SQS QUEUE (Fair Queue with DLQ)                                          │
│    ┌──────────────────────────────────────────────────────────────┐        │
│    │ Configuration:                                               │        │
│    │  • Visibility Timeout: 300s (5 minutes)                      │        │
│    │  • Max Receive Count: 3 attempts                             │        │
│    │  • Message Retention: 14 days                                │        │
│    │  • Long Polling: 20 seconds                                  │        │
│    │  • MessageGroupId: bucket name (fair queue)                  │        │
│    └──────────────────────────────────────────────────────────────┘        │
│                                                                             │
│    Fair Queue Behavior:                                                    │
│    • MessageGroupId = S3 bucket name                                       │
│    • AWS balances delivery across message groups                          │
│    • Prevents large jobs from starving small jobs                         │
│    • Example: bucket-prod (10M objects) + bucket-test (100 objects)      │
│      both get fair share of worker capacity                               │
│                                                                             │
│    Retry Logic:                                                            │
│    1. Worker receives message (visibility timeout starts)                 │
│    2. If processing fails → message becomes visible again                 │
│    3. After 3 failed attempts → moved to Dead Letter Queue                │
│    4. DLQ retention: 14 days for manual inspection                        │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│ 5. ECS FARGATE WORKERS (Auto-scaling)                                       │
│    ┌──────────────────────────────────────────────────────────────┐        │
│    │ Processing Loop:                                             │        │
│    │  1. Long poll SQS (20s wait, batch of 10 messages)          │        │
│    │  2. Download S3 objects (parallel)                           │        │
│    │  3. Scan for sensitive data patterns                         │        │
│    │  4. Write findings to RDS (via RDS Proxy)                    │        │
│    │  5. Delete messages from SQS on success                      │        │
│    │  6. Update job_objects status (queued→processing→succeeded)  │        │
│    └──────────────────────────────────────────────────────────────┘        │
│                                                                             │
│    Performance Optimization:                                              │
│    • max_workers set to 20 per task (configurable via MAX_WORKERS env)   │
│    • Previous CPU utilization was only ~5% with max_workers=5            │
│    • Higher parallelism improves throughput and CPU utilization            │
│                                                                             │
│    Auto-scaling Triggers:                                                  │
│    • Metric: SQS ApproximateNumberOfMessages                        │
│    • Target: 100 messages per task                                         │
│    • Min capacity: 1 task                                                  │
│    • Max capacity: 5-50 tasks (configurable)                               │
│    • Scale-out: When queue depth > (100 × current tasks)                  │
│    • Scale-in: 300s cooldown to prevent thrashing                          │
│                                                                             │
│    Connection Management:                                                  │
│    • Connects via RDS Proxy (not direct to RDS)                           │
│    • Proxy manages connection pooling                                     │
│    • Supports 1000+ concurrent connections                                │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│ 6. RDS POSTGRESQL (with RDS Proxy)                                          │
│    ┌──────────────────────────────────────────────────────────────┐        │
│    │ Tables:                                                      │        │
│    │  • jobs: Job metadata (bucket, prefix, status)              │        │
│    │  • job_objects: Per-object status and progress              │        │
│    │  • findings: Detected sensitive data (deduplicated)         │        │
│    └──────────────────────────────────────────────────────────────┘        │
│                                                                             │
│    RDS Proxy Benefits:                                                     │
│    • Connection pooling (handles 50+ ECS tasks)                           │
│    • Reduces connection overhead                                          │
│    • Automatic failover for Multi-AZ                                      │
│    • IAM authentication support                                           │
│                                                                             │
│    Performance Optimizations:                                             │
│    • Materialized view: job_progress_cache                                │
│    • Refreshed every 1 minute via EventBridge + Lambda                    │
│    • 6000× faster queries for job status (O(1) vs O(n))                   │
│    • Handles millions of objects efficiently                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Components:**
- **API Gateway + Lambda**: Trigger scans, query results
- **Step Functions**: Asynchronous S3 listing with continuation tokens (handles 50M+ objects)
- **SQS Fair Queue**: Prevents noisy neighbor problems across tenants using MessageGroupId
- **ECS Fargate**: Auto-scaling workers (1-50 tasks) with multi-threaded processing
- **RDS + Proxy**: Connection pooling, materialized views for fast queries
- **EventBridge**: Auto-refresh job progress cache every 1 minute

**SQS Reliability Features:**
- **Visibility Timeout (5 min)**: Prevents duplicate processing while worker scans file
- **Retry Logic (3 attempts)**: Automatic retries for transient failures (network, S3 throttling)
- **Dead Letter Queue**: Failed messages preserved for 14 days for debugging
- **Long Polling (20s)**: Reduces empty receives and API costs

## API Endpoints

### POST /scan
Trigger a new scan job (asynchronous, no Lambda timeout limits).

**Request:**
```json
{
  "bucket": "my-bucket",
  "prefix": "path/"  // optional
}
```

**Response:**
```json
{
  "job_id": "uuid",
  "status": "listing",
  "execution_arn": "arn:aws:states:...",
  "message": "Job created. Objects are being listed asynchronously."
}
```

### GET /jobs/{job_id}
Get job status and progress. Uses cached data (refreshed every 1 minute) for fast queries even with millions of objects.

**Response:**
```json
{
  "job_id": "uuid",
  "status": "processing",
  "total": 1000000,
  "succeeded": 750000,
  "progress_percent": 75.0,
  "total_findings": 1543,
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:00:00Z"
}
```

Add `?real_time=true` for live data (slower for large jobs).

### GET /results
Retrieve findings with pagination.

**Parameters:**
- `job_id` (optional): Filter by job
- `bucket`, `key` (optional): Filter by location
- `limit` (default: 100): Results per page
- `cursor` or `offset`: Pagination

**Response:**
```json
{
  "findings": [
    {
      "bucket": "my-bucket",
      "key": "file.txt",
      "detector": "ssn",
      "masked_match": "XXX-XX-6789",
      "context": "My SSN is XXX-XX-6789..."
    }
  ],
  "total": 1543,
  "next_cursor": "12345",
  "has_more": true
}
```

## Scaling Capabilities

The system is designed to handle massive scale. See [SCALING.md](SCALING.md) for detailed capacity analysis.

| Capacity | Time | Notes |
|----------|------|-------|
| **1M objects** | ~1 hour listing + 1 day processing | Current default config |
| **10M objects** | ~10 hours listing + 3 days processing | With ECS max=20 |
| **50M objects** | ~42 hours listing + 6 days processing | With ECS max=50 |

**Key Features:**
- Step Functions with continuation tokens (no Lambda timeout)
- Multi-threaded Lambda SQS enqueueing (20 workers)
- SQS Fair Queue (prevents tenant monopolization)
- ECS auto-scaling (CPU + queue depth)
- RDS Proxy (connection pooling for 1000+ connections)
- Materialized views (6000× faster queries for progress)

## Project Structure

```
aws-strac-scanner/
├── terraform/              # Infrastructure as Code
│   ├── modules/           # VPC, RDS, SQS, ECS, API, Step Functions
│   ├── database_schema.sql
│   └── migrations/        # Database optimization migrations
├── scanner/               # ECS Fargate worker
│   ├── main.py           # Batch processing loop
│   ├── utils/detectors.py # Pattern detection (SSN, CC, etc.)
│   └── tests/            # 72 pytest tests
├── lambda_api/           # API Gateway handler
│   └── main.py           # /scan, /jobs, /results endpoints
├── lambda_refresh/       # Materialized view refresh (EventBridge trigger)
└── build_and_push.sh     # Deployment automation
```

## Detectors

- **SSN**: Social Security Numbers (validated)
- **Credit Card**: Visa, Mastercard, Amex, Discover (Luhn validation)
- **AWS Keys**: Access keys and secret keys
- **Email**: Email addresses (RFC 5322)
- **Phone**: US phone numbers (multiple formats)

All findings include:
- Masked value (e.g., `XXX-XX-6789`)
- Context (surrounding text)
- Byte offset in file
- Unique constraint prevents duplicates

## Monitoring

**CloudWatch Metrics:**
- SQS: Queue depth, message age
- ECS: Task count, CPU utilization
- RDS: Connection count, query latency
- Lambda: Invocations, errors, duration
- Step Functions: Execution status

**CloudWatch Logs:**
- `/aws/lambda/strac-scanner-api` - API requests
- `/aws/stepfunctions/strac-scanner-s3-scanner` - Listing progress
- `/ecs/strac-scanner-scanner` - Worker processing
- `/aws/lambda/strac-scanner-refresh-job-progress` - Cache refresh

## Cost Estimate

**Small deployment** (1M objects/month):
- RDS (db.t3.medium): ~$60/month
- ECS Fargate (5 tasks avg): ~$30/month
- NAT Gateway: ~$32/month (or use VPC endpoints)
- Lambda + Step Functions: ~$5/month
- S3 API calls: ~$5/month
- **Total: ~$130/month**

**Large deployment** (100M objects/month):
- RDS (db.t3.large, Multi-AZ): ~$140/month
- ECS Fargate (20 tasks avg): ~$120/month
- Other services: ~$50/month
- **Total: ~$310/month**

See [SCALING.md](SCALING.md) for detailed cost breakdown.

## Security

- **VPC**: All resources in private subnets (except API Gateway, bastion)
- **Encryption**: S3, RDS, EBS volumes encrypted at rest
- **IAM**: Least privilege roles for each service
- **Secrets Manager**: RDS credentials rotation
- **Security Groups**: Restrictive ingress/egress rules
- **TLS**: All connections encrypted in transit

## Local Testing

```bash
cd scanner/tests
./run_tests.sh  # 72 pytest tests, no AWS required
```

## Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)**: Deployment, testing, troubleshooting
- **[SCALING.md](SCALING.md)**: Capacity analysis, performance data, optimization strategies
- **[integration_tests/TESTING.md](integration_tests/TESTING.md)**: Comprehensive integration testing guide

## Support

For issues:
1. Check CloudWatch Logs for errors
2. Review Terraform outputs: `terraform output`
3. Verify IAM permissions and security groups
4. See [DEVELOPMENT.md](DEVELOPMENT.md) troubleshooting section

## License

[Your License Here]
