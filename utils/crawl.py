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

import hashlib
import re

from datetime import datetime, timezone
from bs4 import BeautifulSoup

from .urlfetch import (
    SESSION,
    process_url,
    request_html,
    diagnose_gallery_page_without_comments,
    extract_newer_version_links,
    select_newest_version_link,
    sleep_with_jitter,
)
from .constants import MAX_GALLERY_VERSION_HOPS
from mongoutils import DataBuffer, get_comment_deletion_tracker, move_gallery_comments

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

def resolve_latest_gallery_version(target_url: str, gallery_id: str, on_switch=None):
    """
    Follow the "There are newer versions of this gallery available:" notice until the newest
    version of the gallery is reached.

    E-Hentai renders that notice inside <div id="gnd"> when the gallery has been replaced by a
    newer upload; the bottom-most entry of the notice is the newest version and is the one we
    crawl (see :func:`utils.urlfetch.select_newest_version_link`). Every switch prints
    "switched to new version: <gallery ID>" right before that version is requested, and the
    chain is followed until a page without such a notice is reached, a version repeats, or
    ``MAX_GALLERY_VERSION_HOPS`` hops were made.

    ``on_switch(from_gallery_id, to_gallery_id, to_url)`` is called for every version that was
    left behind once its successor has been fetched successfully -- this is where the crawler
    re-points the stored comments of the outdated gallery. A switch whose target could not be
    fetched is never reported, so nothing is migrated when the newest version is unreachable.

    Returns a dict:
        {
            "ok": bool,               # True when a gallery page was fetched successfully
            "error": str | None,      # request error of the last failed request
            "status_code": int | None,
            "request_result": dict,   # raw result of the last request
            "soup": BeautifulSoup | None,
            "target_url": str,        # URL of the page in "soup"
            "gallery_id": str         # gallery ID of the page in "soup"
        }
    """
    visited_gallery_ids = {gallery_id}
    pending_switches = []
    soup = None

    for _ in range(max(1, MAX_GALLERY_VERSION_HOPS + 1)):
        print(f"Requesting gallery: {target_url}")

        request_result = request_html(target_url, SESSION)
        if not request_result["ok"]:
            return {
                "ok": False,
                "error": request_result["error"],
                "status_code": request_result["status_code"],
                "request_result": request_result,
                "soup": None,
                "target_url": target_url,
                "gallery_id": gallery_id
            }

        soup = BeautifulSoup(request_result["html"], 'html.parser')

        # The page of the version we switched to has been fetched, so the galleries we left
        # behind are now known to be outdated: hand them over to the caller.
        if pending_switches and on_switch is not None:
            for switch in pending_switches:
                on_switch(switch["from_gallery_id"], switch["to_gallery_id"], switch["to_url"])
        pending_switches = []

        newer_links = extract_newer_version_links(soup, target_url)
        newest_link, warning = select_newest_version_link(newer_links)
        if warning:
            print(warning)

        if not newest_link:
            break

        if newest_link["gallery_id"] == gallery_id or newest_link["gallery_id"] in visited_gallery_ids:
            print(
                f"Gallery {gallery_id} points to an already fetched version "
                f"({newest_link['gallery_id']}); keeping the current page."
            )
            break

        pending_switches.append({
            "from_gallery_id": gallery_id,
            "to_gallery_id": newest_link["gallery_id"],
            "to_url": newest_link["url"]
        })
        target_url = newest_link["url"]
        gallery_id = newest_link["gallery_id"]
        visited_gallery_ids.add(gallery_id)
        print(f"switched to new version: {gallery_id}")
        sleep_with_jitter()
    else:
        print(
            f"Gallery version hop limit ({MAX_GALLERY_VERSION_HOPS}) reached; "
            f"stopping at gallery {gallery_id}."
        )

    return {
        "ok": True,
        "error": None,
        "status_code": 200,
        "request_result": request_result,
        "soup": soup,
        "target_url": target_url,
        "gallery_id": gallery_id
    }


def crawl_comments(mongo_client, input_url: str, data_buffer: DataBuffer = None, deletion_tracker=None):
    """
    Crawl the comments of a single gallery.

    The requested gallery is first resolved to its newest version when E-Hentai reports that
    newer versions exist (see :func:`resolve_latest_gallery_version`). Comments stored under the
    gallery ID of the outdated upload are then re-pointed at the newest version (gallery_id and
    source_url, see :func:`mongoutils.move_gallery_comments`), and comments that are already
    stored in MongoDB for the crawled gallery but are missing from this crawl are flagged as
    deleted (``cleaned = True``) by a :class:`mongoutils.CommentDeletionTracker`.

    For single gallery, data_buffer can be None, and the function will create a temporary DataBuffer to flush data immediately.
    For batch crawling, a shared DataBuffer should be provided to accumulate results and flush later.
    A shared deletion_tracker (batch crawling, pre-filled by CommentDeletionTracker.prefetch) is
    reused when provided; otherwise a tracker is created for this gallery alone.
    """
    target_url, gallery_id = process_url(input_url)
    if not target_url:
        return {"success": False, "gallery_id": None, "comments": 0, "error": "invalid_url"}

    def move_superseded_gallery(from_gallery_id, to_gallery_id, to_url):
        """
        Gallery update: the requested gallery was replaced by a newer upload, so the comments
        stored for it belong to that newer version and are re-pointed at it (gallery_id and
        source_url). Called by resolve_latest_gallery_version once the newer version has been
        fetched successfully, i.e. before the comment IDs of the newest gallery are collected
        for the deletion check.
        """
        moved = move_gallery_comments(mongo_client, from_gallery_id, to_gallery_id, to_url)
        if moved:
            print(f"Gallery update: {moved} comment(s) moved from gallery {from_gallery_id} to {to_gallery_id}")

    on_switch = move_superseded_gallery if mongo_client is not None else None
    resolution = resolve_latest_gallery_version(target_url, gallery_id, on_switch=on_switch)
    target_url = resolution.get("target_url") or target_url
    gallery_id = resolution.get("gallery_id") or gallery_id

    if not resolution["ok"]:
        return {
            "success": False,
            "gallery_id": gallery_id,
            "comments": 0,
            "error": resolution["error"],
            "status_code": resolution["status_code"]
        }

    soup = resolution["soup"]
    request_result = resolution["request_result"]
    comments_list = []
    edits_list = []

    cdiv = soup.find('div', id='cdiv')

    if not cdiv:
        reason = diagnose_gallery_page_without_comments(
            soup,
            target_url,
            request_result=request_result
        )
        return {
            "success": False,
            "gallery_id": gallery_id,
            "comments": 0,
            "error": reason
        }

    # The comment IDs we already store for this gallery must be collected before the comments
    # crawled below reach MongoDB (the DataBuffer may flush while we are still parsing), so the
    # deletion check compares against the state from before this crawl.
    tracker = deletion_tracker
    if tracker is None:
        tracker = get_comment_deletion_tracker(mongo_client)
    if tracker is not None:
        tracker.snapshot_for(gallery_id)

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

        # Comment existence is not decided here: after the whole page has been parsed, the
        # comment IDs that MongoDB knows for this gallery are compared with the IDs collected
        # below, and the ones that are missing are flagged as deleted (see the
        # CommentDeletionTracker call at the end of this function). Comments written here are
        # therefore always stored with cleaned = False.
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
            "fetch_time": convert_to_mongodb_date(utc_now_str),
            "cleaned": False # check if the comment is gone
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

    # Comment deletion check: everything MongoDB stores for this gallery that was not seen in
    # this successful crawl is gone from the gallery page, so it is flagged as deleted. The
    # comparison is made by comment ID (the stable E-Hentai comment ID used as the document _id).
    deletion_report = None
    if tracker is not None:
        deletion_report = tracker.check(gallery_id, [comment["_id"] for comment in comments_list])
        if deletion_report.get("deleted"):
            print(
                f"Deleted comments in gallery {gallery_id}: {deletion_report['deleted']} "
                f"({deletion_report['marked']} flagged as cleaned)."
            )

    result = {
        "success": True,
        "gallery_id": gallery_id,
        "comments": len(comments_list),
        "error": None,
        "deletion": deletion_report
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