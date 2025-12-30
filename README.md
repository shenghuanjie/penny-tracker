# Quick Start

## Prerequisites
Install Miniforge following the installation guide.

## Usage Examples
#### Setup Environment

```
##### Create environment with scraping support
make install

##### Activate environment
conda activate penny-tracker

##### Setup credentials (optional, for authenticated scraping)
cp config/.env.example .env
##### Edit .env with your credentials

```

### Scraping Commands

```
##### Scrape a public Facebook page (no login)
penny-tracker scrape facebook https://facebook.com/publicpage --max-posts 20

##### Scrape with browser visible (for debugging)
penny-tracker scrape facebook https://facebook.com/page --no-headless

##### Scrape with login (requires credentials in .env)
penny-tracker scrape facebook https://facebook.com/groups/123 --login --max-posts 10

```

### Python API
```
from penny_tracker.scraper import FacebookScraper

#### Use as context manager
with FacebookScraper(headless=True) as scraper:
    posts = scraper.scrape_page(
        "https://facebook.com/somepage",
        max_posts=10
    )
    
    for post in posts:
        print(post['text'])

```
