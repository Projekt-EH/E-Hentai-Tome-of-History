import json

def print_single_gallery_result(result: dict):
    status = "success" if result and result.get("success") else "failed"
    gallery_id = result.get("gallery_id") if result else None
    comments = result.get("comments") if result else 0
    error = result.get("error") if result else "unknown_error"
    update_results = result.get("db_stats",{})
    print("\nSingle gallery result:")
    print(f"  status: {status}")
    print(f"  gallery_id: {gallery_id}")
    print(f"  comments: {comments}")
    print(f"  error: {error}")

    update_results_str = json.dumps(update_results, indent=4, ensure_ascii=False,) if update_results else "{}"
    prefix_space = " " * 2
    update_results_str = "\n".join(prefix_space + line for line in update_results_str.splitlines())
    print(f"  update_results:\n{update_results_str}")

def print_batch_crawling_report(report: dict):
    discovered = report.get("discovered", 0)
    succeeded = report.get("succeeded", 0)
    failed = report.get("failed", 0)
    total_comments = report.get("total_comments", 0)
    failed_items = report.get("failed_items", [])
    items = report.get("items", [])
    db_stats = report.get("db_stats", {})

    print("\nBatch crawling report:")
    print(f"  discovered: {discovered}")
    print(f"  succeeded: {succeeded}")
    print(f"  failed: {failed}")
    print(f"  total_comments: {total_comments}")
    
    if failed_items:
        print("  failed_items:")
        for failed_item in failed_items:
            gallery_id = failed_item.get("gallery_id")
            reason = failed_item.get("reason")
            url = failed_item.get("url")
            print(f"    {gallery_id} | {reason} | {url}")

    try:
        db_stats_str = json.dumps(db_stats, indent=4, ensure_ascii=False)
        prefix_space = " " * 2
        db_stats_str_indent = "\n".join(prefix_space + line for line in db_stats_str.splitlines())
        print(f"  details:\n{db_stats_str_indent}")
    except Exception:
        db_stats_str = str(db_stats)
        print(f"  details:\n{db_stats_str}")