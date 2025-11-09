# Demo Narrative: AWS S3 Sensitive Data Scanner

This narrative provides a comprehensive walkthrough of the AWS S3 Sensitive Data Scanner architecture, scaling considerations, and codebase structure for demonstration purposes.

## Part 1: High-Level Architecture Walkthrough

### Overview

The AWS S3 Sensitive Data Scanner is a production-ready service designed to scan millions of S3 objects for sensitive data patterns like SSNs, credit cards, AWS keys, emails, and phone numbers. The architecture is built to handle scale from thousands to millions of objects efficiently.

### Architecture Flow

Let's walk through the complete message flow from API request to data storage:

#### 1. API Request (Entry Point)

**Component:** API Gateway + Lambda API Handler

**Location:** `lambda_api/main.py`

The journey begins when a client makes a POST request to `/scan` with a bucket and optional prefix:

```json
POST /scan
{
  "bucket": "my-bucket",
  "prefix": "path/"
}
```

**What happens:**
- The Lambda API handler (`lambda_api/main.py`) receives the request
- It creates a job record in RDS PostgreSQL with status "listing"
- It immediately returns a `job_id` to the client (no timeout waiting)
- It invokes AWS Step Functions asynchronously to handle the S3 listing

**Key Design Decision:** By returning immediately and using Step Functions, we avoid Lambda's 15-minute timeout limit. This allows us to handle buckets with millions of objects without timing out.

#### 2. Step Functions Orchestration (Asynchronous S3 Listing)

**Component:** AWS Step Functions State Machine

**Location:** `terraform/modules/step_functions/`

**What happens:**
- Step Functions orchestrates the S3 listing process in batches of 10,000 objects per iteration
- Uses S3 continuation tokens to handle pagination across multiple invocations
- Each iteration lists 10K objects, then passes a continuation token to the next iteration
- This process can run indefinitely (no timeout constraints)

**Scaling Consideration (from SCALING.md):**
- **Capacity:** Handles up to 50 million objects (Step Functions event history limit)
- **Performance:** ~10K objects per 30 seconds = 1.2M objects/hour
- **For 50M+ objects:** The system can integrate with S3 Inventory to bypass this limit

**Why Step Functions?**
- Eliminates Lambda timeout bottlenecks
- Provides built-in retry logic and error handling
- Tracks execution state automatically
- Cost-effective: $0.03 per million objects

#### 3. Multi-threaded SQS Enqueueing

**Component:** Lambda (within Step Functions)

**Location:** `lambda_api/main.py` (SQS enqueueing logic)

**What happens:**
- After listing each batch of 10K objects, the system enqueues scan tasks to SQS
- Uses ThreadPoolExecutor with 20 parallel workers for concurrent SQS message sending
- Sends messages in batches of 10 per `SendMessageBatch` call

**Performance Improvement (from SCALING.md):**
- **Before (sequential):** 10K messages = 100 seconds
- **After (20 workers):** 10K messages = 5 seconds
- **Speed-up: 20×**

This optimization eliminates SQS enqueueing as a bottleneck during S3 listing.

#### 4. SQS Fair Queue (Message Distribution)

**Component:** Amazon SQS Queue with Dead Letter Queue

**Location:** `terraform/modules/sqs/`

**Configuration:**
- **Visibility Timeout:** 300 seconds (5 minutes) - prevents duplicate processing
- **Max Receive Count:** 3 attempts before moving to DLQ
- **Message Retention:** 14 days
- **Long Polling:** 20 seconds (reduces empty receives and API costs)
- **MessageGroupId:** Set to S3 bucket name (enables fair queue behavior)

**Fair Queue Behavior:**
The system uses `MessageGroupId` set to the bucket name to implement fair queueing. This prevents large jobs from monopolizing worker capacity and starving smaller jobs.

**Example Scenario:**
```
Without Fair Queue:
  - Job A (bucket-prod): 10M objects → dominates queue
  - Job B (bucket-test): 100 objects → waits 3 days

With Fair Queue:
  - Job A (bucket-prod): 10M objects → processes steadily
  - Job B (bucket-test): 100 objects → completes in 10 minutes
```

**Reliability Features:**
1. **Visibility Timeout:** When a worker receives a message, it becomes invisible for 5 minutes. If processing fails, the message becomes visible again for retry.
2. **Retry Logic:** After 3 failed attempts, messages move to the Dead Letter Queue for manual inspection.
3. **DLQ Retention:** 14 days for debugging and analysis.

#### 5. ECS Fargate Workers (Auto-scaling Processing)

**Component:** Amazon ECS Fargate Service

**Location:** `scanner/main.py`, `scanner/batch_processor.py`

**Processing Loop:**
1. **Long poll SQS** (20s wait, batch of 10 messages)
2. **Download S3 objects** (parallel processing with configurable workers)
3. **Scan for sensitive data patterns** using regex detectors
4. **Write findings to RDS** (via RDS Proxy)
5. **Delete messages from SQS** on success
6. **Update job_objects status** (queued → processing → succeeded)

**Performance Optimization:**
- `max_workers` set to 20 per task (configurable via `MAX_WORKERS` env var)
- Previous CPU utilization was only ~5% with `max_workers=5`
- Higher parallelism improves throughput and CPU utilization significantly

**Auto-scaling Configuration:**
- **Metric:** SQS `ApproximateNumberOfMessages`
- **Target:** 100 messages per task
- **Min capacity:** 1 task
- **Max capacity:** 5-50 tasks (configurable)
- **Scale-out:** When queue depth > (100 × current tasks)
- **Scale-in:** 300s cooldown to prevent thrashing

**Scaling Consideration (from SCALING.md):**
- **Processing rate:** 10 files/sec (5 tasks) to 100 files/sec (50 tasks)
- **Throughput:** 864K files/day (5 tasks) to 8.6M files/day (50 tasks)
- **1M objects:** 1.2 days (5 tasks) to 3 hours (50 tasks)

**Connection Management:**
- Workers connect via RDS Proxy (not direct to RDS)
- Proxy manages connection pooling
- Supports 1000+ concurrent connections

#### 6. RDS PostgreSQL with RDS Proxy (Data Storage)

**Component:** Amazon RDS PostgreSQL + RDS Proxy

**Location:** `terraform/modules/rds/`, `terraform/database_schema.sql`

**Database Schema:**
- **`jobs`:** Job metadata (bucket, prefix, status, execution_arn)
- **`job_objects`:** Per-object status and progress tracking
- **`findings`:** Detected sensitive data (deduplicated with unique constraints)

**RDS Proxy Benefits:**
- **Connection pooling:** Handles 50+ ECS tasks efficiently
- **Reduces connection overhead:** Multiplexes connections
- **Automatic failover:** For Multi-AZ deployments
- **IAM authentication support:** Enhanced security

**Performance Optimizations:**

1. **Materialized View (`job_progress_cache`):**
   - Caches aggregate statistics (total, succeeded, failed counts)
   - Refreshed every 1 minute via EventBridge + Lambda
   - **6000× faster queries** for job status (O(1) vs O(n))
   - Handles millions of objects efficiently

2. **Database Indexes:**
   - Composite indexes on frequently queried columns
   - Partial indexes for specific use cases
   - See `terraform/migrations/002_optimize_for_scale.sql`

**Scaling Consideration (from SCALING.md):**
- **Without materialized view:** 30+ seconds for 1M objects
- **With materialized view:** <50ms for any scale
- **Refresh performance:** 1M objects = ~5 seconds refresh time

### Architecture Summary

**Key Components:**
- **API Gateway + Lambda:** Trigger scans, query results
- **Step Functions:** Asynchronous S3 listing with continuation tokens (handles 50M+ objects)
- **SQS Fair Queue:** Prevents noisy neighbor problems across tenants using MessageGroupId
- **ECS Fargate:** Auto-scaling workers (1-50 tasks) with multi-threaded processing
- **RDS + Proxy:** Connection pooling, materialized views for fast queries
- **EventBridge:** Auto-refresh job progress cache every 1 minute

**Proven Capacity:**
- **1M objects:** ~1 hour listing + 1 day processing (default config)
- **10M objects:** ~10 hours listing + 3 days processing (ECS max=20)
- **50M objects:** ~42 hours listing + 6 days processing (ECS max=50)

---

## Part 2: High-Level Scaling Considerations

### Scaling Mechanisms Overview

The system implements seven key scaling mechanisms to handle massive scale:

#### 1. AWS Step Functions (Asynchronous Listing)

**Problem Solved:** Lambda 300-second timeout limits synchronous listing to ~200K objects.

**Solution:**
- Step Functions orchestrates Lambda in batches of 10K objects
- Continuation tokens track progress across invocations
- No timeout constraints (runs indefinitely)

**Capacity:**
- **Theoretical max:** 50 million objects (Step Functions event history limit)
- **Practical max:** Unlimited with S3 Inventory integration
- **Performance:** ~10K objects per 30 seconds = 1.2M objects/hour

**Cost:** $0.025 per 1K state transitions = $0.03 per million objects

#### 2. Lambda Multi-threaded SQS Enqueueing

**Problem Solved:** Sequential SQS message sending is slow for large batches.

**Solution:**
- ThreadPoolExecutor with 20 parallel workers
- Batch size: 10 messages per SendMessageBatch call
- Concurrent uploads to SQS

**Performance Improvement:**
- **Before (sequential):** 10K messages = 100 seconds
- **After (20 workers):** 10K messages = 5 seconds
- **Speed-up: 20×**

#### 3. SQS Fair Queue

**Problem Solved:** Large jobs monopolize queue, starving smaller jobs (noisy neighbor problem).

**Solution:**
- MessageGroupId set to S3 bucket name
- AWS automatically balances message delivery across groups
- Prevents one tenant from consuming all worker capacity

**Example:** A 10M object job and a 100 object job both get fair share of worker capacity.

#### 4. ECS Fargate Auto-scaling

**Problem Solved:** Static worker count can't handle variable load.

**Solution:**
- Target tracking based on SQS `ApproximateNumberOfMessages`
- Target: 100 messages per task
- Scale-in cooldown: 300 seconds (prevents thrashing)

**Processing Capacity:**
- **5 tasks:** 10 files/second = 36K files/hour = 864K files/day
- **50 tasks:** 100 files/second = 360K files/hour = 8.6M files/day

**Cost Efficiency:**
- Scales to zero (min=1) during idle periods
- Spot Fargate: Up to 70% cost savings (optional)
- Pay only for actual compute time

#### 5. RDS Proxy (Connection Pooling)

**Problem Solved:** Direct RDS connections don't scale beyond 100-200 concurrent clients.

**Solution:**
- RDS Proxy manages connection pooling
- Multiplexes up to 1000+ ECS tasks to RDS
- Automatic connection lifecycle management
- Built-in failover for Multi-AZ deployments

**Without RDS Proxy:**
- 50 ECS tasks × 5 connections = 250 connections
- RDS max_connections = 200 → Connection exhausted ❌

**With RDS Proxy:**
- 50 ECS tasks → RDS Proxy → Pooled connections to RDS
- RDS connections = ~20-50 (efficient reuse) ✅

**Benefits:**
- **Scalability:** Handle 1000+ concurrent workers
- **Reliability:** Automatic retry on transient failures
- **Performance:** Connection multiplexing reduces overhead
- **Security:** IAM authentication support

#### 6. Materialized Views with Auto-refresh

**Problem Solved:** Counting millions of rows for job status is slow (30+ seconds).

**Solution:**
- Materialized view `job_progress` caches aggregate statistics
- EventBridge triggers Lambda refresh every 1 minute
- Queries run in <50ms even with 100M objects

**Performance Comparison:**

| Objects | Without Materialized View | With Materialized View | Speed-up |
|---------|---------------------------|------------------------|----------|
| 100K | 3 seconds | 5ms | **600×** |
| 1M | 30 seconds | 5ms | **6,000×** |
| 10M | 300 seconds | 5ms | **60,000×** |
| 100M | 3000 seconds | 5ms | **600,000×** |

**Architecture:**
```
EventBridge (cron: rate(1 minute))
    ↓
Lambda (VPC-enabled)
    ↓
REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;
    ↓
RDS PostgreSQL (via RDS Proxy)
```

**Staleness:** Data up to 1 minute old (acceptable for progress tracking).

#### 7. Database Indexes and Partitioning

**Problem Solved:** Full table scans on millions of rows are prohibitively slow.

**Solution:**
- Composite indexes on frequently queried columns
- Partial indexes for specific use cases
- Table partitioning for 100M+ rows (optional)

**Performance Impact:**
- **Without index:** 15 seconds (full table scan on 10M rows)
- **With index:** 50ms (index seek on 100K matching rows)
- **Speed-up: 300×**

### Capacity Analysis by Scale

| Scale | Objects | Listing Time | Processing Time | Configuration |
|-------|---------|--------------|-----------------|---------------|
| **Small** | 100K | 5 min | 3 hours | Default (ECS max=5) |
| **Medium** | 1M | 50 min | 1 day | Default (ECS max=5) |
| **Large** | 10M | 8 hours | 3 days | ECS max=20 |
| **Enterprise** | 50M | 42 hours | 6 days | ECS max=50 |
| **Massive** | 1B+ | 24 hours* | Linear scaling | S3 Inventory mode |

*Using S3 Inventory eliminates listing bottleneck.

### Bottlenecks and Mitigations

**Identified Bottlenecks:**
1. **ECS processing speed** (96% of total time) → Increase max_capacity
2. **S3 ListObjects cost** (44% for large scans) → Use S3 Inventory
3. **Step Functions event limit** (50M objects max) → Use S3 Inventory for 50M+

**Scaling Limits:**

| Component | Limit | Workaround |
|-----------|-------|------------|
| Lambda timeout | 15 minutes | Step Functions ✅ |
| Step Functions events | 50M objects | S3 Inventory |
| RDS connections | 420-3400 | RDS Proxy ✅ |
| SQS throughput | Unlimited | N/A |
| ECS tasks | 50 (configurable) | Increase max_capacity |
| Database queries | Slow for 10M+ rows | Materialized views ✅ |

### Recommended Configuration by Scale

| Objects | ECS Max | RDS Instance | Features |
|---------|---------|--------------|----------|
| <1M | 5 | db.t3.medium | Default config |
| 1M-10M | 20 | db.t3.large | Migration 002 |
| 10M-50M | 50 | db.r6g.large | Partitioning + Multi-AZ |
| 50M+ | 50+ | db.r6g.xlarge | S3 Inventory mode |

---

## Part 3: Codebase Structure Walkthrough

### Project Organization

The codebase is organized into clear, modular components:

```
aws-strac-scanner/
├── terraform/              # Infrastructure as Code
│   ├── modules/           # Reusable Terraform modules
│   ├── database_schema.sql
│   └── migrations/        # Database optimization migrations
├── scanner/               # ECS Fargate worker
│   ├── main.py           # Entry point and SQS polling loop
│   ├── batch_processor.py # Batch processing logic
│   ├── utils/            # Utility modules
│   └── tests/            # Comprehensive test suite
├── lambda_api/           # API Gateway handler
│   └── main.py           # /scan, /jobs, /results endpoints
├── lambda_refresh/       # Materialized view refresh
│   └── main.py           # EventBridge-triggered cache refresh
└── integration_tests/     # End-to-end testing scripts
```

### Component Deep Dive

#### 1. Terraform Infrastructure (`terraform/`)

**Purpose:** Infrastructure as Code for all AWS resources

**Structure:**
- **`main.tf`:** Root module that orchestrates all components
- **`modules/`:** Reusable Terraform modules for each service:
  - **`vpc/`:** VPC, subnets, NAT Gateway, security groups
  - **`rds/`:** RDS PostgreSQL instance, RDS Proxy, parameter groups
  - **`sqs/`:** SQS queue, Dead Letter Queue, queue policies
  - **`ecs/`:** ECS cluster, Fargate service, task definitions, auto-scaling
  - **`api/`:** API Gateway, Lambda function, IAM roles
  - **`step_functions/`:** Step Functions state machine, Lambda functions
  - **`refresh_lambda/`:** Lambda for materialized view refresh
  - **`bastion/`:** EC2 bastion host for database access (optional)

**Key Files:**
- **`database_schema.sql`:** Initial database schema (jobs, job_objects, findings tables)
- **`migrations/001_add_execution_arn.sql`:** Adds execution_arn tracking
- **`migrations/002_optimize_for_scale.sql`:** Adds indexes and materialized views

**Design Pattern:** Modular Terraform structure allows for easy customization and reuse.

#### 2. Scanner Worker (`scanner/`)

**Purpose:** ECS Fargate worker that processes SQS messages and scans S3 objects

**Key Files:**

**`main.py`** - Entry Point:
- Initializes SQS client and batch processor
- Implements graceful shutdown handling (SIGTERM, SIGINT)
- Main processing loop:
  1. Long polls SQS (20s wait, batch of 10 messages)
  2. Processes messages via BatchProcessor
  3. Deletes messages on success
  4. Handles errors and retries

**`batch_processor.py`** - Batch Processing Logic:
- Downloads S3 objects in parallel using ThreadPoolExecutor
- Filters files by type (.txt, .csv, .json, .log) and size (<100MB)
- Scans content using Detector class
- Writes findings to database via Database class
- Updates job_objects status (queued → processing → succeeded/failed)

**`utils/detectors.py`** - Pattern Detection:
- Implements regex patterns for:
  - SSN (Social Security Numbers)
  - Credit Cards (with Luhn validation)
  - AWS Access Keys and Secret Keys
  - Email addresses
  - Phone numbers
- Returns findings with masked values and context

**`utils/db.py`** - Database Operations:
- Manages RDS connections via RDS Proxy
- Implements connection pooling
- Batch inserts for findings (efficient for large batches)
- Status updates for job_objects

**`tests/`** - Test Suite:
- **`test_detectors.py`:** Unit tests for pattern detection
- **`test_batch_processor.py`:** Tests for batch processing logic
- **`test_db.py`:** Database operation tests
- **`test_integration.py`:** End-to-end workflow tests
- **`test_main.py`:** Main loop and shutdown tests
- **72 pytest tests total** - can run locally without AWS

**Design Patterns:**
- Separation of concerns (main loop, batch processing, detection, database)
- Configurable parallelism (MAX_WORKERS env var)
- Graceful shutdown for zero-downtime deployments
- Comprehensive error handling and logging

#### 3. Lambda API (`lambda_api/`)

**Purpose:** API Gateway handler for triggering scans and querying results

**Key Functions:**

**`handle_scan()`** - POST /scan:
- Creates job record in RDS
- Invokes Step Functions state machine
- Returns job_id immediately (async pattern)

**`handle_get_job()`** - GET /jobs/{job_id}:
- Queries job status and progress
- Uses materialized view by default (fast, <50ms)
- Falls back to real-time query if `?real_time=true`
- Returns progress percentages and total findings

**`handle_get_results()`** - GET /results:
- Retrieves findings with pagination
- Supports filtering by job_id, bucket, key
- Uses cursor-based pagination for efficiency
- Returns masked findings with context

**Design Patterns:**
- Async job pattern (immediate response, background processing)
- Cached queries with real-time fallback
- Cursor-based pagination for large result sets
- Multi-threaded SQS enqueueing (20 workers)

#### 4. Lambda Refresh (`lambda_refresh/`)

**Purpose:** EventBridge-triggered Lambda to refresh materialized view

**Functionality:**
- Triggered every 1 minute by EventBridge cron
- Connects to RDS via RDS Proxy
- Executes: `REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;`
- Enables fast job status queries even with millions of objects

**Design Pattern:** Scheduled cache refresh pattern for expensive aggregations.

#### 5. Integration Tests (`integration_tests/`)

**Purpose:** End-to-end testing scripts for AWS deployment

**Key Scripts:**
- **`run_integration_test.sh`:** Main test runner
- **`upload_test_files.sh`:** Uploads test files to S3
- **`monitor_queue.sh`:** Monitors SQS queue depth
- **`monitor_scaling.sh`:** Monitors ECS auto-scaling
- **`measure_throughput.sh`:** Measures processing throughput
- **`generate_large_dataset.py`:** Generates large test datasets
- **`TESTING.md`:** Comprehensive testing guide

**Design Pattern:** Automated testing with monitoring and measurement tools.

### Code Quality and Testing

**Test Coverage:**
- **72 pytest tests** in `scanner/tests/`
- **Local testing:** All tests run without AWS infrastructure
- **Integration testing:** Full end-to-end tests with AWS deployment

**Code Organization:**
- Clear separation of concerns
- Modular design (utils, components, tests)
- Comprehensive error handling
- Detailed logging throughout

**Documentation:**
- README files in each component directory
- Inline code comments
- Architecture diagrams in main README
- Scaling analysis in SCALING.md
- Development guide in DEVELOPMENT.md

### Key Design Decisions

1. **Async Job Pattern:** API returns immediately, processing happens in background
2. **Step Functions:** Eliminates Lambda timeout limits for large listings
3. **Fair Queue:** Prevents noisy neighbor problems with MessageGroupId
4. **RDS Proxy:** Enables connection pooling for 1000+ concurrent workers
5. **Materialized Views:** 6000× faster queries with 1-minute refresh
6. **Multi-threading:** 20× faster SQS enqueueing and file processing
7. **Auto-scaling:** ECS scales based on SQS queue depth automatically

### Deployment Flow

1. **Infrastructure:** `terraform apply` creates all AWS resources
2. **Database:** `init_database.sh` creates schema and initializes tables
3. **Containers:** `build_and_push.sh` builds and pushes Docker images to ECR
4. **Testing:** `integration_tests/run_integration_test.sh` validates deployment

---

## Conclusion

The AWS S3 Sensitive Data Scanner demonstrates a production-ready, scalable architecture that can handle millions of objects efficiently. The system combines:

- **Asynchronous processing** to avoid timeout limits
- **Fair queueing** to prevent resource monopolization
- **Auto-scaling** to adapt to workload automatically
- **Connection pooling** to handle thousands of concurrent workers
- **Caching strategies** to enable fast queries at scale
- **Comprehensive testing** to ensure reliability

The codebase is well-organized, modular, and follows best practices for maintainability and scalability. Each component has a clear purpose and can be understood, tested, and modified independently.

For detailed deployment instructions, see `DEVELOPMENT.md`. For scaling analysis and capacity planning, see `SCALING.md`.

