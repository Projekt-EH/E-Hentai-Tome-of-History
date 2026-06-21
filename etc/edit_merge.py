import os
import json
import time
import pandas as pd

CHUNK_SIZE = 10000


def _process_edit_records(records):
    if not records:
        return []

    df = pd.DataFrame(records)

    if 'edit_time' in df.columns:
        print("  检测到编辑记录格式，根据 comment_id 和 edit_time 去重")
        df['edit_time_str'] = df['edit_time'].apply(
            lambda x: x.get('$date', '') if isinstance(x, dict) else ''
        )
        df.drop_duplicates(subset=['comment_id', 'edit_time_str'], inplace=True)
        df.drop('edit_time_str', axis=1, inplace=True)
    else:
        print("  检测到上传者信息格式，根据 gallery_id 去重")
        if 'gallery_id' in df.columns:
            df.drop_duplicates(subset=['gallery_id'], inplace=True)
        else:
            print("  警告：未找到识别的去重字段")

    data_list = df.to_dict(orient='records')
    
    # 过滤NaN值
    result = [{k: v for k, v in rec.items() if pd.notna(v)} for rec in data_list]
    return result


def _write_chunk(records, directory_path, timestamp, chunk_index):
    processed = _process_edit_records(records)
    if not processed:
        return
    merged_file = f"merged-{timestamp}-{chunk_index:03d}.json"
    merged_path = os.path.join(directory_path, merged_file)
    with open(merged_path, 'w', encoding='utf-8') as merged_file_obj:
        json.dump(processed, merged_file_obj, ensure_ascii=False, indent=2)
    print(f"  已写入第 {chunk_index} 批: {merged_path}，记录数: {len(processed)}")


def merge_edit(directory_path):
    if not os.path.exists(directory_path):
        print(f"指定的路径 '{directory_path}' 不存在")
        return

    data_list = []
    delete_files = []
    chunk_index = 0
    timestamp = int(time.time())
    total_input = 0

    for filename in os.listdir(directory_path):
        filepath = os.path.join(directory_path, filename)

        if not filename.endswith('.json') or filename.startswith('merged-'):
            continue

        print(f"正在读取文件: {filename}")
        with open(filepath, 'r', encoding='utf-8') as file:
            try:
                json_data_list = json.load(file)
                if not isinstance(json_data_list, list):
                    print(f"跳过非列表JSON文件: {filename}")
                    continue
                data_list.extend(json_data_list)
                total_input += len(json_data_list)
                delete_files.append(filepath)
            except json.JSONDecodeError as e:
                print(f"解析JSON文件 '{filename}' 时出错: {e}")
                continue

        while len(data_list) >= CHUNK_SIZE:
            chunk = data_list[:CHUNK_SIZE]
            data_list = data_list[CHUNK_SIZE:]
            _write_chunk(chunk, directory_path, timestamp, chunk_index)
            chunk_index += 1
            del chunk

    if data_list:
        _write_chunk(data_list, directory_path, timestamp, chunk_index)
        chunk_index += 1
        data_list = []

    if chunk_index == 0:
        print("没有找到JSON文件")
        return

    print(f"已合并 {len(delete_files)} 个JSON文件，合并前总记录数: {total_input}，输出 {chunk_index} 个分块文件")

    for file in delete_files:
        os.remove(file)


if __name__ == "__main__":
    folder_path = os.path.dirname(__file__)
    target_path = os.path.join(os.path.dirname(folder_path), 'comment_edits')
    merge_edit(target_path)
