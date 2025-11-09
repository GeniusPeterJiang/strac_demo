#!/usr/bin/env python3
"""
Unit tests for batch processor using pytest.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from batch_processor import BatchProcessor
from utils.detectors import Detector
from utils.db import Database


@pytest.fixture
def mock_db():
    """Mock database instance."""
    db = Mock(spec=Database)
    db.insert_findings.return_value = 1
    db.update_job_object_status.return_value = True
    return db


@pytest.fixture
def mock_detector():
    """Mock detector instance."""
    detector = Mock(spec=Detector)
    detector.detect.return_value = [
        {
            'detector': 'ssn',
            'masked_match': 'XXX-XX-6789',
            'context': 'My SSN is...',
            'byte_offset': 10
        }
    ]
    return detector


@pytest.fixture
def mock_s3_client():
    """Mock boto3 S3 client."""
    client = Mock()
    
    # Mock head_object response
    client.head_object.return_value = {
        'ContentType': 'text/plain',
        'ContentLength': 100
    }
    
    # Mock get_object response
    mock_body = Mock()
    mock_body.read.return_value = b'Test content with SSN: 123-45-6789'
    client.get_object.return_value = {
        'Body': mock_body
    }
    
    return client


@pytest.mark.unit
class TestBatchProcessorInitialization:
    """Test batch processor initialization."""
    
    def test_init_with_defaults(self, mock_db, mock_detector):
        """Should initialize with default parameters."""
        with patch('batch_processor.boto3.client') as mock_boto_client:
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            assert processor.max_workers == 20
            assert processor.max_file_size_mb == 100
            assert processor.max_file_size_bytes == 100 * 1024 * 1024
            mock_boto_client.assert_called_once()
    
    def test_init_with_custom_params(self, mock_db, mock_detector):
        """Should initialize with custom parameters."""
        with patch('batch_processor.boto3.client'):
            processor = BatchProcessor(
                db=mock_db,
                detector=mock_detector,
                max_workers=10,
                max_file_size_mb=50
            )
            
            assert processor.max_workers == 10
            assert processor.max_file_size_mb == 50
            assert processor.max_file_size_bytes == 50 * 1024 * 1024
    
    def test_text_extensions_configured(self, mock_db, mock_detector):
        """Should have correct text file extensions."""
        with patch('batch_processor.boto3.client'):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            expected_extensions = {'.txt', '.csv', '.json', '.log'}
            assert processor.text_extensions == expected_extensions


@pytest.mark.unit
class TestShouldProcessFile:
    """Test file filtering logic."""
    
    @pytest.mark.parametrize("key,size,expected", [
        ("document.txt", 1000, True),
        ("data.csv", 2000, True),
        ("config.json", 500, True),
        ("application.log", 3000, True),
        ("Document.TXT", 1000, True),  # Case insensitive
        ("image.png", 1000, False),
        ("document.pdf", 5000, False),
        ("archive.zip", 2000, False),
    ])
    def test_file_extension_filtering(self, mock_db, mock_detector, key, size, expected):
        """Should filter files by extension."""
        with patch('batch_processor.boto3.client'):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            result = processor.should_process_file(key, size)
            assert result == expected
    
    def test_file_size_limit(self, mock_db, mock_detector):
        """Should reject files larger than max size."""
        with patch('batch_processor.boto3.client'):
            processor = BatchProcessor(
                db=mock_db,
                detector=mock_detector,
                max_file_size_mb=1
            )
            
            # 1 MB file should pass
            assert processor.should_process_file("test.txt", 1024 * 1024) is True
            
            # 2 MB file should fail
            assert processor.should_process_file("test.txt", 2 * 1024 * 1024) is False
            
            # Exactly at limit should pass
            assert processor.should_process_file("test.txt", 1024 * 1024) is True


@pytest.mark.unit
class TestDownloadAndScan:
    """Test download and scan functionality."""
    
    def test_download_and_scan_success(self, mock_db, mock_detector, mock_s3_client):
        """Should download, scan, and store findings."""
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            result = processor.download_and_scan(
                bucket='test-bucket',
                key='test/file.txt',
                job_id='job-123',
                etag='abc123'
            )
            
            assert result['status'] == 'succeeded'
            assert result['findings_count'] >= 0
            
            # Verify S3 operations called
            mock_s3_client.head_object.assert_called_once_with(
                Bucket='test-bucket',
                Key='test/file.txt'
            )
            mock_s3_client.get_object.assert_called_once_with(
                Bucket='test-bucket',
                Key='test/file.txt'
            )
            
            # Verify detector called
            mock_detector.detect.assert_called_once()
            
            # Verify database operations
            mock_db.update_job_object_status.assert_called()
    
    def test_skips_unsupported_file_types(self, mock_db, mock_detector, mock_s3_client):
        """Should skip files with unsupported extensions."""
        mock_s3_client.head_object.return_value = {
            'ContentType': 'image/png',
            'ContentLength': 1000
        }
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            result = processor.download_and_scan(
                bucket='test-bucket',
                key='image.png',
                job_id='job-123',
                etag='abc123'
            )
            
            assert result['status'] == 'skipped'
            assert result['findings_count'] == 0
            
            # Should not download or scan
            mock_s3_client.get_object.assert_not_called()
            mock_detector.detect.assert_not_called()
    
    def test_handles_download_error(self, mock_db, mock_detector, mock_s3_client):
        """Should handle S3 download errors."""
        mock_s3_client.get_object.side_effect = Exception('S3 Error')
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            result = processor.download_and_scan(
                bucket='test-bucket',
                key='test/file.txt',
                job_id='job-123',
                etag='abc123'
            )
            
            assert result['status'] == 'failed'
            assert 'error' in result
            
            # Should update status to failed
            mock_db.update_job_object_status.assert_called_with(
                'job-123', 'test-bucket', 'test/file.txt', 'failed', 'abc123', 'S3 Error'
            )
    
    def test_handles_unicode_decode_error(self, mock_db, mock_detector, mock_s3_client):
        """Should handle files that cannot be decoded."""
        mock_body = Mock()
        mock_body.read.return_value = b'\x80\x81\x82\x83'  # Invalid UTF-8
        mock_s3_client.get_object.return_value = {'Body': mock_body}
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            result = processor.download_and_scan(
                bucket='test-bucket',
                key='test/file.txt',
                job_id='job-123',
                etag='abc123'
            )
            
            # Should try UTF-8, then latin-1, and if both fail, mark as skipped
            # Latin-1 will succeed (it accepts all byte values), so this will be processed
            assert result['status'] in ['succeeded', 'skipped']
    
    def test_inserts_findings_when_detected(self, mock_db, mock_detector, mock_s3_client):
        """Should insert findings when sensitive data detected."""
        mock_detector.detect.return_value = [
            {'detector': 'ssn', 'masked_match': 'XXX-XX-6789', 
             'context': 'SSN: 123-45-6789', 'byte_offset': 0},
            {'detector': 'email', 'masked_match': '***MASKED***',
             'context': 'Email: user@test.com', 'byte_offset': 20}
        ]
        mock_db.insert_findings.return_value = 2
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            
            result = processor.download_and_scan(
                bucket='test-bucket',
                key='test/file.txt',
                job_id='job-123',
                etag='abc123'
            )
            
            assert result['findings_count'] == 2
            mock_db.insert_findings.assert_called_once()
            
            # Verify findings passed to DB
            call_args = mock_db.insert_findings.call_args[0]
            assert len(call_args[0]) == 2  # 2 findings


@pytest.mark.unit
class TestProcessBatch:
    """Test batch processing of messages."""
    
    def test_process_batch_success(self, mock_db, mock_detector, mock_s3_client):
        """Should process multiple messages in batch."""
        messages = [
            {
                'MessageId': 'msg-1',
                'ReceiptHandle': 'receipt-1',
                'Body': '{"job_id": "job-123", "bucket": "test-bucket", "key": "file1.txt", "etag": "etag1"}'
            },
            {
                'MessageId': 'msg-2',
                'ReceiptHandle': 'receipt-2',
                'Body': '{"job_id": "job-123", "bucket": "test-bucket", "key": "file2.txt", "etag": "etag2"}'
            }
        ]
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector, max_workers=2)
            results = processor.process_batch(messages)
            
            assert len(results) == 2
            assert all('status' in r for r in results)
    
    def test_process_batch_skips_invalid_messages(self, mock_db, mock_detector, mock_s3_client):
        """Should skip messages with invalid format."""
        messages = [
            {
                'MessageId': 'msg-1',
                'ReceiptHandle': 'receipt-1',
                'Body': '{"job_id": "job-123", "bucket": "test-bucket"}'  # Missing key
            },
            {
                'MessageId': 'msg-2',
                'ReceiptHandle': 'receipt-2',
                'Body': 'invalid json'
            }
        ]
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            results = processor.process_batch(messages)
            
            # Should skip both invalid messages
            assert len(results) == 0
    
    def test_process_batch_with_mixed_results(self, mock_db, mock_detector, mock_s3_client):
        """Should handle mix of successful and failed processing."""
        messages = [
            {
                'MessageId': 'msg-1',
                'ReceiptHandle': 'receipt-1',
                'Body': '{"job_id": "job-123", "bucket": "test-bucket", "key": "good.txt", "etag": "etag1"}'
            },
            {
                'MessageId': 'msg-2',
                'ReceiptHandle': 'receipt-2',
                'Body': '{"job_id": "job-123", "bucket": "test-bucket", "key": "bad.txt", "etag": "etag2"}'
            }
        ]
        
        # Make second file fail
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception('S3 Error')
            return {'Body': Mock(read=lambda: b'content')}
        
        mock_s3_client.get_object.side_effect = side_effect
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            results = processor.process_batch(messages)
            
            # Should have results for both
            assert len(results) == 2
            statuses = [r['status'] for r in results]
            assert 'succeeded' in statuses or 'skipped' in statuses
            assert 'failed' in statuses


@pytest.mark.integration
class TestBatchProcessorIntegration:
    """Integration tests for batch processor."""
    
    def test_end_to_end_processing(self, mock_db, mock_detector, mock_s3_client):
        """Should process message end-to-end."""
        message = {
            'MessageId': 'msg-1',
            'ReceiptHandle': 'receipt-1',
            'Body': '{"job_id": "job-123", "bucket": "test-bucket", "key": "test.txt", "etag": "abc123"}'
        }
        
        with patch('batch_processor.boto3.client', return_value=mock_s3_client):
            processor = BatchProcessor(db=mock_db, detector=mock_detector)
            results = processor.process_batch([message])
            
            assert len(results) == 1
            result = results[0]
            
            # Check all operations completed
            assert 'status' in result
            assert 'bucket' in result
            assert 'key' in result
            assert 'findings_count' in result

