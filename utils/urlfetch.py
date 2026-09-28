# E-Hentai Tome of History - a gallery comment fetcher and preserver for E-Hentai
# Copyright (C) 2026  Projekt-EH & AXIS5(AXIS5hacker)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import requests
import random
import time
import re
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from .debug_mode import build_request_result, report_request_failure, is_debug_enabled, print_missing_cdiv_summary, print_missing_cdiv_debug
from .config import load_runtime_cookies

from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, urljoin


from .constants import REQUEST_DELAY_MS, REQUEST_DELAY_JITTER, HEADERS, NEWER_VERSION_DIV_ID
# ============Session================
def create_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    config_result = load_runtime_cookies()
    if config_result is None:
        exit(0)

    session.cookies.clear()
    session.cookies.update(config_result)

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session

SESSION = create_session()

# ==================== HTTP requests ====================
def request_html(url: str,session):
    try:
        response = session.get(url, timeout=12)
        response.raise_for_status()
        final_url = response.url
        redirected = final_url != url
        if redirected:
            print(f"Request redirected: {url} -> {final_url}")
        return build_request_result(
            True, response.text, None, response.status_code, final_url, redirected, response
        )
    except requests.exceptions.Timeout as e:
        report_request_failure("timeout", None, url, e)
        return build_request_result(False, None, "timeout", None, url, False)
    except requests.exceptions.ConnectionError as e:
        report_request_failure("connection_error", None, url, e)
        return build_request_result(False, None, "connection_error", None, url, False)
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 403:
            error = "http_403"
        elif status_code == 404:
            error = "http_404"
        elif status_code == 429:
            error = "http_429"
        elif status_code and 500 <= status_code <= 599:
            error = "http_5xx"
        elif status_code:
            error = f"http_{status_code}"
        else:
            error = "http_error"
        final_url = e.response.url if e.response is not None else url
        report_request_failure(error, status_code, final_url, e)
        return build_request_result(
            False, None, error, status_code, final_url, final_url != url, e.response
        )
    except requests.exceptions.RequestException as e:
        report_request_failure("request_exception", None, url, e)
        return build_request_result(False, None, "request_exception", None, url, False)

# ==================== URL and pagination helpers ====================
def extract_gallery_key(url: str):
    parsed_url = urlparse(url)
    path_parts = [p for p in parsed_url.path.split('/') if p]
    if len(path_parts) >= 3 and path_parts[0] == "g":
        return path_parts[1], path_parts[2]
    return None

def get_delay_seconds() -> float:
    base_seconds = REQUEST_DELAY_MS / 1000
    jitter_seconds = base_seconds * REQUEST_DELAY_JITTER
    delay_seconds = random.uniform(base_seconds - jitter_seconds, base_seconds + jitter_seconds)
    return 0.650 if delay_seconds< 0.650 else delay_seconds

def sleep_with_jitter():
    time.sleep(get_delay_seconds())

# deprecated

def parse_page_range(page_range_text: str):
    text = page_range_text.strip()
    if not text:
        return None, None

    if re.fullmatch(r'\d+', text):
        page = int(text)
        return page, page

    match = re.fullmatch(r'(\d+)\s*-\s*(\d+)', text)
    if not match:
        raise ValueError("Page range must be empty, a single number, or start-end.")

    start_page = int(match.group(1))
    end_page = int(match.group(2))
    if start_page > end_page:
        raise ValueError("Page range start must be less than or equal to end.")

    return start_page, end_page

    
def set_page_url(url: str, page_number: int):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params["page"] = [str(page_number)]
    return urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        urlencode(query_params, doseq=True),
        parsed_url.fragment
    ))

def process_url(url: str):
    parsed_url = urlparse(url)
    allowed_domains = ["e-hentai.org", "exhentai.org"]
    
    if parsed_url.netloc not in allowed_domains or not parsed_url.path.startswith("/g/"):
        print("Invalid gallery URL. Only https://e-hentai.org/g/* and https://exhentai.org/g/* are allowed.")
        return None, None
    
    path_parts = [p for p in parsed_url.path.split('/') if p]
    gallery_id = path_parts[1] if len(path_parts) > 1 else "unknown"
    
    query_params = parse_qs(parsed_url.query)
    if 'hc' not in query_params or query_params['hc'] != ['1']:
        query_params['hc'] = '1'
        
    new_query = urlencode(query_params, doseq=True)
    clean_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))
    return clean_url, gallery_id

def process_uploader_url(url: str):
    parsed_url = urlparse(url)
    allowed_domains = ["e-hentai.org", "exhentai.org"]
    if parsed_url.scheme not in ["http", "https"] or parsed_url.netloc not in allowed_domains:
        print("Invalid uploader URL. Only e-hentai.org and exhentai.org are allowed.")
        return None
    return urlunparse((
        "https",
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        parsed_url.query,
        parsed_url.fragment
    ))

# ==================== Gallery version notice ====================
def extract_newer_version_links(soup, base_url: str):
    """
    Parse the "There are newer versions of this gallery available:" notice, which E-Hentai
    renders inside <div id="gnd"> whenever a gallery has been replaced by a newer upload:

        <div id="gnd">
            <p style="font-weight:bold">There are newer versions of this gallery available:</p>
            <a href="https://e-hentai.org/g/4084827/59a22262d0/">[Artist] Title [Chinese]</a>, added 2026-07-29 10:32<br />
            <a href="https://e-hentai.org/g/4094456/3eb184d721/">[Artist] Title [Chinese]</a>, added 2026-08-03 12:04<br />
        </div>

    Returns a list of entries in document order (top to bottom), each one a dict:
        {"url": <clean gallery url>, "gallery_id": <str>, "title": <str>, "added": <str|None>}

    Links that are not gallery links are ignored, and an empty list is returned when the
    notice is absent.
    """
    gnd_div = soup.find('div', id=NEWER_VERSION_DIV_ID)
    if not gnd_div:
        return []

    # The "added YYYY-MM-DD HH:MM" stamps sit next to their <a> tag, so collecting them from
    # the container text keeps both sequences in the same (document) order.
    added_stamps = re.findall(
        r'added\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)',
        gnd_div.get_text(" ", strip=True)
    )

    links = []
    for index, anchor in enumerate(gnd_div.find_all('a', href=True)):
        full_url = urljoin(base_url, anchor.get('href'))
        if extract_gallery_key(full_url) is None:
            continue
        clean_url, gallery_id = process_url(full_url)
        if not clean_url or not gallery_id:
            continue
        links.append({
            "url": clean_url,
            "gallery_id": gallery_id,
            "title": anchor.get_text(" ", strip=True),
            "added": added_stamps[index] if index < len(added_stamps) else None
        })

    return links


def select_newest_version_link(newer_links: list):
    """
    Pick the version that should be crawled out of :func:`extract_newer_version_links`.

    Rule: the bottom-most entry is the newest version, and that is the one we crawl.
    E-Hentai lists the entries in ascending "added" order, so the bottom-most entry normally
    carries the latest timestamp as well; when it does not, a warning is returned (and
    printed by the caller) so that a change in the page layout cannot silently send the
    crawler back to an older version.

    Returns (link_or_None, warning_or_None).
    """
    if not newer_links:
        return None, None

    newest_link = newer_links[-1]
    dated_links = [link for link in newer_links if link.get("added")]
    warning = None
    if len(dated_links) == len(newer_links):
        latest_added = max(dated_links, key=lambda link: link["added"])
        if latest_added["gallery_id"] != newest_link["gallery_id"]:
            warning = (
                "Warning: the bottom-most gallery version entry is not the one with the latest "
                f"\"added\" stamp (bottom: {newest_link['gallery_id']} added {newest_link['added']}, "
                f"latest: {latest_added['gallery_id']} added {latest_added['added']}). "
                "Crawling the bottom-most entry as usual."
            )

    return newest_link, warning


# ==================== Gallery page diagnostics ====================
def classify_missing_cdiv_reason(soup, url: str):
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body_text = soup.get_text(" ", strip=True)
    page_text = f"{title} {body_text}".lower()

    content_warning_keywords = [
        "content warning",
        "view gallery",
        "continue to gallery"
    ]
    permission_keywords = [
        "you must be logged on",
        "please log in",
        "not have permission",
        "insufficient privileges",
        "access denied",
        "forbidden"
    ]
    removed_keywords = [
        "this gallery has been removed",
        "gallery has been removed",
        "expunged",
        "removed or unavailable",
        "this gallery is not available"
    ]
    unavailable_keywords = [
        "gallery not found",
        "404 not found",
        "invalid gallery",
        "temporarily unavailable",
        "unavailable"
    ]

    if any(keyword in page_text for keyword in content_warning_keywords):
        reason = "content_warning"
    elif any(keyword in page_text for keyword in permission_keywords):
        reason = "permission_denied"
    elif any(keyword in page_text for keyword in removed_keywords):
        reason = "gallery_removed_or_expunged"
    elif any(keyword in page_text for keyword in unavailable_keywords):
        reason = "gallery_unavailable"
    elif extract_gallery_key(url) is None or "/g/" not in urlparse(url).path:
        reason = "not_gallery_page"
    else:
        reason = "missing_comment_container"

    return reason, title, body_text

def diagnose_gallery_page_without_comments(soup, url: str, request_result=None):
    request_result = request_result or {}
    reason, title, body_text = classify_missing_cdiv_reason(soup, url)

    if not is_debug_enabled():
        print_missing_cdiv_summary(reason, request_result)
        return reason

    print_missing_cdiv_debug(reason, title, url, request_result, body_text)
    return reason