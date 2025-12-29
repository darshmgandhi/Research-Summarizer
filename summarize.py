import argparse
import json
import re
import time
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://drafty.cs.brown.edu/csopenrankings/"
PROFBYSCHOOL_URL = "https://drafty.cs.brown.edu/csopenrankings/frontend/profBySchool.js"

ALLOWED_SUBFIELDS = ["ai", "vision", "ir", "mlmining", "nlp"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; cs-openrankings-scraper/1.0; +https://example.com)"
}


def fetch_url(url, timeout=15, retries=2, backoff=1.0):
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("university", help="University name to search for (partial match allowed)")
    p.add_argument("-o", "--output", help="Optional output file to save JSON results")
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

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
