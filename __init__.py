import argparse
import os

from utils.debug_mode import DEBUG_MODE
from utils.config import load_runtime_cookies
from utils.constants import REQUEST_DELAY_MS, REQUEST_DELAY_JITTER, HEADERS
from utils.batch_crawling import crawl_uploader_galleries
from utils.crawl import crawl_comments
from utils.auto_mode import run_auto_mode, get_default_auto_config_path
from utils.result import print_single_gallery_result, print_batch_crawling_report

from etc.comment_merge import merge_comment
from etc.edit_merge import merge_edit
from etc.uploader_merge import merge_uploader

from mongoutils import get_mongo_client, check_database

# ----------------- Main -----------------
def main(max_workers=15):
    print("=" * 50)
    print("E-Hentai comment crawler - interactive mode")
    print("=" * 50)
    print(f"Parallel crawl workers: {max_workers}")

    mongo_client = get_mongo_client()
    check_database(mongo_client)

    while True:
        print("\nMode:")
        print("1 - Crawl one gallery URL")
        print("2 - Crawl galleries from one uploader/listing URL")
        print("3 - Run JSON merging utility (for merging/summarizing previously saved JSON files)")
        print("4 - Run auto jobs")
        print("Input 'exit' or 'quit' to exit")
        mode = input("> ").strip().lower()

        if mode in ['quit', 'exit', 'q']:
            print("Program exited.")
            break

        if mode not in ['1', '2', '3', '4']:
            print("Invalid input. Please enter 1, 2, 3, 4, exit, or quit.")
            continue

        if mode == '1':
            # Crawl one gallery URL
            user_input = input("\nInput E-Hentai/ExHentai gallery URL:\n> ").strip()
            if not user_input:
                print("Please input a valid URL.")
                continue
            print()
            print_single_gallery_result(crawl_comments(mongo_client,user_input))
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
        else:
            # Auto mode
            config_path = input("\nInput auto jobs JSON path (empty=auto_jobs.json):\n> ").strip()
            run_auto_mode(config_path or get_default_auto_config_path(), client=mongo_client, max_workers=max_workers)
        print()


if __name__ == "__main__":
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

    main(max_workers=max_workers)
