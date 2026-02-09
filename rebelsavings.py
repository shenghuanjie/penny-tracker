import datetime
import shutil
import time
import os
import argparse
import random

import undetected_chromedriver as uc
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
ROW_SIZE = 1000  # Target bytes per line
FIELDNAMES = ["name", "price", "url", "image", "original_timestamp", "hd_status",
              "updated_at", "padding"]
NEWLINE = '\n'
TSV_FILENAME = "rebel_final_report.tsv"
BACKUP_TSV_FILENAME = "rebel_final_report_backup.tsv"


def human_click(driver, element):
    # 1. Get the element's size to calculate safe click boundaries
    size = element.size
    width = size['width']
    height = size['height']

    # 2. Calculate a random offset (avoiding the very edges)
    # We divide by 4 to keep the click safely near the middle area, but not exact center
    rand_x = random.randint(-int(width / 4), int(width / 4))
    rand_y = random.randint(-int(height / 4), int(height / 4))

    # 3. Setup the action chain
    actions = ActionChains(driver)

    # 4. Move to the element with the random offset
    actions.move_to_element_with_offset(element, rand_x, rand_y)

    # 5. "Hesitation" - Humans pause briefly before clicking
    time.sleep(random.uniform(0.2, 0.7))

    # 6. Perform the click
    actions.click()
    actions.perform()

    # 7. Post-click pause (humans don't react instantly after clicking)
    time.sleep(random.uniform(0.5, 1.5))


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
        'clearance': 2,
        'not_penny': 3,
        'error': 4,
        'failure': 5,
        'blocked': 6,
        'unchecked': 7
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
    try:
        d1 = datetime.datetime.strptime(timestamp1, TIMESTAMP_FORMAT)
        d2 = datetime.datetime.strptime(timestamp2, TIMESTAMP_FORMAT)
        diff = abs(d1 - d2)
        return diff <= datetime.timedelta(days=days)
    except ValueError:
        return False


def navigate_ca_filters(driver):
    """Step-by-step navigation for CA state and specific cities."""
    wait = WebDriverWait(driver, 20)
    print("Applying CA State and City filters...")

    # Select CA
    try:
        state_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'All States')]")))
        state_btn.click()
        wait.until(EC.element_to_be_clickable((By.XPATH, "//label[contains(., 'CA')]"))).click()
        state_btn.click()
        time.sleep(2)

        # Select Cities
        city_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'All Cities')]")))
        city_btn.click()
        cities = ["Campbell", "Fremont", "Hayward", "Milpitas", "San Jose", "Sunnyvale",
                  "Union City"]
        for city in cities:
            try:
                city_label = wait.until(
                    EC.element_to_be_clickable((By.XPATH, f"//label[contains(., '{city}')]")))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", city_label)
                city_label.click()
            except:
                continue
        city_btn.click()
        time.sleep(2)
    except Exception as e:
        print(f"Filter navigation warning: {e}")


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


def get_driver():
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    # Force version 138 to match your browser if needed, else remove version_main
    driver = uc.Chrome(options=options, version_main=138)
    return driver


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


def process_tracker_items(driver, deal_list, f_out):
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

    for row in rows:
        try:
            # Re-locate cells to avoid StaleElementReferenceException
            cells = row.find_elements(By.TAG_NAME, "td")

            if not cells:
                continue

            # Column 1: Image, 2: Name, 3: Price, 4: Status, 5: Timestamp, 6: Link
            # (Indices are 0-based: Name=1, Status=3, Link=4)
            import pdb
            pdb.set_trace()
            name_element = cells[1]
            status_element = cells[3]
            link_container = cells[4]
            timestamp_element = cells[5]

            item_name = name_element.text
            status_text = status_element.text
            update_timestamp = timestamp_element.text

            timestamp = datetime.datetime.fromtimestamp(time.time()).strftime(TIMESTAMP_FORMAT)

            # 3. Logic: Skip if strictly "PENNY"
            if status_text != "PENNY" and not is_within_x_days(timestamp, update_timestamp, 1):
                print(f"\n[Checking] {item_name} | Status: {status_text}")

                if item_name not in seen_ids:
                    continue
                else:
                    # 1. Move to the start of the file to read content
                    f_out.seek(0)
                    # 2. Read content to find the 'name'
                    content = f_out.read()
                    match_index = content.find(item_name)
                    f_out.seek(match_index)

                # Find the actual <a> tag element
                link_element = link_container.find_element(By.TAG_NAME, "a")

                # 4. Use your custom human_click function
                human_click(driver, link_element)

                # 5. Handle Tab Switching
                # Wait for the new tab to open
                wait.until(EC.number_of_windows_to_be(2))

                # Switch to the new tab
                all_windows = driver.window_handles
                for window in all_windows:
                    if window != main_window_handle:
                        driver.switch_to.window(window)
                        break

                # --- RUN YOUR CHECK FUNCTION ---
                # The driver is now focused on the new tab
                try:
                    new_hd_status = check_hd_item_tab_status(driver, name=item_name)
                    print(f"   >>> Result: {new_hd_status}")

                    for ideal, current_deal in enumerate(deal_list):
                        if current_deal['name'] == item_name:
                            current_deal['hd_status'] = new_hd_status
                            print(pad_row(current_deal), file=f_out)
                            break

                except Exception as e:
                    print(f"   !!! Error checking status: {e}")

                # 6. Close tab and return to list
                driver.close()
                driver.switch_to.window(main_window_handle)

                # Small pause to ensure stability before next iteration
                time.sleep(1)

        except Exception as e:
            print(f"Skipping row due to error: {e}")
            # Ensure we are back on the main window if something failed mid-loop
            if driver.current_window_handle != main_window_handle:
                driver.switch_to.window(main_window_handle)
            continue


def main():
    parser = argparse.ArgumentParser(description="RebelSavings Scraper & Reporter")
    parser.add_argument("-n", "--max-items", type=int, default=None,
                        help="Maximum number of items to scrape")
    parser.add_argument("-f", "--from-tsv", type=str, metavar="FILE",
                        default=TSV_FILENAME, help="Path to existing CSV")
    parser.add_argument("-o", "--output-dir", type=str, default=".",
                        help="Folder to save the CSV and HTML report")
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
    if os.path.isfile(args.from_tsv):
        print(f"Reading data from {args.from_tsv}...")
        try:
            with open(args.from_tsv, "r", encoding="utf-8") as f_out:
                f_out.readline()  # skip header
                for row in f_out:
                    parts = row.strip().split("\t")
                    if len(parts) >= len(FIELDNAMES):
                        row_dict = dict(zip(FIELDNAMES, parts[:len(FIELDNAMES)]))
                        deal_list.append(row_dict)
        except Exception as e:
            print(f"Error reading TSV: {e}")

    # --- CLEANING OLD DATA ---
    if args.mode in [RunningMode.CLEAN, RunningMode.ALL] and deal_list:
        new_deal_list = []
        for deal_row in deal_list:
            org_timestamp = deal_row["original_timestamp"]
            timestamp = datetime.datetime.fromtimestamp(time.time()).strftime(TIMESTAMP_FORMAT)
            if org_timestamp is None or is_within_x_days(org_timestamp, timestamp, days=60):
                new_deal_list.append(deal_row)

        if len(new_deal_list) != len(deal_list):
            print(f"Cleaned {len(deal_list) - len(new_deal_list)} old items.")
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

            driver.get("https://www.rebelsavings.com/")
            navigate_ca_filters(driver)
            driver.execute_script("document.body.style.zoom='75%'")

            # Open file in append mode (or write if empty)
            open_mode = 'a' if os.path.isfile(tsv_output_path) else 'w'

            # Using 'r+' implies reading/writing, but standard append is safer for logs
            # However, we want to maintain the header if new
            with open(tsv_output_path, open_mode, encoding="utf-8") as f_out:
                if open_mode == "w":
                    print(pad_row(FIELDNAMES), file=f_out)

                max_patience = 3
                current_patience = 0
                main_window = driver.current_window_handle  # Store RebelSavings Handle

                while len(deal_list) < max_items:
                    # 1. Grab whatever is currently in the DOM (Virtual Window)
                    current_rows = driver.find_elements(By.CLASS_NAME, "summary-row")

                    new_items_found_in_this_pass = 0

                    for row in current_rows:

                        if len(deal_list) >= max_items:
                            break

                        try:
                            name_elem = row.find_element(By.CLASS_NAME, "title-column")
                            name = name_elem.text.splitlines()[0].strip()

                            if name in seen_ids:
                                duplicated_item = True
                                print(f'Duplicate item found: {name}')
                                # 1. Move to the start of the file to read content
                                f_out.seek(0)
                                # 2. Read content to find the 'name'
                                content = f_out.read()
                                match_index = content.find(name)
                                f_out.seek(match_index)
                            else:
                                duplicated_item = False

                            # --- 1. Get Rebel Data ---
                            price = row.find_element(By.XPATH, "./td[3]").text.strip()

                            try:
                                img_url = row.find_element(By.TAG_NAME, "img").get_attribute("src")
                            except:
                                img_url = ""

                            # C. Interact (Scroll to it so it is fully rendered/clickable)
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});",
                                                  row)
                            time.sleep(random.uniform(1, 2))

                            # Click row to open modal
                            driver.execute_script("arguments[0].click();", row)

                            # --- Modal Logic ---
                            wait_menu = WebDriverWait(driver, 5)
                            close_btn = wait_menu.until(
                                EC.element_to_be_clickable((By.CLASS_NAME, "close-menu-btn")))

                            hd_link_elem = wait_menu.until(EC.element_to_be_clickable(
                                (By.XPATH, "//div[contains(@class, 'detail-overlay-content')]//a")))
                            hd_url = hd_link_elem.get_attribute("href")

                            # Click for Modal to get Link
                            time.sleep(random.uniform(1, 3))

                            # 1. Capture current window handles to detect the new one
                            old_handles = driver.window_handles

                            # 2. CLICK the link (Using JS is often more reliable in modals)
                            print(f"   Clicking link for: {name[:20]}...")
                            # driver.execute_script("arguments[0].click();", hd_link_elem)
                            human_click(driver, hd_link_elem)

                            # 3. Wait for the new tab to appear in the handle list
                            WebDriverWait(driver, 10).until(EC.new_window_is_opened(old_handles))

                            # --- 5. SWITCH TO NEW TAB & VERIFY ---
                            # Switch to the newest handle (the one just opened)
                            driver.switch_to.window(driver.window_handles[-1])

                            try:
                                # No driver.get() needed; the click triggered the load.
                                # Perform verification on the active tab
                                hd_status = check_hd_item_tab_status(driver, name=name)
                            except Exception as e:
                                print(f"   Error checking tab: {e}")
                                hd_status = HDStatus.ERROR

                            # Close the HD tab
                            driver.close()

                            # 4. Close Modal on the main page (cleanup)
                            driver.switch_to.window(driver.window_handles[0])
                            close_btn.click()
                            wait_menu.until(EC.invisibility_of_element_located(
                                (By.CLASS_NAME, "close-menu-btn")))

                            # Switch back to RebelSavings
                            driver.switch_to.window(main_window)
                            # -------------------------------------

                            # --- 3. SAVE DATA ---
                            current_deal = {
                                "name": name,
                                "price": price,
                                "url": hd_url,
                                "image": img_url,
                                "original_timestamp": datetime.datetime.fromtimestamp(
                                    time.time()).strftime(TIMESTAMP_FORMAT),
                                "hd_status": hd_status,
                                "updated_at": datetime.datetime.fromtimestamp(time.time()).strftime(
                                    TIMESTAMP_FORMAT),
                                "padding": ""
                            }

                            print(pad_row(current_deal), file=f_out)
                            f_out.flush()  # Ensure it's written immediately
                            # always jump back to file end
                            f_out.seek(0, 2)

                            if not duplicated_item:
                                deal_list.append(current_deal)
                                seen_ids.add(name)
                                new_items_found_in_this_pass += 1

                            # Anti-detection pause between tabs
                            if hd_status == HDStatus.BLOCKED:
                                sleep_time = random.randint(300, 600)
                                print(f"!!! BLOCKED DETECTED. Sleeping {sleep_time}s !!!")
                                time.sleep(sleep_time)
                            else:
                                time.sleep(random.uniform(2, 5))

                        except Exception as e1:
                            # Recovery if something broke
                            try:
                                if len(driver.window_handles) > 1:
                                    # Ensure we are on main window and extra tabs are closed
                                    for handle in driver.window_handles:
                                        if handle != main_window:
                                            driver.switch_to.window(handle)
                                            driver.close()
                                    driver.switch_to.window(main_window)
                            except Exception as e2:
                                pass
                            print(f"Skipping row due to error: {e1}\n{e2}")
                            continue

                    # --- End of Pass Logic ---
                    if new_items_found_in_this_pass > 0:
                        current_patience = 0
                        print(
                            f"Pass complete. Found {new_items_found_in_this_pass} new items. Scrolling...")
                    else:
                        current_patience += 1
                        print(
                            f"Pass complete. NO new items. Patience: {current_patience}/{max_patience}")

                    if current_patience >= max_patience:
                        print("Max patience reached. Stopping.")
                        break

                    driver.execute_script("window.scrollBy(0, 800);")
                    time.sleep(random.uniform(4, 7))

        finally:
            driver.quit()
            print("Scraping & Verification complete")

            # Generate Report at the end
            print('Saving HTML report...')
            generate_html_report(deal_list, report_path)

    # --- REPORT ONLY MODE ---
    elif args.mode == RunningMode.REPORT:
        print("Generating report from existing TSV...")
        generate_html_report(deal_list, report_path)

    elif args.mode == RunningMode.CHECK:

        os.system('source update.sh')

        driver = get_driver()

        # Open file in append mode (or write if empty)
        open_mode = 'a' if os.path.isfile(tsv_output_path) else 'w'

        # Using 'r+' implies reading/writing, but standard append is safer for logs
        # However, we want to maintain the header if new
        with open(tsv_output_path, open_mode, encoding="utf-8") as f_out:
            if open_mode == "w":
                print(pad_row(FIELDNAMES), file=f_out)
            process_tracker_items(driver, deal_list, f_out)


if __name__ == "__main__":
    main()