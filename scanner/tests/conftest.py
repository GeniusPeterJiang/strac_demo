"""
Shared pytest fixtures and configuration for scanner tests.

This module provides reusable test fixtures that can be used across all test files.
"""
import pytest
import tempfile
import os
from typing import Generator
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from utils.detectors import Detector


# ============================================================================
# Detector Fixtures
# ============================================================================

@pytest.fixture
def detector() -> Detector:
    """
    Provide a Detector instance for tests.
    
    Returns:
        Detector: Configured detector instance
    """
    return Detector()


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_ssn_content() -> str:
    """Provide sample content containing an SSN."""
    return "Employee SSN: 123-45-6789\nVerification required."


@pytest.fixture
def sample_credit_card_content() -> str:
    """Provide sample content containing a credit card."""
    return "Payment card: 4111-1111-1111-1111\nExpires: 12/25"


@pytest.fixture
def sample_aws_keys_content() -> str:
    """Provide sample content containing AWS keys."""
    return (
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    )


@pytest.fixture
def sample_mixed_content() -> str:
    """Provide sample content with multiple sensitive data types."""
    return """
Customer Information:
Name: John Doe
SSN: 123-45-6789
Email: john.doe@example.com
Phone: (555) 123-4567
Credit Card: 4111-1111-1111-1111
AWS Key: AKIAIOSFODNN7EXAMPLE
"""


@pytest.fixture
def valid_test_credit_cards() -> list:
    """
    Provide list of valid test credit card numbers.
    
    These are standard test card numbers with valid Luhn checksums.
    """
    return [
        "4111111111111111",  # Visa
        "5555555555554444",  # Mastercard
        "378282246310005",   # American Express
    ]


# ============================================================================
# File System Fixtures
# ============================================================================

@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """
    Provide a temporary directory for test files.
    
    The directory is automatically cleaned up after the test.
    
    Yields:
        str: Path to temporary directory
    """
    with tempfile.TemporaryDirectory(prefix="scanner_test_") as tmpdir:
        yield tmpdir


@pytest.fixture
def temp_file(temp_dir: str) -> Generator[str, None, None]:
    """
    Provide a temporary file path.
    
    Args:
        temp_dir: Temporary directory fixture
        
    Yields:
        str: Path to temporary file
    """
    file_path = os.path.join(temp_dir, "test_file.txt")
    yield file_path
    # Cleanup handled by temp_dir fixture


# ============================================================================
# Mock Fixtures (for future use with pytest-mock)
# ============================================================================

# Uncomment when pytest-mock is installed:
#
# @pytest.fixture
# def mock_s3_client(mocker):
#     """Mock boto3 S3 client."""
#     mock = mocker.Mock()
#     mock.get_object.return_value = {
#         'Body': mocker.Mock(read=lambda: b'test content')
#     }
#     mock.head_object.return_value = {
#         'ContentLength': 100,
#         'ContentType': 'text/plain'
#     }
#     return mock
#
# @pytest.fixture
# def mock_db(mocker):
#     """Mock database connection."""
#     from utils.db import Database
#     mock = mocker.Mock(spec=Database)
#     mock.insert_findings.return_value = 1
#     mock.update_job_object_status.return_value = True
#     return mock


# ============================================================================
# Configuration Hooks
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Tests that take longer than 1 second")
    config.addinivalue_line("markers", "requires_aws: Tests requiring AWS credentials")

