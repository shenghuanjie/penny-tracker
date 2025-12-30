"""Utility functions for web scraping."""

import re
from typing import Optional
from datetime import datetime


def clean_text(text: str) -> str:
    """Clean and normalize text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove special characters
    text = text.strip()
    return text


def extract_number(text: str) -> Optional[int]:
    """Extract number from text (e.g., '1.5K' -> 1500)."""
    if not text:
        return None
    
    text = text.strip().upper()
    
    # Handle K (thousands) and M (millions)
    multiplier = 1
    if 'K' in text:
        multiplier = 1000
        text = text.replace('K', '')
    elif 'M' in text:
        multiplier = 1000000
        text = text.replace('M', '')
    
    try:
        number = float(re.sub(r'[^\d.]', '', text))
        return int(number * multiplier)
    except (ValueError, AttributeError):
        return None


def is_valid_facebook_url(url: str) -> bool:
    """Check if URL is a valid Facebook URL."""
    facebook_pattern = r'https?://(www\.)?facebook\.com/.+'
    return bool(re.match(facebook_pattern, url))
