import argparse
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from io import BytesIO
import importlib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "https://drafty.cs.brown.edu/csopenrankings/"
PROFBYSCHOOL_URL = "https://drafty.cs.brown.edu/csopenrankings/frontend/profBySchool.js"

ALLOWED_SUBFIELDS = ["ai", "vision", "ir", "mlmining", "nlp"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.90 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def _setup_selenium_driver():
    """Set up and return a Selenium Chrome driver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver


def fetch_url(url, timeout=15, retries=2, backoff=1.0):
    # Use Selenium for Google Scholar URLs to bypass blocking
    if "scholar.google.com" in url:
        driver = None
        try:
            driver = _setup_selenium_driver()
            driver.get(url)
            # Wait a bit for the page to load
            time.sleep(2)
            return driver.page_source
        except Exception as e:
            if driver:
                driver.quit()
            raise e
        finally:
            if driver:
                driver.quit()
    else:
        # Use requests for other URLs
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, headers=HEADERS, timeout=timeout)
                resp.raise_for_status()
                return resp.text
            except Exception:
                if attempt == retries:
                    raise
                time.sleep(backoff * (attempt + 1))
        raise RuntimeError("unreachable")


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def extract_gs_result_links(html: str, base_url: str = "https://scholar.google.com"):
    """
    Parse a Google Scholar search result HTML and extract ONLY the main
    result links from each result card. Avoids sidebar/profile/auxiliary links.

    Strategy:
    - Select results under #gs_res_ccl with containers having classes
      'gs_r' and 'gs_or' (these are individual results).
    - For each result, take the anchor in h3.gs_rt (the main title link).
    - Resolve relative URLs against base_url.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    links = []

    # Only result cards (skip the top "User profiles" block which lacks gs_or)
    for card in soup.select("#gs_res_ccl .gs_r.gs_or"):
        a = card.select_one("h3.gs_rt a[href]")
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href:
            continue
        # Normalize to absolute URL
        if href.startswith("/"):
            href = requests.compat.urljoin(base_url, href)
            print(f"\033[31mRESOLVED RELATIVE URL TO: {href}\033[0m")
        links.append(href)

    # Verification: parse the header "About N results (T sec)" and compare
    header_el = soup.select_one("#gs_ab_md .gs_ab_mdw") or soup.select_one("#gs_ab_md")
    total_results = None
    if header_el:
        header_text = header_el.get_text(" ", strip=True)
        m = re.search(r"([\d,]+)\s+results?", header_text, flags=re.I)
        if m:
            try:
                total_results = int(m.group(1).replace(",", ""))
            except Exception:
                total_results = None

    if total_results is not None:
        expected = min(10, total_results)
        if expected == len(links):
            print("Verified")
        else:
            print(f"\033[31mERROR: expected {expected} links, got {len(links)} (total {total_results})\033[0m")
    else:
        print(f"\033[31mERROR: Could not find total results for the google scholar results\033[0m")
    return links


def _clean_university_cell_text(td) -> str:
    """
    The university td contains the name plus a '+' span for expanding.
    We remove the span and return clean university name.
    """
    td = BeautifulSoup(str(td), "html.parser")
    span = td.find("span")
    if span:
        span.decompose()
    txt = td.get_text(" ", strip=True)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def list_universities_from_main_table(soup: BeautifulSoup):
    """
    Returns list of dicts:
      [{"id": "<tr id>", "name": "<university name shown>"}]
    """
    tbody = soup.find("tbody", id="tablebody")
    if not tbody:
        return []

    universities = []
    for tr in tbody.find_all("tr", recursive=False):
        tr_id = tr.get("id", "")
        if not tr_id:
            continue
        if " dropdown" in tr_id:
            continue

        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue

        uni_name = _clean_university_cell_text(tds[1])
        if uni_name:
            universities.append({"id": tr_id, "name": uni_name})

    return universities


def find_best_matching_university(univ_query: str):
    """
    Returns (matched_name, matched_id)
    """
    html = fetch_url(BASE_URL)
    soup = BeautifulSoup(html, "html.parser")

    universities = list_universities_from_main_table(soup)
    if not universities:
        return None, None

    scored = []
    for u in universities:
        name = u["name"]
        score = text_similarity(name, univ_query)
        if univ_query.lower() in name.lower():
            score = max(score, 0.95)
        scored.append((score, u["name"], u["id"]))

    scored.sort(reverse=True, key=lambda x: x[0])
    best_score, best_name, best_id = scored[0]

    if best_score < 0.4:
        return None, None

    return best_name, best_id


def load_js_object(js_code: str, var_name: str):
    """
    Convert a JS variable assignment into JSON
    """
    # Remove: let profBySchool_normalized =
    pattern1 = rf"\blet\s+{re.escape(var_name)}\s*=\s*"
    js_code = re.sub(pattern1, "", js_code)

    # Remove: export {profBySchool_normalized};
    pattern2 = rf"export\s*\{{\s*{re.escape(var_name)}\s*\}}\s*;"
    js_code = re.sub(pattern2, "", js_code)

    # Remove trailing semicolon
    js_code = js_code.strip().rstrip(";")

    return json.loads(js_code)


def extract_professors_from_profBySchool(matched_name: str):
    """
    Extract professors from profBySchool_normalized.js

    Returns list of:
      {
        "name": ...,
        "subfield": ...,
        "google_scholar": ...
      }
    """
    js_code = fetch_url(PROFBYSCHOOL_URL)

    prof_by_school = load_js_object(
        js_code,
        "profBySchool_normalized"
    )

    if matched_name not in prof_by_school:
        return []

    university_block = prof_by_school[matched_name]

    results = []
    for _, prof_data in university_block.items():
        if prof_data.get("subfield").lower() in ALLOWED_SUBFIELDS:
            results.append({
                "name": prof_data.get("name"),
                "subfield": prof_data.get("subfield"),
                "google scholar": prof_data.get("google scholar"),
            })

    results.sort(key=lambda x: x.get("name"))

    return results


def _sanitize_filename(name: str) -> str:
    """Make a safe file name for Windows by removing reserved characters."""
    if not name:
        return "untitled"
    # Remove Windows-forbidden characters <>:"/\|?*
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    # Collapse whitespace and dots
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    # Truncate to a reasonable length
    return name[:180] if len(name) > 180 else name


def _page_title_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    t = soup.title.string if soup.title else ""
    return (t or "").strip()


def _is_arxiv_pdf_url(url: str) -> bool:
    try:
        parsed = requests.utils.urlparse(url)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        return "arxiv.org" in host and "/pdf/" in path
    except Exception:
        return False


def fetch_arxiv_text(url: str, timeout: int = 20, retries: int = 2, backoff: float = 1.0) -> str:
    """Fetch an arXiv URL and return extracted plain text.

    - If it's a PDF response, extract text via pdfminer.six
    - If it's HTML (rate-limit or error page), return the HTML text
    """
    # Ensure we hit the PDF endpoint and end with .pdf for arXiv
    if url.startswith("https://arxiv.org/abs"):
        url = url.replace("https://arxiv.org/abs", "https://arxiv.org/pdf")
    if _is_arxiv_pdf_url(url) and not url.lower().endswith(".pdf"):
        url = url + ".pdf"

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
            resp.raise_for_status()
            content_type = (resp.headers.get("Content-Type", "").lower())
            content = resp.content  # bytes

            if "application/pdf" in content_type or url.lower().endswith(".pdf"):
                try:
                    pdfminer_high_level = importlib.import_module("pdfminer.high_level")
                    text = pdfminer_high_level.extract_text(BytesIO(content))
                    return text or ""
                except Exception as e:
                    # If PDF parsing fails, fall back to raw bytes decode
                    last_err = e
                    try:
                        return content.decode(resp.encoding or "utf-8", errors="ignore")
                    except Exception:
                        return ""
            else:
                # Not a PDF; return as HTML text
                try:
                    return content.decode(resp.encoding or "utf-8", errors="ignore")
                except Exception:
                    return resp.text
        except Exception as e:
            last_err = e
            if attempt == retries:
                raise
            time.sleep(backoff * (attempt + 1))
    # Should not reach, but return empty if somehow we do
    if last_err:
        raise last_err
    return ""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("university", help="University name to search for (partial match allowed)")
    args = p.parse_args()

    query = args.university
    print(f"Searching for university matching: {query}")

    matched_name, matched_id = find_best_matching_university(query)
    if not matched_name:
        print("No close match found on CS Open Rankings.")
        return

    print(f"Best match: {matched_name}")
    print("Extracting professors from profBySchool.js...")

    professors = extract_professors_from_profBySchool(matched_name)

    out = {
        "query": query,
        "matched_university": matched_name,
        "source_url": PROFBYSCHOOL_URL,
        "professors": professors,
    }

    text = json.dumps(out, indent=2, ensure_ascii=False)
    print(text)
    print(len(professors), "professors found in the following subfields:", ", ".join(ALLOWED_SUBFIELDS))
    print("Fetching Google Scholar pages for each professor...")

    for prof in out["professors"]:
        gs_url = prof.get("google scholar")
        gs_url_2025 = gs_url.replace("as_ylo=", "as_ylo=2025")
        if gs_url == gs_url_2025:
            raise Exception("Google Scholar URL not replaced.")
        prof["gs_results_2025"] = fetch_url(gs_url_2025, timeout=10)
        print(f"Fetched Google Scholar results for {prof.get('name')}")

    # Step 2: extract only the main result links from each professor's 2025 results
    print("Extracting result links from Google Scholar pages...")
    for prof in out["professors"]:
        html = prof.get("gs_results_2025")
        prof["gs_urls_2025"] = extract_gs_result_links(html)

    # Step 3: fetch each extracted URL and save as text files under data/<University_Professor>/<Page Title>.txt
    print("Fetching and saving research material from individual results...")
    base_dir = Path(__file__).parent / "data"
    uni_name = out.get("matched_university", "UnknownUniversity")
    for prof in out["professors"]:
        prof_name = prof.get("name", "UnknownProfessor")
        prof_dir = base_dir / f"{_sanitize_filename(uni_name)}_{_sanitize_filename(prof_name)}"
        prof_dir.mkdir(parents=True, exist_ok=True)

        for url in prof.get("gs_urls_2025"):

            # For arXiv, fetch and parse PDF into text
            if _is_arxiv_pdf_url(url) or ("arxiv.org" in url.lower()):
                try:
                    page_html = fetch_arxiv_text(url, timeout=20)
                except Exception as e:
                    print(f"Warning: failed to fetch/parse arXiv content {url}: {e}")
                    continue
            else:
                try:
                    page_html = fetch_url(url, timeout=15)
                except Exception as e:
                    print(f"Warning: failed to fetch {url}: {e}")
                    continue

            title = _page_title_from_html(page_html)
            if not title:
                # Fallback to URL path if no title
                parsed = requests.utils.urlparse(url)
                title = parsed.netloc + parsed.path
            file_name = _sanitize_filename(title) + ".txt"
            file_path = prof_dir / file_name

            if file_path.exists():
                print(f"Warning: file already exists, skipping: {file_path}")
                continue

            try:
                file_path.write_text(page_html, encoding="utf-8")
            except Exception as e:
                print(f"Warning: failed to write {file_path}: {e}")

    with open("professors.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"Results written to {f.name}")

if __name__ == "__main__":
    main()
