import os
import json
import time
import pandas as pd
def merge_uploader(directory_path):
    uploader_list=[]
    delete_files = []
    # 确保路径存在
    if not os.path.exists(directory_path):
        print(f"指定的路径 '{directory_path}' 不存在")
        return

    # 遍历目录中的所有文件
    for filename in os.listdir(directory_path):
        filepath = os.path.join(directory_path, filename)

        # 检查文件是否是JSON文件
        if filename.endswith('.json'):
            print(f"正在读取文件: {filename}")

            # 打开并读取JSON文件
            with open(filepath, 'r', encoding='utf-8') as file:
                try:
                    # 解析JSON数据
                    json_data_list = json.load(file) # element list
                    uploader_list.extend(json_data_list)
                    delete_files.append(filepath)
                except json.JSONDecodeError as e:
                    print(f"解析JSON文件 '{filename}' 时出错: {e}")
                    continue
    # 合并所有JSON数据
    timestamp = int(time.time())
    
    # 使用pandas去重，保留gallery_id和comment_sha256的唯一组合
    df = pd.DataFrame(uploader_list)
    df.drop_duplicates(subset=['gallery_id','comment_sha256'], inplace=True)
    uploader_list = df.to_dict(orient='records')
    # filter out NaN values
    result = [{k: v for k, v in rec.items() if pd.notna(v)} for rec in uploader_list]
    uploader_list = result

    merged_file = f"merged-{timestamp}.json"
    merged_path = os.path.join(directory_path, merged_file)
    with open(merged_path, 'w', encoding='utf-8') as merged_file:
        json.dump(uploader_list, merged_file, ensure_ascii=False, indent=2)
    print(f"已合并 {len(delete_files)} 个JSON文件，共 {len(uploader_list)} 条记录，保存为: {merged_path}")
    for file in delete_files:
        os.remove(file)


if __name__ == "__main__":
    # 指定路径，替换成你的路径
    folder_path = os.path.dirname(__file__)
    target_path = os.path.join(os.path.dirname(folder_path), 'gallery_uploaders') 
    merge_uploader(target_path)