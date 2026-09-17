# Penny Tracker

Collect Home Depot deal candidates, maintain a short in-store hunt list, and
optionally add recent posts from the Home Depot One Cent Facebook group.

## Setup

```bash
make install
conda activate penny-tracker
```

If shell activation is unavailable, prefix commands with
`conda run -n penny-tracker`, for example:

```bash
conda run -n penny-tracker python rebelsavings.py -m report
```

The Conda environment includes Tesseract, which `fb_scraper.py` uses to read
SKUs and UPCs from Facebook post images.

## Daily Run

```bash
./run.sh
```

The default run collects RebelSavings and Facebook data in parallel, checks
eligible Home Depot candidates for up to eight hours with no item-count cap,
regenerates `index.html`, and publishes the results using the repository's
existing Git workflow. It does not retry previously blocked requests unless
explicitly requested.

Useful controls:

```bash
./run.sh --sequential
./run.sh --no-facebook
./run.sh --max-hd-checks 50 --hours 2
./run.sh --skip1
./run.sh --retry-blocked
```

By default, the RebelSavings and Facebook collectors run concurrently. The
pipeline waits for both and then builds the combined report. Each collector
receives an isolated temporary Chrome profile so they cannot lock or redirect
one another's browser session. Facebook still loads `fb_cookies.json`; on the
default unattended run, a missing or expired cookie fails quickly instead of
waiting for input. After RebelSavings finishes, the pipeline retries Facebook
once with the existing Chrome profile so it can reuse an active login. Use
`--sequential` when debugging browser behavior.

The Home Depot verification pass starts after both collectors finish. It uses
one reused tab, direct product URLs, and at least one minute between item starts.
The eight-hour window is a hard deadline; unchecked items remain queued for the
next run. A Home Depot challenge or block page stops the pass immediately.

Lower `--max-hd-checks` when Home Depot begins returning verification pages.
The checker retains unprocessed candidates for a later run.

## In-Store View

The first tab in `index.html` is **Store Trip**. It contains at most 60 of the
newest confirmed `PENNY_NEW` and `PENNY` items; out-of-stock, old, blocked, and
unverified rows stay in **All Deals**. Store Trip supports name/SKU search,
department and status filters, and checkboxes saved in the browser.

## Facebook Group

The integrated **Facebook Group** tab refreshes during the default pipeline:

```bash
./run.sh
```

For a Facebook-only refresh followed by report generation:

```bash
python fb_scraper.py --max-posts 30 --max-days 7
python rebelsavings.py -m report
```

The first Facebook run opens Chrome for login and saves session cookies to
`fb_cookies.json`. The scraper keeps posts with extracted SKUs, UPCs, or Home
Depot links, as well as image-only posts for manual review. Images are cached
under `fb_images/` so they remain visible after Facebook CDN links expire.
Each report row links back to the original group post.

The Facebook tab is always visible. Before the first successful collection it
shows zero posts; afterward it provides text search plus filters for posts with
SKUs, UPCs, images, or missing identifiers that need manual review.
