"""
One-shot debug script: dumps the HTML of the RebelSavings item modal to
modal_debug.html so we can inspect the actual DOM structure.

Usage (with Chrome already open on port 9222):
    python debug_modal.py
"""
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

REBEL_URL = "https://www.rebelsavings.com/home-depot?zip=94538"
OUT_FILE = "modal_debug.html"

service = ChromeService(ChromeDriverManager().install())
options = webdriver.ChromeOptions()
options.debugger_address = "localhost:9222"
options.page_load_strategy = "eager"
driver = webdriver.Chrome(service=service, options=options)
driver.set_page_load_timeout(60)

print(f"Navigating to {REBEL_URL} ...")
driver.get(REBEL_URL)

wait = WebDriverWait(driver, 30)
wait.until(EC.presence_of_element_located((By.CLASS_NAME, "summary-row")))
print("Page loaded. Clicking first row...")

rows = driver.find_elements(By.CLASS_NAME, "summary-row")
if not rows:
    print("No rows found!")
    driver.quit()
    exit(1)

# Click the first row to open its modal
driver.execute_script("arguments[0].scrollIntoView({block:'center'});", rows[0])
time.sleep(0.5)
driver.execute_script("arguments[0].click();", rows[0])

# Wait for modal
try:
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "close-menu-btn")))
    print("Modal opened.")
except Exception:
    print("Modal did not open — trying second row...")
    driver.execute_script("arguments[0].click();", rows[1])
    time.sleep(2)

time.sleep(1)

# Dump the full page body (includes the modal overlay)
body_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")

# Also specifically try to grab the overlay
overlay_html = ""
try:
    overlay = driver.find_element(
        By.XPATH, "//div[contains(@class,'detail-overlay') or "
                  "contains(@class,'overlay-content') or "
                  "contains(@class,'modal')]")
    overlay_html = overlay.get_attribute("outerHTML")
    print(f"Found overlay element: {overlay.get_attribute('class')[:80]}")
except Exception as e:
    print(f"Could not find overlay element: {e}")

# Also print all <a> tags in the page for quick reference
print("\n--- All <a> hrefs currently on the page ---")
all_links = driver.find_elements(By.TAG_NAME, "a")
for a in all_links[:40]:
    href = a.get_attribute("href") or ""
    txt = a.text.strip()[:40]
    if href:
        print(f"  [{txt}] {href[:100]}")

# Write the full HTML
with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("<!-- OVERLAY HTML -->\n")
    f.write(overlay_html or "(overlay not found)")
    f.write("\n\n<!-- FULL BODY HTML -->\n")
    f.write(body_html)

print(f"\nDumped HTML to {OUT_FILE}")
print("Open it in a browser or text editor to inspect the modal structure.")
