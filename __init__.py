from utils.debug_mode import DEBUG_MODE
from utils.config import load_runtime_cookies
from utils.constants import REQUEST_DELAY_MS, REQUEST_DELAY_JITTER, HEADERS
from utils.urlfetch import parse_page_range
from utils.batch_crawling import crawl_uploader_galleries
from utils.crawl import crawl_comments

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