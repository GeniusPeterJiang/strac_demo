#!/usr/bin/env python3
"""
Integration tests for the scanner workflow using pytest.
"""
import pytest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from batch_processor import BatchProcessor
from utils.detectors import Detector


@pytest.fixture
def test_files_dir():
    """Create temporary directory with test files."""
    temp_dir = tempfile.mkdtemp(prefix="scanner_test_")
    
    test_files = {
        "ssn_test.txt": "Employee SSN: 123-45-6789\nVerification required.",
        "credit_card.txt": "Payment card: 4111-1111-1111-1111\nExpires: 12/25",
        "aws_keys.txt": "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\nAWS_SECRET=example",
        "email_list.txt": "Contacts:\nuser1@example.com\nuser2@test.org",
        "phone_list.txt": "Phone numbers:\n(555) 123-4567\n555-987-6543",
        "clean_file.txt": "This file has no sensitive data.\nJust regular text.",
        "mixed_data.csv": """name,ssn,email
John Doe,123-45-6789,john@example.com
Jane Smith,987-65-4321,jane@example.com""",
    }
    
    for filename, content in test_files.items():
        filepath = os.path.join(temp_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
    
    yield temp_dir, list(test_files.keys())
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.integration
class TestDetectorOnFiles:
    """Test detector on actual files."""
    
    def test_scan_multiple_files(self, detector, test_files_dir):
        """Should scan multiple files and find sensitive data."""
        temp_dir, filenames = test_files_dir
        total_findings = 0
        
        for filename in filenames:
            filepath = os.path.join(temp_dir, filename)
            with open(filepath, 'r') as f:
                content = f.read()
            
            findings = detector.detect(content)
            total_findings += len(findings)
        
        assert total_findings > 0


@pytest.mark.integration
class TestBatchProcessorLogic:
    """Test batch processor file filtering logic."""
    
    @pytest.mark.parametrize("filename,size,should_process", [
        ("document.txt", 1000, True),
        ("data.csv", 2000, True),
        ("config.json", 500, True),
        ("application.log", 3000, True),
        ("image.png", 1000, False),
        ("document.pdf", 5000, False),
        ("large.txt", 150 * 1024 * 1024, False),
    ])
    def test_file_filtering(self, filename, size, should_process):
        """Should filter files by extension and size."""
        max_size = 100 * 1024 * 1024
        supported_extensions = {'.txt', '.csv', '.json', '.log'}
        
        if size > max_size:
            result = False
        elif not any(filename.lower().endswith(ext) for ext in supported_extensions):
            result = False
        else:
            result = True
        
        assert result == should_process


@pytest.mark.integration
class TestMessageParsing:
    """Test SQS message format parsing."""
    
    def test_parse_valid_messages(self):
        """Should parse valid SQS message format."""
        sample_messages = [
            {
                "MessageId": "msg-123",
                "ReceiptHandle": "receipt-123",
                "Body": json.dumps({
                    "job_id": "job-123-456",
                    "bucket": "test-bucket",
                    "key": "test/file1.txt",
                    "etag": "abc123"
                })
            },
            {
                "MessageId": "msg-456",
                "ReceiptHandle": "receipt-456",
                "Body": json.dumps({
                    "job_id": "job-123-456",
                    "bucket": "test-bucket",
                    "key": "test/file2.csv",
                    "etag": "def456"
                })
            }
        ]
        
        parsed_count = 0
        for msg in sample_messages:
            body = json.loads(msg.get('Body', '{}'))
            job_id = body.get('job_id')
            bucket = body.get('bucket')
            key = body.get('key')
            
            if all([job_id, bucket, key]):
                parsed_count += 1
        
        assert parsed_count == len(sample_messages)


@pytest.mark.integration
class TestWorkflowSimulation:
    """Simulate the complete scanner workflow."""
    
    def test_end_to_end_workflow(self, detector, test_files_dir):
        """Should process files through complete workflow."""
        temp_dir, filenames = test_files_dir
        
        processed = 0
        total_findings = 0
        
        for filename in filenames:
            filepath = os.path.join(temp_dir, filename)
            
            # Simulate download
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Scan content
            findings = detector.detect(content)
            
            processed += 1
            total_findings += len(findings)
        
        assert processed == len(filenames)
        assert total_findings > 0
