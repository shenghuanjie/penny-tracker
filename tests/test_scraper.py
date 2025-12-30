"""Tests for web scraping functionality."""

import pytest
from penny_tracker.scraper.base_scraper import BaseScraper
from penny_tracker.scraper.utils import clean_text, extract_number, is_valid_facebook_url


def test_clean_text():
    """Test text cleaning."""
    assert clean_text("  Hello   World  ") == "Hello World"
    assert clean_text("Line1\n\nLine2") == "Line1 Line2"


def test_extract_number():
    """Test number extraction."""
    assert extract_number("1.5K") == 1500
    assert extract_number("2M") == 2000000
    assert extract_number("500") == 500
    assert extract_number("invalid") is None


def test_is_valid_facebook_url():
    """Test Facebook URL validation."""
    assert is_valid_facebook_url("https://www.facebook.com/somepage")
    assert is_valid_facebook_url("https://facebook.com/groups/123")
    assert not is_valid_facebook_url("https://twitter.com/user")
    assert not is_valid_facebook_url("invalid")


@pytest.fixture
def scraper():
    """Create a scraper instance for testing."""
    return BaseScraper(headless=True, timeout=10)


def test_scraper_initialization(scraper):
    """Test scraper initialization."""
    assert scraper.headless is True
    assert scraper.timeout == 10
    assert scraper.driver is None


def test_scraper_context_manager():
    """Test scraper as context manager."""
    with BaseScraper(headless=True) as scraper:
        assert scraper.driver is not None
    # Driver should be closed after context
