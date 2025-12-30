.PHONY: help install install-dev install-scraping test lint format clean run scrape

help:
	@echo "Penny Tracker - Available Commands"
	@echo "  make install          - Install production dependencies"
	@echo "  make install-dev      - Install development dependencies"
	@echo "  make install-scraping - Install with scraping support"
	@echo "  make test             - Run tests"
	@echo "  make lint             - Run linters"
	@echo "  make format           - Format code"
	@echo "  make clean            - Remove build artifacts"
	@echo "  make run              - Run the application"
	@echo "  make scrape           - Run scraper demo"

install:
	conda env create -f environment.yml
	@echo "Environment created! Activate with: conda activate penny-tracker"

install-dev:
	conda env create -f environment-dev.yml
	conda run -n penny-tracker-dev pre-commit install
	@echo "Dev environment created! Activate with: conda activate penny-tracker-dev"

install-scraping:
	conda activate penny-tracker && pip install -r requirements-scraping.txt
	@echo "Scraping dependencies installed!"

test:
	pytest -v

lint:
	ruff check src/ tests/
	black --check src/ tests/

format:
	black src/ tests/
	ruff check --fix src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info
	rm -rf .pytest_cache/ .coverage htmlcov/
	rm -rf data/screenshots/*.png
	rm -rf logs/*.log
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run:
	python -m penny_tracker.cli

scrape:
	penny-tracker scrape facebook "https://facebook.com/example" --max-posts 5 --no-login
