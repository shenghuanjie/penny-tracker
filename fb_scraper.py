import argparse
import datetime
import json
import logging
import os
import re
import random
import sys
import time

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ── Constants ──────────────────────────────────────────────────────────
FB_GROUP_URL = "https://www.facebook.com/groups/4053530654966334/"
FB_TSV_FILENAME = "fb_deals.tsv"
FB_FIELDNAMES = ["post_id", "post_date", "text_snippet", "skus", "upcs",
                 "hd_links", "images", "scraped_at", "padding"]
ROW_SIZE = 2000
TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'

DEFAULT_CHROME_PROFILE = "/Users/shengh4/Library/Application Support/Google/Chrome"
DEFAULT_PROFILE_DIR = "Profile 1"
DEFAULT_REMOTE_DEBUG = "localhost:9222"
DEBUG_USER_DATA_DIR = "/Users/shengh4/Library/Application Support/Google/Chrome-Debug"


CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _is_port_open(host, port):
    """Check if a TCP port is accepting connections."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _is_chrome_running():
    """Check if any Chrome process is already running (macOS/Linux)."""
    import subprocess as sp
    try:
        result = sp.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _kill_chrome():
    """Quit Chrome completely and wait for all processes to exit."""
    import subprocess as sp
    if not _is_chrome_running():
        return

    logging.warning("Chrome is running without debug port. Quitting Chrome...")

    try:
        sp.run(["osascript", "-e",
                'tell application "Google Chrome" to quit'],
               timeout=5, capture_output=True)
    except (FileNotFoundError, sp.TimeoutExpired):
        pass

    for _ in range(20):
        time.sleep(0.5)
        if not _is_chrome_running():
            logging.info("Chrome quit gracefully.")
            time.sleep(1)
            return

    logging.warning("Chrome didn't quit gracefully. Force killing...")
    sp.run(["pkill", "-9", "-x", "Google Chrome"], capture_output=True)
    time.sleep(2)

    if _is_chrome_running():
        raise RuntimeError(
            "Could not quit Chrome. Please close it manually (Cmd+Q) and try again.")
    logging.info("Chrome force-killed successfully.")


def _setup_debug_profile(real_user_data_dir, profile_dir):
    """Create a debug user-data-dir that symlinks the real profile."""
    debug_dir = DEBUG_USER_DATA_DIR
    os.makedirs(debug_dir, exist_ok=True)

    for fname in ["Local State"]:
        src = os.path.join(real_user_data_dir, fname)
        dst = os.path.join(debug_dir, fname)
        if os.path.isfile(src) and not os.path.exists(dst):
            import shutil
            shutil.copy2(src, dst)

    if profile_dir:
        link_path = os.path.join(debug_dir, profile_dir)
        real_profile = os.path.join(real_user_data_dir, profile_dir)
        if os.path.isdir(real_profile) and not os.path.exists(link_path):
            os.symlink(real_profile, link_path)
            logging.info("Symlinked %s -> %s", link_path, real_profile)

    return debug_dir


def _launch_chrome_debug(port, user_data_dir=None, profile_dir=None):
    """Launch Chrome with --remote-debugging-port and wait for it to be ready.
    If Chrome is already running without the debug port, it will be quit first."""
    import subprocess as sp
    _kill_chrome()

    if user_data_dir:
        debug_data_dir = _setup_debug_profile(user_data_dir, profile_dir)
    else:
        debug_data_dir = DEBUG_USER_DATA_DIR

    cmd = [CHROME_BINARY,
           f"--remote-debugging-port={port}",
           f"--user-data-dir={debug_data_dir}",
           "--no-first-run",
           "--no-default-browser-check"]
    if profile_dir:
        cmd.append(f"--profile-directory={profile_dir}")

    logging.info("Launching Chrome: %s", " ".join(cmd))
    proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE)

    for i in range(60):
        time.sleep(0.5)
        if _is_port_open("localhost", port):
            logging.info("Chrome is ready on port %d", port)
            return
        if proc.poll() is not None:
            stdout = proc.stdout.read().decode(errors="replace")
            stderr = proc.stderr.read().decode(errors="replace")
            raise RuntimeError(
                f"Chrome exited immediately (code {proc.returncode}).\n"
                f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}\n"
                f"This usually means Chrome is still running. "
                f"Quit Chrome (Cmd+Q) and try again.")
        if i > 0 and i % 10 == 0:
            logging.info("Waiting for Chrome on port %d... (%ds)", port, i // 2)

    try:
        stdout, stderr = proc.communicate(timeout=2)
        output = f"stdout: {stdout.decode(errors='replace')[:500]}\n" \
                 f"stderr: {stderr.decode(errors='replace')[:500]}"
    except sp.TimeoutExpired:
        output = "(Chrome running but not listening on port)"
    raise RuntimeError(
        f"Chrome did not start on port {port} within 30 seconds.\n{output}\n"
        f"Try: Cmd+Q Chrome, then run the script again.")


# ── Driver ─────────────────────────────────────────────────────────────
def get_driver(chrome_profile=None, profile_dir=None, remote_debug=None):
    """Create a browser driver.

    Priority: remote_debug → UC with profile (default) → bare UC.

    Args:
        chrome_profile: Path to Chrome user-data-dir (your real Chrome profile).
                        Chrome must be fully closed when using this.
        profile_dir:    Profile directory name inside user-data-dir (e.g. "Default",
                        "Profile 1"). Only used with chrome_profile.
        remote_debug:   Connect to an already-running Chrome via debugging port
                        (e.g. "localhost:9222"). Launch Chrome yourself with
                        --remote-debugging-port=9222 first.
    """
    # --- Remote debugging: attach to existing Chrome ---
    if remote_debug:
        service = ChromeService(ChromeDriverManager().install())
        host, port = remote_debug.split(":")
        port = int(port)
        if not _is_port_open(host, port):
            _launch_chrome_debug(port, chrome_profile, profile_dir)
        logging.info("Connecting to Chrome at %s via remote debugging", remote_debug)
        options = webdriver.ChromeOptions()
        options.debugger_address = remote_debug
        options.page_load_strategy = 'eager'
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        return driver

    # --- Default: undetected_chromedriver (with profile if provided) ---
    options = uc.ChromeOptions()
    options.add_argument("--disable-popup-blocking")
    options.page_load_strategy = 'eager'
    options.add_argument("--window-size=1920,1080")
    prefs = {
        "profile.default_content_setting_values.popups": 1,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    if chrome_profile:
        logging.info("Launching undetected Chrome with profile: %s/%s",
                     chrome_profile, profile_dir or "Default")
        _kill_chrome()
        for lock_file in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = os.path.join(chrome_profile, lock_file)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass
        time.sleep(2)
        options.add_argument(f"--user-data-dir={chrome_profile}")
        if profile_dir:
            options.add_argument(f"--profile-directory={profile_dir}")
    else:
        logging.info("Launching undetected Chrome (no profile)")

    last_err = None
    for attempt in range(1, 4):
        try:
            logging.info("UC launch attempt %d/3...", attempt)
            driver = uc.Chrome(options=options, version_main=138)
            driver.set_page_load_timeout(60)
            logging.info("UC connected successfully")
            return driver
        except Exception as e:
            last_err = e
            logging.warning("UC attempt %d failed: %s", attempt, e)
            if attempt < 3:
                time.sleep(3)
    raise last_err


# ── Cookie Auth ────────────────────────────────────────────────────────
def load_cookies(driver, cookie_file):
    """
    Load cookies from a JSON file exported by a browser extension
    (e.g., EditThisCookie, Cookie-Editor).
    Must navigate to facebook.com first so cookies are set on the right domain.
    """
    if not os.path.isfile(cookie_file):
        print(f"Cookie file not found: {cookie_file}")
        return False

    print(f"Loading cookies from {cookie_file}...")
    driver.get("https://www.facebook.com")
    time.sleep(3)

    with open(cookie_file, "r") as f:
        cookies = json.load(f)

    for cookie in cookies:
        # Selenium requires specific fields; strip extras
        clean = {}
        for key in ("name", "value", "domain", "path", "secure", "httpOnly"):
            if key in cookie:
                clean[key] = cookie[key]
        # Ensure domain is set for facebook
        if "domain" not in clean or "facebook" not in clean.get("domain", ""):
            clean["domain"] = ".facebook.com"
        if "path" not in clean:
            clean["path"] = "/"
        try:
            driver.add_cookie(clean)
        except Exception:
            pass

    print("Cookies loaded. Refreshing page...")
    driver.get("https://www.facebook.com")
    time.sleep(3)
    return True


def manual_login(driver):
    """Open FB login page and wait for user to log in manually."""
    print("\n" + "=" * 60)
    print("  MANUAL LOGIN: Please log in to Facebook in the browser.")
    print("  The script will continue automatically once logged in.")
    print("  (Timeout: 3 minutes)")
    print("=" * 60)

    driver.get("https://www.facebook.com/login")
    time.sleep(3)

    max_wait = 180
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(5)
        elapsed += 5
        url = driver.current_url.lower()
        if "login" not in url and "checkpoint" not in url:
            print("   > Login detected!")
            time.sleep(2)
            return True
        if elapsed % 15 == 0:
            print(f"   > Waiting for login... ({max_wait - elapsed}s remaining)")

    print("   > Login timeout.")
    return False


def is_logged_in(driver):
    """Check if we're logged into Facebook."""
    try:
        # Logged-in FB has a navigation bar with profile link
        driver.find_element(By.XPATH, "//div[@role='navigation']")
        return True
    except Exception:
        pass
    # Check URL — login page means not logged in
    return "login" not in driver.current_url.lower()


def export_cookies(driver, cookie_file):
    """Save current cookies to file for reuse."""
    cookies = driver.get_cookies()
    with open(cookie_file, "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"Cookies saved to {cookie_file}")


# ── Text Extraction ───────────────────────────────────────────────────
def extract_skus(text):
    """
    Extract Home Depot SKU numbers from text.
    HD SKUs are typically 6-9 digit numbers, often preceded by
    'SKU', 'sku', '#', or 'model'.
    """
    skus = set()
    # Explicit SKU/model patterns
    for match in re.finditer(
            r'(?:SKU|sku|model|Model|item|Item)[#:\s]*(\d{6,9})', text):
        skus.add(match.group(1))
    # HD URL pattern: /p/Product-Name/XXXXXXXXX
    for match in re.finditer(r'homedepot\.com/p/[^/]+/(\d{6,12})', text):
        skus.add(match.group(1))
    return sorted(skus)


def extract_upcs(text):
    """Extract UPC codes (12-13 digit numbers) from text."""
    upcs = set()
    for match in re.finditer(r'(?:UPC|upc|barcode)[#:\s]*(\d{12,13})', text):
        upcs.add(match.group(1))
    # Standalone 12-digit numbers that look like UPCs
    for match in re.finditer(r'\b(\d{12,13})\b', text):
        num = match.group(1)
        # Filter out timestamps and other non-UPC numbers
        if not re.search(r'20[12]\d{8,}', num):
            upcs.add(num)
    return sorted(upcs)


def extract_hd_links(text):
    """Extract Home Depot product URLs from text."""
    links = set()
    for match in re.finditer(
            r'https?://(?:www\.)?homedepot\.com/p/[^\s"\'<>]+', text):
        links.add(match.group(0))
    return sorted(links)


# ── Post Scraping ─────────────────────────────────────────────────────
def get_post_id(post_elem):
    """Try to extract a unique post ID from the post element."""
    try:
        # FB posts have links with /posts/ or /permalink/ containing the ID
        links = post_elem.find_elements(
            By.XPATH, ".//a[contains(@href, '/posts/') or "
                      "contains(@href, '/permalink/')]")
        for link in links:
            href = link.get_attribute("href") or ""
            match = re.search(r'/(?:posts|permalink)/(\d+)', href)
            if match:
                return match.group(1)
    except Exception:
        pass
    # Fallback: use hash of text content
    try:
        text = post_elem.text[:200]
        return str(abs(hash(text)))
    except Exception:
        return str(int(time.time() * 1000))


def get_post_date(post_elem):
    """Extract the post date/time from a post element."""
    try:
        # FB uses <a> tags with aria-label containing the date for timestamps
        time_links = post_elem.find_elements(
            By.XPATH, ".//a[contains(@href, '/posts/') or "
                      "contains(@href, '/permalink/')]//span")
        for span in time_links:
            text = span.text.strip()
            # Match patterns like "2h", "3d", "May 5", "May 5 at 3:00 PM"
            if text and (re.match(r'\d+[hmdw]', text) or
                         re.match(r'[A-Z][a-z]+ \d', text) or
                         "Yesterday" in text or "Just now" in text):
                return text

        # Try aria-label on timestamp links
        ts_links = post_elem.find_elements(
            By.XPATH, ".//a[@aria-label and (contains(@href, '/posts/') or "
                      "contains(@href, '/permalink/'))]")
        for link in ts_links:
            label = link.get_attribute("aria-label")
            if label:
                return label
    except Exception:
        pass
    return ""


def get_post_images(post_elem):
    """Extract image URLs from a post."""
    images = set()
    try:
        img_elems = post_elem.find_elements(
            By.XPATH, ".//img[contains(@src, 'scontent') or "
                      "contains(@src, 'fbcdn')]")
        for img in img_elems:
            src = img.get_attribute("src") or ""
            # Skip tiny icons and profile pics
            width = img.get_attribute("width")
            height = img.get_attribute("height")
            if width and height:
                try:
                    if int(width) < 100 or int(height) < 100:
                        continue
                except ValueError:
                    pass
            if src and "emoji" not in src and "profile" not in src.lower():
                images.add(src)
    except Exception:
        pass
    return sorted(images)


def get_post_text(post_elem):
    """Extract the text content of a post."""
    try:
        # Try data-ad-preview="message" first
        msg_divs = post_elem.find_elements(
            By.XPATH, ".//div[@data-ad-preview='message']")
        if msg_divs:
            return msg_divs[0].text

        # Fallback: get all dir="auto" divs (FB's text containers)
        text_divs = post_elem.find_elements(
            By.XPATH, ".//div[@dir='auto']")
        texts = []
        for div in text_divs:
            t = div.text.strip()
            if t and len(t) > 10:
                texts.append(t)
        if texts:
            return "\n".join(texts)

        # Last resort: full post text
        return post_elem.text
    except Exception:
        return ""


def get_post_links(post_elem):
    """Extract all links from a post element."""
    links = set()
    try:
        a_elems = post_elem.find_elements(By.TAG_NAME, "a")
        for a in a_elems:
            href = a.get_attribute("href") or ""
            if "homedepot.com" in href:
                # Clean FB redirect URLs
                if "l.facebook.com" in href:
                    match = re.search(r'u=([^&]+)', href)
                    if match:
                        from urllib.parse import unquote
                        href = unquote(match.group(1))
                links.add(href)
    except Exception:
        pass
    return sorted(links)


def scrape_posts(driver, max_posts=50, max_days=7):
    """
    Scroll through the FB group and extract post data.
    Stops after max_posts or when posts are older than max_days.
    """
    posts_data = []
    seen_ids = set()
    patience = 0
    max_patience = 5

    print(f"Scraping posts (max: {max_posts}, max age: {max_days} days)...")

    while len(posts_data) < max_posts:
        # Find all post articles
        articles = driver.find_elements(By.XPATH, "//div[@role='article']")
        new_found = 0

        for article in articles:
            if len(posts_data) >= max_posts:
                break

            try:
                post_id = get_post_id(article)
                if post_id in seen_ids:
                    continue

                # Get post text and all links
                post_text = get_post_text(article)
                if not post_text or len(post_text) < 5:
                    continue

                post_date = get_post_date(article)
                post_links = get_post_links(article)

                # Check if post is too old
                if post_date:
                    match = re.match(r'(\d+)d', post_date)
                    if match and int(match.group(1)) > max_days:
                        print(f"\nPost is {match.group(1)} days old. Stopping.")
                        return posts_data

                # Combine text and links for extraction
                full_text = post_text + "\n" + "\n".join(post_links)

                skus = extract_skus(full_text)
                upcs = extract_upcs(full_text)
                hd_links = extract_hd_links(full_text) or list(post_links)
                images = get_post_images(article)

                # Only save posts that have relevant deal info
                if skus or upcs or hd_links:
                    post_entry = {
                        "post_id": post_id,
                        "post_date": post_date,
                        "text_snippet": post_text[:200].replace("\t", " ").replace("\n", " "),
                        "skus": ",".join(skus),
                        "upcs": ",".join(upcs),
                        "hd_links": ",".join(hd_links),
                        "images": ",".join(images[:3]),  # Max 3 images
                        "scraped_at": datetime.datetime.now().strftime(TIMESTAMP_FORMAT),
                        "padding": ""
                    }
                    posts_data.append(post_entry)
                    seen_ids.add(post_id)
                    new_found += 1

                    print(f"  [{len(posts_data)}] SKUs:{skus} UPCs:{upcs} "
                          f"Links:{len(hd_links)} Date:{post_date}")

                seen_ids.add(post_id)

            except Exception as e:
                continue

        if new_found > 0:
            patience = 0
        else:
            patience += 1
            if patience >= max_patience:
                print("No new posts found. Stopping.")
                break

        # Scroll down
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(random.uniform(3, 5))

        # Click "See more" buttons to expand posts
        try:
            see_more_btns = driver.find_elements(
                By.XPATH, "//div[@role='button' and contains(text(), 'See more')]")
            for btn in see_more_btns[:3]:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(random.uniform(0.5, 1.0))
                except Exception:
                    pass
        except Exception:
            pass

    return posts_data


# ── TSV I/O ───────────────────────────────────────────────────────────
def pad_row(input_dict, target_char_length=ROW_SIZE, pad_char=" "):
    target_char_length -= 1
    values = [str(input_dict.get(f, "")) for f in FB_FIELDNAMES]
    tsv_string = "\t".join(values)
    current_len = len(tsv_string)
    if current_len < target_char_length:
        return tsv_string.ljust(target_char_length, pad_char)
    elif current_len > target_char_length:
        return tsv_string[:target_char_length]
    return tsv_string


def load_existing_tsv(tsv_path):
    """Load existing FB deals from TSV."""
    deals = []
    seen_ids = set()
    if not os.path.isfile(tsv_path):
        return deals, seen_ids

    with open(tsv_path, "r", encoding="utf-8") as f:
        f.readline()  # skip header
        for row in f:
            parts = row.strip().split("\t")
            while len(parts) < len(FB_FIELDNAMES):
                parts.append("")
            if len(parts) >= len(FB_FIELDNAMES) - 1:
                entry = dict(zip(FB_FIELDNAMES, parts[:len(FB_FIELDNAMES)]))
                deals.append(entry)
                seen_ids.add(entry["post_id"])

    return deals, seen_ids


def save_tsv(deals, tsv_path):
    """Write all deals to TSV."""
    with open(tsv_path, "w", encoding="utf-8") as f:
        print(pad_row(dict(zip(FB_FIELDNAMES, FB_FIELDNAMES))), file=f)
        for deal in deals:
            print(pad_row(deal), file=f)


# ── HTML Report ───────────────────────────────────────────────────────
def generate_fb_html(deals, output_path):
    """Generate an HTML report for FB group deals."""
    html = """
    <html><head><style>
        body { font-family: Arial, sans-serif; background: #f0f2f5; padding: 20px; }
        h2 { color: #1877f2; }
        table { border-collapse: collapse; width: 100%; background: white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th { background: #1877f2; color: white; padding: 10px; text-align: left;
             position: sticky; top: 0; }
        td { padding: 8px 10px; border-bottom: 1px solid #eee; vertical-align: top; }
        tr:hover { background: #f0f7ff; }
        img { max-width: 120px; max-height: 90px; border-radius: 4px; }
        a { color: #1877f2; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .sku { font-weight: bold; color: #e67e22; }
        .upc { font-weight: bold; color: #27ae60; }
        .snippet { max-width: 300px; overflow: hidden; text-overflow: ellipsis;
                   white-space: nowrap; font-size: 13px; color: #555; }
        .date { white-space: nowrap; color: #888; }
    </style></head><body>
    <h2>Facebook Group Deals</h2>
    <p>Source: <a href="https://www.facebook.com/groups/4053530654966334/"
       target="_blank">HD Penny Deals Group</a>
       | Items: """ + str(len(deals)) + """
       | Updated: """ + datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + """</p>
    <table>
    <tr><th>Image</th><th>SKU</th><th>UPC</th><th>HD Link</th>
        <th>Post Snippet</th><th>Date</th></tr>
    """

    for deal in deals:
        # First image
        images = deal.get("images", "").split(",")
        img_html = ""
        if images and images[0]:
            img_html = f'<img src="{images[0]}" loading="lazy">'

        # SKUs
        skus = deal.get("skus", "")
        sku_html = ""
        if skus:
            for sku in skus.split(","):
                sku = sku.strip()
                if sku:
                    hd_search = f"https://www.homedepot.com/s/{sku}"
                    sku_html += f'<a class="sku" href="{hd_search}" target="_blank">{sku}</a><br>'

        # UPCs
        upcs = deal.get("upcs", "")
        upc_html = ""
        if upcs:
            for upc in upcs.split(","):
                upc = upc.strip()
                if upc:
                    upc_html += f'<span class="upc">{upc}</span><br>'

        # HD Links
        hd_links = deal.get("hd_links", "")
        link_html = ""
        if hd_links:
            for link in hd_links.split(","):
                link = link.strip()
                if link and "homedepot.com" in link:
                    link_html += f'<a href="{link}" target="_blank">View</a><br>'

        snippet = deal.get("text_snippet", "")
        date = deal.get("post_date", "")

        html += f"""<tr>
            <td>{img_html}</td>
            <td>{sku_html or '—'}</td>
            <td>{upc_html or '—'}</td>
            <td>{link_html or '—'}</td>
            <td class="snippet" title="{snippet}">{snippet[:100]}</td>
            <td class="date">{date}</td>
        </tr>\n"""

    html += "</table></body></html>"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"FB report saved to {output_path}")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Facebook Group Deal Scraper")
    parser.add_argument("-c", "--cookies", type=str, default="fb_cookies.json",
                        help="Path to FB cookies JSON file")
    parser.add_argument("-n", "--max-posts", type=int, default=50,
                        help="Maximum number of posts to scrape")
    parser.add_argument("-d", "--max-days", type=int, default=7,
                        help="Stop scraping posts older than this many days")
    parser.add_argument("-f", "--from-tsv", type=str, default=FB_TSV_FILENAME,
                        help="Path to existing TSV file")
    parser.add_argument("-o", "--output-dir", type=str, default=".",
                        help="Output directory")
    parser.add_argument("--chrome-profile", type=str, default=DEFAULT_CHROME_PROFILE,
                        help="Path to Chrome user-data-dir (default: %(default)s). "
                             "Chrome will be closed and relaunched via undetected_chromedriver. "
                             "Use --no-chrome-profile for a fresh UC session.")
    parser.add_argument("--profile-dir", type=str, default=DEFAULT_PROFILE_DIR,
                        help="Profile directory name inside user-data-dir (default: %(default)s).")
    parser.add_argument("--no-chrome-profile", action="store_true",
                        help="Don't use a Chrome profile — launch a fresh undetected_chromedriver.")
    parser.add_argument("--remote-debug", type=str, default=None,
                        help="Connect to running Chrome via remote debugging (e.g. 'localhost:9222'). "
                             "Overrides --chrome-profile. Launch Chrome with --remote-debugging-port=9222 first.")
    parser.add_argument("-m", "--mode", choices=["scrape", "report"],
                        default="scrape",
                        help="scrape: scrape FB group; report: generate HTML only")
    args = parser.parse_args()

    # Handle opt-out flag
    if args.no_chrome_profile:
        args.chrome_profile = None
        args.profile_dir = None

    # --- LOGGING SETUP ---
    log_path = os.path.join(args.output_dir or ".", "fb_scraper.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    class _TeeWriter:
        """Write to both stdout and a log file."""
        def __init__(self, log_file, orig_stdout):
            self._log = open(log_file, "a", encoding="utf-8")
            self._orig = orig_stdout
        def write(self, msg):
            self._orig.write(msg)
            self._log.write(msg)
        def flush(self):
            self._orig.flush()
            self._log.flush()
    sys.stdout = _TeeWriter(log_path, sys.__stdout__)
    sys.stderr = _TeeWriter(log_path, sys.__stderr__)
    logging.info("Logging to %s", log_path)

    tsv_path = os.path.join(args.output_dir, args.from_tsv)
    report_path = os.path.join(args.output_dir, "fb_deals.html")

    # Load existing data
    existing_deals, existing_ids = load_existing_tsv(tsv_path)
    print(f"Loaded {len(existing_deals)} existing deals from TSV.")

    if args.mode == "report":
        generate_fb_html(existing_deals, report_path)
        return

    # --- Scrape mode ---
    driver = get_driver(chrome_profile=args.chrome_profile,
                        profile_dir=args.profile_dir,
                        remote_debug=args.remote_debug)
    try:
        # Authenticate
        logged_in = False
        if os.path.isfile(args.cookies):
            load_cookies(driver, args.cookies)
            driver.get(FB_GROUP_URL)
            time.sleep(5)
            logged_in = is_logged_in(driver)
            if logged_in:
                print("Logged in via cookies.")
            else:
                print("Cookie login failed.")

        if not logged_in:
            manual_login(driver)
            driver.get(FB_GROUP_URL)
            time.sleep(5)
            logged_in = is_logged_in(driver)
            if logged_in:
                # Save cookies for next time
                export_cookies(driver, args.cookies)

        if not logged_in:
            print("ERROR: Could not log in to Facebook.")
            return

        # Navigate to group
        print(f"Navigating to group: {FB_GROUP_URL}")
        try:
            driver.get(FB_GROUP_URL)
        except Exception:
            pass
        time.sleep(random.uniform(4, 7))

        # Wait for posts to load
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='article']")))
            print("Group page loaded.")
        except Exception:
            print("Could not find posts on group page.")
            return

        # Scrape
        new_posts = scrape_posts(driver, max_posts=args.max_posts,
                                 max_days=args.max_days)

        # Merge with existing
        merged = list(existing_deals)
        for post in new_posts:
            if post["post_id"] not in existing_ids:
                merged.append(post)
                existing_ids.add(post["post_id"])
            else:
                # Update existing entry
                for i, d in enumerate(merged):
                    if d["post_id"] == post["post_id"]:
                        merged[i] = post
                        break

        print(f"\nTotal deals: {len(merged)} "
              f"({len(new_posts)} new, {len(existing_deals)} existing)")

        # Save
        save_tsv(merged, tsv_path)
        generate_fb_html(merged, report_path)

    finally:
        driver.quit()
        print("Done.")


if __name__ == "__main__":
    main()
