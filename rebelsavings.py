import datetime
import re
import shutil
import subprocess
import time
import os
import argparse
import random

import undetected_chromedriver as uc
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
ROW_SIZE = 1000  # Target bytes per line
FIELDNAMES = ["name", "price", "url", "image", "original_timestamp", "hd_status",
              "updated_at", "padding"]
NEWLINE = '\n'
TSV_FILENAME = "rebel_final_report.tsv"
BACKUP_TSV_FILENAME = "rebel_final_report_backup.tsv"
DEFAULT_ZIP = "94538"
REBEL_SAVINGS_DEAL_URL = "https://www.rebelsavings.com/home-depot?zip={zip}"


def human_click(driver, element):
    """
    Robust clicker for Selenium 4.9.
    Calculates the 'Visual Center' of a zoomed element to ensure the click hits.
    """
    try:
        # --- 1. DETECT ZOOM LEVEL ---
        # Get the CSS zoom value (e.g., "0.75" or "75%")
        zoom_style = element.value_of_css_property("zoom")
        zoom_factor = 1.0

        if zoom_style and zoom_style != 'normal':
            clean_zoom = zoom_style.strip().replace('%', '')
            try:
                val = float(clean_zoom)
                # Normalize: 75 -> 0.75, 0.75 -> 0.75
                zoom_factor = val / 100.0 if val > 1 else val
            except ValueError:
                pass

        # --- 2. CALCULATE VISUAL TARGET ---
        # Selenium sees the "Logical Size" (e.g., 100px).
        # We need the "Visual Size" (e.g., 75px).
        rect = element.rect # .rect gets {'x':, 'y':, 'width':, 'height':}

        logical_width = rect['width']
        logical_height = rect['height']

        # The visual box is smaller/larger based on zoom
        visual_width = logical_width * zoom_factor
        visual_height = logical_height * zoom_factor

        # --- 3. CALCULATE OFFSET (Relative to Top-Left) ---
        # We want to click the Center of the VISUAL box, not the logical box.
        center_x = visual_width / 2
        center_y = visual_height / 2

        # Add small random jitter (approx 10% of size)
        jitter_x = random.randint(-int(visual_width * 0.1), int(visual_width * 0.1))
        jitter_y = random.randint(-int(visual_height * 0.1), int(visual_height * 0.1))

        # Final Target relative to the element's Top-Left corner
        target_x = int(center_x + jitter_x)
        target_y = int(center_y + jitter_y)

        # Safety: Ensure we don't accidentally jitter outside the visual box
        target_x = max(1, min(target_x, int(visual_width) - 1))
        target_y = max(1, min(target_y, int(visual_height) - 1))

        # --- 4. EXECUTE MOVE & CLICK ---
        actions = ActionChains(driver)

        # This moves to the top-left of the element, then shifts by our calculated pixels
        actions.move_to_element_with_offset(element, target_x, target_y)

        time.sleep(random.uniform(0.1, 0.3)) # Human hesitation
        actions.click()
        actions.perform()

        wait = WebDriverWait(driver, 5)
        wait.until(EC.number_of_windows_to_be(2))

    except Exception as e:
        print(f"Human click failed: {e}")
        print("Engaging Backup: Force JS Click")
        # 100% Reliable Backup (Does not use mouse, just fires event)
        driver.execute_script("arguments[0].click();", element)


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
    PENNY = 'penny'
    NOT_PENNY = 'not_penny'
    PENNY_CANDIDATE = 'penny_candidate'
    CLEARANCE = 'clearance'
    OUT_OF_STOCK = 'out_of_stock'
    ERROR = 'error'
    FAILURE = 'failure'
    BLOCKED = 'blocked'


def generate_html_report(deals, output_path):
    """Creates a visual HTML report with images, status colors, and timestamps."""

    # --- SORTING LOGIC ---
    # Define priority: Penny items first, then candidates, then clearance, then failures.
    status_priority = {
        'penny': 0,
        'penny_candidate': 1,
        'out_of_stock': 2,
        'clearance': 3,
        'not_penny': 4,
        'blocked': 5,
        'error': 6,
        'failure': 7,
        'unchecked': 8
    }

    # Sort in-place
    deals.sort(key=lambda d: (
        status_priority.get(d.get('hd_status'), 99),
        d.get('original_timestamp', '')
    ))
    # ---------------------

    html = """
    <html><head><style>
        body { font-family: Arial, sans-serif; background: #f0f2f5; padding: 20px; }
        h2 { color: #333; }
        table { width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        th, td { padding: 12px; border: 1px solid #ddd; text-align: left; vertical-align: middle; }
        th { background: #f96302; color: white; font-weight: bold; } /* Home Depot Orange */
        tr:nth-child(even) { background-color: #f9f9f9; }
        img { width: 70px; height: auto; border-radius: 4px; object-fit: cover; }

        /* Status Colors */
        .penny { color: #3498db; font-weight: bold; }             /* Blue: Likely Penny */
        .not_penny { color: #e74c3c; font-weight: bold; }         /* Red: Definite No */
        .penny_candidate { color: #f39c12; font-weight: bold; }   /* Orange: Strong Maybe */
        .clearance { color: #2ecc71; font-weight: bold; }         /* Green: Verified Clearance */
        .error { color: #8e44ad; font-weight: bold; }             /* Purple: Code Exception */
        .failure { color: #95a5a6; font-style: italic; }          /* Grey: Page Crash/Missing Data */
        .out_of_stock { color: #7f8c8d; font-weight: bold; font-style: italic; } /* Grey: Out of Stock on RebelSavings */
        .blocked { color: #c0392b; font-weight: bold; text-decoration: underline; } /* Dark Red: Bot Detected */

    </style></head><body>
        <h2>Home Depot Clearance Report</h2>
        <table><tr><th>Image</th><th>Name</th><th>Price</th><th>Status</th><th>Updated At</th><th>Link</th></tr>"""

    for d in deals:
        status = d.get('hd_status', 'unchecked')
        if not status: status = 'unchecked'

        image_src = d.get('image', '')
        name = d.get('name', 'Unknown')
        price = d.get('price', 'N/A')
        url = d.get('url', '#')

        # safely get updated_at, default to empty string if missing
        timestamp = d.get('updated_at', '')

        # Added timestamp cell before the Link cell
        html += f"""<tr>
            <td><img src="{image_src}"></td>
            <td>{name}</td>
            <td>{price}</td>
            <td class="{status}">{status.upper()}</td>
            <td>{timestamp}</td>
            <td><a href="{url}" target="_blank">Link</a></td>
        </tr>"""

    html += "</table></body></html>"

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


def navigate_hd_via_google(driver, hd_url, name=''):
    """
    Navigate to a Home Depot product page via Google search.
    Searching on Google and clicking through gives a legitimate Referer
    header and mimics real user behavior, which avoids Akamai bot detection.

    Falls back to HD on-site search, then direct URL as last resort.
    """
    sku = extract_sku_from_url(hd_url)
    if not sku:
        print(f"   > Could not extract SKU from URL: {hd_url}")
        return False

    print(f"   > Google search for HD SKU: {sku}")

    try:
        # Search Google for the SKU on homedepot.com
        query = f"site:homedepot.com {sku}"
        driver.get(f"https://www.google.com/search?q={query}")
        time.sleep(random.uniform(3, 5))

        wait = WebDriverWait(driver, 10)

        # Look for a homedepot.com link in Google results
        try:
            hd_result = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, 'homedepot.com/p/')]")))
            print(f"   > Found HD link in Google results, clicking...")
            # Scroll to it first
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", hd_result)
            time.sleep(random.uniform(0.5, 1.5))
            hd_result.click()
            time.sleep(random.uniform(4, 7))

            if not is_hd_blocked(driver):
                return True
            else:
                print(f"   > Blocked after Google click-through")
        except Exception:
            print(f"   > No HD result found on Google, trying HD search...")

    except Exception as e:
        print(f"   > Google search failed: {e}")

    # Fallback: HD on-site search
    return navigate_hd_via_site_search(driver, sku)


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
    Main entry point for navigating to an HD product page.
    Tries strategies in order: Google click-through → HD site search → direct URL.
    Returns True if navigation succeeded (not blocked), False otherwise.
    """
    # Strategy 1: Google search click-through
    if navigate_hd_via_google(driver, hd_url, name=name):
        return True

    # Strategy 2: Clear cookies, wait, try Google again
    print(f"   > Clearing cookies and retrying via Google...")
    clear_hd_cookies(driver)
    time.sleep(random.uniform(15, 30))
    if navigate_hd_via_google(driver, hd_url, name=name):
        return True

    # Strategy 3: Direct URL as last resort
    print(f"   > All strategies failed, trying direct URL...")
    try:
        driver.get(hd_url)
        time.sleep(random.uniform(3, 5))
        return not is_hd_blocked(driver)
    except Exception:
        return False


def browse_hd_homepage(driver):
    """
    Navigate back to HD homepage and simulate brief browsing.
    Builds Akamai sensor trust between product checks.
    """
    try:
        driver.get("https://www.homedepot.com")
        time.sleep(random.uniform(3, 5))

        if is_hd_blocked(driver):
            clear_hd_cookies(driver)
            time.sleep(random.uniform(5, 10))
            driver.get("https://www.homedepot.com")
            time.sleep(random.uniform(3, 5))

        # Simulate browsing
        driver.execute_script("window.scrollBy(0, %d);" % random.randint(200, 500))
        time.sleep(random.uniform(1, 3))
        driver.execute_script("window.scrollBy(0, %d);" % random.randint(-300, -100))
        time.sleep(random.uniform(1, 2))
    except Exception:
        pass


def check_hd_item_tab_status(driver, name=''):
    """
    Analyzes the CURRENT active tab (Home Depot) to determine status.
    Does NOT perform navigation (driver.get).
    """
    print(f"   > Verifying: {name[:25]}...")

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
            # print(f"   > Normal stock found.")
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

    # --- Stage 2: Iframe Badge Check ---
    try:
        # 1. Open Store Overlay
        nearby_link = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[@data-testid='check-nearby-stores']")))
        # driver.execute_script("arguments[0].click();", nearby_link)
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

        status = HDStatus.PENNY_CANDIDATE if len(badges) > 0 else HDStatus.PENNY
        return status

    except Exception as e:
        driver.switch_to.default_content()  # Safety switch back

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


def get_driver():
    options = uc.ChromeOptions()
    # 1. Disable the popup blocking flag explicitly
    options.add_argument("--disable-popup-blocking")

    # Don't wait for full page load — React SPAs fire DOMContentLoaded
    # early but keep loading JS bundles that can cause 300s timeouts
    options.page_load_strategy = 'eager'

    # 2. Set the content setting preference to '1' (Allow) for popups
    #    0 = Default, 1 = Allow, 2 = Block
    prefs = {
        "profile.default_content_setting_values.popups": 1,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    # Initialize the driver with these options
    options.add_argument("--window-size=1920,1080")
    # Force version 138 to match your browser if needed, else remove version_main
    driver = uc.Chrome(options=options, version_main=138)
    # Set page load timeout to 60s as a safety net
    driver.set_page_load_timeout(60)
    return driver


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


def warm_up_hd_session(driver, zip_code=DEFAULT_ZIP):
    """
    Establish a trusted session on homedepot.com by visiting the homepage,
    setting the ZIP code, and browsing briefly. This builds up the Akamai
    sensor data that makes subsequent requests look legitimate.
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

    # Simulate brief browsing to build sensor data
    print("   > Simulating browsing behavior...")
    driver.execute_script("window.scrollBy(0, 400);")
    time.sleep(random.uniform(1, 2))
    driver.execute_script("window.scrollBy(0, -200);")
    time.sleep(random.uniform(1, 2))

    print("   > HD session warm-up complete.")
    return True


def pad_row(input_list, target_char_length=ROW_SIZE, pad_char=" "):
    target_char_length -= 1
    if isinstance(input_list, dict):
        input_list = input_list.values()
    tsv_string = "\t".join(str(item) for item in input_list)
    current_len = len(tsv_string)

    if current_len < target_char_length:
        return tsv_string.ljust(target_char_length, pad_char)
    elif current_len > target_char_length:
        return tsv_string[:target_char_length]
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
                        print(f"!!! {max_consecutive_blocks} consecutive blocks. Stopping to avoid IP ban.")
                        break
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
                    close_btn = wait_menu.until(
                        EC.element_to_be_clickable((By.CLASS_NAME, "close-menu-btn")))
                    hd_link_elem = wait_menu.until(EC.presence_of_element_located(
                        (By.XPATH, "//div[contains(@class, 'detail-overlay-content')]//a")))
                    hd_url = hd_link_elem.get_attribute("href")
                    close_btn.click()
                    time.sleep(random.uniform(0.3, 0.6))
                except Exception:
                    hd_url = ""
                    # Try to close modal if it opened
                    try:
                        driver.find_element(By.CLASS_NAME, "close-menu-btn").click()
                    except Exception:
                        pass

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
    parser.add_argument("-m", "--mode", choices=[
        RunningMode.CLEAN,
        RunningMode.SEARCH, RunningMode.REPORT, RunningMode.ALL, RunningMode.CHECK],
                        default=RunningMode.ALL,
                        help="Running mode.")

    args = parser.parse_args()

    if args.output_dir and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    html_filename = "index.html"
    deal_list = []
    report_path = os.path.join(args.output_dir, html_filename)
    tsv_output_path = os.path.join(args.output_dir, TSV_FILENAME)
    backuptsv_output_path = os.path.join(args.output_dir, BACKUP_TSV_FILENAME)

    # --- LOAD EXISTING DATA ---
    # Minimum number of fields required to parse a row (excluding padding)
    min_fields = len(FIELDNAMES) - 1  # padding column may be stripped

    if os.path.isfile(args.from_tsv):
        print(f"Reading data from {args.from_tsv}...")
        try:
            with open(args.from_tsv, "r", encoding="utf-8") as f_out:
                f_out.readline()  # skip header
                for row in f_out:
                    parts = row.strip().split("\t")
                    if len(parts) >= min_fields:
                        # Pad parts to match FIELDNAMES length if padding was stripped
                        while len(parts) < len(FIELDNAMES):
                            parts.append("")
                        row_dict = dict(zip(FIELDNAMES, parts[:len(FIELDNAMES)]))
                        deal_list.append(row_dict)
        except Exception as e:
            print(f"Error reading TSV: {e}")

    # --- CLEANING OLD DATA ---
    if args.mode in [RunningMode.CLEAN] and deal_list:
        new_deal_list = []
        seen_ids = set()
        for deal_row in deal_list:
            org_timestamp = deal_row["original_timestamp"]
            timestamp = datetime.datetime.fromtimestamp(time.time()).strftime(TIMESTAMP_FORMAT)
            if org_timestamp is None or is_within_x_days(org_timestamp, timestamp, days=60):
                if deal_row["name"] not in seen_ids:
                    seen_ids.add(deal_row["name"])
                    new_deal_list.append(deal_row)
                else:
                    pass

        if len(new_deal_list) != len(deal_list):
            print(f"Cleaned {len(deal_list) - len(new_deal_list)} old or duplicated items.")
            shutil.copyfile(args.from_tsv, backuptsv_output_path)
            deal_list = new_deal_list  # Update memory
            with open(tsv_output_path, 'w', encoding="utf-8") as fp:
                print(pad_row(FIELDNAMES), file=fp)
                for deal_row in new_deal_list:
                    print(pad_row(deal_row), file=fp)

    # --- SEARCH AND CHECK (MERGED) ---
    if args.mode in [RunningMode.SEARCH, RunningMode.ALL]:
        driver = get_driver()
        try:
            seen_ids = set(deal['name'] for deal in deal_list)
            max_items = args.max_items if args.max_items is not None else float('inf')

            print(f"Starting item collection & verification (Max: {max_items})...")

            # Warm up HD session first to build Akamai trust
            warm_up_hd_session(driver, zip_code=args.zip)

            rebel_url = REBEL_SAVINGS_DEAL_URL.format(zip=args.zip)
            print(f"Navigating to: {rebel_url}")
            try:
                driver.get(rebel_url)
            except Exception as e:
                # Page load timeout is OK with eager strategy — DOM may already be ready
                print(f"Page load warning (may be OK): {e}")
            # Wait for the React app to load and render deal rows
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "summary-row")))
            print("Deal page loaded successfully.")
            driver.execute_script("document.body.style.zoom='75%'")

            main_window = driver.current_window_handle

            # ============================================================
            # PHASE 1: Collect all IN-STOCK items (OOS filter OFF)
            # ============================================================
            print("\n=== PHASE 1: Collecting in-stock items ===")
            toggle_oos_filter(driver, enable=False)
            in_stock_items = collect_all_rebel_items(driver, max_items=max_items)

            # ============================================================
            # PHASE 2: Enable OOS filter and collect ALL items
            # ============================================================
            print("\n=== PHASE 2: Collecting all items (including out-of-stock) ===")
            toggle_oos_filter(driver, enable=True)
            all_items = collect_all_rebel_items(driver, max_items=max_items)

            # ============================================================
            # PHASE 3: Diff to find out-of-stock items
            # ============================================================
            oos_names = set(all_items.keys()) - set(in_stock_items.keys())
            print(f"\n=== Found {len(oos_names)} out-of-stock items, "
                  f"{len(in_stock_items)} in-stock items ===")

            # ============================================================
            # PHASE 4: Save OOS items immediately (no HD check needed)
            # ============================================================
            open_mode = 'a+' if os.path.isfile(tsv_output_path) else 'w+'
            with open(tsv_output_path, open_mode, encoding="utf-8") as f_out:
                if open_mode == "w+":
                    print(pad_row(FIELDNAMES), file=f_out)

                now = datetime.datetime.fromtimestamp(time.time()).strftime(TIMESTAMP_FORMAT)

                for oos_name in oos_names:
                    item = all_items[oos_name]

                    # Check if already in TSV
                    if oos_name in seen_ids:
                        # Read existing entry to check status
                        f_out.seek(0)
                        content = f_out.read()
                        match_index = content.find(oos_name)
                        if match_index != -1:
                            line_start = content.rfind("\n", 0, match_index) + 1
                            f_out.seek(line_start)
                            data = f_out.readline()
                            parts = data.strip().split("\t")
                            while len(parts) < len(FIELDNAMES):
                                parts.append("")
                            existing_status = parts[FIELDNAMES.index('hd_status')]
                            # Don't overwrite PENNY status
                            if existing_status == HDStatus.PENNY:
                                continue
                        f_out.seek(0, 2)

                    current_deal = {
                        "name": oos_name,
                        "price": item["price"],
                        "url": item["url"],
                        "image": item["image"],
                        "original_timestamp": now,
                        "hd_status": HDStatus.OUT_OF_STOCK,
                        "updated_at": now,
                        "padding": ""
                    }
                    print(pad_row(current_deal), file=f_out)
                    f_out.flush()

                    if oos_name not in seen_ids:
                        deal_list.append(current_deal)
                        seen_ids.add(oos_name)

                    print(f"  [OOS] {oos_name[:60]}")

                print(f"\nSaved {len(oos_names)} out-of-stock items.")

                # Also save in-stock items that haven't been seen yet
                # (so the report includes them even before HD check)
                for name, item in in_stock_items.items():
                    if name not in seen_ids:
                        current_deal = {
                            "name": name,
                            "price": item["price"],
                            "url": item["url"],
                            "image": item["image"],
                            "original_timestamp": now,
                            "hd_status": "",
                            "updated_at": "",
                            "padding": ""
                        }
                        print(pad_row(current_deal), file=f_out)
                        f_out.flush()
                        deal_list.append(current_deal)
                        seen_ids.add(name)

                f_out.flush()

            # ============================================================
            # PHASE 4.5: Generate report, commit and push OOS data
            # ============================================================
            print("\n=== Generating interim report and pushing OOS data ===")
            generate_html_report(deal_list, report_path)
            try:
                subprocess.run(["git", "add", "-A"], cwd=args.output_dir, check=True)
                subprocess.run(["git", "commit", "-m", "update data"],
                               cwd=args.output_dir, check=True)
                subprocess.run(
                    ["git", "push"],
                    cwd=args.output_dir,
                    env={**os.environ,
                         "GIT_SSH_COMMAND": "ssh -i ~/.ssh/id_rsa_public_github -o IdentitiesOnly=yes"},
                    check=True)
                print("OOS data committed and pushed.")
            except subprocess.CalledProcessError as e:
                print(f"Git commit/push failed (non-fatal): {e}")

            # Reopen TSV for Phase 5
            with open(tsv_output_path, "a+", encoding="utf-8") as f_out:

                # ============================================================
                # PHASE 5: Check in-stock items on HD (with long delays)
                # ============================================================
                print(f"\n=== PHASE 5: Checking {len(in_stock_items)} in-stock items on HD ===")

                consecutive_blocks = 0
                max_consecutive_blocks = 3
                items_checked = 0

                for name, item in in_stock_items.items():
                    if items_checked >= max_items:
                        break

                    # Skip items already confirmed as penny or recently updated
                    if name in seen_ids:
                        f_out.seek(0)
                        content = f_out.read()
                        match_index = content.find(name)
                        if match_index != -1:
                            line_start = content.rfind("\n", 0, match_index) + 1
                            f_out.seek(line_start)
                            data = f_out.readline()
                            parts = data.strip().split("\t")
                            while len(parts) < len(FIELDNAMES):
                                parts.append("")

                            existing_status = parts[FIELDNAMES.index('hd_status')]
                            if existing_status == HDStatus.PENNY:
                                print(f'Already confirmed PENNY. Skipping {name[:50]}')
                                continue

                            update_timestamp = parts[FIELDNAMES.index('updated_at')]
                            current_timestamp = datetime.datetime.fromtimestamp(
                                time.time()).strftime(TIMESTAMP_FORMAT)
                            if is_within_x_days(current_timestamp, update_timestamp, 1):
                                print(f'Updated today. Skipping {name[:50]}')
                                continue

                        f_out.seek(0, 2)
                        duplicated_item = True
                    else:
                        duplicated_item = False

                    hd_url = item["url"]
                    if not hd_url:
                        continue

                    print(f"\n[{items_checked + 1}] Checking: {name[:60]}")
                    print(f"   HD URL: {hd_url}")

                    # Open HD tab if it doesn't exist, otherwise reuse it
                    if len(driver.window_handles) < 2:
                        driver.execute_script("window.open('');")
                    driver.switch_to.window(driver.window_handles[-1])

                    hd_status = HDStatus.ERROR
                    try:
                        nav_ok = navigate_to_hd_product(driver, hd_url, name=name)
                        if nav_ok:
                            time.sleep(random.uniform(2, 4))
                            hd_status = check_hd_item_tab_status(driver, name=name)
                        else:
                            hd_status = HDStatus.BLOCKED
                    except Exception as e:
                        print(f"   Error checking tab: {e}")
                        hd_status = HDStatus.ERROR

                    # Switch back to RebelSavings (keep HD tab open)
                    driver.switch_to.window(main_window)

                    # Save result
                    current_deal = {
                        "name": name,
                        "price": item["price"],
                        "url": hd_url,
                        "image": item["image"],
                        "original_timestamp": datetime.datetime.fromtimestamp(
                            time.time()).strftime(TIMESTAMP_FORMAT),
                        "hd_status": hd_status,
                        "updated_at": datetime.datetime.fromtimestamp(
                            time.time()).strftime(TIMESTAMP_FORMAT),
                        "padding": ""
                    }

                    print(pad_row(current_deal), file=f_out)
                    f_out.flush()
                    f_out.seek(0, 2)

                    if not duplicated_item:
                        deal_list.append(current_deal)
                        seen_ids.add(name)

                    items_checked += 1

                    # Handle blocks and pacing
                    if hd_status == HDStatus.BLOCKED:
                        consecutive_blocks += 1
                        print(f"!!! BLOCKED ({consecutive_blocks}/{max_consecutive_blocks})")
                        if len(driver.window_handles) > 1:
                            driver.switch_to.window(driver.window_handles[-1])
                            clear_hd_cookies(driver)
                            driver.switch_to.window(main_window)
                        if consecutive_blocks >= max_consecutive_blocks:
                            print(f"!!! {max_consecutive_blocks} consecutive blocks. Stopping.")
                            break
                        sleep_time = random.randint(90, 180)
                        print(f"   Sleeping {sleep_time}s...")
                        time.sleep(sleep_time)
                    else:
                        consecutive_blocks = 0
                        # Browse HD homepage between checks
                        if len(driver.window_handles) > 1:
                            driver.switch_to.window(driver.window_handles[-1])
                            browse_hd_homepage(driver)
                            driver.switch_to.window(main_window)
                        # Longer delay between checks (60-120s)
                        delay = random.uniform(60, 120)
                        print(f"   Waiting {delay:.0f}s before next check...")
                        time.sleep(delay)

        finally:
            driver.quit()
            print("Scraping & Verification complete")

            # Generate final report and push
            print('Saving HTML report...')
            generate_html_report(deal_list, report_path)
            try:
                subprocess.run(["git", "add", "-A"], cwd=args.output_dir, check=True)
                subprocess.run(["git", "commit", "-m", "update data"],
                               cwd=args.output_dir, check=True)
                subprocess.run(
                    ["git", "push"],
                    cwd=args.output_dir,
                    env={**os.environ,
                         "GIT_SSH_COMMAND": "ssh -i ~/.ssh/id_rsa_public_github -o IdentitiesOnly=yes"},
                    check=True)
                print("Final data committed and pushed.")
            except subprocess.CalledProcessError as e:
                print(f"Final git commit/push failed (non-fatal): {e}")

    # --- REPORT ONLY MODE ---
    elif args.mode == RunningMode.REPORT:
        print("Generating report from existing TSV...")
        generate_html_report(deal_list, report_path)

    elif args.mode == RunningMode.CHECK:

        # os.system('source update.sh')
        #
        # if has_git_updates():
        #     time.sleep(30)

        driver = get_driver()
        warm_up_hd_session(driver, zip_code=args.zip)
        process_tracker_items(driver, deal_list, tsv_output_path)


if __name__ == "__main__":
    main()