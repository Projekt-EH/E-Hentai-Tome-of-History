from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from mongoutils import DataBuffer, get_comment_deletion_tracker
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

    # Comment deletion detection for the whole batch: snapshot the comment IDs we already store
    # for every gallery of the list before the first request is made, so that all comparisons of
    # this run are made against one consistent database state. Galleries that fail to crawl are
    # never compared, and a gallery whose newest version is a different gallery gets its own
    # just-in-time snapshot (see CommentDeletionTracker.snapshot_for).
    deletion_tracker = get_comment_deletion_tracker(client)
    if deletion_tracker is not None:
        gallery_ids = []
        for gallery_url in gallery_urls:
            key = extract_gallery_key(gallery_url)
            if key:
                gallery_ids.append(key[0])
        snapshotted = deletion_tracker.prefetch(gallery_ids)
        print(f"Comment deletion check: snapshotted existing comments of {snapshotted} gallery/galleries.")

    print(f"Discovered {total} galleries.")

    def process_gallery(args):
        index, gallery_url = args
        key = extract_gallery_key(gallery_url)
        gallery_id = key[0] if key else None

        print(f"[{index}/{total}] Crawl gallery {gallery_id}: {gallery_url}")
        crawl_result = crawl_comments(client, gallery_url, data_buffer=data_buffer, deletion_tracker=deletion_tracker)

        if crawl_result and crawl_result.get("success"):
            comment_count = crawl_result.get("comments", 0)
            deletion = crawl_result.get("deletion") or {}
            result = {
                "gallery_id": crawl_result.get("gallery_id") or gallery_id,
                "url": gallery_url,
                "status": "success",
                "comments": comment_count,
                "deleted_comments": deletion.get("deleted", 0),
                "marked_deleted_comments": deletion.get("marked", 0),
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

    total_deleted_comments = sum(item.get("deleted_comments", 0) for item in items if item["status"] == "success")
    total_marked_deleted = sum(item.get("marked_deleted_comments", 0) for item in items if item["status"] == "success")

    report = {
        "discovered": total,
        "succeeded": success,
        "failed": failed,
        "total_comments": total_comments,
        "total_deleted_comments": total_deleted_comments,
        "total_marked_deleted_comments": total_marked_deleted,
        "failed_items": failed_items,
        "items": items
    }

    data_buffer.flush()
    db_stats = data_buffer.get_stats()
    report["db_stats"] = db_stats
    report["deletion_stats"] = deletion_tracker.get_stats() if deletion_tracker is not None else None

    return report
