import datetime
import io
import time
import os
import argparse
import random

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
ROW_SIZE = 1000  # Target bytes per line
FIELDNAMES = ["name", "price", "url", "image", "hd_status", "timestamp", "padding"]
NEWLINE = '\n'
TSV_FILENAME = "rebel_final_report.tsv"


class HDStatus:
    PENNY = 'penny'
    NOT_PENNY = 'not_penny'
    PENNY_CANDIDATE = 'penny_candidate'
    CLEARANCE = 'clearance'
    ERROR = 'error'
    FAILURE = 'failure'
    BLOCKED = 'blocked'


def generate_html_report(deals, output_path):
    """Creates a visual HTML report with images and status colors."""
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
        <table><tr><th>Image</th><th>Name</th><th>Price</th><th>Status</th><th>Link</th></tr>"""

    for d in deals:
        # Handle cases where CSV might not have status or image
        status = d.get('hd_status', 'unchecked')
        # If status is empty string, treat as unchecked
        if not status: status = 'unchecked'

        image_src = d.get('image', '')
        name = d.get('name', 'Unknown')
        price = d.get('price', 'N/A')
        url = d.get('url', '#')

        html += f"""<tr>
            <td><img src="{image_src}"></td>
            <td>{name}</td>
            <td>{price}</td>
            <td class="{status}">{status.upper()}</td>
            <td><a href="{url}" target="_blank">Link</a></td>
        </tr>"""

    html += "</table></body></html>"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nVisual report created: {output_path}")


def is_within_one_day(timestamp1, timestamp2):
    """
    Checks if two timestamp strings are within 24 hours of each other.
    Format: '%Y-%m-%d %H:%M:%S'
    """

    # Convert strings to datetime objects
    try:
        d1 = datetime.datetime.strptime(timestamp1, TIMESTAMP_FORMAT)
        d2 = datetime.datetime.strptime(timestamp2, TIMESTAMP_FORMAT)

        # Calculate absolute difference
        diff = abs(d1 - d2)

        # Check if difference is less than or equal to 1 day
        return diff <= datetime.timedelta(days=1)
    except ValueError:
        return False


def navigate_ca_filters(driver):
    """Step-by-step navigation for CA state and specific cities."""
    wait = WebDriverWait(driver, 20)
    print("Applying CA State and City filters...")

    # Select CA
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
    cities = ["Campbell", "Fremont", "Hayward", "Milpitas", "San Jose", "Sunnyvale", "Union City"]
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


def verify_on_home_depot(driver, deal):
    """Handles switching into the Home Depot iframe to find the clearance badge."""
    print(f"Deep checking: {deal['name'][:30]}...")
    try:
        driver.get(deal['url'])

        # --- Stage 0: Immediate Block/Error Check ---
        error_msgs = driver.find_elements(
            By.XPATH, "//div[@class='msg' and contains(text(), 'Something went wrong')]")

        if error_msgs:
            print(f"Blocked/Error detected for {deal['name'][:10]}: 'Oops' message found.")
            return HDStatus.BLOCKED

        wait = WebDriverWait(driver, 12)

        # --- Stage 0.5: Normal Stock Check (The "Pickup" Element) ---
        # If "Pickup" is displayed, it usually means the item is in stock at normal/clearance price
        # and not a hidden "Penny" item.
        # We use a loose XPath to match the "Pickup" text inside the styled div.
        try:
            pickup_badges = driver.find_elements(
                By.XPATH, "//div[contains(@class, 'sui-font-bold') and contains(text(), 'Pickup')]")

            if pickup_badges:
                print(f"Normal stock found for {deal['name'][:10]}: 'Pickup' option detected.")
                return HDStatus.NOT_PENNY
        except Exception:
            pass  # Continue if check fails or element not found

        # --- Stage 1: Main Page Text ---
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//p[contains(text(), 'See In-Store Clearance Price')]")))
            return HDStatus.CLEARANCE
        except:
            pass

        for _ in range(1):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(3)
            driver.execute_script("window.scrollBy(0, -1000);")
            time.sleep(2)

        # --- Stage 2: Iframe Badge Check ---
        try:
            # 1. Open the Store Overlay
            nearby_link = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//a[@data-testid='check-nearby-stores']")))
            driver.execute_script("arguments[0].click();", nearby_link)
            time.sleep(3)  # Wait for iframe to mount

            # 2. SWITCH TO THE IFRAME
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "thd-drawer-frame")))

            # 3. Scroll inside the iframe context
            for _ in range(1):
                driver.execute_script("window.scrollBy(0, 1000);")
                time.sleep(3)

            # 4. Search for the Badge
            badge_xpath = "//img[contains(@src, 'Value-Pricing-Clearance')]"
            badges = driver.find_elements(By.XPATH, badge_xpath)

            # Switch back to the main document before returning
            status = HDStatus.PENNY_CANDIDATE if len(badges) > 0 else HDStatus.PENNY
            driver.switch_to.default_content()
            return status

        except Exception as e:
            # print(f"Iframe/Overlay check failed: {e}")
            driver.switch_to.default_content()  # Always switch back on error
        finally:
            time.sleep(3)

        return HDStatus.PENNY

    except Exception:
        # Fallback check in case the element wasn't caught in Stage 0
        # but appears in the page source during a crash
        if "Something went wrong" in driver.page_source:
            return HDStatus.FAILURE
        return HDStatus.ERROR


def get_driver():
    # profile_path = os.path.join(os.getcwd(), "hd_profile")
    options = uc.ChromeOptions()
    # options.add_argument(f"--user-data-dir={profile_path}")
    # Important: Randomize window size slightly to avoid "default selenium" dimensions
    options.add_argument("--window-size=1920,1080")
    # Force version 138 to match your browser
    driver = uc.Chrome(options=options, version_main=138)
    return driver


def pad_row(input_list, target_char_length=ROW_SIZE, pad_char=" "):
    """
    Converts a list to a tab-delimited string of a strictly fixed character length.

    Args:
        input_list (list or dict): The list of items to join.
        target_char_length (int): The total character count required.
        pad_char (str): The character to use for padding (default is space).

    Returns:
        str: A string exactly `target_char_length` characters long.
    """
    # new to consider the extra line break
    target_char_length -= 1
    if isinstance(input_list, dict):
        input_list = input_list.values()
    # 1. Join the list into a standard TSV string
    # Convert all items to strings first to handle None/Ints safely
    tsv_string = "\t".join(str(item) for item in input_list)

    current_len = len(tsv_string)

    # 2. Pad if too short
    if current_len < target_char_length:
        # ljust adds padding to the right side
        return tsv_string.ljust(target_char_length, pad_char)

    # 3. Truncate if too long
    elif current_len > target_char_length:
        return tsv_string[:target_char_length]

    # 4. Exact match
    return tsv_string



def main():
    parser = argparse.ArgumentParser(description="RebelSavings Scraper & Reporter")

    # 1. Max Items
    parser.add_argument("-m", "--max-items", type=int, default=None,
                        help="Maximum number of items to scrape (default: None)")

    # 2. Read CSV Only
    parser.add_argument("-f", "--from-tsv", type=str, metavar="FILE",
                        default=TSV_FILENAME,
                        help="Path to an existing CSV file. "
                             "If provided, skips scraping and only generates the report.")

    # 3. Output Folder
    parser.add_argument("-o", "--output-dir", type=str, default=".",
                        help="Folder to save the CSV and HTML report (default: current directory)")

    parser.add_argument("-c", "--continuing", action="store_true",
                        help="Continue searching for items even if one found in the CSV.")

    parser.add_argument("-ns", "--no-search", action="store_true",
                        help="Do NOT search for new items.")

    parser.add_argument("-rp", "--report-only", action="store_true",
                        help="Only generate report.")

    args = parser.parse_args()

    # Ensure output directory exists
    if args.output_dir and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # Define Output Paths
    html_filename = "index.html"
    deal_list = []

    # If a CSV input is not provided, we use the standard output name
    # If a CSV input IS provided, we still output the HTML to the output dir

    report_path = os.path.join(args.output_dir, html_filename)
    tsv_output_path = os.path.join(args.output_dir, TSV_FILENAME)

    # --- MODE: REPORT ONLY ---
    if args.from_tsv and os.path.isfile(args.from_tsv):
        print(f"Reading data from {args.from_tsv}...")
        deal_list = []
        with open(args.from_tsv, "r", encoding="utf-8") as f_out:
            f_out.readline() # skip header
            for row in f_out:
                row = dict(zip(FIELDNAMES, row.strip().split("\t")[:len(FIELDNAMES)]))
                if len(row) >= 4:
                    deal_list.append(row)
                else:
                    print(f'{len(row)}: {row}')

        print(f"Loaded {len(deal_list)} items.")

    if not args.report_only:
        driver = get_driver()
        # --- MODE: SCRAPE AND VERIFY ---
        try:
            if deal_list:
                seen_ids = set(deal['name'] for deal in deal_list)
            else:
                seen_ids = set()
            max_items = args.max_items  # Use the argument
            if max_items is None:
                max_items = float('inf')
            patience = 0

            print(f"Starting item collection (Max: {max_items})...")

            if not args.no_search and deal_list:

                driver.get("https://www.rebelsavings.com/")
                navigate_ca_filters(driver)

                # Help the virtual scroll by zooming out
                driver.execute_script("document.body.style.zoom='75%'")

                # Save results to the specified output folder
                if os.path.isfile(tsv_output_path):
                    open_mode = 'a'
                else:
                    open_mode = 'w'

                with open(tsv_output_path, open_mode, encoding="utf-8") as f_out:
                    if open_mode == "w":
                        print('\t'.join(FIELDNAMES), file=f_out)

                    while len(deal_list) < max_items:
                        rows = driver.find_elements(By.CLASS_NAME, "summary-row")
                        initial_count = len(seen_ids)

                        for i in range(len(rows)):
                            if len(deal_list) >= max_items: break

                            current_rows = driver.find_elements(By.CLASS_NAME, "summary-row")
                            if i >= len(current_rows): break
                            row = current_rows[i]

                            try:
                                name = row.find_element(
                                    By.CLASS_NAME, "title-column").text.splitlines()[0].strip()
                                price = row.find_element(By.XPATH, "./td[3]").text.strip()
                                item_id = name

                                if item_id in seen_ids:
                                    if args.continuing:
                                        continue
                                    else:
                                        print(f'Duplicate item found: {item_id}. '
                                              'Terminating the search.')
                                        max_items = -1

                                img_url = row.find_element(By.TAG_NAME, "img").get_attribute("src")

                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});",
                                                      row)
                                time.sleep(3)
                                driver.execute_script("arguments[0].click();", row)

                                hd_link_elem = WebDriverWait(driver, 8).until(
                                    EC.presence_of_element_located((By.XPATH, "//a[@target='_blank']"))
                                )
                                hd_url = hd_link_elem.get_attribute("href")
                                time.sleep(2)

                                driver.find_element(By.CLASS_NAME, "close-menu-btn").click()
                                WebDriverWait(driver, 5).until(
                                    EC.invisibility_of_element_located(
                                        (By.CLASS_NAME, "close-menu-btn")))

                                # Note: hd_status is initially empty/None, filled later
                                current_deal = {
                                    "name": name,
                                    "price": price,
                                    "url": hd_url,
                                    "image": img_url,
                                    "hd_status": "",
                                    "timestamp": "",
                                    "padding": ""
                                }
                                # write info
                                print(pad_row(current_deal), file=f_out)
                                deal_list.append(current_deal)
                                seen_ids.add(item_id)
                                print(f"[{len(deal_list)}] Collected: {name[:35]}...")
                                time.sleep(3)

                            except Exception as e:
                                try:
                                    driver.find_element(By.CLASS_NAME, "close-menu-btn").click()
                                except:
                                    pass
                                time.sleep(10)
                                continue

                        if len(seen_ids) == initial_count:
                            patience += 1
                            if patience >= 3: break
                        else:
                            patience = 0

                        driver.execute_script("window.scrollBy(0, 800);")
                        time.sleep(2)
            # Verification & HTML Report
            print(f"\nVerifying {len(deal_list)} items on Home Depot...")
            fp = open(tsv_output_path, 'r+', encoding="utf-8")
            fp.readline()
            file_pointer = fp.tell()
            # now we should align deal_list with actual line
            for ideal, loaded_deal in enumerate(deal_list):
                print(f"[{ideal}] {loaded_deal['name']} at {file_pointer}...")
                loaded_deal = dict(loaded_deal)
                if fp.closed:
                    fp = open(tsv_output_path, 'r+', encoding="utf-8")
                    fp.seek(file_pointer)
                else:
                    fp.seek(file_pointer)
                file_deal = dict(zip(FIELDNAMES, fp.readline().strip().split('\t')[:len(FIELDNAMES)]))
                if loaded_deal['name'] != file_deal['name']:
                    print(ideal)
                    import pdb
                    pdb.set_trace()
                    break
                org_timestamp = loaded_deal.get("timestamp", None)
                timestamp = datetime.datetime.fromtimestamp(
                    time.time()).strftime(TIMESTAMP_FORMAT)
                if not org_timestamp or not is_within_one_day(org_timestamp, timestamp):
                    while True:
                        loaded_deal['hd_status'] = verify_on_home_depot(driver, loaded_deal)
                        if loaded_deal['hd_status'] not in {
                            HDStatus.FAILURE, HDStatus.ERROR, HDStatus.BLOCKED}:
                            break
                        else:
                            if random.randint(0, 1):
                                driver.get('https://www.homedepot.com/')
                            else:
                                driver.get('https://www.google.com/')
                            waittime = random.randint(300, 600)
                            print(f"Blocked. Waiting for {waittime} seconds...")
                            time.sleep(waittime)
                            print(f"Have waited for {waittime} seconds...")

                    loaded_deal['timestamp'] = timestamp
                    # reset padding so padding will be ready
                    loaded_deal['padding'] = ''
                    fp.seek(file_pointer)
                    padded_line = pad_row(loaded_deal)
                    print(f'Writing to file...\n{padded_line}')
                    print(padded_line, file=fp)
                    # ok now we have a new file pointer position
                    file_pointer = fp.tell()
                    fp.close()
                    # Optional: You could update the CSV here row by row if desired,
                    # but currently we just generate the HTML at the end.
                    waittime = random.randint(20, 30)
                    print(f"[{ideal} of {len(deal_list)}] Waiting for {waittime} seconds...")
                    time.sleep(waittime)
                    if random.randint(0, 1):
                        driver.get('https://www.homedepot.com/')
                    else:
                        driver.get('https://www.google.com/')
                    waittime = random.randint(20, 30)
                    print(f"[{ideal} of {len(deal_list)}] Waiting for {waittime} seconds...")
                    time.sleep(waittime)
                    if ideal % 20 == 0:
                        waittime = random.randint(30, 60)
                        time.sleep(waittime)
                        print(f"[{ideal} of {len(deal_list)}] "
                              f"Waiting for {waittime} seconds...")
                else:
                    # no need to update status, switch to a new line
                    # but there is no need to reopen file
                    file_pointer = fp.tell()
        finally:
            driver.quit()
            print("Scraping complete. Saving report...")
            generate_html_report(deal_list, report_path)
    else:
        print("Scraping complete. Saving report...")
        generate_html_report(deal_list, report_path)


if __name__ == "__main__":
    main()
