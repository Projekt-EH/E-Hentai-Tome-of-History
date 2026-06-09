import os
import re
import json
import time
import random
import requests
import hashlib
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, urljoin
from datetime import datetime, timezone
from urllib3.util.retry import Retry


# ==================== Configuration ====================
# Cookie credentials are stored in config.json. Keep this source template empty.
DEFAULT_COOKIES = {
    'ipb_member_id': '',
    'ipb_pass_hash': '',
    'igneous': '',
    'nw': '1',
    "star": ""
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

REQUEST_DELAY_MS = 1000
REQUEST_DELAY_JITTER = 0.30
DEBUG_MODE = False
# ================================================

def create_session():
    session = requests.Session()
    session.headers.update(HEADERS)

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

# ==================== Debug and diagnostics ====================
def is_debug_enabled() -> bool:
    return DEBUG_MODE

def debug_print(message: str):
    if is_debug_enabled():
        print(message)

def build_request_result(ok, html, error, status_code, final_url, redirected, response=None):
    result = {
        "ok": ok,
        "html": html,
        "error": error,
        "status_code": status_code,
        "final_url": final_url,
        "redirected": redirected
    }
    if is_debug_enabled():
        result.update({
            "content_type": response.headers.get("content-type") if response is not None else None,
            "content_length": len(response.text) if response is not None and response.text else 0
        })
    return result

def report_request_failure(error, status_code, final_url, exception=None):
    print(f"Request diagnosis: {error} | status={status_code} | final_url={final_url}")
    if exception is not None:
        debug_print(f"  request_error: {exception}")

def print_missing_cdiv_summary(reason, request_result):
    print(
        f"Gallery page diagnosis: {reason} "
        f"| status={request_result.get('status_code', 'N/A')} "
        f"| final_url={request_result.get('final_url', 'N/A')}"
    )

def print_missing_cdiv_debug(reason, title, url, request_result, body_text):
    debug_print(f"Gallery page diagnosis: {reason} | title={title or 'N/A'}")
    debug_print(f"  target_url: {url}")
    debug_print(f"  final_url: {request_result.get('final_url', 'N/A')}")
    debug_print(f"  redirected: {request_result.get('redirected', 'N/A')}")
    debug_print(f"  status_code: {request_result.get('status_code', 'N/A')}")
    debug_print(f"  content_type: {request_result.get('content_type', 'N/A')}")
    debug_print(f"  content_length: {request_result.get('content_length', 'N/A')}")
    snippet = body_text[:300].replace("\n", " ").strip()
    if snippet:
        debug_print(f"  page_text: {snippet}")

# ==================== Config and cookies ====================
def get_config_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "config.json")

def create_default_config():
    config_path = get_config_path()
    
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_COOKIES, f, ensure_ascii=False, indent=2)
            print(f"Created empty config template: {config_path}")
        except Exception as e:
            print(f"Failed to create config file: {e}")
    
    return config_path

def load_config_from_file():
    config_path = get_config_path()
    
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config
        else:
            print(f"Config file does not exist: {config_path}")
            return None
    except Exception as e:
        print(f"Failed to read config file: {e}")
        return None

def has_usable_cookies(cookies: dict) -> bool:
    required_cookie_names = ("ipb_member_id", "ipb_pass_hash")
    return all(str(cookies.get(name, "")).strip() for name in required_cookie_names)

def load_runtime_cookies():
    config_path = create_default_config()
    config = load_config_from_file()
    if config and has_usable_cookies(config):
        print(f"Loaded cookie config: {config_path}")
        return config

    print(f"Cookie config is missing or empty: {config_path}")
    choice = input("Continue with empty cookies? (y/N): ").strip().lower()
    if choice in ["y", "yes"]:
        print("Using empty cookies. Requests may fail.")
        return DEFAULT_COOKIES.copy()

    print("Program exited. Fill config.json and run again.")
    return None

# ==================== HTTP requests ====================
def request_html(url: str):
    try:
        response = SESSION.get(url, timeout=12)
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
    return random.uniform(base_seconds - jitter_seconds, base_seconds + jitter_seconds)

def sleep_with_jitter():
    time.sleep(get_delay_seconds())

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

# ==================== Listing page parsing ====================
def extract_gallery_urls_from_soup(soup, base_url: str):
    urls = []
    seen_keys = set()
    gallery_href_pattern = re.compile(r'/g/\d+/[A-Za-z0-9]+/?')

    for link in soup.find_all('a', href=gallery_href_pattern):
        href = link.get('href')
        full_url = urljoin(base_url, href)
        clean_url, gallery_id = process_url(full_url)
        if not clean_url or not gallery_id:
            continue
        key = extract_gallery_key(clean_url)
        if key and key not in seen_keys:
            seen_keys.add(key)
            urls.append(clean_url)

    return urls

def discover_next_page_url(soup, current_url: str):
    current_page = parse_qs(urlparse(current_url).query).get("page", ["0"])[0]

    for link in soup.find_all('a', href=True):
        text = link.get_text(" ", strip=True).lower()
        href = link.get('href')
        parsed_href = urlparse(urljoin(current_url, href))
        href_query = parse_qs(parsed_href.query)
        href_page = href_query.get("page", [None])[0]

        if text in ["next", ">"] or "next" in text:
            return urljoin(current_url, href)

        if href_page is not None:
            try:
                if int(href_page) > int(current_page):
                    return urljoin(current_url, href)
            except ValueError:
                continue

    return None

def build_incremental_page_url(current_url: str):
    parsed_url = urlparse(current_url)
    query_params = parse_qs(parsed_url.query)
    current_page = query_params.get("page", ["0"])[0]
    try:
        next_page = int(current_page) + 1
    except ValueError:
        return None

    return set_page_url(current_url, next_page)

def collect_uploader_gallery_urls(uploader_url: str, start_page=None, end_page=None):
    start_url = process_uploader_url(uploader_url)
    if not start_url:
        return []

    visited_pages = set()
    seen_gallery_keys = set()
    gallery_urls = []

    def scan_page(page_url: str):
        visited_pages.add(page_url)
        print(f"Scanning uploader page: {page_url}")

        request_result = request_html(page_url)
        if not request_result["ok"]:
            print(
                f"Uploader page request failed: {request_result['error']} "
                f"| status_code={request_result['status_code']} | {page_url}"
            )
            return 0, None

        html_content = request_result["html"]
        soup = BeautifulSoup(html_content, 'html.parser')
        page_gallery_urls = extract_gallery_urls_from_soup(soup, page_url)
        new_count = 0

        for gallery_url in page_gallery_urls:
            key = extract_gallery_key(gallery_url)
            if key and key not in seen_gallery_keys:
                seen_gallery_keys.add(key)
                gallery_urls.append(gallery_url)
                new_count += 1

        print(f"Found {new_count} new galleries on this page.")
        return new_count, soup

    if start_page is not None and end_page is not None:
        for page_number in range(start_page, end_page + 1):
            page_url = set_page_url(start_url, page_number)
            if page_url in visited_pages:
                continue
            scan_page(page_url)
            if page_number < end_page:
                sleep_with_jitter()
        return gallery_urls

    page_url = start_url
    while page_url and page_url not in visited_pages:
        new_count, soup = scan_page(page_url)
        if soup is None:
            break

        next_url = discover_next_page_url(soup, page_url)
        if not next_url:
            next_url = build_incremental_page_url(page_url)

        if not next_url or next_url in visited_pages:
            break

        if new_count == 0:
            # Stop the page=N fallback when a page no longer contributes galleries.
            break

        page_url = next_url
        sleep_with_jitter()

    return gallery_urls

# ==================== Crawl orchestration ====================
def crawl_uploader_galleries(uploader_url: str, start_page=None, end_page=None):
    gallery_urls = collect_uploader_gallery_urls(uploader_url, start_page, end_page)
    existing_gallery_ids = get_existing_gallery_ids()

    total = len(gallery_urls)
    skipped = 0
    success = 0
    failed = 0
    total_comments = 0
    failed_items = []
    skipped_items = []
    items = []

    print(f"Discovered {total} galleries.")

    for index, gallery_url in enumerate(gallery_urls, start=1):
        key = extract_gallery_key(gallery_url)
        gallery_id = key[0] if key else None

        if gallery_id in existing_gallery_ids:
            skipped += 1
            skipped_items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "reason": "already_exported"
            })
            items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "skipped_existing",
                "comments": 0,
                "reason": "already_exported"
            })
            print(f"[{index}/{total}] Skip existing gallery {gallery_id}: {gallery_url}")
            continue

        print(f"[{index}/{total}] Crawl gallery {gallery_id}: {gallery_url}")
        result = crawl_comments(gallery_url)

        if result and result.get("success"):
            success += 1
            comment_count = result.get("comments", 0)
            total_comments += comment_count
            items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "success",
                "comments": comment_count,
                "reason": None
            })
            if gallery_id:
                existing_gallery_ids.add(gallery_id)
        else:
            failed += 1
            reason = result.get("error") if result else "unknown_error"
            failed_items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "reason": reason
            })
            items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "failed",
                "comments": 0,
                "reason": reason
            })

        if index < total:
            sleep_with_jitter()

    report = {
        "discovered": total,
        "skipped_existing": skipped,
        "succeeded": success,
        "failed": failed,
        "total_comments": total_comments,
        "failed_items": failed_items,
        "skipped_items": skipped_items,
        "items": items
    }

    print("\nBatch report:")
    print(f"  discovered: {report['discovered']}")
    print(f"  skipped_existing: {report['skipped_existing']}")
    print(f"  succeeded: {report['succeeded']}")
    print(f"  failed: {report['failed']}")
    print(f"  total_comments: {report['total_comments']}")
    if failed_items:
        print("  failed_items:")
        for failed_item in failed_items:
            print(f"    {failed_item['gallery_id']} | {failed_item['reason']} | {failed_item['url']}")

    return report

def parse_time(time_str: str) -> str:
    time_str = time_str.strip()
    if "just now" in time_str.lower() or "刚刚" in time_str:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    
    formats = [
        "%d %B %Y, %H:%M",      # "04 June 2026, 12:39"
        "%d %B %Y, %H:%M:%S",   # "04 June 2026, 12:39:45"
        "%Y-%m-%d %H:%M:%S",    # "2026-06-04 12:39:45"
        "%Y-%m-%d %H:%M",       # "2026-06-04 12:39"
        "%Y-%m-%d",             # "2026-06-04"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.isoformat() + "Z"
        except ValueError:
            continue
    
    return time_str

def convert_to_mongodb_date(iso_timestamp: str) -> dict:
    if not iso_timestamp:
        return {"$date": ""}
    return {"$date": iso_timestamp}

def crawl_comments(input_url: str):
    target_url, gallery_id = process_url(input_url)
    if not target_url:
        return {"success": False, "gallery_id": None, "comments": 0, "error": "invalid_url"}
    
    print(f"Requesting gallery: {target_url}")
    
    request_result = request_html(target_url)
    if not request_result["ok"]:
        return {
            "success": False,
            "gallery_id": gallery_id,
            "comments": 0,
            "error": request_result["error"],
            "status_code": request_result["status_code"]
        }

    html_content = request_result["html"]

    soup = BeautifulSoup(html_content, 'html.parser')
    comments_list = []
    edits_list = []
    
    cdiv = soup.find('div', id='cdiv')

    if not cdiv:
        reason = diagnose_gallery_page_without_comments(
            soup,
            target_url,
            request_result=request_result
        )
        return {"success": False, "gallery_id": gallery_id, "comments": 0, "error": reason}
        
    uploader_comment = ""
    anchors = cdiv.find_all('a', attrs={'name': re.compile(r'^c\d+$')})
    
    utc_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    for anchor in anchors:
        anchor_name = anchor.get('name')
        
        if anchor_name == 'c0':
            comment_div = anchor.find_next_sibling('div')
            if comment_div:
                c6_div = comment_div.find('div', id='comment_0')
                if not c6_div:
                    c6_div = comment_div.find('div', class_='c6')
                if c6_div:
                    uploader_comment = "".join(str(child) for child in c6_div.children)
            continue
            
        comment_id = anchor_name[1:] 
        comment_div = anchor.find_next_sibling('div')
        if not comment_div:
            continue
            
        c3_div = comment_div.find('div', class_='c3')
        username = "Unknown"
        post_time = None
        
        extracted_user_id = None
        extracted_forums_url = None
        
        if c3_div:
            text_content = c3_div.get_text()
            time_match = re.search(r'Posted on\s+(.*?)\s+by:', text_content)
            if time_match:
                iso_time = parse_time(time_match.group(1))
                post_time = convert_to_mongodb_date(iso_time)
            
            user_a = c3_div.find('a')
            if user_a:
                username = user_a.get_text().strip()
            
            forums_a = c3_div.find('a', href=re.compile(r'showuser=\d+'))
            if forums_a:
                href_str = forums_a.get('href')
                id_match = re.search(r'showuser=(\d+)', href_str)
                if id_match:
                    extracted_user_id = id_match.group(1)
                    extracted_forums_url = f"https://forums.e-hentai.org/index.php?showuser={extracted_user_id}"
                
        score_span = comment_div.find('span', id=f'comment_score_{comment_id}')
        current_score = 0
        if score_span:
            try:
                current_score = int(score_span.get_text().strip())
            except ValueError:
                pass

        c7_div = comment_div.find('div', id=f'cvotes_{comment_id}')
        if not c7_div:
            c7_div = comment_div.find('div', class_='c7')
        
        power = 0
        vote_list = []
        if c7_div:
            c7_text = c7_div.get_text()
            base_match = re.search(r'Base\s+([+-]?\d+)', c7_text)
            if base_match:
                power = int(base_match.group(1))
            for span in c7_div.find_all('span'):
                span_text = span.get_text().strip()
                if "and" in span_text and "more" in span_text:
                    continue
                span_match = re.search(r'^(.*?)\s+([+-]?\d+)$', span_text, re.DOTALL)
                if span_match:
                    voter_name = span_match.group(1).strip()
                    voter_power = int(span_match.group(2))
                    vote_list.append({
                        "voter": voter_name,
                        "power": voter_power
                    })

        c6_div = comment_div.find('div', id=f'comment_{comment_id}')
        if not c6_div:
            c6_div = comment_div.find('div', class_='c6')
        
        content_html = "".join(str(child) for child in c6_div.children) if c6_div else ""
        
        c8_divs = comment_div.find_all('div', class_='c8')
        is_edited = len(c8_divs) > 0
        
        for c8 in c8_divs:
            c8_text = c8.get_text()
            edit_time_match = re.search(r'on\s+(.*)', c8_text)
            if edit_time_match:
                iso_edit_time = parse_time(edit_time_match.group(1).rstrip('.'))
            else:
                iso_edit_time = parse_time(c8_text.rstrip('.'))
            
            mongodb_edit_time = convert_to_mongodb_date(iso_edit_time)
            edit_content = content_html
            
            edits_list.append({
                "comment_id": comment_id,
                "edit_time": mongodb_edit_time,
                "edit_content": edit_content
            })

        # _id MUST be comment_id for proper indexing and upsert operations in MongoDB
        # Taking gallery updates into consideration, we should not use a composite key of gallery_id + comment_id, as comment_id will change in an update.
        comment_data = {
            "_id": comment_id,
            "gallery_id": gallery_id,
            "username": username,
            "post_time": post_time,
            "source_url": target_url,
            "current_score": current_score,
            "power": power,
            "vote_list": vote_list,
            "is_edited": is_edited,
            "fetch_time": convert_to_mongodb_date(utc_now_str)
        }
        
        if extracted_user_id:
            comment_data["user_id"] = extracted_user_id
        if extracted_forums_url:
            comment_data["user_forums_url"] = extracted_forums_url
        
        if not is_edited:
            comment_data["content"] = content_html
        
        comments_list.append(comment_data)
        
    gdn_div = soup.find('div', id='gdn')
    
    uploader_data = {
        "gallery_id": gallery_id,
        "source_url": target_url,
        "time": convert_to_mongodb_date(utc_now_str)
    }
    
    if uploader_comment:
        comment_digest = hashlib.sha256(uploader_comment.encode('utf-8')).hexdigest()
        uploader_data["uploader_comment"] = uploader_comment
        uploader_data["comment_sha256"] = comment_digest
    
    if gdn_div:
        uploader_a = gdn_div.find('a', href=re.compile(r'/uploader/'))
        if uploader_a:
            uploader_data["uploader_name"] = uploader_a.get_text().strip()
            
        forums_a = gdn_div.find('a', href=re.compile(r'showuser=\d+'))
        if forums_a:
            id_match = re.search(r'showuser=(\d+)', forums_a.get('href', ''))
            if id_match:
                uploader_data["uploader_id"] = id_match.group(1)

    if comments_list or uploader_data:
        save_all_data(comments_list, edits_list, uploader_data, gallery_id)

    return {"success": True, "gallery_id": gallery_id, "comments": len(comments_list), "error": None}

# ==================== Storage helpers ====================
def write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_existing_gallery_ids():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    comments_dir = os.path.join(current_dir, "comments")
    if not os.path.exists(comments_dir):
        return set()

    return {
        match.group(1)
        for filename in os.listdir(comments_dir)
        for match in [re.match(r'^(\d+)-\d+\.json$', filename)]
        if match
    }

def save_all_data(comments_list, edits_list, uploader_data, gallery_id: str):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = int(time.time())
    filename = f"{gallery_id}-{timestamp}.json"
    filename_edit = f"{gallery_id}-{timestamp}-edits.json"
    filename_uploader = f"{gallery_id}-{timestamp}-uploader.json"
    message = ""

    if len(comments_list) == 0:
        message += "No comments found in this gallery."
    else:
        comments_path = os.path.join(current_dir, "comments", filename)
        write_json(comments_path, comments_list)
        message += f"Saved comments: {comments_path}"
    message +="\n"
    if len(edits_list) > 0:
        edits_path = os.path.join(current_dir, "comment_edits", filename_edit)
        write_json(edits_path, edits_list)
        message += f"Saved comment edits: {edits_path}\n"
    
    if uploader_data:
        uploader_path = os.path.join(current_dir, "gallery_uploaders", filename_uploader)
        write_json(uploader_path, [uploader_data])
        message += f"Saved uploader metadata: {uploader_path}"
    message += "\n"
    print(message)

# ==================== CLI helpers and main ====================
def print_single_gallery_result(result: dict):
    status = "success" if result and result.get("success") else "failed"
    gallery_id = result.get("gallery_id") if result else None
    comments = result.get("comments") if result else 0
    error = result.get("error") if result else "unknown_error"
    print("\nSingle gallery result:")
    print(f"  status: {status}")
    print(f"  gallery_id: {gallery_id}")
    print(f"  comments: {comments}")
    print(f"  error: {error}")

# ----------------- Main -----------------
def main():
    print("=" * 50)
    print("E-Hentai comment crawler - interactive mode")
    print("=" * 50)

    config_result = load_runtime_cookies()

    if config_result is None:
        exit(0)

    SESSION.cookies.clear()
    SESSION.cookies.update(config_result)

    print("\nCrawler ready.")

    while True:
        print("\nMode:")
        print("1 - Crawl one gallery URL")
        print("2 - Crawl galleries from one uploader/listing URL")
        print("Input 'exit' or 'quit' to exit")
        mode = input("> ").strip().lower()

        if mode in ['quit', 'exit', 'q']:
            print("Program exited.")
            break

        if mode not in ['1', '2']:
            print("Invalid input. Please enter 1, 2, exit, or quit.")
            continue

        if mode == '1':
            user_input = input("\nInput E-Hentai/ExHentai gallery URL:\n> ").strip()
            if not user_input:
                print("Please input a valid URL.")
                continue
            print()
            print_single_gallery_result(crawl_comments(user_input))
        else:
            user_input = input("\nInput uploader/listing URL:\n> ").strip()
            if not user_input:
                print("Please input a valid URL.")
                continue
            page_range_input = input("\nInput page range (empty=auto, 0-3, or 2):\n> ").strip()
            try:
                start_page, end_page = parse_page_range(page_range_input)
                crawl_uploader_galleries(user_input, start_page, end_page)
            except ValueError as e:
                print(f"Invalid page range: {e}")
                continue
        print()

if __name__ == "__main__":
    main()
