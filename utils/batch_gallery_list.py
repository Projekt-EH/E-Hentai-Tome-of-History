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

import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urljoin

from .urlfetch import *
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

# auto discovery mode: find "next page" link inside div.searchnav > unext
def discover_next_page_url(soup, current_url: str):
    searchnav = soup.find('div', class_='searchnav')
    if not searchnav:
        return None

    unext = searchnav.find(id='unext')
    if unext is None or unext.name != 'a':
        return None

    href = unext.get('href')
    if not href:
        return None

    return urljoin(current_url, href)

# invalid
"""
def build_incremental_page_url(current_url: str):
    parsed_url = urlparse(current_url)
    query_params = parse_qs(parsed_url.query)
    current_page = query_params.get("page", ["0"])[0]
    try:
        next_page = int(current_page) + 1
    except ValueError:
        return None

    return set_page_url(current_url, next_page)
"""

def collect_uploader_gallery_urls(uploader_url: str, page_depth=None):
    start_url = process_uploader_url(uploader_url)
    if not start_url:
        return []

    visited_pages = set()
    seen_gallery_keys = set()
    gallery_urls = []

    def scan_page(page_url: str):
        visited_pages.add(page_url)
        print(f"Scanning uploader page: {page_url}")

        request_result = request_html(page_url, SESSION)
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

    page_url = start_url
    depth = 0
    while page_url and page_url not in visited_pages:
        new_count, soup = scan_page(page_url)
        if soup is None:
            break

        if page_depth is not None and depth >= page_depth:
            break

        next_url = discover_next_page_url(soup, page_url)
        if not next_url or next_url in visited_pages:
            break

        page_url = next_url
        depth += 1
        sleep_with_jitter()

    return gallery_urls
