import os
import re
import json
import time

# ==================== Storage helpers ====================
def write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_existing_gallery_ids():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    comments_dir = os.path.join(current_dir, "comments")
    if not os.path.exists(comments_dir):
        return set()

    return {
        match.group(1)
        for filename in os.listdir(comments_dir)
        for match in [re.match(r'^(\d+)-\d+\.json$', filename)]
        if match
    }

def save_all_data(comments_list, edits_list, uploader_data, gallery_id: str):
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    timestamp = int(time.time())
    filename = f"{gallery_id}-{timestamp}.json"
    filename_edit = f"{gallery_id}-{timestamp}-edits.json"
    filename_uploader = f"{gallery_id}-{timestamp}-uploader.json"
    message = ""

    if len(comments_list) == 0:
        message += "No comments found in this gallery."
    else:
        comments_path = os.path.join(current_dir, "comments", filename)
        write_json(comments_path, comments_list)
        message += f"Saved comments: {comments_path}"
    message +="\n"
    if len(edits_list) > 0:
        edits_path = os.path.join(current_dir, "comment_edits", filename_edit)
        write_json(edits_path, edits_list)
        message += f"Saved comment edits: {edits_path}\n"
    
    if uploader_data:
        uploader_path = os.path.join(current_dir, "gallery_uploaders", filename_uploader)
        write_json(uploader_path, [uploader_data])
        message += f"Saved uploader metadata: {uploader_path}"
    message += "\n"
    print(message)