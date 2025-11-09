Demo Narrative: AWS S3 Sensitive Data Scanner

Welcome to this demo of the AWS S3 Sensitive Data Scanner. 

The Problem We're Solving

Imagine you have hundreds of terabytes of data in S3, which can easily translate to millions of files. You need to scan them all for sensitive data. Our architecture handles this scale with asynchronous processing and orchestration.

The Architecture Flow

Let's start at the beginning. When a user wants to scan a bucket, they make a simple API call: POST to slash scan with a bucket name and optional prefix. This hits our API Gateway, which routes to a Lambda function.

Why use Lambda plus Step Functions? A single Lambda function has a 15-minute timeout limit and can only list about 300,000 objects before timing out. Based on our calculations in SCALING dot MD, listing 1 million objects takes 50 minutes, and 10 million objects takes 8 hours. A single Lambda invocation can't handle this scale, so we combine Lambda with Step Functions for orchestration.

The Lambda function uses an asynchronous pattern: instead of trying to list all the objects immediately—which would timeout for large buckets—it creates a job record in our PostgreSQL database and immediately returns a job ID to the user. The user gets an instant response, and the heavy lifting happens in the background.

The Lambda function starts an AWS Step Functions execution to orchestrate the S3 listing. Step Functions then invokes the same Lambda function repeatedly in a loop. Each Lambda invocation lists a batch of 10,000 S3 objects using continuation tokens, inserts them into the database, and enqueues them to SQS using 20 parallel workers. This multi-threaded enqueueing makes the process 20 times faster than sequential processing. Step Functions orchestrates the loop, checking if there are more objects and continuing until done. The Step Functions and Lambda architecture was designed to handle up to 50 million objects, with the orchestration pattern and batch processing carefully architected to achieve this scale. Step Functions can run a lot longer with much higher limitations, unlike a single Lambda invocation which has a 15-minute timeout.

The SQS queue is configured as a fair queue using MessageGroupId set to the bucket name. This is important because it prevents large jobs from monopolizing all the worker capacity. If you have a job with 10 million objects and another with just 100 objects, both get a fair share of processing resources. The queue also has retry logic—messages get three attempts before moving to a Dead Letter Queue for manual inspection.

Now we get to the workers. Our ECS Fargate service runs containerized workers that poll the SQS queue. Each worker long-polls for 20 seconds, receiving batches of up to 10 messages. The workers download S3 objects in parallel—we use 5 worker threads per task—and scan the content using regex-based detectors for patterns like SSNs, credit cards, and AWS keys. ECS tasks are designed to be fully stateless, which makes them very suitable for horizontal scaling and can scale up very well, even if there's complicated logic. ECS auto-scales based on SQS queue depth, and the current target is 100 messages per task, which can be further tuned based on real-world metrics.

The scanning happens in the scanner component, which filters files by type—supporting text, CSV, JSON, and log files—and size, with a 100-megabyte limit which is adjustable. When sensitive data is detected, the findings are written to our PostgreSQL database via RDS Proxy.

RDS Proxy manages connection pooling. Instead of each worker opening direct connections to RDS—which would exhaust connection limits—the proxy handles connection management. This allows us to scale to 50 or more ECS tasks, with thousands of concurrent workers, all efficiently sharing a pool of database connections.

The database stores three main things: job metadata in the jobs table, per-object status in the job_objects table, and detected findings in the findings table with deduplication. We use materialized views for fast job status queries. Instead of counting millions of rows—which could take 30 seconds—we maintain a cached view that refreshes every minute. This enables status queries to complete in under 50 milliseconds even with 100 million objects, representing a 6,000 times speed improvement. We also support real-time queries when needed with a parameter control, or when the cached view is not available. We've added composite database indexes making lookups 300 times faster. It's very rare that two workers work on the same S3 file—this only happens in a race condition where an SQS message gets polled by two workers, which is uncommon. We lock at the record level, so the chance of two workers locking each other when writing to the database is very low. This is why the database scales well even with many concurrent workers.

Codebase Structure

The codebase is available on GitHub.

Live Demo

Now let me show a live demo. I'll create a scanning job and show you the status of it. Notice that the status changed from listing to processing. Listing means the Step Functions and Lambda are enumerating the S3 directory and adding objects to the SQS queue. Now it's processing, which means the ECS tasks are processing messages from the SQS queue and fetching the S3 files to scan them.

ECS memory and maximum tasks were tuned to handle up to 100-megabyte files. If you need to handle bigger files, the task definition and memory need to be scaled accordingly.

Fast forward a little bit, and it has processed all the files. Now we can see the findings that were detected during the scan.

Manual testing scripts are available in github repo under integration-tests directory. 
