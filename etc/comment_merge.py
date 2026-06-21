import os
import json
import time
import pandas as pd

def merge_json(directory_path):
    comment_list = []
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
                    comment_list.extend(json_data_list)
                    delete_files.append(filepath)
                except json.JSONDecodeError as e:
                    print(f"解析JSON文件 '{filename}' 时出错: {e}")
                    continue
    
    if not comment_list:
        print("没有找到JSON文件")
        return
    
    len_before = len(comment_list)
    # 创建 DataFrame
    df = pd.DataFrame(comment_list)
    
    # --- 核心逻辑处理开始 ---
    
    # 1. 解析 fetch_time 用于精确排序（兼容字符串和 MongoDB $date 字典格式）
    def parse_fetch_time(x):
        if isinstance(x, dict) and '$date' in x:
            return pd.to_datetime(x['$date'])
        return pd.to_datetime(x, errors='coerce')

    
    if 'comment_id' in df.columns and '_id' in df.columns:
        df.drop(['_id'],axis=1,inplace=True)  # 删除 _id 列，避免与 comment_id 冲突
        df.rename(columns={'comment_id': '_id'}, inplace=True)  # 将 comment_id 重命名为 _id 作为唯一标识

    if 'fetch_time' in df.columns and '_id' in df.columns:
        print("正在进行数据同步与去重...")
        
        # 临时创建一个可以用来比较的 datetime 列
        df['_parsed_time'] = df['fetch_time'].apply(parse_fetch_time)
        
        # 预先将 is_edited 转换为布尔型，防止类型不一致，缺失值默认为 False
        if 'is_edited' in df.columns:
            df['is_edited'] = df['is_edited'].fillna(False).astype(bool)
        else:
            df['is_edited'] = False

        # 2. 核心步骤一：同步编辑状态的 comment 字段
        # 目的：相同 _id 内，如果存在 is_edited=False 且有 comment，把 comment 赋给 is_edited=True 的记录
        if 'comment' in df.columns:
            # 定义一个分组处理函数
            def sync_comment_group(group):
                # 寻找未编辑（is_edited == False）且 comment 不为空的有效评论内容
                false_mask = (~group['is_edited']) & group['comment'].notna()
                if false_mask.any():
                    # 取出第一条未编辑的评论文本
                    valid_comment = group.loc[false_mask, 'comment'].iloc[0]
                    # 找到已编辑（is_edited == True）的记录
                    true_mask = group['is_edited']
                    # 将未编辑的评论内容同步过去
                    group.loc[true_mask, 'comment'] = valid_comment
                return group

            # 按 _id 分组并应用同步逻辑
            df = df.groupby('_id', group_keys=False).apply(sync_comment_group)

        # 3. 核心步骤二：根据 fetch_time 降序排序，保留最新的记录
        df = df.sort_values(by='_parsed_time', ascending=False)
        df = df.drop_duplicates(subset=['_id'], keep='first')
        
        # 清理临时排序列
        df = df.drop(columns=['_parsed_time'])
        
    # --- 核心逻辑处理结束 ---

    # 转回列表
    data_list = df.to_dict(orient='records')
    
    # 如果 v 是列表或字典，直接保留（视为有效数据）；如果是普通标量，再用 pd.notna(v) 判断
    result = [
        {
            k: v for k, v in rec.items() 
            if isinstance(v, (dict, list)) or (pd.notna(v) if not hasattr(v, '__len__') else True)
        } 
        for rec in data_list
    ]

    data_list = result

    # 写入文件
    timestamp = int(time.time())
    merged_file = f"merged-{timestamp}.json"
    merged_path = os.path.join(directory_path, merged_file)
    with open(merged_path, 'w', encoding='utf-8') as merged_file_obj:
        json.dump(data_list, merged_file_obj, ensure_ascii=False, indent=2)
        
    deduped_count = len(data_list)
    print(f"已合并 {len(delete_files)} 个JSON文件，合并前总记录数: {len_before}，合并后总记录数: {deduped_count}，保存为: {merged_path}")
    
    # 删除原文件
    for file in delete_files:
        os.remove(file)

if __name__ == "__main__":
    folder_path=os.path.dirname(__file__)
    target_path = os.path.join(os.path.dirname(folder_path), 'comments') 
    merge_json(target_path)