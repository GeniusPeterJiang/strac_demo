"""
Main entry point for the S3 scanner worker.
Consumes messages from SQS and processes S3 objects.
"""
import os
import sys
import json
import logging
import signal
import time
from typing import List, Dict, Optional
import boto3
from botocore.exceptions import ClientError

from batch_processor import BatchProcessor
from utils.db import Database
from utils.detectors import Detector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables for graceful shutdown
shutdown_flag = False
sqs_client = None
queue_url = None
batch_processor = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_flag
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag = True


def init_components():
    """Initialize SQS client and batch processor."""
    global sqs_client, queue_url, batch_processor
    
    # Get configuration from environment
    queue_url = os.getenv("SQS_QUEUE_URL")
    if not queue_url:
        raise ValueError("SQS_QUEUE_URL environment variable not set")
    
    aws_region = os.getenv("AWS_REGION", "us-west-2")
    
    # Initialize SQS client
    sqs_client = boto3.client('sqs', region_name=aws_region)
    
    # Initialize batch processor
    batch_size = int(os.getenv("BATCH_SIZE", "40"))
    max_workers = int(os.getenv("MAX_WORKERS", "20"))
    max_file_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    
    db = Database()
    detector = Detector()
    batch_processor = BatchProcessor(
        db=db,
        detector=detector,
        max_workers=max_workers,
        max_file_size_mb=max_file_size_mb
    )
    
    logger.info(f"Initialized scanner worker")
    logger.info(f"  Queue URL: {queue_url}")
    logger.info(f"  Batch size: {batch_size}")
    logger.info(f"  Max workers: {max_workers}")
    logger.info(f"  Max file size: {max_file_size_mb}MB")


def receive_messages(max_messages: int = 10, wait_time: int = 20) -> List[Dict]:
    """
    Receive messages from SQS queue.
    
    Args:
        max_messages: Maximum number of messages to receive
        wait_time: Long polling wait time in seconds
        
    Returns:
        List of message dictionaries
    """
    try:
        response = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=min(max_messages, 10),  # SQS limit
            WaitTimeSeconds=wait_time,
            AttributeNames=['All'],
            MessageAttributeNames=['All']
        )
        
        messages = response.get('Messages', [])
        if messages:
            logger.info(f"Received {len(messages)} messages from queue")
        
        return messages
    except Exception as e:
        logger.error(f"Error receiving messages: {e}")
        return []


def delete_messages(messages: List[Dict]) -> bool:
    """
    Delete processed messages from SQS queue.
    
    Args:
        messages: List of message dictionaries with ReceiptHandle
        
    Returns:
        True if successful
    """
    if not messages:
        return True
    
    try:
        entries = [
            {
                'Id': str(i),
                'ReceiptHandle': msg.get('ReceiptHandle')
            }
            for i, msg in enumerate(messages)
            if msg.get('ReceiptHandle')
        ]
        
        if not entries:
            return True
        
        response = sqs_client.delete_message_batch(
            QueueUrl=queue_url,
            Entries=entries
        )
        
        failed = response.get('Failed', [])
        if failed:
            logger.warning(f"Failed to delete {len(failed)} messages")
            return False
        
        logger.info(f"Deleted {len(entries)} messages from queue")
        return True
    except Exception as e:
        logger.error(f"Error deleting messages: {e}")
        return False


def process_messages(messages: List[Dict]) -> List[Dict]:
    """
    Process a batch of messages.
    
    Args:
        messages: List of SQS message dictionaries
        
    Returns:
        List of processing results
    """
    if not messages:
        return []
    
    logger.info(f"Processing {len(messages)} messages...")
    
    # Process batch
    results = batch_processor.process_batch(messages)
    
    # Log summary
    succeeded = sum(1 for r in results if r.get("status") == "succeeded")
    failed = sum(1 for r in results if r.get("status") == "failed")
    total_findings = sum(r.get("findings_count", 0) for r in results)
    
    logger.info(
        f"Batch complete: {succeeded} succeeded, {failed} failed, "
        f"{total_findings} total findings"
    )
    
    return results


def main_loop():
    """Main processing loop."""
    global shutdown_flag
    
    logger.info("Starting scanner worker main loop...")
    
    batch_size = int(os.getenv("BATCH_SIZE", "40"))
    poll_wait_time = 20  # Long polling
    
    consecutive_empty_polls = 0
    max_empty_polls = 3  # Exit after 3 empty polls (for testing, remove in production)
    
    while not shutdown_flag:
        try:
            # Receive messages
            messages = receive_messages(max_messages=batch_size, wait_time=poll_wait_time)
            
            if not messages:
                consecutive_empty_polls += 1
                if consecutive_empty_polls >= max_empty_polls:
                    logger.info("No messages received, continuing to poll...")
                    consecutive_empty_polls = 0  # Reset counter, keep running
                continue
            
            consecutive_empty_polls = 0
            
            # Process messages
            results = process_messages(messages)
            
            # Delete successfully processed messages
            # Only delete messages that succeeded or failed (not retrying)
            messages_to_delete = [
                msg for msg, result in zip(messages, results)
                if result.get("status") in ["succeeded", "failed", "skipped"]
            ]
            
            if messages_to_delete:
                delete_messages(messages_to_delete)
            
            # Small delay to avoid tight loop
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            shutdown_flag = True
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(5)  # Wait before retrying
    
    logger.info("Scanner worker shutting down...")


def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize components
        init_components()
        
        # Run main loop
        main_loop()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        if batch_processor and batch_processor.db:
            batch_processor.db.close()
        logger.info("Scanner worker exited")


if __name__ == "__main__":
    main()

