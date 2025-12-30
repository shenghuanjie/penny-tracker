"""Facebook scraper implementation."""

import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper


class FacebookScraper(BaseScraper):
    """Scraper for Facebook pages and groups."""
    
    def __init__(self, **kwargs):
        """Initialize Facebook scraper."""
        super().__init__(**kwargs)
        load_dotenv()
        
        self.email = os.getenv('FB_EMAIL')
        self.password = os.getenv('FB_PASSWORD')
        self.base_url = "https://www.facebook.com"
    
    def login(self) -> bool:
        """
        Login to Facebook.
        
        IMPORTANT: This is for educational purposes only.
        Automated login may violate Facebook's Terms of Service.
        """
        if not self.email or not self.password:
            self.logger.warning("No credentials provided, skipping login")
            return False
        
        try:
            self.logger.info("Attempting to login to Facebook")
            self.driver.get(self.base_url)
            self.random_delay(2, 4)
            
            # Find and fill email
            email_field = self.wait.until(
                lambda d: d.find_element(By.ID, "email")
            )
            email_field.send_keys(self.email)
            self.random_delay(0.5, 1.5)
            
            # Find and fill password
            password_field = self.driver.find_element(By.ID, "pass")
            password_field.send_keys(self.password)
            self.random_delay(0.5, 1.5)
            
            # Submit
            password_field.send_keys(Keys.RETURN)
            self.random_delay(3, 5)
            
            # Check if login was successful
            if "login" not in self.driver.current_url.lower():
                self.logger.info("Login successful")
                self.take_screenshot("login_success")
                return True
            else:
                self.logger.error("Login failed")
                self.take_screenshot("login_failed")
                return False
                
        except Exception as e:
            self.logger.error(f"Login error: {e}")
            self.take_screenshot("login_error")
            return False
    
    def scrape_page(self, page_url: str, max_posts: int = 10) -> List[Dict[str, Any]]:
        """
        Scrape posts from a Facebook page.
        
        Note: This is a basic implementation for educational purposes.
        Facebook actively blocks scrapers and this may not work reliably.
        
        Args:
            page_url: URL of the Facebook page
            max_posts: Maximum number of posts to scrape
        
        Returns:
            List of post data dictionaries
        """
        if not self.driver:
            self.start()
        
        posts = []
        
        try:
            self.logger.info(f"Navigating to: {page_url}")
            self.driver.get(page_url)
            self.random_delay(3, 5)
            
            # Take screenshot of the page
            self.take_screenshot("page_loaded")
            
            # Scroll to load more posts
            self.logger.info("Scrolling to load content")
            self.scroll_page(scrolls=5, delay=2)
            
            # Get page source and parse with BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'lxml')
            
            # Find post containers (selectors may need updating)
            post_elements = soup.find_all('div', attrs={'role': 'article'})
            self.logger.info(f"Found {len(post_elements)} potential posts")
            
            for idx, post_elem in enumerate(post_elements[:max_posts]):
                try:
                    post_data = self._extract_post_data(post_elem)
                    if post_data:
                        posts.append(post_data)
                        self.logger.info(f"Extracted post {idx + 1}")
                except Exception as e:
                    self.logger.warning(f"Failed to extract post {idx + 1}: {e}")
                    continue
            
            self.logger.info(f"Successfully scraped {len(posts)} posts")
            return posts
            
        except TimeoutException:
            self.logger.error("Timeout while loading page")
            self.take_screenshot("timeout_error")
            return posts
        except Exception as e:
            self.logger.error(f"Scraping error: {e}")
            self.take_screenshot("scraping_error")
            return posts
    
    def _extract_post_data(self, post_element) -> Optional[Dict[str, Any]]:
        """
        Extract data from a post element.
        
        Note: Facebook's HTML structure changes frequently.
        These selectors are examples and will likely need updating.
        """
        try:
            # Extract text content
            text_elements = post_element.find_all('div', attrs={'dir': 'auto'})
            text = ' '.join([elem.get_text(strip=True) for elem in text_elements])
            
            if not text:
                return None
            
            post_data = {
                'text': text,
                'timestamp': None,  # Would need proper selector
                'author': None,     # Would need proper selector
                'likes': None,      # Would need proper selector
                'comments': None,   # Would need proper selector
                'shares': None,     # Would need proper selector
            }
            
            return post_data
            
        except Exception as e:
            self.logger.debug(f"Error extracting post data: {e}")
            return None
    
    def scrape_group(self, group_url: str, max_posts: int = 10) -> List[Dict[str, Any]]:
        """
        Scrape posts from a Facebook group.
        
        Note: Requires login and group membership.
        This is for educational purposes only.
        """
        # Login first if credentials are provided
        if self.email and self.password:
            logged_in = self.login()
            if not logged_in:
                self.logger.error("Failed to login, cannot access group")
                return []
        
        # Scrape the group (similar to page scraping)
        return self.scrape_page(group_url, max_posts)
