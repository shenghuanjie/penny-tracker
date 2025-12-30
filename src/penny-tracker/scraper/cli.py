"""Command-line interface for Penny Tracker."""

import click
from datetime import datetime
from .database import Database
from .transactions import TransactionManager
from .reports import ReportGenerator
from .scraper.facebook_scraper import FacebookScraper


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Penny Tracker - Track your expenses and income."""
    pass


@main.command()
@click.option("--amount", "-a", type=float, required=True, help="Transaction amount")
@click.option("--category", "-c", required=True, help="Transaction category")
@click.option("--description", "-d", default="", help="Transaction description")
@click.option("--type", "-t", type=click.Choice(["expense", "income"]), default="expense")
def add(amount: float, category: str, description: str, type: str):
    """Add a new transaction."""
    db = Database()
    manager = TransactionManager(db)
    
    transaction = manager.add_transaction(
        amount=amount,
        category=category,
        description=description,
        transaction_type=type,
        date=datetime.now()
    )
    
    click.echo(f"✓ Added {type}: ${amount:.2f} in {category}")


@main.group()
def scrape():
    """Web scraping commands."""
    pass


@scrape.command()
@click.argument("url")
@click.option("--max-posts", "-n", default=10, help="Maximum posts to scrape")
@click.option("--headless/--no-headless", default=True, help="Run browser in headless mode")
@click.option("--login/--no-login", default=False, help="Login to Facebook (requires .env)")
def facebook(url: str, max_posts: int, headless: bool, login: bool):
    """
    Scrape data from a Facebook page or group.
    
    Example:
        penny-tracker scrape facebook https://facebook.com/somepage --max-posts 20
    
    WARNING: This is for educational purposes only.
    Automated scraping may violate Facebook's Terms of Service.
    """
    click.echo(f"🕷️  Starting Facebook scraper...")
    click.echo(f"URL: {url}")
    click.echo(f"Max posts: {max_posts}")
    click.echo(f"Headless: {headless}")
    
    try:
        with FacebookScraper(headless=headless) as scraper:
            if login:
                click.echo("Attempting to login...")
                scraper.login()
            
            click.echo("Scraping posts...")
            posts = scraper.scrape_page(url, max_posts=max_posts)
            
            click.echo(f"\n✓ Scraped {len(posts)} posts")
            
            for idx, post in enumerate(posts, 1):
                click.echo(f"\n--- Post {idx} ---")
                click.echo(f"Text: {post.get('text', 'N/A')[:100]}...")
                
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)


if __name__ == "__main__":
    main()
