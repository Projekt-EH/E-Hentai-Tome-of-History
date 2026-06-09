import os
import json
import time
import pandas as pd

def merge_json(directory_path):
    data_list = []
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
                    data_list.extend(json_data_list)
                    delete_files.append(filepath)
                except json.JSONDecodeError as e:
                    print(f"解析JSON文件 '{filename}' 时出错: {e}")
                    continue
    
    if not data_list:
        print("没有找到JSON文件")
        return
    
    # 合并所有JSON数据
    timestamp = int(time.time())
    
    # 创建DataFrame用于去重
    df = pd.DataFrame(data_list)
    
    # 判断数据类型：根据字段判断是编辑记录还是上传者信息
    if 'edit_time' in df.columns:
        # 编辑记录：根据comment_id和edit_time去重
        print("检测到编辑记录格式，根据 comment_id 和 edit_time 去重")
        # 提取edit_time中的$date字段作为比较列
        df['edit_time_str'] = df['edit_time'].apply(
            lambda x: x.get('$date', '') if isinstance(x, dict) else ''
        )
        df.drop_duplicates(subset=['comment_id', 'edit_time_str'], inplace=True)
        df.drop('edit_time_str', axis=1, inplace=True)
    else:
        # 上传者信息：根据gallery_id去重
        print("检测到上传者信息格式，根据 gallery_id 去重")
        if 'gallery_id' in df.columns:
            df.drop_duplicates(subset=['gallery_id'], inplace=True)
        else:
            print("警告：未找到识别的去重字段")
    
    # 转回列表
    data_list = df.to_dict(orient='records')
    
    # 过滤NaN值
    result = [{k: v for k, v in rec.items() if pd.notna(v)} for rec in data_list]
    data_list = result

    merged_file = f"merged-{timestamp}.json"
    merged_path = os.path.join(directory_path, merged_file)
    with open(merged_path, 'w', encoding='utf-8') as merged_file:
        json.dump(data_list, merged_file, ensure_ascii=False, indent=2)
    print(f"已合并 {len(delete_files)} 个JSON文件，共 {len(data_list)} 条记录，保存为: {merged_path}")
    for file in delete_files:
        os.remove(file)

if __name__ == "__main__":
    # 指定路径，替换成你的路径
    directory_path = os.path.join(os.path.dirname(__file__),'comment_edits') 
    merge_json(directory_path)