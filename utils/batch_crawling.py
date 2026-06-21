import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .batch_gallery_list import collect_uploader_gallery_urls
from .savejson import get_existing_gallery_ids
from .urlfetch import *
from .crawl import crawl_comments

# ==================== Crawl orchestration ====================
def crawl_uploader_galleries(uploader_url: str, page_depth=None, max_workers=15):
    gallery_urls = collect_uploader_gallery_urls(uploader_url, page_depth)
    existing_gallery_ids = get_existing_gallery_ids()

    total = len(gallery_urls)
    skipped = 0
    success = 0
    failed = 0
    total_comments = 0
    failed_items = []
    skipped_items = []
    items = []

    lock = threading.Lock()

    print(f"Discovered {total} galleries.")

    def process_gallery(args):
        index, gallery_url = args
        key = extract_gallery_key(gallery_url)
        gallery_id = key[0] if key else None

        with lock:
            already_exported = gallery_id in existing_gallery_ids
        # Prepare a result dict and always sleep before returning so each
        # worker thread pauses between gallery crawls.
        if already_exported:
            print(f"[{index}/{total}] Skip existing gallery {gallery_id}: {gallery_url}")
            result = {
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "skipped_existing",
                "comments": 0,
                "reason": "already_exported"
            }
            sleep_with_jitter()
            return result

        print(f"[{index}/{total}] Crawl gallery {gallery_id}: {gallery_url}")
        crawl_result = crawl_comments(gallery_url)

        if crawl_result and crawl_result.get("success"):
            comment_count = crawl_result.get("comments", 0)
            with lock:
                if gallery_id:
                    existing_gallery_ids.add(gallery_id)
            result = {
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "success",
                "comments": comment_count,
                "reason": None
            }
        else:
            reason = crawl_result.get("error") if crawl_result else "unknown_error"
            result = {
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "failed",
                "comments": 0,
                "reason": reason
            }
        sleep_with_jitter()
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(process_gallery, (index, url)): url
            for index, url in enumerate(gallery_urls, start=1)
        }
        for future in as_completed(future_to_url):
            item = future.result()
            items.append(item)
            if item["status"] == "skipped_existing":
                skipped += 1
                skipped_items.append({
                    "gallery_id": item["gallery_id"],
                    "url": item["url"],
                    "reason": item["reason"]
                })
            elif item["status"] == "success":
                success += 1
                total_comments += item["comments"]
            else:
                failed += 1
                failed_items.append({
                    "gallery_id": item["gallery_id"],
                    "url": item["url"],
                    "reason": item["reason"]
                })

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
