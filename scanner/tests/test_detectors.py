#!/usr/bin/env python3
"""
Unit tests for the sensitive data detector using pytest.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from utils.detectors import Detector


@pytest.mark.unit
class TestSSNDetection:
    """Test suite for SSN pattern detection."""
    
    def test_valid_ssn_detected(self, detector, sample_ssn_content):
        """Should detect valid SSN in content."""
        findings = detector.detect(sample_ssn_content)
        ssn_findings = [f for f in findings if f['detector'] == 'ssn']
        
        assert len(ssn_findings) == 1
        assert ssn_findings[0]['masked_match'] == 'XXX-XX-6789'
    
    @pytest.mark.parametrize("content", [
        "My SSN is 123-45-6789",
        "SSN: 987-65-4321 for verification",
    ])
    def test_various_ssn_formats(self, detector, content):
        """Should detect SSN in various content formats."""
        findings = detector.detect(content)
        ssn_findings = [f for f in findings if f['detector'] == 'ssn']
        assert len(ssn_findings) >= 1
    
    @pytest.mark.parametrize("invalid_content", [
        "No SSN here",
        "Invalid: 12-345-6789",
    ])
    def test_invalid_ssn_ignored(self, detector, invalid_content):
        """Should not detect invalid SSN formats."""
        findings = detector.detect(invalid_content)
        ssn_findings = [f for f in findings if f['detector'] == 'ssn']
        assert len(ssn_findings) == 0


@pytest.mark.unit
class TestCreditCardDetection:
    """Test suite for credit card detection with Luhn validation."""
    
    def test_valid_visa_detected(self, detector):
        """Should detect valid Visa card number."""
        content = "Card: 4111-1111-1111-1111"
        findings = detector.detect(content)
        cc_findings = [f for f in findings if f['detector'] == 'credit_card']
        
        assert len(cc_findings) == 1
        assert cc_findings[0]['masked_match'] == '****-****-****-1111'
    
    @pytest.mark.parametrize("card_number", [
        "4111111111111111",
        "5555555555554444",
        "378282246310005",
    ])
    def test_valid_cards_detected(self, detector, card_number):
        """Should detect all valid card types."""
        content = f"Payment via {card_number}"
        findings = detector.detect(content)
        cc_findings = [f for f in findings if f['detector'] == 'credit_card']
        assert len(cc_findings) == 1
    
    @pytest.mark.parametrize("invalid_card", [
        "1234-5678-9012-3456",
        "123456",
    ])
    def test_invalid_cards_rejected(self, detector, invalid_card):
        """Should reject cards with invalid Luhn checksum."""
        content = f"Card: {invalid_card}"
        findings = detector.detect(content)
        cc_findings = [f for f in findings if f['detector'] == 'credit_card']
        assert len(cc_findings) == 0
    
    def test_luhn_validation_method(self, detector, valid_test_credit_cards):
        """Should validate credit cards using Luhn algorithm."""
        for card in valid_test_credit_cards:
            assert detector.validate_credit_card(card) is True


@pytest.mark.unit
class TestAWSKeyDetection:
    """Test suite for AWS access key detection."""
    
    def test_aws_access_key_detected(self, detector, sample_aws_keys_content):
        """Should detect AWS access key ID."""
        findings = detector.detect(sample_aws_keys_content)
        aws_findings = [f for f in findings if f['detector'] == 'aws_key']
        assert len(aws_findings) >= 1
    
    @pytest.mark.parametrize("content", [
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        "Key: AKIAI44QH8DHBEXAMPLE",
    ])
    def test_various_aws_key_formats(self, detector, content):
        """Should detect AWS keys in various formats."""
        findings = detector.detect(content)
        aws_findings = [f for f in findings if f['detector'] == 'aws_key']
        assert len(aws_findings) == 1


@pytest.mark.unit
class TestEmailDetection:
    """Test suite for email address detection."""
    
    @pytest.mark.parametrize("email", [
        "user@example.com",
        "john.doe+tag@company.co.uk",
    ])
    def test_valid_emails_detected(self, detector, email):
        """Should detect various valid email formats."""
        content = f"Contact: {email}"
        findings = detector.detect(content)
        email_findings = [f for f in findings if f['detector'] == 'email']
        assert len(email_findings) >= 1


@pytest.mark.unit
class TestPhoneDetection:
    """Test suite for US phone number detection."""
    
    @pytest.mark.parametrize("phone", [
        "(555) 123-4567",
        "555-123-4567",
        "5551234567",
    ])
    def test_valid_phones_detected(self, detector, phone):
        """Should detect various US phone formats."""
        content = f"Call: {phone}"
        findings = detector.detect(content)
        phone_findings = [f for f in findings if f['detector'] == 'phone_us']
        assert len(phone_findings) >= 1


@pytest.mark.unit
class TestMultiplePatterns:
    """Test suite for detecting multiple patterns in content."""
    
    def test_multiple_patterns_detected(self, detector, sample_mixed_content):
        """Should detect all pattern types in mixed content."""
        findings = detector.detect(sample_mixed_content)
        detector_types = {f['detector'] for f in findings}
        expected_types = {'ssn', 'email', 'phone_us', 'credit_card', 'aws_key'}
        
        assert expected_types.issubset(detector_types)
        assert len(findings) >= 5
    
    def test_findings_have_required_fields(self, detector, sample_mixed_content):
        """Should include all required fields in findings."""
        findings = detector.detect(sample_mixed_content)
        required_fields = {'detector', 'masked_match', 'context', 'byte_offset'}
        
        for finding in findings:
            assert required_fields.issubset(finding.keys())


@pytest.mark.unit
class TestContextExtraction:
    """Test suite for context extraction around matches."""
    
    def test_context_includes_surrounding_text(self, detector):
        """Should extract context around matches."""
        content = "Start of document. My SSN is 123-45-6789 for reference. End of document."
        findings = detector.detect(content, context_chars=20)
        
        assert len(findings) >= 1
        context = findings[0]['context']
        assert "My SSN is" in context
        assert "for reference" in context
    
    def test_max_matches_limit_enforced(self, detector):
        """Should limit number of matches per type."""
        content = "\n".join([f"SSN {i}: 123-45-{6789 + i}" for i in range(15)])
        findings = detector.detect(content, max_matches_per_type=10)
        ssn_findings = [f for f in findings if f['detector'] == 'ssn']
        
        assert len(ssn_findings) == 10


@pytest.mark.integration
class TestDetectorFileIntegration:
    """Integration tests with file operations."""
    
    def test_scan_file_from_disk(self, detector, temp_file, sample_ssn_content):
        """Should scan content from file."""
        with open(temp_file, 'w') as f:
            f.write(sample_ssn_content)
        
        with open(temp_file, 'r') as f:
            content = f.read()
        
        findings = detector.detect(content)
        assert len(findings) >= 1
        assert any(f['detector'] == 'ssn' for f in findings)
