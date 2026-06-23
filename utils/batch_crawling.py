from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from mongoutils import DataBuffer
from .batch_gallery_list import collect_uploader_gallery_urls
from .urlfetch import *
from .crawl import crawl_comments


# ==================== Crawl orchestration ====================
def crawl_uploader_galleries(uploader_url: str, page_depth=None, max_workers=15, client=None):
    gallery_urls = collect_uploader_gallery_urls(uploader_url, page_depth)

    total = len(gallery_urls)
    success = 0
    failed = 0
    total_comments = 0
    failed_items = []
    items = []

    if client is None:
        raise ValueError("A MongoDB client is required for batch crawling.")

    data_buffer = DataBuffer(client)

    print(f"Discovered {total} galleries.")

    def process_gallery(args):
        index, gallery_url = args
        key = extract_gallery_key(gallery_url)
        gallery_id = key[0] if key else None

        print(f"[{index}/{total}] Crawl gallery {gallery_id}: {gallery_url}")
        crawl_result = crawl_comments(client, gallery_url, data_buffer=data_buffer)

        if crawl_result and crawl_result.get("success"):
            comment_count = crawl_result.get("comments", 0)
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
            if item["status"] == "success":
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
        "succeeded": success,
        "failed": failed,
        "total_comments": total_comments,
        "failed_items": failed_items,
        "items": items
    }

    data_buffer.flush()
    db_stats = data_buffer.get_stats()
    report["db_stats"] = db_stats

    return report
