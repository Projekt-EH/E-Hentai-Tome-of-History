from utils.debug_mode import DEBUG_MODE
from utils.config import load_runtime_cookies
from utils.constants import REQUEST_DELAY_MS, REQUEST_DELAY_JITTER, HEADERS
from utils.batch_crawling import crawl_uploader_galleries
from utils.crawl import crawl_comments

from etc.comment_merge import merge_comment
from etc.edit_merge import merge_edit
from etc.uploader_merge import merge_uploader

import os
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
    
    print("\nCrawler ready.")

    while True:
        print("\nMode:")
        print("1 - Crawl one gallery URL")
        print("2 - Crawl galleries from one uploader/listing URL")
        print("3 - Run JSON merging utility (for merging/summarizing previously saved JSON files)")
        print("Input 'exit' or 'quit' to exit")
        mode = input("> ").strip().lower()

        if mode in ['quit', 'exit', 'q']:
            print("Program exited.")
            break

        if mode not in ['1', '2','3']:
            print("Invalid input. Please enter 1, 2, exit, or quit.")
            continue

        if mode == '1':
            # Crawl one gallery URL
            user_input = input("\nInput E-Hentai/ExHentai gallery URL:\n> ").strip()
            if not user_input:
                print("Please input a valid URL.")
                continue
            print()
            print_single_gallery_result(crawl_comments(user_input))
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
            crawl_uploader_galleries(user_input, page_depth)
        else:
            # JSON merging utility
            print("Starting JSON merging utility...")
            merge_comment(os.path.join(os.path.dirname(__file__), 'comments'))
            merge_edit(os.path.join(os.path.dirname(__file__), 'comment_edits'))
            merge_uploader(os.path.join(os.path.dirname(__file__), 'gallery_uploaders'))
        print()

if __name__ == "__main__":
    main()