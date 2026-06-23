import hashlib
import re

from datetime import datetime, timezone
from bs4 import BeautifulSoup

from .urlfetch import SESSION, process_url, request_html, diagnose_gallery_page_without_comments
from mongoutils import DataBuffer

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

def convert_to_mongodb_date(iso_timestamp: str):
    """
    Convert an ISO 8601 timestamp string to a Python datetime object.
    Returns None for empty/invalid input so MongoDB stores it as null.
    """
    if not iso_timestamp:
        return None
    try:
        normalized = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None

def crawl_comments(mongo_client, input_url: str, data_buffer: DataBuffer = None):
    """
    For single gallery, data_buffer can be None, and the function will create a temporary DataBuffer to flush data immediately.
    For batch crawling, a shared DataBuffer should be provided to accumulate results and flush later.
    """
    target_url, gallery_id = process_url(input_url)
    if not target_url:
        return {"success": False, "gallery_id": None, "comments": 0, "error": "invalid_url"}
    
    print(f"Requesting gallery: {target_url}")
    
    request_result = request_html(target_url,SESSION)
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

    result = {
        "success": True,
        "gallery_id": gallery_id,
        "comments": len(comments_list),
        "error": None
    }

    if comments_list or edits_list or uploader_data:
        buffer = data_buffer
        # single gallery crawl, create a temporary DataBuffer to flush immediately
        if buffer is None:
            buffer = DataBuffer(mongo_client)
        buffer.add_gallery_result(comments_list, edits_list, [uploader_data] if uploader_data else [])
        # flush immediately for single gallery crawl
        if data_buffer is None:
            buffer.flush()
            result["db_stats"] = buffer.get_stats()

    return result