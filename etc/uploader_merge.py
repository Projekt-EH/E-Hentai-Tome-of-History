# E-Hentai Tome of History - a gallery comment fetcher and preserver for E-Hentai
# Copyright (C) 2026  Projekt-EH & AXIS5(AXIS5hacker)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import json
import time
import pandas as pd

CHUNK_SIZE = 10000


def _process_uploader_records(records):
    if not records:
        return []

    df = pd.DataFrame(records)
    df.drop_duplicates(subset=['gallery_id', 'comment_sha256'], inplace=True)
    uploader_list = df.to_dict(orient='records')
    result = [{k: v for k, v in rec.items() if pd.notna(v)} for rec in uploader_list]
    return result


def _write_chunk(records, directory_path, timestamp, chunk_index):
    processed = _process_uploader_records(records)
    if not processed:
        return
    merged_file = f"merged-{timestamp}-{chunk_index:03d}.json"
    merged_path = os.path.join(directory_path, merged_file)
    with open(merged_path, 'w', encoding='utf-8') as merged_file_obj:
        json.dump(processed, merged_file_obj, ensure_ascii=False, indent=2)
    print(f"  已写入第 {chunk_index} 批: {merged_path}，记录数: {len(processed)}")


def merge_uploader(directory_path):
    if not os.path.exists(directory_path):
        print(f"指定的路径 '{directory_path}' 不存在")
        return

    uploader_list = []
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
                uploader_list.extend(json_data_list)
                total_input += len(json_data_list)
                delete_files.append(filepath)
            except json.JSONDecodeError as e:
                print(f"解析JSON文件 '{filename}' 时出错: {e}")
                continue

        while len(uploader_list) >= CHUNK_SIZE:
            chunk = uploader_list[:CHUNK_SIZE]
            uploader_list = uploader_list[CHUNK_SIZE:]
            _write_chunk(chunk, directory_path, timestamp, chunk_index)
            chunk_index += 1
            del chunk

    if uploader_list:
        _write_chunk(uploader_list, directory_path, timestamp, chunk_index)
        chunk_index += 1
        uploader_list = []

    if chunk_index == 0:
        print("没有找到JSON文件")
        return

    print(f"已合并 {len(delete_files)} 个JSON文件，合并前总记录数: {total_input}，输出 {chunk_index} 个分块文件")

    for file in delete_files:
        os.remove(file)


if __name__ == "__main__":
    folder_path = os.path.dirname(__file__)
    target_path = os.path.join(os.path.dirname(folder_path), 'gallery_uploaders')
    merge_uploader(target_path)
