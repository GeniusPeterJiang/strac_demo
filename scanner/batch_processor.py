"""
Batch processor for handling multiple S3 objects efficiently.
"""
import os
import boto3
import logging
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError
import time

from utils.detectors import Detector
from utils.db import Database

logger = logging.getLogger(__name__)


class BatchProcessor:
    """Processes batches of S3 objects for sensitive data scanning."""
    
    def __init__(self, db: Optional[Database] = None, detector: Optional[Detector] = None,
                 max_workers: int = 20, max_file_size_mb: int = 100):
        """
        Initialize batch processor.
        
        Args:
            db: Database instance
            detector: Detector instance
            max_workers: Maximum number of concurrent workers
            max_file_size_mb: Maximum file size to process in MB
        """
        self.db = db or Database()
        self.detector = detector or Detector()
        self.max_workers = max_workers
        self.max_file_size_mb = max_file_size_mb
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        
        # Initialize S3 client
        self.s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-west-2'))
        
        # Supported text file extensions (per requirements: .txt, .csv, .json, .log)
        self.text_extensions = {
            '.txt', '.csv', '.json', '.log'
        }
    
    def should_process_file(self, key: str, size: int) -> bool:
        """
        Determine if a file should be processed.
        Only processes .txt, .csv, .json, .log files per requirements.
        
        Args:
            key: S3 object key
            size: File size in bytes
            
        Returns:
            True if file should be processed
        """
        # Skip if file is too large
        if size > self.max_file_size_bytes:
            logger.warning(f"Skipping {key}: file too large ({size} bytes)")
            return False
        
        # Check if it's a supported text file extension
        key_lower = key.lower()
        if any(key_lower.endswith(ext) for ext in self.text_extensions):
            return True
        
        # Skip files without supported extensions
        logger.debug(f"Skipping {key}: unsupported file extension (only .txt, .csv, .json, .log supported)")
        return False
    
    def download_and_scan(self, bucket: str, key: str, job_id: str, etag: str) -> Dict:
        """
        Download and scan a single S3 object.
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            job_id: Job ID
            etag: Object ETag for deduplication
            
        Returns:
            Dictionary with processing results
        """
        try:
            # Update status to processing
            self.db.update_job_object_status(job_id, bucket, key, "processing", etag, None)
            
            # Get object metadata
            try:
                head_response = self.s3_client.head_object(Bucket=bucket, Key=key)
                content_type = head_response.get('ContentType', '')
                size = head_response.get('ContentLength', 0)
            except ClientError as e:
                logger.error(f"Failed to get metadata for {bucket}/{key}: {e}")
                raise
            
            # Check if we should process this file
            if not self.should_process_file(key, size):
                self.db.update_job_object_status(
                    job_id, bucket, key, "succeeded", etag, None
                )
                return {
                    "bucket": bucket,
                    "key": key,
                    "status": "skipped",
                    "findings_count": 0
                }
            
            # Download object
            try:
                response = self.s3_client.get_object(Bucket=bucket, Key=key)
                content = response['Body'].read()
            except ClientError as e:
                logger.error(f"Failed to download {bucket}/{key}: {e}")
                raise
            
            # Decode content (try UTF-8, fallback to latin-1)
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content.decode('latin-1')
                except UnicodeDecodeError:
                    logger.warning(f"Could not decode {bucket}/{key}, skipping")
                    self.db.update_job_object_status(
                        job_id, bucket, key, "succeeded", etag, "Could not decode file"
                    )
                    return {
                        "bucket": bucket,
                        "key": key,
                        "status": "skipped",
                        "findings_count": 0,
                        "error": "Could not decode file"
                    }
            
            # Detect sensitive data
            findings = self.detector.detect(text_content)
            
            # Insert findings into database
            findings_count = 0
            if findings:
                findings_count = self.db.insert_findings(
                    findings, job_id, bucket, key, etag
                )
            
            # Update status to succeeded
            self.db.update_job_object_status(
                job_id, bucket, key, "succeeded", etag, None
            )
            
            logger.info(
                f"Processed {bucket}/{key}: {findings_count} findings"
            )
            
            return {
                "bucket": bucket,
                "key": key,
                "status": "succeeded",
                "findings_count": findings_count
            }
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error processing {bucket}/{key}: {error_message}")
            
            # Update status to failed
            self.db.update_job_object_status(
                job_id, bucket, key, "failed", etag, error_message
            )
            
            return {
                "bucket": bucket,
                "key": key,
                "status": "failed",
                "error": error_message,
                "findings_count": 0
            }
    
    def process_batch(self, messages: List[Dict]) -> List[Dict]:
        """
        Process a batch of SQS messages.
        
        Args:
            messages: List of SQS message dictionaries with body containing
                     JSON with job_id, bucket, key, etag
                     
        Returns:
            List of processing results
        """
        import json
        
        results = []
        
        # Parse messages and extract job info
        tasks = []
        for message in messages:
            try:
                body = json.loads(message.get('Body', '{}'))
                job_id = body.get('job_id')
                bucket = body.get('bucket')
                key = body.get('key')
                etag = body.get('etag', '')
                
                if not all([job_id, bucket, key]):
                    logger.warning(f"Invalid message: {message}")
                    continue
                
                tasks.append({
                    "job_id": job_id,
                    "bucket": bucket,
                    "key": key,
                    "etag": etag,
                    "message": message
                })
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message: {e}")
                continue
        
        # Process tasks with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(
                    self.download_and_scan,
                    task["bucket"],
                    task["key"],
                    task["job_id"],
                    task["etag"]
                ): task
                for task in tasks
            }
            
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    result["message_receipt_handle"] = task["message"].get("ReceiptHandle")
                    results.append(result)
                except Exception as e:
                    logger.error(f"Task failed: {e}")
                    results.append({
                        "bucket": task["bucket"],
                        "key": task["key"],
                        "status": "failed",
                        "error": str(e),
                        "message_receipt_handle": task["message"].get("ReceiptHandle")
                    })
        
        return results

