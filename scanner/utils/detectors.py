"""
Sensitive data pattern detectors using regex patterns.
"""
import re
from typing import Dict, List, Tuple, Optional

# Pattern definitions for sensitive data detection
PATTERNS = {
    "ssn": {
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "description": "Social Security Number (XXX-XX-XXXX)"
    },
    "credit_card": {
        "pattern": r"\b(?:\d[ -]*?){13,16}\b",
        "description": "Credit Card Number (13-16 digits)"
    },
    "aws_key": {
        "pattern": r"AKIA[0-9A-Z]{16}",
        "description": "AWS Access Key ID"
    },
    "aws_secret": {
        "pattern": r"aws_secret_access_key\s*=\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?",
        "description": "AWS Secret Access Key"
    },
    "email": {
        "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "description": "Email Address"
    },
    "phone_us": {
        "pattern": r"\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}",
        "description": "US Phone Number"
    }
}


class Detector:
    """Detector class for finding sensitive data patterns in text."""
    
    def __init__(self, patterns: Optional[Dict] = None):
        """
        Initialize detector with patterns.
        
        Args:
            patterns: Optional custom patterns dict. Uses default PATTERNS if None.
        """
        self.patterns = patterns or PATTERNS
        self.compiled_patterns = {
            name: re.compile(pattern["pattern"], re.IGNORECASE | re.MULTILINE)
            for name, pattern in self.patterns.items()
        }
    
    def detect(self, content: str, max_matches_per_type: int = 10, context_chars: int = 50) -> List[Dict]:
        """
        Detect sensitive data patterns in content.
        
        Args:
            content: Text content to scan
            max_matches_per_type: Maximum number of matches to return per pattern type
            context_chars: Number of characters before/after match to include as context
            
        Returns:
            List of findings with detector, masked_match, context, and byte_offset
        """
        findings = []
        
        for pattern_name, compiled_pattern in self.compiled_patterns.items():
            matches = compiled_pattern.finditer(content)
            count = 0
            
            for match in matches:
                if count >= max_matches_per_type:
                    break
                
                # Additional validation for credit cards using Luhn algorithm
                if pattern_name == "credit_card":
                    digits = re.sub(r'[^\d]', '', match.group(0))
                    if len(digits) < 13 or len(digits) > 16:
                        continue
                    # Validate using Luhn algorithm
                    if not self._luhn_check(digits):
                        continue
                
                # Extract context around the match
                start_pos = max(0, match.start() - context_chars)
                end_pos = min(len(content), match.end() + context_chars)
                context = content[start_pos:end_pos]
                
                # Mask the sensitive data in the match
                matched_text = match.group(0)
                if pattern_name == "ssn":
                    masked = "XXX-XX-" + matched_text[-4:] if len(matched_text) >= 4 else "XXX-XX-XXXX"
                elif pattern_name == "credit_card":
                    masked = "****-****-****-" + matched_text[-4:] if len(matched_text) >= 4 else "****-****-****-****"
                elif pattern_name == "aws_key":
                    masked = matched_text[:4] + "..." + matched_text[-4:] if len(matched_text) > 8 else "AKIA****"
                else:
                    masked = "***MASKED***"
                
                finding = {
                    "detector": pattern_name,
                    "masked_match": masked,
                    "context": context,
                    "byte_offset": match.start()
                }
                
                findings.append(finding)
                count += 1
        
        return findings
    
    def detect_in_file(self, file_path: str, encoding: str = "utf-8", 
                      max_size_mb: int = 100) -> List[Dict]:
        """
        Detect sensitive data in a file.
        
        Args:
            file_path: Path to file (local or S3)
            encoding: File encoding
            max_size_mb: Maximum file size to process in MB
            
        Returns:
            List of findings
        """
        # This is a placeholder - actual implementation will read from S3
        # For now, assume content is passed as string
        raise NotImplementedError("Use detect() method with file content")
    
    def validate_ssn(self, ssn: str) -> bool:
        """
        Validate SSN format (basic check).
        
        Args:
            ssn: SSN string to validate
            
        Returns:
            True if valid format
        """
        pattern = re.compile(r"^\d{3}-\d{2}-\d{4}$")
        return bool(pattern.match(ssn))
    
    def _luhn_check(self, card_number: str) -> bool:
        """
        Validate credit card number using Luhn algorithm.
        
        Args:
            card_number: Credit card number as string of digits
            
        Returns:
            True if valid Luhn checksum
        """
        def luhn_sum(n):
            return sum(int(d) if i % 2 == 0 else sum(divmod(int(d) * 2, 10))
                      for i, d in enumerate(reversed(n)))
        
        return len(card_number) >= 13 and luhn_sum(card_number) % 10 == 0
    
    def validate_credit_card(self, card: str) -> bool:
        """
        Validate credit card using Luhn algorithm.
        
        Args:
            card: Credit card string to validate
            
        Returns:
            True if valid format and Luhn checksum
        """
        digits = re.sub(r'[^\d]', '', card)
        if not (13 <= len(digits) <= 16):
            return False
        return self._luhn_check(digits)


def get_detector() -> Detector:
    """Factory function to get a configured detector instance."""
    return Detector()

