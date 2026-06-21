from .batch_gallery_list import collect_uploader_gallery_urls
from .savejson import get_existing_gallery_ids
from .urlfetch import *
from .crawl import crawl_comments
# ==================== Crawl orchestration ====================
def crawl_uploader_galleries(uploader_url: str, page_depth=None):
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

    print(f"Discovered {total} galleries.")

    for index, gallery_url in enumerate(gallery_urls, start=1):
        key = extract_gallery_key(gallery_url)
        gallery_id = key[0] if key else None

        if gallery_id in existing_gallery_ids:
            skipped += 1
            skipped_items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "reason": "already_exported"
            })
            items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "skipped_existing",
                "comments": 0,
                "reason": "already_exported"
            })
            print(f"[{index}/{total}] Skip existing gallery {gallery_id}: {gallery_url}")
            continue

        print(f"[{index}/{total}] Crawl gallery {gallery_id}: {gallery_url}")
        result = crawl_comments(gallery_url)

        if result and result.get("success"):
            success += 1
            comment_count = result.get("comments", 0)
            total_comments += comment_count
            items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "success",
                "comments": comment_count,
                "reason": None
            })
            if gallery_id:
                existing_gallery_ids.add(gallery_id)
        else:
            failed += 1
            reason = result.get("error") if result else "unknown_error"
            failed_items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "reason": reason
            })
            items.append({
                "gallery_id": gallery_id,
                "url": gallery_url,
                "status": "failed",
                "comments": 0,
                "reason": reason
            })

        if index < total:
            sleep_with_jitter()

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