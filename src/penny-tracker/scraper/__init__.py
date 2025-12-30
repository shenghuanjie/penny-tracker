"""Web scraping module for Penny Tracker."""

from .base_scraper import BaseScraper
from .facebook_scraper import FacebookScraper

__all__ = ["BaseScraper", "FacebookScraper"]
