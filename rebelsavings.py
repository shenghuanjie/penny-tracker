import datetime
import logging
import re
import requests
import shutil
import subprocess
import sys
import time
import os
import argparse
import random

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
ROW_SIZE = 1000  # Target bytes per line
FIELDNAMES = ["name", "price", "url", "image", "original_timestamp", "hd_status",
              "updated_at", "padding"]
NEWLINE = '\n'
TSV_FILENAME = "rebel_final_report.tsv"
BACKUP_TSV_FILENAME = "rebel_final_report_backup.tsv"
DEFAULT_ZIP = "94538"
REBEL_SAVINGS_DEAL_URL = "https://www.rebelsavings.com/home-depot?zip={zip}"

DEFAULT_CHROME_PROFILE = "/Users/shengh4/Library/Application Support/Google/Chrome"
DEFAULT_PROFILE_DIR = "Profile 1"
DEFAULT_REMOTE_DEBUG = "localhost:9222"
# Chrome refuses --remote-debugging-port with the default user-data-dir.
# Use a separate debug directory that symlinks to the real profile.
DEBUG_USER_DATA_DIR = "/Users/shengh4/Library/Application Support/Google/Chrome-Debug"


def _bezier_curve(x0, y0, x1, y1, steps=15):
    """Generate points along a cubic Bezier curve between two points.
    Produces natural-looking mouse trajectories with slight curvature."""
    cx1 = x0 + (x1 - x0) * random.uniform(0.2, 0.5) + random.randint(-40, 40)
    cy1 = y0 + (y1 - y0) * random.uniform(0.0, 0.3) + random.randint(-40, 40)
    cx2 = x0 + (x1 - x0) * random.uniform(0.5, 0.8) + random.randint(-40, 40)
    cy2 = y0 + (y1 - y0) * random.uniform(0.7, 1.0) + random.randint(-40, 40)
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = int(u**3 * x0 + 3 * u**2 * t * cx1 +
                3 * u * t**2 * cx2 + t**3 * x1)
        y = int(u**3 * y0 + 3 * u**2 * t * cy1 +
                3 * u * t**2 * cy2 + t**3 * y1)
        points.append((x, y))
    return points


def simulate_human_behavior(driver, duration=None):
    """Generate realistic mouse movements, scrolls, keyboard presses,
    and pauses using real ActionChains (isTrusted: true events).

    Akamai's sensor detects JS-dispatched events (isTrusted: false).
    ActionChains go through Chrome DevTools Protocol which produces
    isTrusted: true events, indistinguishable from real human input.
    Mouse follows Bezier curves for natural trajectories.
    """
    if duration is None:
        duration = random.uniform(3, 8)

    start = time.time()

    try:
        vw = driver.execute_script("return window.innerWidth;") or 1920
        vh = driver.execute_script("return window.innerHeight;") or 1080
    except Exception:
        vw, vh = 1920, 1080

    # Move mouse to a safe starting position near center
    mx, my = vw // 2, vh // 2
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        ActionChains(driver).move_to_element(body).perform()
    except Exception:
        pass

    while time.time() - start < duration:
        action = random.choices(
            ["move", "scroll", "pause", "key"],
            weights=[40, 30, 20, 10]
        )[0]

        if action == "move":
            # Move mouse along a Bezier curve to a random target
            tx = random.randint(80, vw - 80)
            ty = random.randint(80, vh - 80)
            points = _bezier_curve(mx, my, tx, ty,
                                   steps=random.randint(8, 20))
            try:
                for px, py in points:
                    dx = px - mx
                    dy = py - my
                    if abs(dx) < 1 and abs(dy) < 1:
                        continue
                    ActionChains(driver).move_by_offset(dx, dy).perform()
                    mx, my = px, py
                    time.sleep(random.uniform(0.01, 0.04))
            except Exception:
                # Reset to body center if we drifted out of bounds
                try:
                    mx, my = vw // 2, vh // 2
                    body = driver.find_element(By.TAG_NAME, "body")
                    ActionChains(driver).move_to_element(body).perform()
                except Exception:
                    pass
            time.sleep(random.uniform(0.1, 0.5))

        elif action == "scroll":
            direction = random.choice([1, 1, 1, -1])
            amount = direction * random.randint(100, 400)
            try:
                driver.execute_script(
                    f"window.scrollBy({{top: {amount}, "
                    f"behavior: 'smooth'}});")
            except Exception:
                pass
            time.sleep(random.uniform(0.5, 1.5))

        elif action == "key":
            key = random.choice([
                Keys.PAGE_DOWN, Keys.PAGE_UP,
                Keys.ARROW_DOWN, Keys.ARROW_DOWN, Keys.ARROW_DOWN,
                Keys.ARROW_UP,
            ])
            try:
                ActionChains(driver).send_keys(key).perform()
            except Exception:
                pass
            time.sleep(random.uniform(0.3, 0.8))

        elif action == "pause":
            time.sleep(random.uniform(0.5, 2.0))


def human_click(driver, element):
    """
    Robust clicker. Calculates the 'Visual Center' of a zoomed element.
    Includes rendering enforcement to prevent 'no size and location' errors.
    """
    try:
        # --- 0. ENFORCE RENDERING ---
        # Force the element into the viewport to trigger lazy-loading
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                              element)
        time.sleep(random.uniform(0.3, 0.7))  # Give React a moment to paint the dimensions

        rect = element.rect

        # If still 0x0, the <a> might be a logical wrapper. Look for a visible child.
        if rect['width'] == 0 or rect['height'] == 0:
            try:
                # Find the first child (usually an img or div) that actually has size
                visible_child = driver.execute_script("""
                    for (let child of arguments[0].querySelectorAll('*')) {
                        let bounds = child.getBoundingClientRect();
                        if (bounds.width > 0 && bounds.height > 0) return child;
                    }
                    return null;
                """, element)

                if visible_child:
                    element = visible_child
                    rect = element.rect
                else:
                    raise ValueError("Element and all children have 0x0 dimensions.")
            except Exception as e:
                raise ValueError(f"Could not resolve 0x0 dimensions: {e}")

        # --- 1. DETECT ZOOM LEVEL ---
        zoom_style = element.value_of_css_property("zoom")
        zoom_factor = 1.0

        if zoom_style and zoom_style != 'normal':
            clean_zoom = zoom_style.strip().replace('%', '')
            try:
                val = float(clean_zoom)
                zoom_factor = val / 100.0 if val > 1 else val
            except ValueError:
                pass

        # --- 2. CALCULATE VISUAL TARGET ---
        logical_width = rect['width']
        logical_height = rect['height']

        visual_width = logical_width * zoom_factor
        visual_height = logical_height * zoom_factor

        # --- 3. CALCULATE OFFSET (Relative to Top-Left) ---
        center_x = visual_width / 2
        center_y = visual_height / 2

        jitter_x = random.randint(-int(visual_width * 0.1), int(visual_width * 0.1))
        jitter_y = random.randint(-int(visual_height * 0.1), int(visual_height * 0.1))

        target_x = max(1, min(int(center_x + jitter_x), int(visual_width) - 1))
        target_y = max(1, min(int(center_y + jitter_y), int(visual_height) - 1))

        # --- 4. EXECUTE MOVE & CLICK ---
        actions = ActionChains(driver)
        actions.move_to_element_with_offset(element, target_x, target_y)
        time.sleep(random.uniform(0.1, 0.3))
        actions.click()
        actions.perform()

        # Optional: wait for new window if your script expects a new tab
        # wait = WebDriverWait(driver, 5)
        # wait.until(EC.number_of_windows_to_be(2))

    except Exception as e:
        print(f"Human click failed: {e}")
        print("Engaging Backup: Force JS Click")
        driver.execute_script("arguments[0].click();", element)


def close_modal(driver):
    """Close the RebelSavings detail overlay modal.
    Uses JS click to bypass the backdrop overlay that intercepts normal clicks."""
    try:
        btn = driver.find_element(By.CLASS_NAME, "close-menu-btn")
        driver.execute_script("arguments[0].click();", btn)
    except Exception:
        # Fallback: click the backdrop to dismiss
        try:
            backdrop = driver.find_element(By.CLASS_NAME, "detail-overlay-backdrop")
            driver.execute_script("arguments[0].click();", backdrop)
        except Exception:
            # Last resort: press Escape
            try:
                from selenium.webdriver.common.keys import Keys
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass


def is_chrome_alive(driver):
    """Check if Chrome still has network connectivity."""
    try:
        # Try a lightweight navigation to check connectivity
        driver.execute_script("return navigator.onLine;")
        return True
    except Exception:
        return False


def restart_driver(driver, chrome_profile=None, profile_dir=None,
                   remote_debug=None):
    """Quit the current driver and create a new one."""
    logging.warning("Restarting Chrome driver...")
    try:
        driver.quit()
    except Exception:
        pass
    time.sleep(3)
    return get_driver(chrome_profile=chrome_profile, profile_dir=profile_dir,
                      remote_debug=remote_debug)


class RunningMode:
    # clean up TSV by removing old entries
    CLEAN = 'clean'
    SEARCH = 'search'
    # Report only
    REPORT = 'report'
    # clean followed by search and report
    ALL = 'all'
    # check non-penny items
    CHECK = 'check'


class HDStatus:
    PENNY_NEW = 'penny_new'       # $0.01 and Ship To Store available
    PENNY = 'penny'               # $0.01 (pickup/in-store only or unknown)
    NOT_PENNY = 'not_penny'
    PENNY_CANDIDATE = 'penny_candidate'
    CLEARANCE = 'clearance'
    PENNY_OLD = 'penny_old'       # $0.01 but out of stock everywhere
    OUT_OF_STOCK = 'out_of_stock'
    ERROR = 'error'
    FAILURE = 'failure'
    BLOCKED = 'blocked'


def _load_fb_deals(output_dir):
    """Load FB deals from fb_deals.tsv if it exists."""
    fb_tsv = os.path.join(output_dir, "fb_deals.tsv")
    if not os.path.isfile(fb_tsv):
        return []
    fb_fields = ["post_id", "post_date", "text_snippet", "skus", "upcs",
                 "hd_links", "images", "scraped_at", "padding"]
    deals = []
    with open(fb_tsv, "r", encoding="utf-8") as f:
        f.readline()  # skip header
        for row in f:
            parts = row.strip().split("\t")
            while len(parts) < len(fb_fields):
                parts.append("")
            if len(parts) >= len(fb_fields) - 1:
                entry = dict(zip(fb_fields, parts[:len(fb_fields)]))
                deals.append(entry)
    return deals


def generate_html_report(deals, output_path):
    """Creates a visual HTML report with images, status colors, and timestamps.
    Includes a second tab for Facebook group deals if fb_deals.tsv exists."""
    print(f"Generating HTML report with {len(deals)} items → {output_path}")

    # --- DEFAULT SORT ---
    # Primary: penny & OOS first (by latest updated_at desc),
    # then blocked/failed, clearance, everything else
    status_priority = {
        'penny_new': 0,
        'penny': 1,
        'penny_old': 2,
        'out_of_stock': 3,
        'blocked': 4,
        'failure': 5,
        'error': 6,
        'clearance': 7,
        'penny_candidate': 8,
        'not_penny': 9,
        'unchecked': 10,
    }

    def _sort_key(d):
        s = d.get('hd_status', '') or 'unchecked'
        pri = status_priority.get(s, 99)
        # Within same priority, sort by updated_at descending (newest first)
        updated = d.get('updated_at', '') or ''
        # Invert for descending: use a large string minus the timestamp
        return (pri, updated == '', updated)

    deals_sorted = sorted(deals, key=_sort_key)
    # Reverse updated_at within each priority group (newest first)
    # We do this by sorting with a tuple that puts newest first
    def _sort_key_final(d):
        s = d.get('hd_status', '') or 'unchecked'
        pri = status_priority.get(s, 99)
        updated = d.get('updated_at', '') or '0000'
        # Negate by using reverse string trick — just use negative approach
        return (pri, updated)

    # Sort: priority asc, then updated_at desc within each group
    from itertools import groupby
    final_order = []
    deals_sorted = sorted(deals, key=lambda d: status_priority.get(
        d.get('hd_status', '') or 'unchecked', 99))
    for _, group in groupby(deals_sorted, key=lambda d: status_priority.get(
            d.get('hd_status', '') or 'unchecked', 99)):
        group_list = list(group)
        group_list.sort(key=lambda d: d.get('updated_at', '') or '', reverse=True)
        final_order.extend(group_list)
    deals = final_order

    # Load FB deals
    output_dir = os.path.dirname(output_path) or "."
    fb_deals = _load_fb_deals(output_dir)
    has_fb = len(fb_deals) > 0

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- Build rows with sort index ---
    rows_html = ""
    for idx, d in enumerate(deals):
        status = d.get('hd_status', 'unchecked') or 'unchecked'
        image_src = d.get('image', '')
        name = d.get('name', 'Unknown')
        price = d.get('price', 'N/A')
        url = d.get('url', '#')
        updated = d.get('updated_at', '')
        added = d.get('original_timestamp', '')

        rows_html += f"""<tr data-idx="{idx}">
            <td><img src="{image_src}" loading="lazy"></td>
            <td>{name}</td>
            <td>{price}</td>
            <td class="{status}">{status.upper()}</td>
            <td>{updated}</td>
            <td>{added}</td>
            <td><a href="{url}" target="_blank">Link</a></td>
        </tr>"""

    # --- Build penny SKU lookup for the scanner tab ---
    import json as _json
    penny_skus = {}
    for d in deals:
        status = d.get('hd_status', '') or ''
        url = d.get('url', '')
        if not url or 'homedepot.com' not in url:
            continue
        sku = extract_sku_from_url(url)
        if not sku:
            continue
        penny_skus[sku] = {
            "name": d.get('name', '')[:80],
            "status": status,
            "url": url,
        }
    penny_skus_json = _json.dumps(penny_skus)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Penny Deal Tracker</title>
<style>
    body {{ font-family: Arial, sans-serif; background: #f0f2f5; padding: 20px; }}
    h2 {{ color: #333; margin-bottom: 5px; }}
    .tabs {{ display: flex; gap: 0; margin-bottom: 0; }}
    .tab {{ padding: 12px 24px; cursor: pointer; border: 1px solid #ddd;
            border-bottom: none; border-radius: 8px 8px 0 0; background: #e8e8e8;
            font-weight: bold; font-size: 15px; color: #555; user-select: none; }}
    .tab:hover {{ background: #f5f5f5; }}
    .tab.active {{ background: white; color: #333; border-bottom: 2px solid white;
                   margin-bottom: -1px; position: relative; z-index: 1; }}
    .tab.hd.active {{ color: #f96302; }}
    .tab.fb.active {{ color: #1877f2; }}
    .tab-content {{ display: none; border: 1px solid #ddd; border-radius: 0 8px 8px 8px;
                    background: white; padding: 0; }}
    .tab-content.active {{ display: block; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ padding: 10px 12px; border: 1px solid #eee; text-align: left; vertical-align: middle; }}
    th {{ color: white; font-weight: bold; position: sticky; top: 0; z-index: 2; }}
    .hd-table th {{ background: #f96302; cursor: pointer; user-select: none; }}
    .hd-table th:hover {{ background: #e05800; }}
    .hd-table th .arrow {{ font-size: 10px; margin-left: 4px; }}
    .fb-table th {{ background: #1877f2; }}
    tr:nth-child(even) {{ background-color: #f9f9f9; }}
    img {{ width: 70px; height: auto; border-radius: 4px; object-fit: cover; }}
    .penny_new {{ color: #27ae60; font-weight: bold; }}
    .penny {{ color: #3498db; font-weight: bold; }}
    .penny_old {{ color: #7f8c8d; font-weight: bold; font-style: italic; }}
    .not_penny {{ color: #e74c3c; font-weight: bold; }}
    .penny_candidate {{ color: #f39c12; font-weight: bold; }}
    .clearance {{ color: #2ecc71; font-weight: bold; }}
    .error {{ color: #8e44ad; font-weight: bold; }}
    .failure {{ color: #95a5a6; font-style: italic; }}
    .out_of_stock {{ color: #7f8c8d; font-weight: bold; font-style: italic; }}
    .blocked {{ color: #c0392b; font-weight: bold; text-decoration: underline; }}
    .unchecked {{ color: #3498db; font-style: italic; }}
    .sku {{ font-weight: bold; color: #e67e22; }}
    .upc {{ font-weight: bold; color: #27ae60; }}
    .snippet {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis;
                white-space: nowrap; font-size: 13px; color: #555; }}
    .date {{ white-space: nowrap; color: #888; }}
    .fb-img {{ max-width: 120px; max-height: 90px; }}
    a {{ color: #1877f2; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .meta {{ color: #888; font-size: 13px; margin: 4px 0 12px 0; }}
    .reset-btn {{ background: #f96302; color: white; border: none; padding: 6px 14px;
                  border-radius: 4px; cursor: pointer; font-size: 13px; margin-left: 12px; }}
    .reset-btn:hover {{ background: #e05800; }}
    /* Scanner tab */
    .scanner-container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
    .drop-zone {{ border: 3px dashed #ccc; border-radius: 12px; padding: 40px 20px;
                   text-align: center; cursor: pointer; transition: all 0.3s;
                   background: #fafafa; margin-bottom: 20px; }}
    .drop-zone:hover, .drop-zone.dragover {{ border-color: #f96302; background: #fff5ee; }}
    .drop-zone p {{ margin: 8px 0; color: #666; }}
    .drop-zone .icon {{ font-size: 48px; }}
    .scanner-btn {{ background: #f96302; color: white; border: none; padding: 10px 20px;
                     border-radius: 6px; cursor: pointer; font-size: 14px; margin: 5px; }}
    .scanner-btn:hover {{ background: #e05800; }}
    .scanner-btn:disabled {{ background: #ccc; cursor: not-allowed; }}
    .scanner-preview {{ max-width: 100%; max-height: 300px; border-radius: 8px;
                         margin: 10px 0; display: none; }}
    .scanner-progress {{ display: none; margin: 15px 0; }}
    .scanner-progress .bar {{ height: 6px; background: #eee; border-radius: 3px; overflow: hidden; }}
    .scanner-progress .fill {{ height: 100%; background: #f96302; transition: width 0.3s; width: 0%; }}
    .scanner-progress .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
    .scanner-results {{ margin-top: 20px; }}
    .scanner-results h3 {{ margin-bottom: 10px; }}
    .sku-result {{ padding: 12px 16px; margin: 8px 0; border-radius: 8px; border: 1px solid #eee; }}
    .sku-result.match {{ background: #e8f5e9; border-color: #4caf50; }}
    .sku-result.penny-match {{ background: #e3f2fd; border-color: #2196f3; }}
    .sku-result.no-match {{ background: #fff3e0; border-color: #ff9800; }}
    .sku-result .sku-num {{ font-weight: bold; font-size: 16px; font-family: monospace; }}
    .sku-result .sku-status {{ font-size: 13px; margin-top: 4px; }}
    .ocr-text {{ background: #f5f5f5; padding: 12px; border-radius: 6px; font-family: monospace;
                  font-size: 12px; max-height: 200px; overflow-y: auto; white-space: pre-wrap;
                  margin: 10px 0; display: none; }}
    .toggle-link {{ color: #1877f2; cursor: pointer; font-size: 13px; }}
</style>
</head><body>
    <h2>Penny Deal Tracker</h2>
    <p class="meta">Updated: {now_str}
        <button class="reset-btn" onclick="resetSort()">Reset Sort</button>
    </p>

    <div class="tabs">
        <div class="tab hd active" onclick="switchTab('hd')">RebelSavings ({len(deals)})</div>
        {('<div class="tab fb" onclick="switchTab(&#39;fb&#39;)">Facebook Group (' + str(len(fb_deals)) + ')</div>') if has_fb else ''}
        <div class="tab scanner" onclick="switchTab('scanner')">📷 SKU Scanner</div>
    </div>

    <div id="tab-hd" class="tab-content active">
    <table class="hd-table" id="hd-table">
    <thead><tr>
        <th>Image</th>
        <th onclick="sortTable(1)">Name <span class="arrow"></span></th>
        <th onclick="sortTable(2)">Price <span class="arrow"></span></th>
        <th onclick="sortTable(3)">Status <span class="arrow"></span></th>
        <th onclick="sortTable(4)">Updated <span class="arrow"></span></th>
        <th onclick="sortTable(5)">Added <span class="arrow"></span></th>
        <th>Link</th>
    </tr></thead>
    <tbody>
    {rows_html}
    </tbody>
    </table>
    </div>"""

    # --- Facebook Tab ---
    if has_fb:
        fb_rows = ""
        for deal in fb_deals:
            images = deal.get("images", "").split(",")
            img_html = ""
            if images and images[0]:
                img_html = f'<img class="fb-img" src="{images[0]}" loading="lazy">'

            skus = deal.get("skus", "")
            sku_html = ""
            if skus:
                for sku in skus.split(","):
                    sku = sku.strip()
                    if sku:
                        hd_search = f"https://www.homedepot.com/s/{sku}"
                        sku_html += f'<a class="sku" href="{hd_search}" target="_blank">{sku}</a><br>'

            upcs = deal.get("upcs", "")
            upc_html = ""
            if upcs:
                for upc_val in upcs.split(","):
                    upc_val = upc_val.strip()
                    if upc_val:
                        upc_html += f'<span class="upc">{upc_val}</span><br>'

            hd_links = deal.get("hd_links", "")
            link_html = ""
            if hd_links:
                for link in hd_links.split(","):
                    link = link.strip()
                    if link and "homedepot.com" in link:
                        link_html += f'<a href="{link}" target="_blank">View</a><br>'

            snippet = deal.get("text_snippet", "")
            date_val = deal.get("post_date", "")

            fb_rows += f"""<tr>
                <td>{img_html}</td>
                <td>{sku_html or '—'}</td>
                <td>{upc_html or '—'}</td>
                <td>{link_html or '—'}</td>
                <td class="snippet" title="{snippet}">{snippet[:100]}</td>
                <td class="date">{date_val}</td>
            </tr>"""

        html += f"""
    <div id="tab-fb" class="tab-content">
    <table class="fb-table"><tr><th>Image</th><th>SKU</th><th>UPC</th><th>HD Link</th>
        <th>Post Snippet</th><th>Date</th></tr>
    {fb_rows}
    </table></div>"""

    # --- Scanner Tab ---
    html += f"""
    <div id="tab-scanner" class="tab-content">
    <div class="scanner-container">
        <h3>SKU Scanner</h3>
        <p style="color:#666; margin-bottom:15px;">
            Upload a receipt, shelf tag, or price scanner photo.
            OCR runs in your browser — nothing is uploaded to any server.
        </p>

        <div class="drop-zone" id="dropZone">
            <div class="icon">📷</div>
            <p><b>Drop image here</b> or click to upload</p>
            <p style="font-size:12px; color:#999;">Also supports Ctrl+V paste</p>
        </div>
        <input type="file" id="fileInput" accept="image/*" style="display:none;">
        <button class="scanner-btn" id="cameraBtn" style="display:none;">📱 Use Camera</button>
        <input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none;">

        <img id="scannerPreview" class="scanner-preview">

        <div class="scanner-progress" id="scannerProgress">
            <div class="bar"><div class="fill" id="progressFill"></div></div>
            <div class="label" id="progressLabel">Initializing OCR...</div>
        </div>

        <div class="scanner-results" id="scannerResults"></div>

        <div class="ocr-text" id="ocrText"></div>
        <span class="toggle-link" id="toggleOcr" style="display:none;"
              onclick="document.getElementById('ocrText').style.display=
                       document.getElementById('ocrText').style.display==='none'?'block':'none';">
            Show/hide raw OCR text
        </span>
    </div>
    </div>

    <script>const PENNY_SKUS = {penny_skus_json};</script>
    """

    # --- JavaScript: tab switching + column sorting ---
    html += """
<script>
function switchTab(tab) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    document.querySelector('.tab.' + tab).classList.add('active');
}

// Column sorting state
let currentSortCol = -1;
let currentSortDir = 0; // 0=default, 1=asc, 2=desc

function sortTable(col) {
    const table = document.getElementById('hd-table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const headers = table.querySelectorAll('thead th');

    // Cycle: default → asc → desc → default
    if (currentSortCol === col) {
        currentSortDir = (currentSortDir + 1) % 3;
    } else {
        currentSortCol = col;
        currentSortDir = 1; // start with asc
    }

    // Clear all arrows
    headers.forEach(th => {
        const arrow = th.querySelector('.arrow');
        if (arrow) arrow.textContent = '';
    });

    if (currentSortDir === 0) {
        // Reset to default order
        rows.sort((a, b) => parseInt(a.dataset.idx) - parseInt(b.dataset.idx));
        currentSortCol = -1;
    } else {
        const arrow = headers[col].querySelector('.arrow');
        if (arrow) arrow.textContent = currentSortDir === 1 ? ' ▲' : ' ▼';

        rows.sort((a, b) => {
            let A = a.cells[col].textContent.trim();
            let B = b.cells[col].textContent.trim();
            // Try numeric comparison for price
            let nA = parseFloat(A.replace(/[^0-9.-]/g, ''));
            let nB = parseFloat(B.replace(/[^0-9.-]/g, ''));
            if (!isNaN(nA) && !isNaN(nB)) {
                return currentSortDir === 1 ? nA - nB : nB - nA;
            }
            // String comparison
            let cmp = A.localeCompare(B, undefined, {numeric: true, sensitivity: 'base'});
            return currentSortDir === 1 ? cmp : -cmp;
        });
    }

    rows.forEach(r => tbody.appendChild(r));
}

function resetSort() {
    currentSortCol = -1;
    currentSortDir = 0;
    const table = document.getElementById('hd-table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const headers = table.querySelectorAll('thead th');
    headers.forEach(th => {
        const arrow = th.querySelector('.arrow');
        if (arrow) arrow.textContent = '';
    });
    rows.sort((a, b) => parseInt(a.dataset.idx) - parseInt(b.dataset.idx));
    rows.forEach(r => tbody.appendChild(r));
}
</script>

<!-- Tesseract.js for client-side OCR -->
<script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>
<script>
(function() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const cameraBtn = document.getElementById('cameraBtn');
    const cameraInput = document.getElementById('cameraInput');
    const preview = document.getElementById('scannerPreview');
    const progress = document.getElementById('scannerProgress');
    const progressFill = document.getElementById('progressFill');
    const progressLabel = document.getElementById('progressLabel');
    const results = document.getElementById('scannerResults');
    const ocrTextEl = document.getElementById('ocrText');
    const toggleOcr = document.getElementById('toggleOcr');

    // Show camera button on mobile
    if (/Mobi|Android/i.test(navigator.userAgent)) {
        cameraBtn.style.display = 'inline-block';
    }

    // Drop zone events
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', e => {
        e.preventDefault(); dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault(); dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) processImage(e.dataTransfer.files[0]);
    });

    fileInput.addEventListener('change', e => {
        if (e.target.files.length) processImage(e.target.files[0]);
    });

    cameraBtn.addEventListener('click', () => cameraInput.click());
    cameraInput.addEventListener('change', e => {
        if (e.target.files.length) processImage(e.target.files[0]);
    });

    // Paste support
    document.addEventListener('paste', e => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                processImage(item.getAsFile());
                // Switch to scanner tab
                switchTab('scanner');
                return;
            }
        }
    });

    async function processImage(file) {
        // Show preview
        const url = URL.createObjectURL(file);
        preview.src = url;
        preview.style.display = 'block';

        // Reset
        results.innerHTML = '';
        ocrTextEl.textContent = '';
        ocrTextEl.style.display = 'none';
        toggleOcr.style.display = 'none';
        progress.style.display = 'block';
        progressFill.style.width = '0%';
        progressLabel.textContent = 'Loading OCR engine...';

        try {
            const { data } = await Tesseract.recognize(file, 'eng', {
                logger: m => {
                    if (m.status === 'recognizing text') {
                        const pct = Math.round((m.progress || 0) * 100);
                        progressFill.style.width = pct + '%';
                        progressLabel.textContent = `Scanning... ${pct}%`;
                    } else if (m.status) {
                        progressLabel.textContent = m.status;
                    }
                }
            });

            progressFill.style.width = '100%';
            progressLabel.textContent = 'Done!';
            setTimeout(() => { progress.style.display = 'none'; }, 1500);

            // Show raw OCR text
            ocrTextEl.textContent = data.text;
            toggleOcr.style.display = 'inline';

            // Extract and check SKUs
            analyzeText(data.text);

        } catch (err) {
            progressLabel.textContent = 'OCR failed: ' + err.message;
            progressFill.style.width = '0%';
        }
    }

    function analyzeText(text) {
        // Extract potential SKUs: 6-12 digit numbers
        const allNums = text.match(/\\b\\d{6,12}\\b/g) || [];
        // Also look for explicit SKU/model patterns
        const skuPattern = /(?:SKU|sku|model|Model|item|Item)[#:\\s]*(\\d{6,9})/g;
        let m;
        while ((m = skuPattern.exec(text)) !== null) {
            if (!allNums.includes(m[1])) allNums.push(m[1]);
        }

        // Deduplicate
        const skus = [...new Set(allNums)];

        if (skus.length === 0) {
            results.innerHTML = '<p style="color:#999;">No SKU numbers found in image. ' +
                'Try a clearer photo of the receipt or shelf tag.</p>';
            return;
        }

        let html = '<h3>Found ' + skus.length + ' potential SKU(s)</h3>';
        let pennyCount = 0;

        for (const sku of skus) {
            const info = PENNY_SKUS[sku];
            if (info) {
                const isPenny = info.status.includes('penny');
                const cssClass = isPenny ? 'penny-match' : 'match';
                if (isPenny) pennyCount++;
                const statusLabel = info.status.toUpperCase().replace(/_/g, ' ');
                html += `<div class="sku-result ${cssClass}">
                    <div class="sku-num">${isPenny ? '🎯 ' : '✅ '}${sku}</div>
                    <div class="sku-status">
                        <b>${info.name}</b><br>
                        Status: <span class="${info.status}">${statusLabel}</span>
                        &nbsp;|&nbsp; <a href="${info.url}" target="_blank">View on HD</a>
                    </div>
                </div>`;
            } else {
                html += `<div class="sku-result no-match">
                    <div class="sku-num">❓ ${sku}</div>
                    <div class="sku-status">Not in our tracker &nbsp;|&nbsp;
                        <a href="https://www.homedepot.com/s/${sku}" target="_blank">Search HD</a>
                    </div>
                </div>`;
            }
        }

        if (pennyCount > 0) {
            html = `<div style="background:#e3f2fd; padding:12px 16px; border-radius:8px;
                     margin-bottom:15px; font-size:16px;">
                     🎯 <b>${pennyCount} penny item(s) found!</b></div>` + html;
        }

        results.innerHTML = html;
    }
})();
</script>
</body></html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nVisual report created: {output_path}")


def is_within_x_days(timestamp1, timestamp2, days=3):
    if timestamp1 is None or timestamp2 is None:
        return True
    try:
        d1 = datetime.datetime.strptime(timestamp1, TIMESTAMP_FORMAT)
        d2 = datetime.datetime.strptime(timestamp2, TIMESTAMP_FORMAT)
        diff = abs(d1 - d2)
        return diff <= datetime.timedelta(days=days)
    except ValueError:
        return False


def navigate_ca_filters(driver):
    """
    Navigate to the RebelSavings Home Depot deal page with a ZIP code.
    The old state/city filter UI no longer exists — the site now uses
    a retailer + ZIP URL pattern: /home-depot?zip=XXXXX
    """
    # No longer needed — navigation is handled by direct URL in the main loop.
    # Kept as a no-op for backward compatibility.
    pass


def extract_sku_from_url(hd_url):
    """
    Extract the product SKU/model number from a Home Depot URL.
    HD URLs typically end with /XXXXXXXXX (a numeric ID).
    e.g. https://www.homedepot.com/p/Some-Product-Name/123456789
    """
    # Match the numeric ID at the end of the URL path
    match = re.search(r'/(\d{6,12})(?:\?|$|#)', hd_url)
    if match:
        return match.group(1)
    # Fallback: try to get the last path segment
    match = re.search(r'/p/[^/]+/(\d+)', hd_url)
    if match:
        return match.group(1)
    return None


_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) "
    "Gecko/20100101 Firefox/138.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
]

# Nearest store IDs to try (rotated per request for variety)
_STORE_IDS = ["6636", "0629", "0658", "6604", "6673"]


def check_hd_price_api(sku, zip_code=DEFAULT_ZIP, store_id=None):
    """Check HD product price via their GraphQL API. No browser needed.

    Returns (price_float, status_string) or (None, None) on failure.
    Returns (None, 'blocked') if the API returns 403/429 (IP blocked).
    """
    if store_id is None:
        store_id = random.choice(_STORE_IDS)

    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-experience-name": "general-merchandise",
        "x-current-url": f"/p/product/{sku}",
        "x-hd-dc": "origin",
        "Origin": "https://www.homedepot.com",
        "Referer": f"https://www.homedepot.com/p/product/{sku}",
    }
    api_url = ("https://www.homedepot.com/federation-gateway/graphql"
               "?opname=productClientOnlyProduct")
    payload = {
        "operationName": "productClientOnlyProduct",
        "variables": {
            "itemId": sku,
            "storeId": store_id,
            "zipCode": zip_code,
        },
        "query": """query productClientOnlyProduct($itemId: String!, $storeId: String!, $zipCode: String!) {
            product(itemId: $itemId) {
                identifiers { itemId productLabel canonicalUrl }
                pricing(storeId: $storeId) {
                    value originalPrice specialPrice
                    promotion { dollarOff percentageOff }
                    message
                }
                availabilityType { type discontinued buyable }
                fulfillment(storeId: $storeId, zipCode: $zipCode) {
                    fulfillmentOptions { type services { type } }
                }
            }
        }"""
    }
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)

        # Detect IP-level blocks
        if resp.status_code in (403, 429):
            return None, HDStatus.BLOCKED
        if resp.status_code != 200:
            return None, None

        # Check for Akamai block page in response body
        text = resp.text
        if "Access Denied" in text or "Reference #" in text:
            return None, HDStatus.BLOCKED

        data = resp.json()
        product = data.get("data", {}).get("product")
        if not product:
            return None, None

        pricing = product.get("pricing", {})
        price = pricing.get("value") or pricing.get("specialPrice")
        original = pricing.get("originalPrice")

        avail = product.get("availabilityType", {})
        discontinued = avail.get("discontinued", False)

        if price is not None:
            price = float(price)
            if price <= 0.03:
                return price, HDStatus.PENNY
            elif price <= 1.00:
                return price, HDStatus.PENNY_CANDIDATE
            elif original and price < float(original) * 0.5:
                return price, HDStatus.CLEARANCE
            else:
                return price, HDStatus.NOT_PENNY

        if discontinued:
            return None, HDStatus.OUT_OF_STOCK

        return None, None
    except Exception as e:
        logging.debug("API price check failed for %s: %s", sku, e)
        return None, None


GITHUB_PAGES_URL = "https://shenghuanjie.github.io/penny-tracker/"

# Cache: avoid re-checking freshness on every single item
_github_pages_fresh = None  # True/False/None
_github_pages_checked_at = 0


def _is_github_pages_fresh(driver, max_age_minutes=10):
    """Check if the GitHub Pages report was updated within *max_age_minutes*.
    Looks for the 'Updated: YYYY-MM-DD HH:MM' text in the page.
    Result is cached for 5 minutes to avoid repeated checks."""
    global _github_pages_fresh, _github_pages_checked_at

    # Use cached result if checked recently (within 5 min)
    if _github_pages_fresh is not None and time.time() - _github_pages_checked_at < 300:
        return _github_pages_fresh

    try:
        meta = driver.find_elements(By.CLASS_NAME, "meta")
        for el in meta:
            text = el.text  # e.g. "Updated: 2026-05-17 14:30"
            match = re.search(r'Updated:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', text)
            if match:
                report_time = datetime.datetime.strptime(
                    match.group(1), "%Y-%m-%d %H:%M")
                age = datetime.datetime.now() - report_time
                fresh = age.total_seconds() < max_age_minutes * 60
                _github_pages_fresh = fresh
                _github_pages_checked_at = time.time()
                if not fresh:
                    print(f"   > GitHub Pages report is stale "
                          f"(updated {age.total_seconds()/60:.0f}m ago)")
                return fresh
    except Exception:
        pass

    _github_pages_fresh = False
    _github_pages_checked_at = time.time()
    print(f"   > Could not determine GitHub Pages freshness")
    return False


def navigate_hd_via_github_pages(driver, hd_url, name=''):
    """Navigate to an HD product page by clicking its link on the GitHub
    Pages report.  This gives a legitimate Referer from github.io.
    Skips if the report is stale (>10 minutes old)."""
    sku = extract_sku_from_url(hd_url)
    if not sku:
        return False

    print(f"   > GitHub Pages click-through for SKU: {sku}")
    try:
        tabs_before = set(driver.window_handles)
        driver.get(GITHUB_PAGES_URL)
        time.sleep(random.uniform(3, 5))

        # Check freshness before using the report
        if not _is_github_pages_fresh(driver):
            return False

        # Find the HD link that contains this SKU
        wait = WebDriverWait(driver, 12)
        xpath = f"//a[contains(@href, 'homedepot.com') and contains(@href, '{sku}')]"
        try:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", link)
            time.sleep(random.uniform(0.5, 1.5))
            link.click()
            time.sleep(random.uniform(4, 7))

            # The link has target="_blank" so it opens in a new tab.
            # Switch to the new tab.
            tabs_after = set(driver.window_handles)
            new_tabs = tabs_after - tabs_before
            if new_tabs:
                new_tab = new_tabs.pop()
                driver.switch_to.window(new_tab)
                time.sleep(random.uniform(2, 4))

            if not is_hd_blocked(driver):
                return True
            else:
                print(f"   > Blocked after GitHub Pages click-through")
        except Exception:
            print(f"   > SKU {sku} not found on GitHub Pages report")
    except Exception as e:
        print(f"   > GitHub Pages navigation failed: {e}")
    return False


def navigate_hd_via_google(driver, hd_url, name=''):
    """Navigate to an HD product page via Google search click-through."""
    sku = extract_sku_from_url(hd_url)
    if not sku:
        print(f"   > Could not extract SKU from URL: {hd_url}")
        return False

    print(f"   > Google search for HD SKU: {sku}")

    try:
        query = f"site:homedepot.com {sku}"
        driver.get(f"https://www.google.com/search?q={query}")
        time.sleep(random.uniform(3, 5))

        # Check for CAPTCHA / robot detection
        page_text = driver.page_source.lower()
        if ("unusual traffic" in page_text or "captcha" in page_text
                or "recaptcha" in page_text
                or "sorry/index" in driver.current_url):
            print(f"   > Google robot detection triggered, skipping")
            return False

        wait = WebDriverWait(driver, 10)

        try:
            hd_result = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, 'homedepot.com/p/')]")))
            print(f"   > Found HD link in Google results, clicking...")
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", hd_result)
            time.sleep(random.uniform(0.5, 1.5))
            hd_result.click()
            time.sleep(random.uniform(4, 7))

            if not is_hd_blocked(driver):
                return True
            else:
                print(f"   > Blocked after Google click-through")
        except Exception:
            print(f"   > No HD result found on Google")

    except Exception as e:
        print(f"   > Google search failed: {e}")

    return False


def navigate_hd_via_duckduckgo(driver, hd_url, name=''):
    """Navigate to an HD product page via DuckDuckGo search click-through."""
    sku = extract_sku_from_url(hd_url)
    if not sku:
        return False

    print(f"   > DuckDuckGo search for HD SKU: {sku}")

    try:
        query = f"site:homedepot.com {sku}"
        driver.get(f"https://duckduckgo.com/?q={query}")
        time.sleep(random.uniform(3, 5))

        wait = WebDriverWait(driver, 10)

        try:
            hd_result = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, 'homedepot.com/p/')]")))
            print(f"   > Found HD link in DuckDuckGo results, clicking...")
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", hd_result)
            time.sleep(random.uniform(0.5, 1.5))
            hd_result.click()
            time.sleep(random.uniform(4, 7))

            if not is_hd_blocked(driver):
                return True
            else:
                print(f"   > Blocked after DuckDuckGo click-through")
        except Exception:
            print(f"   > No HD result found on DuckDuckGo")

    except Exception as e:
        print(f"   > DuckDuckGo search failed: {e}")

    return False


def navigate_hd_via_bing(driver, hd_url, name=''):
    """Navigate to an HD product page via Bing search click-through."""
    sku = extract_sku_from_url(hd_url)
    if not sku:
        return False

    print(f"   > Bing search for HD SKU: {sku}")

    try:
        query = f"site:homedepot.com {sku}"
        driver.get(f"https://www.bing.com/search?q={query}")
        time.sleep(random.uniform(3, 5))

        wait = WebDriverWait(driver, 10)

        try:
            hd_result = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, 'homedepot.com/p/')]")))
            print(f"   > Found HD link in Bing results, clicking...")
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", hd_result)
            time.sleep(random.uniform(0.5, 1.5))
            hd_result.click()
            time.sleep(random.uniform(4, 7))

            if not is_hd_blocked(driver):
                return True
            else:
                print(f"   > Blocked after Bing click-through")
        except Exception:
            print(f"   > No HD result found on Bing")

    except Exception as e:
        print(f"   > Bing search failed: {e}")

    return False


def navigate_hd_via_site_search(driver, sku):
    """
    Fallback: search for a product SKU using HD's on-site search bar.
    Only used when Google click-through fails.
    """
    try:
        # Navigate to HD homepage if not already there
        if "homedepot.com" not in driver.current_url or is_hd_blocked(driver):
            driver.get("https://www.homedepot.com")
            time.sleep(random.uniform(4, 7))

        if is_hd_blocked(driver):
            print(f"   > Blocked on HD homepage")
            return False

        wait = WebDriverWait(driver, 15)

        search_box = wait.until(EC.presence_of_element_located(
            (By.ID, "typeahead-search-field-input")))

        search_box.click()
        time.sleep(random.uniform(0.5, 1.0))

        # Clear existing text
        search_box.send_keys(Keys.CONTROL + "a")
        time.sleep(0.1)
        search_box.send_keys(Keys.BACKSPACE)
        time.sleep(random.uniform(0.3, 0.6))

        # Type the SKU human-like
        for char in sku:
            search_box.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(random.uniform(0.5, 1.0))
        search_box.send_keys(Keys.ENTER)
        time.sleep(random.uniform(4, 7))

        if is_hd_blocked(driver):
            return False

        # HD often redirects directly to the product page for exact SKU matches
        if "/s/" in driver.current_url or "Ntt=" in driver.current_url:
            try:
                product_link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(@href, '/p/')]")))
                driver.execute_script("arguments[0].click();", product_link)
                time.sleep(random.uniform(3, 5))
            except Exception:
                print(f"   > No product found in HD search results for SKU: {sku}")
                return False

        return not is_hd_blocked(driver)

    except Exception as e:
        print(f"   > HD site search failed: {e}")
        return False


def navigate_to_hd_product(driver, hd_url, name=''):
    """
    Navigate to an HD product page via a randomly chosen source.

    Picks one source at random (GitHub Pages, Google, DuckDuckGo, Bing),
    tries it, and only falls back to others if it fails.  This distributes
    traffic across sources and avoids triggering any single engine's bot
    detection.
    """
    sources = [
        navigate_hd_via_github_pages,
        navigate_hd_via_google,
        navigate_hd_via_duckduckgo,
        navigate_hd_via_bing,
    ]
    random.shuffle(sources)

    for i, source_fn in enumerate(sources):
        if source_fn(driver, hd_url, name=name):
            return True
        if i < len(sources) - 1:
            time.sleep(random.uniform(2, 4))

    # Fallback: HD on-site search
    sku = extract_sku_from_url(hd_url)
    if sku:
        print(f"   > Trying HD on-site search...")
        clear_hd_cookies(driver)
        time.sleep(random.uniform(3, 8))
        if navigate_hd_via_site_search(driver, sku):
            return True

    # Last resort: direct URL
    print(f"   > All sources failed, trying direct URL...")
    try:
        driver.get(hd_url)
        time.sleep(random.uniform(3, 5))
        return not is_hd_blocked(driver)
    except Exception:
        return False


def browse_hd_homepage(driver):
    """
    Browse HD like a real person: visit a page, scroll around, click on
    a product or link, read it, maybe go back.  Each call picks a random
    action sequence so the pattern never repeats exactly.
    """
    try:
        # Pick a random HD page to visit
        pages = [
            "https://www.homedepot.com",
            "https://www.homedepot.com/b/Tools/N-5yc1vZc1xy",
            "https://www.homedepot.com/b/Outdoors/N-5yc1vZbx3j",
            "https://www.homedepot.com/b/Hardware/N-5yc1vZc21m",
            "https://www.homedepot.com/b/Appliances/N-5yc1vZbv09",
            "https://www.homedepot.com/b/Bath/N-5yc1vZbzb3",
            "https://www.homedepot.com/b/Lighting/N-5yc1vZbvn5",
            "https://www.homedepot.com/b/Kitchen/N-5yc1vZas6p",
            "https://www.homedepot.com/b/Paint/N-5yc1vZar2d",
            "https://www.homedepot.com/b/Electrical/N-5yc1vZbm09",
        ]
        url = random.choice(pages)
        driver.get(url)
        time.sleep(random.uniform(3, 6))

        if is_hd_blocked(driver):
            clear_hd_cookies(driver)
            time.sleep(random.uniform(5, 10))
            driver.get("https://www.homedepot.com")
            time.sleep(random.uniform(3, 5))

        # Browse and interact like a real person
        simulate_human_behavior(driver, duration=random.uniform(5, 10))

        # Pick a random action sequence
        action = random.choice([
            "click_product", "click_product", "click_product",
            "use_search", "click_nav", "just_browse",
        ])

        if action == "click_product":
            # Click on a random product card
            try:
                product_links = driver.find_elements(
                    By.XPATH,
                    "//a[contains(@href, '/p/') and .//img]"
                    " | //div[contains(@class, 'product-pod')]//a"
                    " | //a[@data-testid='product-header']")
                if product_links:
                    link = random.choice(product_links[:12])
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        link)
                    time.sleep(random.uniform(0.5, 1.5))
                    human_click(driver, link)
                    time.sleep(random.uniform(3, 6))
                    # Browse the product page
                    simulate_human_behavior(
                        driver, duration=random.uniform(5, 15))
                    # Sometimes go back, sometimes stay
                    if random.random() < 0.6:
                        driver.back()
                        time.sleep(random.uniform(2, 4))
                        simulate_human_behavior(
                            driver, duration=random.uniform(3, 6))
            except Exception:
                pass

        elif action == "use_search":
            # Type a random search term
            try:
                search_terms = [
                    "hammer", "drill", "paint", "screws", "light bulb",
                    "faucet", "door knob", "shelf", "tape", "gloves",
                    "saw blade", "sandpaper", "extension cord", "pliers",
                ]
                search_box = driver.find_element(
                    By.XPATH,
                    "//input[@data-testid='header-search-input']"
                    " | //input[@id='headerSearch']"
                    " | //input[@type='search']")
                human_click(driver, search_box)
                time.sleep(random.uniform(0.5, 1.0))
                term = random.choice(search_terms)
                # Type character by character
                for ch in term:
                    ActionChains(driver).send_keys(ch).perform()
                    time.sleep(random.uniform(0.05, 0.15))
                time.sleep(random.uniform(0.5, 1.5))
                ActionChains(driver).send_keys(Keys.RETURN).perform()
                time.sleep(random.uniform(3, 6))
                simulate_human_behavior(
                    driver, duration=random.uniform(5, 10))
                # Click a result sometimes
                if random.random() < 0.4:
                    results = driver.find_elements(
                        By.XPATH, "//a[contains(@href, '/p/')]")
                    if results:
                        r = random.choice(results[:8])
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            r)
                        time.sleep(random.uniform(0.5, 1.0))
                        human_click(driver, r)
                        time.sleep(random.uniform(3, 5))
                        simulate_human_behavior(
                            driver, duration=random.uniform(4, 8))
            except Exception:
                pass

        elif action == "click_nav":
            # Click a navigation menu item
            try:
                nav_links = driver.find_elements(
                    By.XPATH,
                    "//a[contains(@href, '/b/') and @data-testid]"
                    " | //nav//a[contains(@href, '/b/')]")
                if nav_links:
                    link = random.choice(nav_links[:10])
                    human_click(driver, link)
                    time.sleep(random.uniform(3, 6))
                    simulate_human_behavior(
                        driver, duration=random.uniform(5, 10))
            except Exception:
                pass

        else:  # just_browse
            simulate_human_behavior(
                driver, duration=random.uniform(5, 10))

    except Exception:
        pass


def _detect_ship_to_store(driver):
    """Check if 'Ship to Store' fulfillment is available on the current HD page.
    Returns True if the option exists and is not greyed out / unavailable."""
    try:
        # HD shows fulfillment options in the buy box area.
        # "Ship to Store" appears as text in a fulfillment tile/pod.
        sts_xpaths = [
            "//*[contains(text(), 'Ship to Store')]",
            "//*[contains(text(), 'ship to store')]",
            "//*[contains(text(), 'Ship To Store')]",
            "//*[@data-testid='fulfillment-ship-to-store']",
        ]
        for xpath in sts_xpaths:
            elems = driver.find_elements(By.XPATH, xpath)
            for elem in elems:
                # Check it's not struck-through or inside an unavailable container
                parent_html = elem.get_attribute("outerHTML") or ""
                if "unavailable" in parent_html.lower():
                    continue
                if "line-through" in parent_html.lower():
                    continue
                return True
    except Exception:
        pass
    return False


def _detect_delivery_available(driver):
    """Check if 'Delivery' or 'Schedule Delivery' is available."""
    try:
        delivery_xpaths = [
            "//*[contains(text(), 'Delivery')]"
            "[not(contains(text(), 'unavailable'))]",
            "//*[contains(text(), 'Schedule')]"
            "[not(contains(text(), 'unavailable'))]",
        ]
        for xpath in delivery_xpaths:
            elems = driver.find_elements(By.XPATH, xpath)
            for elem in elems:
                txt = elem.text.strip().lower()
                # Skip "Delivery unavailable" or similar
                if "unavailable" in txt or "not available" in txt:
                    continue
                if "delivery" in txt or "schedule" in txt:
                    return True
    except Exception:
        pass
    return False


def check_hd_item_tab_status(driver, name=''):
    """
    Analyzes the CURRENT active tab (Home Depot) to determine status.
    Does NOT perform navigation (driver.get).
    Simulates human browsing before reading the page to feed Akamai's
    sensor script with interaction data.

    Returns one of:
      PENNY_NEW   — $0.01 with Ship To Store or Delivery available
      PENNY       — $0.01, fulfillment unknown or pickup-only
      PENNY_OLD   — $0.01 but out of stock everywhere
      NOT_PENNY   — normal priced item in stock
      CLEARANCE   — clearance pricing shown
      BLOCKED     — Akamai block detected
    """
    print(f"   > Verifying: {name[:25]}...")

    # Simulate human browsing the product page before checking anything.
    simulate_human_behavior(driver, duration=random.uniform(5, 12))

    # --- Stage 0: Immediate Block/Error Check ---
    if "Access Denied" in driver.title:
        print(f"   > Blocked: Access Denied title.")
        return HDStatus.BLOCKED

    error_msgs = driver.find_elements(
        By.XPATH, "//div[@class='msg' and contains(text(), 'Something went wrong')]")

    if error_msgs:
        print(f"   > Blocked/Error detected: 'Oops' message found.")
        return HDStatus.BLOCKED

    wait = WebDriverWait(driver, 8)

    # --- Stage 0.5: Normal Stock Check ---
    try:
        pickup_badges = driver.find_elements(
            By.XPATH, "//div[contains(@class, 'sui-font-bold') and contains(text(), 'Pickup')]")
        if pickup_badges:
            return HDStatus.NOT_PENNY
    except Exception:
        pass

    # --- Stage 1: Main Page Text ---
    try:
        wait.until(EC.presence_of_element_located(
            (By.XPATH, "//p[contains(text(), 'See In-Store Clearance Price')]")))
        return HDStatus.CLEARANCE
    except:
        pass

    # Scroll Trigger for lazy load
    driver.execute_script("window.scrollBy(0, 700);")
    time.sleep(1.5)
    driver.execute_script("window.scrollBy(0, -500);")

    # --- Stage 1.5: Check fulfillment options for penny classification ---
    has_ship_to_store = _detect_ship_to_store(driver)
    has_delivery = _detect_delivery_available(driver)

    # --- Stage 2: Iframe Badge Check ---
    try:
        # 1. Open Store Overlay
        nearby_link = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[@data-testid='check-nearby-stores']")))
        human_click(driver, nearby_link)
        time.sleep(2)

        # 2. SWITCH TO IFRAME
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "thd-drawer-frame")))

        # 3. Scroll inside iframe
        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(1)

        # 4. Search for Badge
        badge_xpath = "//img[contains(@src, 'Value-Pricing-Clearance')]"
        badges = driver.find_elements(By.XPATH, badge_xpath)

        # Switch back before returning
        driver.switch_to.default_content()

        if len(badges) > 0:
            return HDStatus.PENNY_CANDIDATE

        # It's a penny — classify by fulfillment availability
        if has_ship_to_store or has_delivery:
            return HDStatus.PENNY_NEW
        return HDStatus.PENNY

    except Exception as e:
        driver.switch_to.default_content()  # Safety switch back

    # Fell through — likely a penny item. Check if it's out of stock.
    # Look for "Out of Stock" or "Unavailable" signals on the page.
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        # If the page says out of stock and no fulfillment is available
        if (("out of stock" in page_text or "currently unavailable" in page_text)
                and not has_ship_to_store and not has_delivery):
            return HDStatus.PENNY_OLD
    except Exception:
        pass

    if has_ship_to_store or has_delivery:
        return HDStatus.PENNY_NEW
    return HDStatus.PENNY


def has_git_updates(repo_path="."):
    """
    Checks if there are any changes (modified, staged, or untracked files)
    in the git repository.

    Returns:
        True: If there are changes.
        False: If the working tree is clean.
    """
    try:
        # --porcelain gives a machine-readable output.
        # If the output is empty, there are no changes.
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,  # Run in the specific directory
            capture_output=True,  # Capture the output so we can read it
            text=True,  # return output as string instead of bytes
            check=True  # Raise error if git command fails
        )

        # If stdout has content (after stripping whitespace), there are updates.
        return bool(result.stdout.strip())

    except subprocess.CalledProcessError:
        print("Error: The current directory is not a git repository or git failed.")
        return False
    except FileNotFoundError:
        print("Error: Git is not installed or not found in PATH.")
        return False


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
    try:
        result = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _kill_chrome():
    """Quit Chrome completely and wait for all processes to exit."""
    if not _is_chrome_running():
        return

    logging.warning("Chrome is running without debug port. Quitting Chrome...")

    # 1. Graceful quit via AppleScript (macOS)
    try:
        subprocess.run(["osascript", "-e",
                        'tell application "Google Chrome" to quit'],
                       timeout=5, capture_output=True)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Wait up to 10s for graceful exit
    for _ in range(20):
        time.sleep(0.5)
        if not _is_chrome_running():
            logging.info("Chrome quit gracefully.")
            time.sleep(1)  # extra settle time
            return

    # 2. Force kill if graceful quit didn't work
    logging.warning("Chrome didn't quit gracefully. Force killing...")
    subprocess.run(["pkill", "-9", "-x", "Google Chrome"], capture_output=True)
    time.sleep(2)

    if _is_chrome_running():
        raise RuntimeError(
            "Could not quit Chrome. Please close it manually (Cmd+Q) and try again.")
    logging.info("Chrome force-killed successfully.")


def _setup_debug_profile(real_user_data_dir, profile_dir):
    """Create a debug user-data-dir that symlinks the real profile.
    Chrome won't allow --remote-debugging-port with the default data dir,
    so we create a separate dir and symlink the profile folder into it."""
    debug_dir = DEBUG_USER_DATA_DIR
    os.makedirs(debug_dir, exist_ok=True)

    # Copy essential top-level files Chrome needs
    for fname in ["Local State"]:
        src = os.path.join(real_user_data_dir, fname)
        dst = os.path.join(debug_dir, fname)
        if os.path.isfile(src) and not os.path.exists(dst):
            import shutil
            shutil.copy2(src, dst)

    # Symlink the profile directory so cookies/sessions are shared
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
    _kill_chrome()

    # Chrome refuses --remote-debugging-port with the default user-data-dir.
    # Use a separate debug dir that symlinks to the real profile.
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
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait up to 30s for Chrome to start listening
    for i in range(60):
        time.sleep(0.5)
        if _is_port_open("localhost", port):
            logging.info("Chrome is ready on port %d", port)
            return
        # Check if process died (e.g. "Opening in existing browser session")
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

    # Timed out
    try:
        stdout, stderr = proc.communicate(timeout=2)
        output = f"stdout: {stdout.decode(errors='replace')[:500]}\n" \
                 f"stderr: {stderr.decode(errors='replace')[:500]}"
    except subprocess.TimeoutExpired:
        output = "(Chrome running but not listening on port)"
    raise RuntimeError(
        f"Chrome did not start on port {port} within 30 seconds.\n{output}\n"
        f"Try: Cmd+Q Chrome, then run the script again.")


def get_driver(chrome_profile=None, profile_dir=None, remote_debug=None):
    """Create a browser driver.

    Priority:
      1. Explicit --remote-debug flag → attach to that address
      2. Auto-detect Chrome on localhost:9222 → attach if found
      3. UC with profile (default) → bare UC

    Args:
        chrome_profile: Path to Chrome user-data-dir (your real Chrome profile).
                        Chrome must be fully closed when using this.
        profile_dir:    Profile directory name inside user-data-dir (e.g. "Default",
                        "Profile 1"). Only used with chrome_profile.
        remote_debug:   Connect to running Chrome via debugging port
                        (e.g. "localhost:9222"). Launch Chrome yourself with
                        --remote-debugging-port=9222 first.
                        If not set, auto-detects Chrome on localhost:9222.
    """
    # --- Remote debugging: explicit flag or auto-detect ---
    debug_addr = remote_debug
    if not debug_addr and _is_port_open("localhost", 9222):
        debug_addr = DEFAULT_REMOTE_DEBUG
        logging.info("Auto-detected Chrome on port 9222 — attaching via remote debug")

    if debug_addr:
        service = ChromeService(ChromeDriverManager().install())
        host, port = debug_addr.split(":")
        port = int(port)
        if not _is_port_open(host, port):
            _launch_chrome_debug(port, chrome_profile, profile_dir)
        logging.info("Connecting to Chrome at %s via remote debugging", debug_addr)
        options = webdriver.ChromeOptions()
        options.debugger_address = debug_addr
        options.page_load_strategy = 'eager'
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        return driver

    # --- Default: undetected_chromedriver (with profile if provided) ---
    # UC patches out automation flags to bypass Cloudflare and Akamai.
    # Using your real profile gives you existing cookies and sessions.
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
        # Remove lock files Chrome leaves behind
        for lock_file in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = os.path.join(chrome_profile, lock_file)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass
        time.sleep(3)  # settle time for profile release
        # Use the Chrome-Debug dir with symlink to avoid "default dir" issues
        debug_data_dir = _setup_debug_profile(chrome_profile, profile_dir)
        options.add_argument(f"--user-data-dir={debug_data_dir}")
        if profile_dir:
            options.add_argument(f"--profile-directory={profile_dir}")
    else:
        logging.info("Launching undetected Chrome (no profile)")

    # UC can be flaky connecting to Chrome — retry up to 3 times
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
                # Kill any zombie Chrome and clean locks
                _kill_chrome()
                if chrome_profile:
                    for lf in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
                        try:
                            os.remove(os.path.join(
                                DEBUG_USER_DATA_DIR, lf))
                        except FileNotFoundError:
                            pass
                time.sleep(5)
    raise last_err


def is_hd_blocked(driver):
    """Check if Home Depot has blocked the current page."""
    try:
        if "Access Denied" in driver.title:
            return True
        # Akamai bot manager "Oops" page
        error_msgs = driver.find_elements(
            By.XPATH, "//div[@class='msg' and contains(text(), 'Something went wrong')]")
        if error_msgs:
            return True
        # Also check for the error page title pattern
        if "Error Page" in driver.title:
            return True
    except Exception:
        pass
    return False


def clear_hd_cookies(driver):
    """Clear Akamai bot manager cookies to reset detection state."""
    bot_cookies = ['_bman_adv', 'bm_s', 'bm_so', 'bm_ss', 'bm_sv', 'bm_sz', '_abck', 'bm_mi']
    for name in bot_cookies:
        try:
            driver.delete_cookie(name)
        except Exception:
            pass
    # Also try via JS for domain-level cookies
    driver.execute_script("""
        ['_bman_adv','bm_s','bm_so','bm_ss','bm_sv','bm_sz','_abck','bm_mi'].forEach(n => {
            document.cookie = n + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; domain=.homedepot.com';
            document.cookie = n + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; domain=.www.homedepot.com';
        });
    """)


def login_hd_manual(driver):
    """
    Open HD sign-in page and wait for the user to log in manually.
    This handles verification codes, passkeys, and 2FA that can't
    be automated. Polls every 5s until the user completes login
    or 3 minutes elapse.
    """
    print("\n" + "=" * 60)
    print("  MANUAL LOGIN: Please log in to Home Depot in the browser.")
    print("  Complete any verification code / passkey prompts.")
    print("  The script will continue automatically once logged in.")
    print("  (Timeout: 3 minutes)")
    print("=" * 60)

    driver.get("https://www.homedepot.com/auth/view/signin")
    time.sleep(3)

    # Poll until login completes or timeout
    max_wait = 180  # 3 minutes
    elapsed = 0
    poll_interval = 5

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        # Check if we've left the signin page
        current_url = driver.current_url.lower()
        if "signin" not in current_url and "auth" not in current_url:
            print("   > Login detected! Continuing...")
            time.sleep(2)
            return True

        remaining = max_wait - elapsed
        if remaining > 0 and elapsed % 15 == 0:
            print(f"   > Waiting for login... ({remaining}s remaining)")

    print("   > Login timeout. Continuing without login.")
    return False


def warm_up_hd_session(driver, zip_code=DEFAULT_ZIP, hd_login=False):
    """
    Establish a trusted session on homedepot.com by optionally logging in,
    setting the ZIP code, and browsing briefly.
    """
    print(f"Warming up Home Depot session (ZIP: {zip_code})...")

    driver.get("https://www.homedepot.com")
    time.sleep(random.uniform(4, 7))

    if is_hd_blocked(driver):
        print("   > Blocked on initial load. Clearing cookies and retrying...")
        clear_hd_cookies(driver)
        time.sleep(random.uniform(10, 20))
        driver.get("https://www.homedepot.com")
        time.sleep(random.uniform(4, 7))

    if is_hd_blocked(driver):
        print("   > Still blocked after retry. HD session may be compromised.")
        return False

    # Manual login if requested
    if hd_login:
        login_hd_manual(driver)

    # Navigate back to homepage after login
    driver.get("https://www.homedepot.com")
    time.sleep(random.uniform(3, 5))

    wait = WebDriverWait(driver, 15)

    # Set ZIP code to establish location context
    try:
        print("   > Setting ZIP code...")
        trigger = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[@data-testid='delivery-zip-button']")))
        driver.execute_script("arguments[0].click();", trigger)

        wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//div[@data-testid='header-drawer-content']")))
        time.sleep(2)

        # Find the ZIP input — try JS first (more reliable in React drawers),
        # then use Selenium's native method to interact with it
        zip_input = driver.execute_script("""
            var drawer = document.querySelector('div[data-testid="header-drawer-content"]');
            if (!drawer) return null;
            return drawer.querySelector('input[placeholder="Enter ZIP Code"]');
        """)

        if zip_input:
            # Use JS to set value and fire React-compatible events
            # (avoids 'element not interactable' from send_keys)
            driver.execute_script("""
                var el = arguments[0];
                var zip = arguments[1];
                // Clear and set value
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(el, zip);
                // Fire React-compatible events
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            """, zip_input, zip_code)
            time.sleep(1)

            # Click Update
            update_btn = driver.find_element(
                By.XPATH,
                "//div[@data-testid='header-drawer-content']//button[contains(text(), 'Update')]")
            driver.execute_script("arguments[0].click();", update_btn)
            time.sleep(random.uniform(3, 5))
            print(f"   > ZIP set to {zip_code}")
        else:
            print("   > ZIP input not found, continuing without setting ZIP")

    except Exception as e:
        print(f"   > ZIP setup failed (non-fatal): {e}")

    # Build Akamai sensor trust with realistic browsing behavior.
    # This is critical — the sensor collects mouse/scroll/timing data
    # and flags sessions with no human interaction as bots.
    print("   > Building sensor trust (browsing HD)...")
    simulate_human_behavior(driver, duration=random.uniform(15, 30))

    # Visit 2-3 category pages to establish a natural browsing pattern
    for _ in range(random.randint(2, 3)):
        browse_hd_homepage(driver)

    print("   > HD session warm-up complete.")
    return True


def pad_row(input_list, target_char_length=ROW_SIZE, pad_char=" "):
    target_char_length -= 1
    if isinstance(input_list, dict):
        # Ensure field order matches FIELDNAMES
        input_list = [str(input_list.get(f, "")) for f in FIELDNAMES]
    tsv_string = "\t".join(str(item) for item in input_list)
    current_len = len(tsv_string)

    if current_len < target_char_length:
        return tsv_string.ljust(target_char_length, pad_char)
    elif current_len > target_char_length:
        # Don't truncate data fields — only trim the padding column
        # This prevents rows from being corrupted
        return tsv_string
    return tsv_string


def process_tracker_items(driver, deal_list, tsv_output_path):
    # Open file in append mode (or write if empty)
    open_mode = 'a+' if os.path.isfile(tsv_output_path) else 'w+'

    # Using 'r+' implies reading/writing, but standard append is safer for logs
    # However, we want to maintain the header if new
    with open(tsv_output_path, open_mode, encoding="utf-8") as f_out:
        if open_mode == "w+":
            print(pad_row(FIELDNAMES), file=f_out)
        seen_ids = [deal['name'] for deal in deal_list]
        url = "https://shenghuanjie.github.io/penny-tracker/"
        driver.get(url)

        # 1. Wait for the table to load
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

        # Store the ID of the main window so we can return to it
        main_window_handle = driver.current_window_handle

        # 2. Find all rows (skipping the first header row)
        rows = driver.find_elements(By.XPATH, "//table//tr")[1:]

        print(f"Found {len(rows)} items in the table.")

        consecutive_blocks = 0
        max_consecutive_blocks = 3

        for row in rows:
            try:
                # Re-locate cells to avoid StaleElementReferenceException
                cells = row.find_elements(By.TAG_NAME, "td")

                if not cells:
                    continue

                # Column 1: Image, 2: Name, 3: Price, 4: Status, 5: Timestamp, 6: Link
                # (Indices are 0-based: Name=1, Status=3, Link=4)
                name_element = cells[1]
                status_element = cells[3]
                timestamp_element = cells[4]
                link_container = cells[5]

                item_name = name_element.text
                status_text = status_element.text
                update_timestamp = timestamp_element.text

                timestamp = datetime.datetime.fromtimestamp(time.time()).strftime(TIMESTAMP_FORMAT)

                # Skip items already confirmed as PENNY
                if status_text == "PENNY":
                    continue

                # Skip items updated within the last 24 hours
                if is_within_x_days(timestamp, update_timestamp, 1):
                    continue

                print(f"\n[Checking] {item_name} | Status: {status_text}")

                if item_name not in seen_ids:
                    continue

                # Check TSV for more recent update
                f_out.seek(0)
                content = f_out.read()
                match_index = content.find(item_name)
                if match_index == -1:
                    continue
                # Seek back to the start of the line containing the name
                # content.find() lands in the middle of the line, so we need
                # to find the actual line start
                line_start = content.rfind("\n", 0, match_index) + 1
                f_out.seek(line_start)
                line_start_index = f_out.tell()
                data = f_out.readline()
                parts = data.strip().split("\t")
                while len(parts) < len(FIELDNAMES):
                    parts.append("")
                current_timestamp = datetime.datetime.fromtimestamp(time.time()).strftime(TIMESTAMP_FORMAT)
                tsv_update_timestamp = parts[FIELDNAMES.index('updated_at')]
                if is_within_x_days(current_timestamp, tsv_update_timestamp, 1):
                    print(f'Already updated earlier today. Skipping update for {item_name}')
                    f_out.seek(line_start_index)
                    continue
                else:
                    f_out.seek(line_start_index)

                # Extract the HD URL from the link element
                try:
                    link_element = link_container.find_element(By.XPATH, ".//a")
                except Exception:
                    link_element = link_container.find_element(By.TAG_NAME, "a")

                hd_url = link_element.get_attribute("href")
                print(f"   HD URL: {hd_url}")

                # Open HD tab if it doesn't exist, otherwise reuse it
                if len(driver.window_handles) < 2:
                    driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[-1])

                # --- RUN YOUR CHECK FUNCTION ---
                new_hd_status = HDStatus.ERROR
                try:
                    nav_ok = navigate_to_hd_product(driver, hd_url, name=item_name)
                    if nav_ok:
                        time.sleep(random.uniform(2, 4))
                        new_hd_status = check_hd_item_tab_status(driver, name=item_name)
                    else:
                        new_hd_status = HDStatus.BLOCKED
                    print(f"   >>> Result: {new_hd_status}")

                    for ideal, current_deal in enumerate(deal_list):
                        if current_deal['name'] == item_name:
                            current_deal['hd_status'] = new_hd_status
                            print(pad_row(current_deal), file=f_out)
                            break

                except Exception as e:
                    print(f"   !!! Error checking status: {e}")

                # Switch back (keep HD tab open)
                driver.switch_to.window(main_window_handle)

                # Track consecutive blocks
                if new_hd_status == HDStatus.BLOCKED:
                    consecutive_blocks += 1
                    print(f"!!! BLOCKED ({consecutive_blocks}/{max_consecutive_blocks}). Clearing cookies...")
                    if len(driver.window_handles) > 1:
                        driver.switch_to.window(driver.window_handles[-1])
                        clear_hd_cookies(driver)
                        driver.switch_to.window(main_window_handle)
                    if consecutive_blocks >= max_consecutive_blocks:
                        print(f"\n!!! {max_consecutive_blocks} consecutive blocks.")
                        print("   Waiting 60 minutes before resuming... "
                              "(Ctrl+C to stop)")
                        try:
                            for minute in range(60):
                                remaining = 60 - minute
                                ts = datetime.datetime.now().strftime("%H:%M:%S")
                                print(f"   [{ts}] Resuming in {remaining} min...",
                                      end="\r")
                                time.sleep(60)
                            print()
                        except KeyboardInterrupt:
                            print("\n   Manually cancelled. Stopping.")
                            break
                        consecutive_blocks = 0
                        continue
                    sleep_time = random.randint(60, 120)
                    print(f"   Sleeping {sleep_time}s before next item...")
                    time.sleep(sleep_time)
                else:
                    consecutive_blocks = 0  # Reset on success
                    # Browse HD homepage between checks to build trust
                    if len(driver.window_handles) > 1:
                        driver.switch_to.window(driver.window_handles[-1])
                        browse_hd_homepage(driver)
                        driver.switch_to.window(main_window_handle)
                    time.sleep(random.uniform(8, 15))

            except Exception as e:
                print(f"Skipping row due to error: {e}")
                # Ensure we are back on the main window if something failed mid-loop
                if driver.current_window_handle != main_window_handle:
                    driver.switch_to.window(main_window_handle)
                continue


def collect_all_rebel_items(driver, max_items=float('inf')):
    """
    Scroll through the RebelSavings deal page and collect all visible items.
    Returns a dict of {name: {price, url, image}} for each item found.
    """
    collected = {}
    max_patience = 3
    patience = 0

    while len(collected) < max_items:
        current_rows = driver.find_elements(By.CLASS_NAME, "summary-row")
        new_found = 0

        for row in current_rows:
            if len(collected) >= max_items:
                break
            try:
                name_elem = row.find_element(By.CLASS_NAME, "title-column")
                name = name_elem.text.splitlines()[0].strip()
                if not name or name in collected:
                    continue

                price = row.find_element(By.XPATH, "./td[3]").text.strip()
                try:
                    img_url = row.find_element(By.TAG_NAME, "img").get_attribute("src")
                except Exception:
                    img_url = ""

                # Click row to open modal and get HD URL
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                time.sleep(random.uniform(0.5, 1.0))
                driver.execute_script("arguments[0].click();", row)

                try:
                    wait_menu = WebDriverWait(driver, 5)
                    wait_menu.until(
                        EC.presence_of_element_located((By.CLASS_NAME, "close-menu-btn")))
                    hd_link_elem = wait_menu.until(EC.presence_of_element_located(
                        (By.XPATH, "//div[contains(@class, 'detail-overlay-content')]//a")))
                    hd_url = hd_link_elem.get_attribute("href")
                    close_modal(driver)
                    time.sleep(random.uniform(0.3, 0.6))
                except Exception:
                    hd_url = ""
                    close_modal(driver)

                collected[name] = {
                    "price": price,
                    "url": hd_url,
                    "image": img_url,
                }
                new_found += 1
                print(f"  [{len(collected)}] {name[:60]}")

            except Exception as e:
                continue

        if new_found > 0:
            patience = 0
        else:
            patience += 1
            if patience >= max_patience:
                break

        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(random.uniform(2, 4))

    print(f"Collected {len(collected)} items total.")
    return collected


def toggle_oos_filter(driver, enable=True):
    """Toggle the 'Show Out of Stock' checkbox on RebelSavings."""
    try:
        oos_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//label[contains(., 'Show Out of Stock')]//input"
                           " | //input[following-sibling::*[contains(text(),'Show Out of Stock')]]"
                           " | //*[contains(text(),'Show Out of Stock')]")))

        # Determine current state
        is_checked = oos_elem.get_attribute("checked") or \
            oos_elem.get_attribute("aria-checked") == "true"

        if enable and not is_checked:
            driver.execute_script("arguments[0].click();", oos_elem)
            print("'Show Out of Stock' enabled.")
        elif not enable and is_checked:
            driver.execute_script("arguments[0].click();", oos_elem)
            print("'Show Out of Stock' disabled.")
        else:
            print(f"'Show Out of Stock' already {'enabled' if enable else 'disabled'}.")

        time.sleep(random.uniform(2, 4))
        # Wait for list to refresh
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "summary-row")))
        # Scroll back to top
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        return True
    except Exception as e:
        print(f"Could not toggle 'Show Out of Stock': {e}")
        return False


def collect_rebel_items(driver, deal_list, seen_ids, tsv_output_path,
                        zip_code=DEFAULT_ZIP, max_items=float('inf'),
                        max_days=60):
    """Phase 1: Scroll RebelSavings and collect items. No HD checks.
    Opens each modal to get HD URL + stock status, then closes it.
    Uses a clean UC session (no profile) to avoid Cloudflare issues."""
    rebel_url = REBEL_SAVINGS_DEAL_URL.format(zip=zip_code)
    def _load_rebel_page(drv):
        """Navigate to RebelSavings, sort, and enable OOS filter."""
        print(f"Navigating to: {rebel_url}")
        try:
            drv.get(rebel_url)
        except Exception as e:
            print(f"Page load warning (may be OK): {e}")
        WebDriverWait(drv, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "summary-row")))
        print("Deal page loaded successfully.")
        drv.execute_script("document.body.style.zoom='75%'")
        try:
            sort_link = WebDriverWait(drv, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(text(), 'Newest')]"
                               " | //button[contains(text(), 'Newest')]"
                               " | //th[contains(text(), 'Added')]")))
            drv.execute_script("arguments[0].click();", sort_link)
            time.sleep(random.uniform(2, 4))
            WebDriverWait(drv, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "summary-row")))
            print("Sorted by Added (newest first).")
        except Exception as e:
            print(f"Could not sort by Added (non-fatal): {e}")
        toggle_oos_filter(drv, enable=True)

    print(f"\n{'='*60}")
    print(f"PHASE 1: Collecting items from RebelSavings (up to {max_days} days)")
    print(f"{'='*60}")

    _load_rebel_page(driver)

    open_mode = 'a+' if os.path.isfile(tsv_output_path) else 'w+'
    items_collected = 0
    max_patience = 3
    patience = 0
    stop_scrolling = False

    with open(tsv_output_path, open_mode, encoding="utf-8") as f_out:
        if open_mode == "w+":
            print(pad_row(FIELDNAMES), file=f_out)

        while items_collected < max_items and not stop_scrolling:
            current_rows = driver.find_elements(By.CLASS_NAME, "summary-row")
            new_found = 0

            for row in current_rows:
                if items_collected >= max_items:
                    break
                try:
                    # Check "Added" date — this is when RebelSavings
                    # first recorded the item.  We use it as
                    # original_timestamp (day resolution).
                    added_date = None
                    tds = row.find_elements(By.TAG_NAME, "td")
                    for td in tds:
                        td_text = td.text.strip()
                        try:
                            added_date = datetime.datetime.strptime(
                                td_text, "%b %d, %Y")
                            days_ago = (datetime.datetime.now() - added_date).days
                            if days_ago > max_days:
                                print(f"\nItem added {days_ago} days ago "
                                      f"({td_text}). Stopping scroll.")
                                stop_scrolling = True
                                break
                        except ValueError:
                            continue
                    if stop_scrolling:
                        break

                    name_elem = row.find_element(By.CLASS_NAME, "title-column")
                    name = name_elem.text.splitlines()[0].strip()
                    if not name or name in seen_ids:
                        continue

                    price = row.find_element(By.XPATH, "./td[3]").text.strip()
                    try:
                        img_url = row.find_element(
                            By.TAG_NAME, "img").get_attribute("src")
                    except Exception:
                        img_url = ""

                    # Open modal to get HD URL and stock status
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", row)
                    time.sleep(random.uniform(0.3, 0.6))
                    driver.execute_script("arguments[0].click();", row)

                    try:
                        wait_menu = WebDriverWait(driver, 5)
                        wait_menu.until(EC.presence_of_element_located(
                            (By.CLASS_NAME, "close-menu-btn")))

                        # Find all store entries in the modal.
                        # Each store has a link, stock status, and added date.
                        # Pick the most recently added store.
                        overlay = driver.find_element(
                            By.XPATH,
                            "//div[contains(@class, 'detail-overlay-content')]")
                        all_links = overlay.find_elements(By.TAG_NAME, "a")

                        # Try to find per-store rows/sections.
                        # RebelSavings groups each store as a block with
                        # link + status + date.  Look for common containers.
                        store_rows = overlay.find_elements(
                            By.XPATH,
                            ".//*[contains(@class, 'store-row') or "
                            "contains(@class, 'store-entry') or "
                            "contains(@class, 'store-item') or "
                            "contains(@class, 'detail-row')]")

                        hd_url = ""
                        best_date = None

                        if len(store_rows) > 1:
                            # Multiple store entries — pick newest
                            for sr in store_rows:
                                sr_text = sr.text
                                sr_link = None
                                try:
                                    sr_link = sr.find_element(
                                        By.TAG_NAME, "a"
                                    ).get_attribute("href")
                                except Exception:
                                    continue
                                # Parse date from the store row text
                                sr_date = None
                                for fmt in ("%b %d, %Y", "%m/%d/%Y",
                                            "%Y-%m-%d"):
                                    for token in re.findall(
                                            r'[A-Z][a-z]+ \d{1,2}, \d{4}'
                                            r'|\d{1,2}/\d{1,2}/\d{4}'
                                            r'|\d{4}-\d{2}-\d{2}',
                                            sr_text):
                                        try:
                                            sr_date = (
                                                datetime.datetime.strptime(
                                                    token, fmt))
                                            break
                                        except ValueError:
                                            continue
                                    if sr_date:
                                        break
                                if sr_link and (best_date is None
                                                or (sr_date and sr_date
                                                    > best_date)):
                                    best_date = sr_date
                                    hd_url = sr_link
                        else:
                            # Single store or no structured rows — use
                            # the last link (most recently added is
                            # typically appended last)
                            if all_links:
                                hd_url = all_links[-1].get_attribute("href")

                        if not hd_url and all_links:
                            hd_url = all_links[-1].get_attribute("href")

                        # Read stock status across all stores
                        stock_elems = driver.find_elements(
                            By.XPATH,
                            "//div[contains(@class, 'detail-overlay-body')]"
                            "//*[contains(@class, 'status-instock') or "
                            "contains(@class, 'status-limited') or "
                            "contains(@class, 'status-outofstock') or "
                            "contains(@class, 'instock')]")
                        in_stock = 0
                        oos = 0
                        for elem in stock_elems:
                            cls = elem.get_attribute("class") or ""
                            txt = elem.text.lower()
                            if "outofstock" in cls or "out of stock" in txt:
                                oos += 1
                            elif ("instock" in cls or "limited" in cls
                                  or "in stock" in txt or "left" in txt):
                                in_stock += 1

                        close_modal(driver)
                        time.sleep(random.uniform(0.2, 0.4))
                    except Exception:
                        hd_url = ""
                        in_stock = 0
                        oos = 0
                        close_modal(driver)

                    # Determine initial status (no HD check yet)
                    if in_stock == 0 and oos > 0:
                        hd_status = HDStatus.OUT_OF_STOCK
                    else:
                        hd_status = ""  # unchecked

                    now = datetime.datetime.fromtimestamp(
                        time.time()).strftime(TIMESTAMP_FORMAT)
                    # Use the RebelSavings "Added" date as original_timestamp
                    # (day resolution).  Fall back to current time if not found.
                    if added_date:
                        orig_ts = added_date.strftime(TIMESTAMP_FORMAT)
                    else:
                        orig_ts = now
                    current_deal = {
                        "name": name, "price": price, "url": hd_url,
                        "image": img_url, "original_timestamp": orig_ts,
                        "hd_status": hd_status, "updated_at": now,
                        "padding": ""
                    }
                    print(pad_row(current_deal), file=f_out)
                    f_out.flush()

                    deal_list.append(current_deal)
                    seen_ids.add(name)
                    items_collected += 1
                    new_found += 1

                    stock_str = f"({in_stock} in-stock, {oos} OOS)"
                    status_str = hd_status.upper() if hd_status else "UNCHECKED"
                    print(f"  [{items_collected}] {name[:55]} "
                          f"{stock_str} → {status_str}")

                except Exception as e:
                    close_modal(driver)
                    continue

            if stop_scrolling:
                break
            if new_found > 0:
                patience = 0
            else:
                patience += 1
                if patience >= max_patience:
                    print("Max patience reached. Stopping.")
                    break
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(random.uniform(2, 4))

    print(f"\nPhase 1 complete: {items_collected} new items collected.")
    return items_collected


def check_hd_status_phase(driver, deal_list, tsv_output_path,
                          chrome_profile=None, profile_dir=None,
                          remote_debug=None, zip_code=DEFAULT_ZIP,
                          hd_login=False, recheck=False, hours=8):
    """Phase 2: Check HD status using random-sized batches (1-10 tabs).

    Work is spread uniformly over *hours* hours so traffic looks natural.
    Items are processed oldest-first. Each item gets an API check first;
    only items that fail the API are queued for the browser batch.
    Items updated within the last 24 hours are skipped.

    If *recheck* is True, items with 'blocked' or 'error' status are also
    re-checked.
    """
    # Find items that need HD checking
    now_ts = datetime.datetime.fromtimestamp(
        time.time()).strftime(TIMESTAMP_FORMAT)
    skipped_24h = 0
    to_check = []
    for i, deal in enumerate(deal_list):
        status = deal.get('hd_status', '')
        url = deal.get('url', '')
        if not url or 'homedepot.com' not in url:
            continue
        # Always skip terminal statuses
        if status in (HDStatus.PENNY_NEW, HDStatus.PENNY,
                      HDStatus.PENNY_OLD, HDStatus.OUT_OF_STOCK):
            continue
        # Skip anything updated within the last 24 hours
        updated = deal.get('updated_at', '')
        if updated and is_within_x_days(now_ts, updated, 1):
            skipped_24h += 1
            continue
        # Normal mode: only unchecked items
        # Recheck mode: also include blocked/error/failure
        if status and status != 'unchecked':
            if not (recheck and status in (HDStatus.BLOCKED, HDStatus.ERROR,
                                           HDStatus.FAILURE)):
                continue
        to_check.append((i, deal))

    # Sort by original_timestamp ascending (oldest first)
    to_check.sort(key=lambda x: x[1].get('original_timestamp', ''))

    recheck_count = sum(1 for _, d in to_check
                        if d.get('hd_status') in (HDStatus.BLOCKED,
                                                  HDStatus.ERROR,
                                                  HDStatus.FAILURE))
    print(f"\n{'='*60}")
    print(f"PHASE 2: Checking {len(to_check)} items on Home Depot "
          f"(oldest first)")
    if skipped_24h:
        print(f"  Skipped {skipped_24h} items updated within 24h")
    if recheck:
        print(f"  Re-check mode: {recheck_count} blocked/error items included")
    print(f"{'='*60}")

    if not to_check:
        print("No items to check.")
        return

    checked = 0
    restart_count = 0
    max_restarts = 3

    # All items go straight to browser (API is always blocked by Akamai)
    browser_queue = list(to_check)

    # ── Pass 2: Browser batch checks (random batch size 1-10) ───────
    if not browser_queue:
        print(f"\nPhase 2 complete: {checked} items checked on HD.")
        return

    def _save_tsv():
        with open(tsv_output_path, 'w', encoding="utf-8") as f_out:
            print(pad_row(FIELDNAMES), file=f_out)
            for d in deal_list:
                print(pad_row(d), file=f_out)

    def _close_extra_tabs(keep_handle):
        """Close every tab except *keep_handle*."""
        try:
            for h in driver.window_handles:
                if h != keep_handle:
                    driver.switch_to.window(h)
                    driver.close()
            driver.switch_to.window(keep_handle)
        except Exception:
            pass

    # ── Pacing: spread work uniformly over the time window ─────────
    total_seconds = hours * 3600
    phase2_start = time.time()
    items_remaining = len(browser_queue)
    # Average seconds per item, with a floor so we don't go too fast
    avg_interval = max(total_seconds / max(items_remaining, 1), 30)
    print(f"\n   Pacing: {items_remaining} items over {hours}h "
          f"(~{avg_interval:.0f}s per item, ~{avg_interval/60:.1f}min)")

    main_window = driver.current_window_handle
    consecutive_blocks = 0
    batch_num = 0
    i = 0

    # Per-batch log file for debugging block patterns
    log_path = os.path.join(os.path.dirname(tsv_output_path) or ".",
                            "phase2_log.tsv")
    with open(log_path, 'a', encoding='utf-8') as logf:
        logf.write(f"\n# Phase 2 started: "
                   f"{datetime.datetime.now().strftime(TIMESTAMP_FORMAT)} "
                   f"| {len(browser_queue)} items | {hours}h window\n")
        logf.write("timestamp\tbatch\tsize\titem\tstatus\tnav_source\turl\n")

    def _log_item(batch_n, size, name, status, url):
        ts = datetime.datetime.now().strftime(TIMESTAMP_FORMAT)
        try:
            with open(log_path, 'a', encoding='utf-8') as logf:
                logf.write(f"{ts}\t{batch_n}\t{size}\t"
                           f"{name[:60]}\t{status}\t{url}\n")
        except Exception:
            pass

    while i < len(browser_queue):
        batch_start = time.time()

        # Random batch size 1-10 for each batch
        cur_batch_size = random.randint(1, 10)
        batch = browser_queue[i:i + cur_batch_size]
        batch_num += 1

        elapsed_total = time.time() - phase2_start
        remaining_time = max(total_seconds - elapsed_total, 0)
        items_left = len(browser_queue) - i
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] ── Batch {batch_num} (size {len(batch)}): "
              f"items {i + 1}–{i + len(batch)} "
              f"of {len(browser_queue)} | "
              f"{remaining_time/3600:.1f}h left | "
              f"{checked} checked ──")

        # Ensure Chrome is alive
        if not is_chrome_alive(driver):
            if restart_count >= max_restarts:
                print("Max driver restarts reached. Stopping HD checks.")
                break
            restart_count += 1
            print(f"   Chrome lost connectivity. Restarting "
                  f"({restart_count}/{max_restarts})...")
            driver = restart_driver(driver, chrome_profile=chrome_profile,
                                    profile_dir=profile_dir,
                                    remote_debug=remote_debug)
            warm_up_hd_session(driver, zip_code=zip_code, hd_login=hd_login)
            main_window = driver.current_window_handle

        # ── Open a tab for each item in the batch ──────────────────
        tab_map = []  # (idx, deal, tab_handle, nav_ok)
        for idx, deal in batch:
            hd_url = deal['url']
            name = deal['name']
            try:
                driver.execute_script("window.open('', '_blank');")
                new_tab = driver.window_handles[-1]
                driver.switch_to.window(new_tab)
                nav_ok = navigate_to_hd_product(driver, hd_url, name=name)
                tab_map.append((idx, deal, new_tab, nav_ok))
                print(f"   Opened: {name[:55]}"
                      f" {'✅' if nav_ok else '❌'}")
                # Stagger between tab opens
                if len(batch) > 1:
                    time.sleep(random.uniform(1.5, 3.0))
            except Exception as exc:
                print(f"   Failed to open tab for {name[:40]}: {exc}")

        if not tab_map:
            print("   No tabs opened — skipping batch")
            i += cur_batch_size
            continue

        # ── Wait for pages to finish loading ───────────────────────
        load_wait = random.uniform(5, 12)
        print(f"   Waiting {load_wait:.0f}s for {len(tab_map)} tabs to load…")
        time.sleep(load_wait)

        # ── Read each tab's status ─────────────────────────────────
        batch_checked = 0
        batch_blocked = 0
        for idx, deal, tab_handle, nav_ok in tab_map:
            name = deal['name']
            hd_url = deal.get('url', '')
            try:
                driver.switch_to.window(tab_handle)
                if nav_ok:
                    time.sleep(random.uniform(1, 2))
                    hd_status = check_hd_item_tab_status(driver, name=name)
                else:
                    hd_status = HDStatus.FAILURE

                now = datetime.datetime.fromtimestamp(
                    time.time()).strftime(TIMESTAMP_FORMAT)
                deal_list[idx]['hd_status'] = hd_status
                deal_list[idx]['updated_at'] = now
                print(f"   Result: {name[:50]} → {hd_status.upper()}")
                _log_item(batch_num, len(batch), name, hd_status, hd_url)
                checked += 1
                batch_checked += 1

                if hd_status == HDStatus.BLOCKED:
                    batch_blocked += 1
            except Exception as exc:
                print(f"   Error reading tab for {name[:40]}: {exc}")
                _log_item(batch_num, len(batch), name, "EXCEPTION", hd_url)

        # ── Close all tabs except main ─────────────────────────────
        _close_extra_tabs(main_window)

        # ── Save TSV after each batch ──────────────────────────────
        _save_tsv()

        # ── Track consecutive blocks (only BLOCKED status, not transient errors) ──
        if batch_blocked > 0 and batch_blocked >= batch_checked:
            consecutive_blocks += 1
            print(f"   Batch {batch_num}: blocked by Akamai "
                  f"({consecutive_blocks}/3)")
            if consecutive_blocks >= 3:
                # Clear cookies and wait 1 hour before resuming
                print("\n   !!! 3 consecutive blocks detected.")
                try:
                    driver.delete_all_cookies()
                    print("   Cleared all cookies.")
                except Exception:
                    pass
                _save_tsv()
                wait_mins = 60
                print(f"   Waiting {wait_mins} minutes before resuming... "
                      f"(Ctrl+C to stop)")
                try:
                    for minute in range(wait_mins):
                        remaining = wait_mins - minute
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        print(f"   [{ts}] Resuming in {remaining} min...",
                              end="\r")
                        time.sleep(60)
                    print()
                except KeyboardInterrupt:
                    print("\n   Manually cancelled. Stopping.")
                    break
                consecutive_blocks = 0
                # Warm up session again after cookie clear
                print("   Warming up HD session...")
                try:
                    warm_up_hd_session(driver, zip_code=zip_code)
                except Exception as e:
                    print(f"   Warm-up failed: {e}")
        elif batch_checked > 0:
            consecutive_blocks = 0
            # Browse HD homepage to build trust between batches
            try:
                browse_hd_homepage(driver)
            except Exception:
                pass

        i += cur_batch_size

        # ── Time-distributed pause ─────────────────────────────────
        items_left_after = len(browser_queue) - i
        if items_left_after <= 0:
            break

        elapsed_total = time.time() - phase2_start
        remaining_time = max(total_seconds - elapsed_total, 0)

        if remaining_time <= 0:
            print("   Time window exhausted. Stopping.")
            break

        target_interval = remaining_time / items_left_after
        # Cap at 10 minutes — no point waiting longer between batches
        target_interval = min(target_interval, 600)
        # Add ±30% jitter
        jitter = target_interval * random.uniform(-0.3, 0.3)
        pause = max(target_interval + jitter, 15)

        # Account for time already spent on this batch
        batch_elapsed = time.time() - batch_start
        pause = max(pause - batch_elapsed, 10)

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"   [{ts}] Sleeping {pause:.0f}s "
              f"(~{pause/60:.1f}min, {items_left_after} items in "
              f"{remaining_time/3600:.1f}h)")
        time.sleep(pause)

    elapsed = time.time() - phase2_start
    print(f"\nPhase 2 complete: {checked} items checked on HD "
          f"in {elapsed/3600:.1f}h.")
    print(f"Detailed log: {log_path}")


def main():
    parser = argparse.ArgumentParser(description="RebelSavings Scraper & Reporter")
    parser.add_argument("-n", "--max-items", type=int, default=None,
                        help="Maximum number of items to scrape")
    parser.add_argument("-f", "--from-tsv", type=str, metavar="FILE",
                        default=TSV_FILENAME, help="Path to existing CSV")
    parser.add_argument("-o", "--output-dir", type=str, default=".",
                        help="Folder to save the CSV and HTML report")
    parser.add_argument("-z", "--zip", type=str, default=DEFAULT_ZIP,
                        help="ZIP code for RebelSavings location filter (default: 94538)")
    parser.add_argument("--hd-login", action="store_true",
                        help="Pause for manual HD login before scraping (handle 2FA/passkey yourself)")
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
    parser.add_argument("-m", "--mode", choices=[
        RunningMode.CLEAN,
        RunningMode.SEARCH, RunningMode.REPORT, RunningMode.ALL, RunningMode.CHECK],
                        default=RunningMode.ALL,
                        help="Running mode.")
    parser.add_argument("--phase", choices=["1", "2", "both"], default="both",
                        help="Run only phase 1 (collect), phase 2 (HD check), "
                             "or both (default: both). Only applies to 'search' "
                             "and 'all' modes.")
    parser.add_argument("--recheck", action="store_true",
                        help="Re-check items previously marked as 'blocked' "
                             "or 'error' in Phase 2.")
    parser.add_argument("--hours", type=float, default=8,
                        help="Spread Phase 2 browser checks over this many "
                             "hours (default: 8). Work is distributed "
                             "uniformly with random jitter.")

    args = parser.parse_args()

    # Handle opt-out flag
    if args.no_chrome_profile:
        args.chrome_profile = None
        args.profile_dir = None

    # --- LOGGING SETUP ---
    log_path = os.path.join(args.output_dir or ".", "rebelsavings.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Redirect print() to also go to the log file
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
    logging.info("Settings: phase=%s, recheck=%s, hours=%.1f",
                 args.phase, args.recheck, args.hours)

    if args.output_dir and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    html_filename = "index.html"
    deal_list = []
    report_path = os.path.join(args.output_dir, html_filename)
    tsv_output_path = os.path.join(args.output_dir, TSV_FILENAME)
    backuptsv_output_path = os.path.join(args.output_dir, BACKUP_TSV_FILENAME)

    # --- LOAD EXISTING DATA ---
    if os.path.isfile(args.from_tsv):
        print(f"Reading data from {args.from_tsv}...")
        skipped = 0
        try:
            with open(args.from_tsv, "r", encoding="utf-8") as f_out:
                f_out.readline()  # skip header
                for row in f_out:
                    parts = row.strip().split("\t")
                    parts = [p.strip() for p in parts]
                    # Need at least a name (first field) to keep the row
                    if not parts or not parts[0] or parts[0] == "name":
                        skipped += 1
                        continue
                    # Pad missing fields with defaults
                    while len(parts) < len(FIELDNAMES):
                        parts.append("")
                    row_dict = dict(zip(FIELDNAMES, parts[:len(FIELDNAMES)]))
                    # Fill in defaults for missing/empty fields
                    if not row_dict.get("price"):
                        row_dict["price"] = "N/A"
                    if not row_dict.get("url"):
                        row_dict["url"] = ""
                    if not row_dict.get("image"):
                        row_dict["image"] = ""
                    if not row_dict.get("hd_status"):
                        row_dict["hd_status"] = "unchecked"
                    if not row_dict.get("original_timestamp"):
                        row_dict["original_timestamp"] = datetime.datetime.now().strftime(TIMESTAMP_FORMAT)
                    if not row_dict.get("updated_at"):
                        row_dict["updated_at"] = ""
                    deal_list.append(row_dict)
        except Exception as e:
            print(f"Error reading TSV: {e}")
        print(f"Loaded {len(deal_list)} items from TSV."
              f"{f' (skipped {skipped} bad rows)' if skipped else ''}")

        # Rewrite TSV to fix any previously truncated rows
        if deal_list:
            with open(args.from_tsv, "w", encoding="utf-8") as f_out:
                print(pad_row(FIELDNAMES), file=f_out)
                for deal in deal_list:
                    print(pad_row(deal), file=f_out)
            print(f"TSV repaired: {len(deal_list)} rows written.")

    # --- CLEANING OLD DATA ---
    if args.mode in [RunningMode.CLEAN] and deal_list:
        new_deal_list = []
        seen_ids = set()
        now_ts = datetime.datetime.fromtimestamp(
            time.time()).strftime(TIMESTAMP_FORMAT)
        removed_old = 0
        removed_penny_old = 0
        removed_dup = 0
        for deal_row in deal_list:
            org_timestamp = deal_row.get("original_timestamp", "")
            status = deal_row.get("hd_status", "")

            # Remove penny items older than 30 days
            if status in (HDStatus.PENNY_NEW, HDStatus.PENNY,
                          HDStatus.PENNY_OLD) and org_timestamp:
                if not is_within_x_days(org_timestamp, now_ts, days=30):
                    removed_penny_old += 1
                    continue

            # Remove all items older than 60 days
            if org_timestamp and not is_within_x_days(
                    org_timestamp, now_ts, days=60):
                removed_old += 1
                continue

            # Deduplicate by name
            name = deal_row.get("name", "")
            if name in seen_ids:
                removed_dup += 1
                continue
            seen_ids.add(name)
            new_deal_list.append(deal_row)

        total_removed = removed_old + removed_penny_old + removed_dup
        if total_removed > 0:
            print(f"Cleaned {total_removed} items: "
                  f"{removed_penny_old} penny >30d, "
                  f"{removed_old} other >60d, "
                  f"{removed_dup} duplicates.")
            shutil.copyfile(args.from_tsv, backuptsv_output_path)
            deal_list = new_deal_list
            with open(tsv_output_path, 'w', encoding="utf-8") as fp:
                print(pad_row(FIELDNAMES), file=fp)
                for deal_row in new_deal_list:
                    print(pad_row(deal_row), file=fp)
        else:
            print("Nothing to clean.")

    # --- SEARCH AND CHECK (TWO-PHASE) ---
    if args.mode in [RunningMode.SEARCH, RunningMode.ALL]:
        run_phase1 = args.phase in ("1", "both")
        run_phase2 = args.phase in ("2", "both")
        seen_ids = set(deal['name'] for deal in deal_list)
        max_items = args.max_items if args.max_items is not None else float('inf')

        # --- SETUP: Launch HD driver if Phase 2 will run ---
        hd_driver = None
        if run_phase2:
            hd_driver = get_driver(chrome_profile=args.chrome_profile,
                                   profile_dir=args.profile_dir,
                                   remote_debug=args.remote_debug)
            print(f"\n{'='*60}")
            print("SETUP: Warming up HD session with your profile")
            print(f"{'='*60}")
            warm_up_hd_session(hd_driver, zip_code=args.zip,
                               hd_login=args.hd_login)
            print("HD session ready. You can walk away now.\n")

        try:
            # --- PHASE 1: Collect from RebelSavings (separate clean UC) ---
            if run_phase1:
                rebel_driver = get_driver(chrome_profile=None,
                                          profile_dir=None,
                                          remote_debug=None)
                try:
                    collect_rebel_items(rebel_driver, deal_list, seen_ids,
                                        tsv_output_path,
                                        zip_code=args.zip,
                                        max_items=max_items,
                                        max_days=60)
                finally:
                    rebel_driver.quit()
                    print("Phase 1 driver closed.")

                # Git push after collection
                print("\n=== Pushing collected data ===")
                generate_html_report(deal_list, report_path)
                try:
                    subprocess.run(["git", "add", "-A"],
                                   cwd=args.output_dir, check=True)
                    subprocess.run(["git", "commit", "-m",
                                    "update data (collection)"],
                                   cwd=args.output_dir, check=True)
                    subprocess.run(
                        ["git", "push"], cwd=args.output_dir,
                        env={**os.environ,
                             "GIT_SSH_COMMAND":
                                 "ssh -i ~/.ssh/id_rsa_public_github"
                                 " -o IdentitiesOnly=yes"},
                        check=True)
                    print("Collection data pushed.")
                except subprocess.CalledProcessError as e:
                    print(f"Git push failed (non-fatal): {e}")
            else:
                print(f"\nSkipping Phase 1 (--phase {args.phase})")

            # --- PHASE 2: HD checks ---
            if run_phase2 and hd_driver:
                print(f"\n{'='*60}")
                print(f"PHASE 2: HD checks"
                      f"{' (re-checking blocked/error)' if args.recheck else ''}")
                print(f"{'='*60}")
                check_hd_status_phase(hd_driver, deal_list, tsv_output_path,
                                      chrome_profile=args.chrome_profile,
                                      profile_dir=args.profile_dir,
                                      remote_debug=args.remote_debug,
                                      zip_code=args.zip,
                                      hd_login=False,
                                      recheck=args.recheck,
                                      hours=args.hours)
            elif run_phase2:
                print("No HD driver available — skipping Phase 2")
            else:
                print(f"\nSkipping Phase 2 (--phase {args.phase})")
        finally:
            if hd_driver:
                hd_driver.quit()
                print("HD driver closed.")

        # Git push after HD checks (or after phase 1 if phase 2 skipped)
        if run_phase2:
            print("\n=== Pushing HD check results ===")
            generate_html_report(deal_list, report_path)
            try:
                subprocess.run(["git", "add", "-A"],
                               cwd=args.output_dir, check=True)
                subprocess.run(["git", "commit", "-m",
                                "update data (HD checks)"],
                               cwd=args.output_dir, check=True)
                subprocess.run(
                    ["git", "push"], cwd=args.output_dir,
                    env={**os.environ,
                         "GIT_SSH_COMMAND":
                             "ssh -i ~/.ssh/id_rsa_public_github"
                             " -o IdentitiesOnly=yes"},
                    check=True)
                print("HD check data pushed.")
            except subprocess.CalledProcessError as e:
                print(f"Git push failed (non-fatal): {e}")

    # --- REPORT ONLY MODE ---
    elif args.mode == RunningMode.REPORT:
        print("Generating report from existing TSV...")
        generate_html_report(deal_list, report_path)

    elif args.mode == RunningMode.CHECK:

        # os.system('source update.sh')
        #
        # if has_git_updates():
        #     time.sleep(30)

        driver = get_driver(chrome_profile=args.chrome_profile,
                            profile_dir=args.profile_dir,
                            remote_debug=args.remote_debug)
        warm_up_hd_session(driver, zip_code=args.zip, hd_login=args.hd_login)
        process_tracker_items(driver, deal_list, tsv_output_path)

    # --- ALWAYS generate final report at end ---
    print("\n=== Generating final report ===")
    # Reload from TSV to pick up any changes from phases
    if os.path.isfile(tsv_output_path):
        deal_list = []
        with open(tsv_output_path, "r", encoding="utf-8") as f:
            f.readline()  # skip header
            for row in f:
                parts = row.strip().split("\t")
                parts = [p.strip() for p in parts]
                if not parts or not parts[0] or parts[0] == "name":
                    continue
                while len(parts) < len(FIELDNAMES):
                    parts.append("")
                row_dict = dict(zip(FIELDNAMES, parts[:len(FIELDNAMES)]))
                if not row_dict.get("price"):
                    row_dict["price"] = "N/A"
                if not row_dict.get("hd_status"):
                    row_dict["hd_status"] = "unchecked"
                if not row_dict.get("original_timestamp"):
                    row_dict["original_timestamp"] = ""
                if not row_dict.get("updated_at"):
                    row_dict["updated_at"] = ""
                deal_list.append(row_dict)
    generate_html_report(deal_list, report_path)
    print(f"Report written to {report_path} ({len(deal_list)} items)")


if __name__ == "__main__":
    main()