import time
import csv
import os
import argparse
from lib2to3.pgen2 import driver

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def generate_html_report(deals, output_path):
    """Creates a visual HTML report with images and status colors."""
    html = """
    <html><head><style>
        body { font-family: Arial; background: #f0f2f5; padding: 20px; }
        table { width: 100%; border-collapse: collapse; background: white; }
        th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
        th { background: #f8991d; color: white; }
        img { width: 70px; height: auto; border-radius: 5px; }
        .clearance { color: #2ecc71; font-weight: bold; }
        .penny_candidate { color: #f39c12; font-weight: bold; }
        .penny { color: #3498db; }
        .unchecked { color: #7f8c8d; font-style: italic; }
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
    cities = ["Campbell", "Fremont", "Hayward", "Milpitas", "San Jose", "Union City"]
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
        wait = WebDriverWait(driver, 12)

        # --- Stage 1: Main Page Text ---
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//p[contains(text(), 'See In-Store Clearance Price')]")))
            return "clearance"
        except:
            pass

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
            status = "penny_candidate" if len(badges) > 0 else "penny"
            driver.switch_to.default_content()
            return status

        except Exception as e:
            # print(f"Iframe/Overlay check failed: {e}")
            driver.switch_to.default_content()  # Always switch back on error
        finally:
            time.sleep(3)

        return "penny"

    except Exception:
        if "Something went wrong" in driver.page_source:
            return "BLOCKED"
        return "error"


def main():
    parser = argparse.ArgumentParser(description="RebelSavings Scraper & Reporter")

    # 1. Max Items
    parser.add_argument("-m", "--max-items", type=int, default=None,
                        help="Maximum number of items to scrape (default: None)")

    # 2. Read CSV Only
    parser.add_argument("-f", "--from-csv", type=str, metavar="FILE",
                        default="rebel_final_report.csv",
                        help="Path to an existing CSV file. "
                             "If provided, skips scraping and only generates the report.")

    # 3. Output Folder
    parser.add_argument("-o", "--output-dir", type=str, default=".",
                        help="Folder to save the CSV and HTML report (default: current directory)")

    args = parser.parse_args()

    # Ensure output directory exists
    if args.output_dir and not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # Define Output Paths
    csv_filename = "rebel_final_report.csv"
    html_filename = "report.html"
    deal_list = []

    # If a CSV input is not provided, we use the standard output name
    # If a CSV input IS provided, we still output the HTML to the output dir

    report_path = os.path.join(args.output_dir, html_filename)
    csv_output_path = os.path.join(args.output_dir, csv_filename)

    # --- MODE: REPORT ONLY ---
    if args.from_csv:
        print(f"Reading data from {args.from_csv}...")
        deal_list = []
        try:
            with open(args.from_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    deal_list.append(row)

            print(f"Loaded {len(deal_list)} items.")

        except FileNotFoundError:
            print(f"Error: File {args.from_csv} not found.")
            return

    # --- MODE: SCRAPE AND VERIFY ---

    options = uc.ChromeOptions()
    # Force version 138 to match your browser
    driver = uc.Chrome(options=options, version_main=138)

    try:
        driver.get("https://www.rebelsavings.com/")
        navigate_ca_filters(driver)

        # Help the virtual scroll by zooming out
        driver.execute_script("document.body.style.zoom='75%'")

        if deal_list:
            seen_ids = set(deal['name'] for deal in deal_list)
        else:
            seen_ids = set()
        max_items = args.max_items  # Use the argument
        if max_items is None:
            max_items = float('inf')
        patience = 0

        print(f"Starting item collection (Max: {max_items})...")

        # Save results to the specified output folder
        with open(csv_output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "price", "url", "image", "hd_status"])
            writer.writeheader()

            while len(deal_list) < max_items:
                rows = driver.find_elements(By.CLASS_NAME, "summary-row")
                initial_count = len(seen_ids)

                for i in range(len(rows)):
                    if len(deal_list) >= max_items: break

                    current_rows = driver.find_elements(By.CLASS_NAME, "summary-row")
                    if i >= len(current_rows): break
                    row = current_rows[i]

                    try:
                        name = row.find_element(By.CLASS_NAME, "title-column").text.splitlines()[
                            0].strip()
                        price = row.find_element(By.XPATH, "./td[3]").text.strip()
                        item_id = name

                        if item_id in seen_ids: continue

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
                            EC.invisibility_of_element_located((By.CLASS_NAME, "close-menu-btn")))

                        # Note: hd_status is initially empty/None, filled later
                        current_deal = {
                            "name": name,
                            "price": price,
                            "url": hd_url,
                            "image": img_url,
                            "hd_status": ""
                        }

                        writer.writerow(current_deal)
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
        for d in deal_list:
            d['hd_status'] = verify_on_home_depot(driver, d)
            # Optional: You could update the CSV here row by row if desired,
            # but currently we just generate the HTML at the end.
            time.sleep(3)

    finally:
        driver.quit()

    print("Scraping complete. Saving report...")
    generate_html_report(deal_list, report_path)


if __name__ == "__main__":
    main()
