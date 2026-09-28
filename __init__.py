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

import argparse
import os

from utils.debug_mode import DEBUG_MODE
from utils.config import load_runtime_cookies
from utils.constants import REQUEST_DELAY_MS, REQUEST_DELAY_JITTER, HEADERS
from utils.batch_crawling import crawl_uploader_galleries, crawl_gallery_urls
from utils.auto_mode import run_auto_mode, get_default_auto_config_path
from utils.result import print_batch_crawling_report

from etc.comment_merge import merge_comment
from etc.edit_merge import merge_edit
from etc.uploader_merge import merge_uploader

from mongoutils import get_mongo_client, check_database

# ----------------- Input helpers -----------------
def read_gallery_urls():
    """
    Read gallery URLs from the terminal, one URL per line. An empty line ends the input.

    Returns the URLs in input order; duplicate lines are reported and skipped.
    """
    print("\nInput E-Hentai/ExHentai gallery URL(s), one per line. Finish with an empty line.")
    urls = []
    seen = set()
    while True:
        line = input("> ").strip()
        if not line:
            break
        if line in seen:
            print(f"Skipped duplicate URL: {line}")
            continue
        seen.add(line)
        urls.append(line)
    return urls


# ----------------- Main -----------------
def main(max_workers=15):
    
    print(f"Parallel crawl workers: {max_workers}")

    while True:
        print("\nMode:")
        print("1 - Crawl gallery URL(s), one URL per line (empty line to start)")
        print("2 - Crawl galleries from one uploader/listing URL")
        print("3 - Run JSON merging utility (for merging/summarizing previously saved JSON files)")
        print("4 - Run auto jobs")
        print("5 - About")
        print("Input 'exit' or 'quit' to exit")
        mode = input("> ").strip().lower()

        if mode in ['quit', 'exit', 'q']:
            print("Program exited.")
            break

        if mode not in ['1', '2', '3', '4','5']:
            print("Invalid input. Please enter 1, 2, 3, 4, 5 ,exit, or quit.")
            continue

        if mode == '1':
            # Crawl one or more gallery URLs, one URL per line
            gallery_urls = read_gallery_urls()
            if not gallery_urls:
                print("No gallery URL was given.")
                continue
            print()
            crawl_gallery_urls(gallery_urls, mongo_client)
        elif mode == '2':
            # Batch crawl from uploader/listing URL
            user_input = input("\nInput uploader/listing URL:\n> ").strip()
            if not user_input:
                print("Please input a valid URL.")
                continue
            page_depth_input = input("\nInput page depth (empty=auto, 0=first page only, N=click next N times):\n> ").strip()
            if page_depth_input == "":
                page_depth = None
            else:
                try:
                    page_depth = int(page_depth_input)
                    if page_depth < 0:
                        raise ValueError("page depth must be >= 0")
                except ValueError as e:
                    print(f"Invalid page depth: {e}")
                    continue
            print_batch_crawling_report(crawl_uploader_galleries(user_input, page_depth, client=mongo_client,max_workers=max_workers))
        elif mode == '3':
            # JSON merging utility
            print("Starting JSON merging utility...")
            merge_comment(os.path.join(os.path.dirname(__file__), 'comments'))
            merge_edit(os.path.join(os.path.dirname(__file__), 'comment_edits'))
            merge_uploader(os.path.join(os.path.dirname(__file__), 'gallery_uploaders'))
        elif mode == '4':
            # Auto mode
            config_path = input("\nInput auto jobs JSON path (empty=auto_jobs.json):\n> ").strip()
            run_auto_mode(config_path or get_default_auto_config_path(), client=mongo_client, max_workers=max_workers)
        else:
            # About
            print("""
E-Hentai Tome of History - a gallery comment fetcher and preserver for E-Hentai
Copyright (C) 2026  Projekt-EH & AXIS5(AXIS5hacker)

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.""")
        print()


if __name__ == "__main__":

    print("=" * 50)
    print("""
    E-Hentai Tome of History - a gallery comment fetcher and preserver for E-Hentai
    Copyright (C) 2026  Projekt-EH & AXIS5(AXIS5hacker)
    """)
    print("=" * 50)

    parser = argparse.ArgumentParser(description="E-Hentai comment crawler")
    parser.add_argument("-p", "--parallel", type=int, default=15,
                        help="Max parallel workers for uploader/listing crawling (1-20, default: 15)")
    parser.add_argument("--auto", nargs="?", const=get_default_auto_config_path(),
                        help="Run auto mode with an optional auto_jobs.json path.")
    args = parser.parse_args()
    max_workers = max(1, min(args.parallel, 20))

    mongo_client = get_mongo_client()
    check_database(mongo_client)

    if args.auto is not None:
        exit(run_auto_mode(args.auto, client=mongo_client, max_workers=max_workers))

    print(f"Interactive mode started.")
    main(max_workers=max_workers)
