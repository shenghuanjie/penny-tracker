"""Base scraper class with common functionality."""

import os
import time
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.firefox import GeckoDriverManager
from fake_useragent import UserAgent
import random


class BaseScraper:
    """Base class for web scrapers."""
    
    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30,
        screenshot_dir: str = "data/screenshots",
        log_file: str = "logs/scraper.log"
    ):
        """Initialize the scraper."""
        self.headless = headless
        self.timeout = timeout
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self._setup_logging(log_file)
        
        # Initialize driver
        self.driver: Optional[webdriver.Firefox] = None
        self.wait: Optional[WebDriverWait] = None
    
    def _setup_logging(self, log_file: str):
        """Setup logging configuration."""
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def _create_driver(self) -> webdriver.Firefox:
        """Create and configure Firefox WebDriver."""
        options = FirefoxOptions()
        
        if self.headless:
            options.add_argument('--headless')
        
        # Anti-detection measures
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.set_preference('dom.webdriver.enabled', False)
        options.set_preference('useAutomationExtension', False)
        
        # Random user agent
        ua = UserAgent()
        options.set_preference('general.useragent.override', ua.random)
        
        # Other preferences
        options.set_preference('permissions.default.image', 2)  # Disable images for speed
        
        try:
            service = FirefoxService(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=service, options=options)
            driver.set_window_size(1920, 1080)
            
            self.logger.info("Firefox WebDriver created successfully")
            return driver
        except Exception as e:
            self.logger.error(f"Failed to create WebDriver: {e}")
            raise
    
    def start(self):
        """Start the scraper."""
        if self.driver is None:
            self.driver = self._create_driver()
            self.wait = WebDriverWait(self.driver, self.timeout)
            self.logger.info("Scraper started")
    
    def stop(self):
        """Stop the scraper and cleanup."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.wait = None
            self.logger.info("Scraper stopped")
    
    def take_screenshot(self, name: str = "screenshot"):
        """Take a screenshot."""
        if not self.driver:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.screenshot_dir / f"{name}_{timestamp}.png"
        
        try:
            self.driver.save_screenshot(str(filename))
            self.logger.info(f"Screenshot saved: {filename}")
            return str(filename)
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {e}")
            return None
    
    def random_delay(self, min_seconds: float = 2, max_seconds: float = 5):
        """Add random delay to avoid detection."""
        delay = random.uniform(min_seconds, max_seconds)
        self.logger.debug(f"Waiting {delay:.2f} seconds")
        time.sleep(delay)
    
    def scroll_page(self, scrolls: int = 3, delay: float = 2):
        """Scroll the page to load dynamic content."""
        if not self.driver:
            return
        
        for i in range(scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            self.logger.debug(f"Scroll {i+1}/{scrolls}")
            time.sleep(delay)
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
