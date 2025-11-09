"""
Lambda API handler for S3 Scanner.
Provides endpoints for triggering scans, checking job status, and retrieving results.
"""
import os
import json
import uuid
import logging
import boto3
from typing import Dict, Any, Optional, List
from datetime import datetime, date
from decimal import Decimal
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AWS clients
sqs_client = boto3.client('sqs', region_name=os.getenv('AWS_REGION', 'us-west-2'))
s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-west-2'))


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def get_db_connection():
    """Get database connection."""
    host = os.getenv("RDS_PROXY_ENDPOINT", "").split(":")[0]
    port = os.getenv("RDS_PORT", "5432")
    dbname = os.getenv("RDS_DBNAME", "scanner_db")
    user = os.getenv("RDS_USERNAME", "scanner_admin")
    password = os.getenv("RDS_PASSWORD", "")
    
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode='require'
    )


def create_response(status_code: int, body: Dict[str, Any], 
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Create API Gateway response."""
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
    }
    
    if headers:
        default_headers.update(headers)
    
    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": json.dumps(body, default=json_serial)
    }


def list_s3_objects(bucket: str, prefix: str = "", max_keys: int = 1000) -> list:
    """
    List S3 objects with prefix fan-out for scalability.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix
        max_keys: Maximum number of keys to return
        
    Returns:
        List of object dictionaries with bucket, key, etag
    """
    objects = []
    paginator = s3_client.get_paginator('list_objects_v2')
    
    try:
        page_iterator = paginator.paginate(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=1000  # S3 API limit per page
        )
        
        for page in page_iterator:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects.append({
                        'bucket': bucket,
                        'key': obj['Key'],
                        'etag': obj.get('ETag', '').strip('"'),
                        'size': obj.get('Size', 0)
                    })
                    
                    if len(objects) >= max_keys:
                        return objects
        
        return objects
    except ClientError as e:
        logger.error(f"Error listing S3 objects: {e}")
        raise


def prefix_fanout_list(bucket: str, prefix: str = "") -> list:
    """
    Use prefix fan-out to parallelize S3 listing.
    For very large buckets, this can be extended to use S3 Inventory.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix
        
    Returns:
        List of object dictionaries
    """
    # For now, use standard listing
    # In production, you might want to:
    # 1. Use S3 Inventory for very large buckets
    # 2. Use prefix fan-out (a-z, 0-9) for parallel listing
    # 3. Use S3 Batch Operations for massive scale
    
    # Limit to 200K objects (with parallel SQS, this fits in Lambda timeout)
    return list_s3_objects(bucket, prefix, max_keys=200000)


def send_sqs_batch(queue_url: str, batch_objects: List[Dict[str, Any]], 
                   job_id: str, batch_index: int) -> int:
    """
    Send a batch of objects to SQS.
    
    Args:
        queue_url: SQS queue URL
        batch_objects: List of objects to enqueue (max 10)
        job_id: Job ID
        batch_index: Index of this batch (for unique message IDs)
        
    Returns:
        Number of messages successfully sent
    """
    entries = [
        {
            'Id': f"{batch_index}-{j}",
            'MessageBody': json.dumps({
                'job_id': job_id,
                'bucket': obj['bucket'],
                'key': obj['key'],
                'etag': obj['etag']
            }),
            # Enable SQS Fair Queue feature by setting MessageGroupId to bucket name
            # This ensures fair processing across different S3 buckets (tenants)
            # Different buckets represent different teams/projects/applications
            # This prevents one large bucket from monopolizing processing capacity
            'MessageGroupId': obj['bucket']
        }
        for j, obj in enumerate(batch_objects)
    ]
    
    try:
        response = sqs_client.send_message_batch(
            QueueUrl=queue_url,
            Entries=entries
        )
        failed_count = len(response.get('Failed', []))
        success_count = len(entries) - failed_count
        
        if failed_count > 0:
            logger.warning(f"Batch {batch_index}: {failed_count} messages failed to send")
        
        return success_count
    except ClientError as e:
        logger.error(f"Error sending batch {batch_index} to SQS: {e}")
        return 0


def enqueue_objects_parallel(queue_url: str, job_id: str, objects: List[Dict[str, Any]]) -> int:
    """
    Enqueue objects to SQS in parallel.
    
    Args:
        queue_url: SQS queue URL
        job_id: Job ID
        objects: List of objects to enqueue
        
    Returns:
        Number of messages successfully sent
    """
    messages_sent = 0
    batch_size = 10  # SQS batch limit
    max_workers = 20
    
    # Split objects into batches
    batches = []
    for i in range(0, len(objects), batch_size):
        batch = objects[i:i + batch_size]
        batches.append((i // batch_size, batch))
    
    # Send batches in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(send_sqs_batch, queue_url, batch, job_id, batch_idx): batch_idx
            for batch_idx, batch in batches
        }
        
        for future in as_completed(future_to_batch):
            try:
                sent_count = future.result()
                messages_sent += sent_count
            except Exception as e:
                logger.error(f"Batch raised exception: {e}")
    
    return messages_sent


def list_and_process_batch(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process one batch of S3 objects (called by Step Functions).
    This function lists a batch of S3 objects, inserts them to DB, and enqueues to SQS.
    
    Args:
        event: {
            job_id: str,
            bucket: str,
            prefix: str,
            continuation_token: Optional[str],
            objects_processed: int
        }
        
    Returns:
        {
            job_id: str,
            bucket: str,
            prefix: str,
            continuation_token: Optional[str],
            objects_processed: int,
            batch_size: int,
            messages_enqueued: int,
            done: bool
        }
    """
    job_id = event['job_id']
    bucket = event['bucket']
    prefix = event.get('prefix', '')
    continuation_token = event.get('continuation_token')
    objects_processed = event.get('objects_processed', 0)
    
    batch_limit = 10000  # Process 10K objects per invocation
    queue_url = os.getenv("SQS_QUEUE_URL")
    
    if not queue_url:
        raise ValueError("SQS_QUEUE_URL environment variable not set")
    
    logger.info(f"Processing batch for job {job_id}, objects so far: {objects_processed}")
    
    # List S3 objects with pagination
    objects = []
    paginator = s3_client.get_paginator('list_objects_v2')
    
    pagination_config = {
        'MaxItems': batch_limit,
        'PageSize': 1000
    }
    
    params = {
        'Bucket': bucket,
        'Prefix': prefix
    }
    
    if continuation_token:
        params['ContinuationToken'] = continuation_token
    
    try:
        page_iterator = paginator.paginate(**params, PaginationConfig=pagination_config)
        
        next_token = None
        for page in page_iterator:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects.append({
                        'bucket': bucket,
                        'key': obj['Key'],
                        'etag': obj.get('ETag', '').strip('"'),
                        'size': obj.get('Size', 0)
                    })
            
            # Check for more results
            if page.get('IsTruncated', False):
                next_token = page.get('NextContinuationToken')
        
        logger.info(f"Listed {len(objects)} objects, has more: {bool(next_token)}")
        
    except ClientError as e:
        logger.error(f"Error listing S3 objects: {e}")
        raise
    
    # Insert objects to database
    if objects:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                insert_query = """
                    INSERT INTO job_objects (job_id, bucket, key, etag, status, updated_at)
                    VALUES (%s, %s, %s, %s, 'queued', NOW())
                    ON CONFLICT DO NOTHING
                """
                values = [(job_id, obj['bucket'], obj['key'], obj['etag']) for obj in objects]
                
                from psycopg2.extras import execute_batch
                execute_batch(cur, insert_query, values, page_size=1000)
            conn.commit()
            logger.info(f"Inserted {len(objects)} objects to database")
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error inserting objects to DB: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    # Enqueue to SQS in parallel
    messages_sent = 0
    if objects:
        messages_sent = enqueue_objects_parallel(queue_url, job_id, objects)
        logger.info(f"Enqueued {messages_sent}/{len(objects)} messages to SQS")
    
    # Return state for Step Functions
    return {
        'job_id': job_id,
        'bucket': bucket,
        'prefix': prefix,
        'continuation_token': next_token,
        'objects_processed': objects_processed + len(objects),
        'batch_size': len(objects),
        'messages_enqueued': messages_sent,
        'done': next_token is None
    }


def create_scan_job_async(bucket: str, prefix: str = "") -> Dict[str, Any]:
    """
    Create a new scan job and start Step Function for async processing.
    This supports unlimited objects using continuation tokens.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix (optional)
        
    Returns:
        Job information dictionary
    """
    job_id = str(uuid.uuid4())
    step_function_arn = os.getenv("STEP_FUNCTION_ARN")
    
    if not step_function_arn:
        # Fallback to synchronous processing if Step Function not configured
        logger.warning("STEP_FUNCTION_ARN not set, falling back to synchronous processing")
        return create_scan_job_sync(bucket, prefix)
    
    # Start Step Function execution first to get execution ARN
    try:
        stepfunctions_client = boto3.client('stepfunctions', region_name=os.getenv('AWS_REGION', 'us-west-2'))
        execution_response = stepfunctions_client.start_execution(
            stateMachineArn=step_function_arn,
            name=f"scan-{job_id}",
            input=json.dumps({
                'job_id': job_id,
                'bucket': bucket,
                'prefix': prefix,
                'continuation_token': None,
                'objects_processed': 0
            })
        )
        
        execution_arn = execution_response['executionArn']
        logger.info(f"Started Step Function execution: {execution_arn}")
    except Exception as e:
        logger.error(f"Error starting Step Function: {e}")
        raise
    
    # Create job record in database with execution ARN
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO jobs (job_id, bucket, prefix, execution_arn, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (job_id, bucket, prefix, execution_arn))
        conn.commit()
        logger.info(f"Created job {job_id} for s3://{bucket}/{prefix}")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error creating job: {e}")
        # Job record creation failed, but Step Function is already running
        # This is okay - the job will still process, just harder to track
        logger.warning(f"Step Function {execution_arn} is running but job record creation failed")
    finally:
        if conn:
            conn.close()
    
    return {
        "job_id": job_id,
        "bucket": bucket,
        "prefix": prefix,
        "status": "listing",
        "execution_arn": execution_arn,
        "message": "Job created. Objects are being listed and enqueued asynchronously.",
        "async": True
    }


def create_scan_job_sync(bucket: str, prefix: str = "") -> Dict[str, Any]:
    """
    Create a new scan job and enqueue S3 objects synchronously.
    Limited to ~200K objects due to Lambda timeout.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix (optional)
        
    Returns:
        Job information dictionary
    """
    job_id = str(uuid.uuid4())
    queue_url = os.getenv("SQS_QUEUE_URL")
    
    if not queue_url:
        raise ValueError("SQS_QUEUE_URL environment variable not set")
    
    # List S3 objects
    logger.info(f"Listing objects in s3://{bucket}/{prefix}")
    objects = prefix_fanout_list(bucket, prefix)
    logger.info(f"Found {len(objects)} objects")
    
    # Create job record in database
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Insert job (job_id is UUID)
            cur.execute("""
                INSERT INTO jobs (job_id, bucket, prefix, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (job_id, bucket, prefix))
            
            # Insert job objects
            if objects:
                insert_query = """
                    INSERT INTO job_objects (job_id, bucket, key, etag, status, updated_at)
                    VALUES (%s, %s, %s, %s, 'queued', NOW())
                """
                values = [(job_id, obj['bucket'], obj['key'], obj['etag']) for obj in objects]
                
                from psycopg2.extras import execute_batch
                execute_batch(cur, insert_query, values, page_size=1000)
            
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error creating job: {e}")
        raise
    finally:
        if conn:
            conn.close()
    
    # Enqueue messages to SQS (parallelized for better performance)
    messages_sent = 0
    batch_size = 10  # SQS batch limit (AWS maximum)
    max_workers = 20  # Number of parallel threads
    
    # Split objects into batches of 10 (SQS limit)
    batches = []
    for i in range(0, len(objects), batch_size):
        batch = objects[i:i + batch_size]
        batches.append((i // batch_size, batch))
    
    logger.info(f"Enqueueing {len(objects)} objects in {len(batches)} batches using {max_workers} workers")
    
    # Send batches in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all batches
        future_to_batch = {
            executor.submit(send_sqs_batch, queue_url, batch, job_id, batch_idx): batch_idx
            for batch_idx, batch in batches
        }
        
        # Collect results
        for future in as_completed(future_to_batch):
            batch_idx = future_to_batch[future]
            try:
                sent_count = future.result()
                messages_sent += sent_count
            except Exception as e:
                logger.error(f"Batch {batch_idx} raised an exception: {e}")
    
    logger.info(f"Created job {job_id} with {messages_sent}/{len(objects)} messages enqueued")
    
    return {
        "job_id": job_id,
        "bucket": bucket,
        "prefix": prefix,
        "total_objects": len(objects),
        "messages_enqueued": messages_sent,
        "status": "queued"
    }


def get_step_function_status(execution_arn: str) -> Optional[Dict[str, Any]]:
    """
    Get Step Functions execution status by ARN.
    
    Args:
        execution_arn: Step Functions execution ARN
        
    Returns:
        Dict with execution status or None if error
    """
    if not execution_arn:
        return None
    
    try:
        stepfunctions_client = boto3.client('stepfunctions', region_name=os.getenv('AWS_REGION', 'us-west-2'))
        
        # Describe execution to get current status
        response = stepfunctions_client.describe_execution(
            executionArn=execution_arn
        )
        
        return {
            'execution_arn': response['executionArn'],
            'status': response['status'],
            'start_date': response['startDate'],
            'stop_date': response.get('stopDate')
        }
    except Exception as e:
        logger.warning(f"Error describing Step Functions execution: {e}")
        return None


def get_job_status(job_id: str, real_time: bool = False) -> Dict[str, Any]:
    """
    Get status of a scan job, including Step Functions execution status.
    
    Args:
        job_id: Job ID
        real_time: If True, fetch real-time data (slower). If False, use cached data (faster, default)
        
    Returns:
        Job status dictionary with 'cache_timestamp' if cached data is used
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check if materialized view exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_matviews 
                    WHERE schemaname = 'public' 
                    AND matviewname = 'job_progress'
                ) as exists;
            """)
            result = cur.fetchone()
            has_matview = result['exists'] if result else False
            
            # Decide whether to use cached or real-time data
            use_cache = has_matview and not real_time
            
            if use_cache:
                # Get last refresh time from tracking table (if it exists)
                cache_timestamp = None
                refresh_duration_ms = None
                try:
                    cur.execute("""
                        SELECT last_refreshed_at, refresh_duration_ms
                        FROM materialized_view_refresh_log
                        WHERE view_name = 'job_progress';
                    """)
                    refresh_info = cur.fetchone()
                    if refresh_info:
                        cache_timestamp = refresh_info['last_refreshed_at']
                        refresh_duration_ms = refresh_info['refresh_duration_ms']
                except Exception as e:
                    # Tracking table might not exist (old migration version)
                    logger.warning(f"Could not query refresh log (table may not exist): {e}")
                    # Continue without timestamp - still use cached data
                
                # Use materialized view (cached, very fast)
                cur.execute("""
                    SELECT 
                        job_id, bucket, prefix, execution_arn, 
                        created_at, updated_at,
                        total_objects as total,
                        queued_count as queued,
                        processing_count as processing,
                        succeeded_count as succeeded,
                        failed_count as failed,
                        total_findings,
                        progress_percent
                    FROM job_progress
                    WHERE job_id = %s
                """, (job_id,))
                
                result = cur.fetchone()
                
                if result:
                    result = dict(result)
                    result['data_source'] = 'cached'
                    result['cache_refreshed_at'] = cache_timestamp
                    if refresh_duration_ms:
                        result['cache_refresh_duration_ms'] = refresh_duration_ms
                else:
                    # Job not in materialized view yet (very recent job)
                    # Fall back to real-time query
                    use_cache = False
            
            if not use_cache:
                # Fall back to direct queries (slower but always up-to-date)
                cur.execute("""
                    SELECT job_id, bucket, prefix, execution_arn, created_at, updated_at
                    FROM jobs
                    WHERE job_id = %s
                """, (job_id,))
                
                job = cur.fetchone()
                
                if not job:
                    return None
                
                # Get job statistics
                cur.execute("""
                    SELECT 
                        COUNT(*) FILTER (WHERE status = 'queued') as queued,
                        COUNT(*) FILTER (WHERE status = 'processing') as processing,
                        COUNT(*) FILTER (WHERE status = 'succeeded') as succeeded,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed,
                        COUNT(*) as total
                    FROM job_objects
                    WHERE job_id = %s
                """, (job_id,))
                
                stats = cur.fetchone()
                
                # Get total findings count
                cur.execute("""
                    SELECT COUNT(*) as total_findings
                    FROM findings
                    WHERE job_id = %s
                """, (job_id,))
                
                findings_result = cur.fetchone()
                
                result = dict(job)
                result.update(dict(stats) if stats else {})
                result['total_findings'] = findings_result['total_findings'] if findings_result else 0
                result['data_source'] = 'real_time'
                
                # Calculate progress percentage
                total = result.get('total', 0)
                completed = (result.get('succeeded', 0) or 0) + (result.get('failed', 0) or 0)
                result['progress_percent'] = (completed / total * 100) if total > 0 else 0
            
            # Check Step Functions execution status using ARN from database
            execution_arn = result.get('execution_arn')
            sf_status = get_step_function_status(execution_arn) if execution_arn else None
            
            if sf_status:
                result['step_function_status'] = sf_status['status']
                result['execution_arn'] = sf_status.get('execution_arn')
                
                # Determine overall job status based on Step Functions
                if sf_status['status'] == 'RUNNING':
                    result['status'] = 'listing'
                    result['status_message'] = 'Step Functions is listing S3 objects'
                elif sf_status['status'] == 'SUCCEEDED':
                    # Step Functions completed, now check processing status
                    total = result.get('total', 0)
                    completed = (result.get('succeeded', 0) or 0) + (result.get('failed', 0) or 0)
                    
                    if total == 0:
                        result['status'] = 'completed'
                        result['status_message'] = 'No objects found to scan'
                    elif completed >= total:
                        result['status'] = 'completed'
                        result['status_message'] = 'All objects scanned'
                    else:
                        result['status'] = 'processing'
                        result['status_message'] = f'Scanning objects ({completed}/{total})'
                elif sf_status['status'] == 'FAILED':
                    result['status'] = 'failed'
                    result['status_message'] = 'Step Functions execution failed'
                elif sf_status['status'] == 'TIMED_OUT':
                    result['status'] = 'failed'
                    result['status_message'] = 'Step Functions execution timed out'
                elif sf_status['status'] == 'ABORTED':
                    result['status'] = 'aborted'
                    result['status_message'] = 'Step Functions execution was aborted'
            else:
                # No Step Functions (sync mode or Step Functions completed long ago)
                total = result.get('total', 0)
                completed = (result.get('succeeded', 0) or 0) + (result.get('failed', 0) or 0)
                
                if total == 0:
                    result['status'] = 'completed'
                    result['status_message'] = 'No objects found to scan'
                elif completed >= total:
                    result['status'] = 'completed'
                    result['status_message'] = 'All objects scanned'
                else:
                    result['status'] = 'processing'
                    result['status_message'] = f'Scanning objects ({completed}/{total})'
            
            # Calculate progress percentage if not already present (from materialized view)
            if 'progress_percent' not in result or result['progress_percent'] is None:
                total = result.get('total', 0)
                completed = (result.get('succeeded', 0) or 0) + (result.get('failed', 0) or 0)
                result['progress_percent'] = (completed / total * 100) if total > 0 else 0
            
            return result
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise
    finally:
        if conn:
            conn.close()


def get_results(job_id: Optional[str] = None, bucket: Optional[str] = None,
                key: Optional[str] = None, limit: int = 100,
                cursor: Optional[str] = None, offset: Optional[int] = None) -> Dict[str, Any]:
    """
    Retrieve scan results with pagination (supports both cursor and offset).
    
    Args:
        job_id: Optional job ID filter
        bucket: Optional bucket filter
        key: Optional key filter
        limit: Maximum number of results
        cursor: Cursor for pagination (ID of last item from previous page)
        offset: Offset for pagination (fallback if cursor not provided)
        
    Returns:
        Results dictionary with findings and pagination info
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = []
            params = []
            
            if job_id:
                conditions.append("job_id = %s")
                params.append(job_id)
            
            if bucket:
                conditions.append("bucket = %s")
                params.append(bucket)
            
            if key:
                # Support prefix filtering (if key ends with /, treat as prefix)
                if key.endswith('/'):
                    conditions.append("key LIKE %s")
                    params.append(key + "%")
                else:
                    # Exact match or prefix match
                    conditions.append("key LIKE %s")
                    params.append(key + "%")
            
            # Cursor-based pagination (more efficient for large datasets)
            if cursor:
                try:
                    cursor_id = int(cursor)
                    conditions.append("id < %s")
                    params.append(cursor_id)
                except ValueError:
                    # Invalid cursor, ignore it
                    pass
            
            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)
            
            # Get total count
            count_query = f"SELECT COUNT(*) as total FROM findings {where_clause}"
            cur.execute(count_query, params)
            total = cur.fetchone()['total']
            
            # Get findings with cursor-based pagination
            if cursor:
                query = f"""
                    SELECT 
                        id, job_id, bucket, key, detector,
                        masked_match, context, byte_offset, created_at
                    FROM findings
                    {where_clause}
                    ORDER BY id DESC
                    LIMIT %s
                """
                params.append(limit)
            else:
                # Fallback to offset-based pagination
                offset_val = offset if offset is not None else 0
                query = f"""
                    SELECT 
                        id, job_id, bucket, key, detector,
                        masked_match, context, byte_offset, created_at
                    FROM findings
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([limit, offset_val])
            
            cur.execute(query, params)
            findings = [dict(row) for row in cur.fetchall()]
            
            # Generate next cursor (ID of last item)
            next_cursor = None
            if findings:
                next_cursor = str(findings[-1]['id'])
            
            result = {
                "findings": findings,
                "total": total,
                "limit": limit,
                "has_more": len(findings) == limit
            }
            
            if cursor:
                result["cursor"] = cursor
                if next_cursor:
                    result["next_cursor"] = next_cursor
            else:
                offset_val = offset if offset is not None else 0
                result["offset"] = offset_val
                result["has_more"] = (offset_val + limit) < total
            
            return result
    except Exception as e:
        logger.error(f"Error getting results: {e}")
        raise
    finally:
        if conn:
            conn.close()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for API Gateway requests and Step Functions.
    
    Args:
        event: API Gateway event or Step Functions event
        context: Lambda context
        
    Returns:
        API Gateway response or Step Functions result
    """
    try:
        # Check if this is a Step Functions invocation (batch processing)
        if 'job_id' in event and 'bucket' in event:
            # Called by Step Functions for batch processing
            logger.info(f"Processing batch for job {event['job_id']}")
            return list_and_process_batch(event, context)
        
        # Otherwise, it's an API Gateway request
        # Parse request
        http_method = event.get('requestContext', {}).get('http', {}).get('method', '')
        path = event.get('rawPath', '')
        query_params = event.get('queryStringParameters') or {}
        body_str = event.get('body', '{}')
        
        # Parse body if present
        body = {}
        if body_str:
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError:
                pass
        
        logger.info(f"Request: {http_method} {path}")
        
        # Route requests
        if http_method == 'POST' and path == '/scan':
            # Create scan job (async with Step Functions)
            bucket = body.get('bucket')
            prefix = body.get('prefix', '')
            
            if not bucket:
                return create_response(400, {"error": "bucket is required"})
            
            try:
                result = create_scan_job_async(bucket, prefix)
                return create_response(200, result)
            except Exception as e:
                logger.error(f"Error creating scan job: {type(e).__name__}: {e}", exc_info=True)
                error_message = str(e) if str(e) else f"{type(e).__name__} occurred"
                return create_response(500, {"error": error_message})
        
        elif http_method == 'GET' and path.startswith('/jobs/'):
            # Get job status
            job_id = path.split('/')[-1]
            
            # Parse real_time parameter (defaults to False for cached results)
            real_time_param = query_params.get('real_time', 'false').lower()
            real_time = real_time_param in ['true', '1', 'yes']
            
            try:
                result = get_job_status(job_id, real_time=real_time)
                if not result:
                    return create_response(404, {"error": "Job not found"})
                return create_response(200, result)
            except Exception as e:
                logger.error(f"Error getting job status for {job_id}: {type(e).__name__}: {e}", exc_info=True)
                error_message = str(e) if str(e) else f"{type(e).__name__} occurred"
                return create_response(500, {"error": error_message})
        
        elif http_method == 'GET' and path == '/results':
            # Get results (supports bucket, prefix via key filter, limit, cursor)
            job_id = query_params.get('job_id')
            bucket = query_params.get('bucket')
            key = query_params.get('key')  # Can be used as prefix filter
            limit = int(query_params.get('limit', 100))
            cursor = query_params.get('cursor')
            offset = query_params.get('offset')
            offset_int = int(offset) if offset else None
            
            try:
                result = get_results(job_id, bucket, key, limit, cursor, offset_int)
                return create_response(200, result)
            except Exception as e:
                logger.error(f"Error getting results: {type(e).__name__}: {e}", exc_info=True)
                error_message = str(e) if str(e) else f"{type(e).__name__} occurred"
                return create_response(500, {"error": error_message})
        
        elif http_method == 'OPTIONS':
            # CORS preflight
            return create_response(200, {})
        
        else:
            return create_response(404, {"error": "Not found"})
    
    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        return create_response(500, {"error": "Internal server error"})


# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "rawPath": "/scan",
        "body": json.dumps({
            "bucket": "test-bucket",
            "prefix": "test/"
        })
    }
    
    result = handler(test_event, None)
    print(json.dumps(result, indent=2))

