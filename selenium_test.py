import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.90 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

ipify_url = 'https://api.ipify.org'

try:
    response = requests.get(ipify_url)
    public_ip = response.text
    print(f"My public IP address is: {public_ip}")
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")

scholar_url = 'https://scholar.google.com/scholar?hl=en&as_sdt=0%2C40&q=author%3AYejin+author%3AChoi&btnG='

print("\nAccessing Google Scholar with Selenium...")
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# Set up Chrome options
chrome_options = Options()
chrome_options.add_argument("--headless")  # Run in headless mode
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument(f"--user-agent={HEADERS['User-Agent']}")

# Initialize the driver
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

try:
    # Get the IP first
    driver.get(ipify_url)
    public_ip = driver.find_element("tag name", "body").text
    print(f"My public IP address is: {public_ip}")
    
    # Now access Google Scholar
    driver.get(scholar_url)
    page_source = driver.page_source
    print("Successfully accessed Google Scholar with Selenium")
    print("Page title:", driver.title)
    # Print first 500 characters of the page source
    print("Page source preview:", page_source[:500])
    
finally:
    driver.quit()