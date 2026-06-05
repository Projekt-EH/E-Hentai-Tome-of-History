import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from datetime import datetime

# ==================== 配置区 ====================
# 【方案二】在此处配置你的 E-Hentai / ExHentai Cookies 字典
COOKIES = {
    'igneous': 'mystery',       # 替换为你的 igneous 值
    'ipb_member_id': '0',                          # 替换为你的 member_id
    'ipb_pass_hash': '0'   # 替换为你的 pass_hash
}

# 全局请求头设置
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
# ================================================

def process_url(url: str):
    """
    验证和规范化URL。
    1. 限定网址为 https://e-hentai.org/g/* 或 https://exhentai.org/g/*
    2. 检查是否有 ?hc=1 参数，没有则加上。
    3. 不在范围内直接返回 None，并同时提取出画廊 ID。
    """
    parsed_url = urlparse(url)
    allowed_domains = ["e-hentai.org", "exhentai.org"]
    
    if parsed_url.netloc not in allowed_domains or not parsed_url.path.startswith("/g/"):
        print("错误：输入的网址不在限定范围 (https://e-hentai.org/g/*) 内。")
        return None, None
    
    # 从路径中提取画廊 ID
    path_parts = [p for p in parsed_url.path.split('/') if p]
    gallery_id = path_parts[1] if len(path_parts) > 1 else "unknown"
    
    # 处理查询参数
    query_params = parse_qs(parsed_url.query)
    if 'hc' not in query_params or query_params['hc'] != ['1']:
        query_params['hc'] = '1'
        
    # 重新组装 URL
    new_query = urlencode(query_params, doseq=True)
    clean_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))
    return clean_url, gallery_id

def parse_time(time_str: str) -> str:
    """
    处理时间格式。将时间转换为 ISO 8601 格式的时间戳。
    如果是"just now"或"刚刚"，转换为当前系统时间的 ISO 格式。
    """
    time_str = time_str.strip()
    if "just now" in time_str.lower() or "刚刚" in time_str:
        return datetime.now().isoformat() + "Z"
    
    # 尝试解析常见的时间格式并转换为 ISO 格式
    formats = [
        "%d %B %Y, %H:%M",      # "04 June 2026, 12:39"
        "%d %B %Y, %H:%M:%S",   # "04 June 2026, 12:39:45"
        "%Y-%m-%d %H:%M:%S",    # "2026-06-04 12:39:45"
        "%Y-%m-%d %H:%M",       # "2026-06-04 12:39"
        "%Y-%m-%d",             # "2026-06-04"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.isoformat() + "Z"
        except ValueError:
            continue
    
    # 如果无法解析，直接返回原字符串
    return time_str

def convert_to_mongodb_date(iso_timestamp: str) -> dict:
    """
    将 ISO 格式时间戳转换为 MongoDB $date 格式。
    例如: "2021-12-31T16:00:00Z" -> {"$date": "2021-12-31T16:00:00Z"}
    """
    if not iso_timestamp:
        return {"$date": ""}
    return {"$date": iso_timestamp}

def crawl_comments(input_url: str):
    # 1. 验证并处理 URL，同时拿到画廊 ID
    target_url, gallery_id = process_url(input_url)
    if not target_url:
        return
    
    print(f"正在请求网址: {target_url}")
    
    # 2. 发起网络请求
    try:
        response = requests.get(target_url, headers=HEADERS, cookies=COOKIES, timeout=12)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        print(f"网络请求失败: {e}")
        return

    # 3. 解析 HTML 结构
    soup = BeautifulSoup(html_content, 'html.parser')
    comments_list = []
    
    cdiv = soup.find('div', id='cdiv')
    if not cdiv:
        print("未在页面中找到评论区容器 (#cdiv)。请确认您的 Cookies 是否有效且拥有相应权限。")
        return
        
    # 【已修复】改用 attrs 字典传入，避免了内置位置参数 'name' 的多值冲突报错
    anchors = cdiv.find_all('a', attrs={'name': re.compile(r'^c\d+$')})
    
    for anchor in anchors:
        anchor_name = anchor.get('name')
        
        # 严格过滤置顶评论 c0
        if anchor_name == 'c0':
            continue
            
        comment_id = anchor_name[1:] 
        comment_div = anchor.find_next_sibling('div')
        if not comment_div:
            continue
            
        # 提取发送人、原始发送时间以及论坛用户 ID / 用户地址 (对应 class="c3")
        c3_div = comment_div.find('div', class_='c3')
        username = "Unknown"
        post_time = None
        user_id = ""
        user_forums_url = ""
        
        if c3_div:
            text_content = c3_div.get_text()
            time_match = re.search(r'Posted on\s+(.*?)\s+by:', text_content)
            if time_match:
                iso_time = parse_time(time_match.group(1))
                post_time = convert_to_mongodb_date(iso_time)
            
            # 提取显示名
            user_a = c3_div.find('a')
            if user_a:
                username = user_a.get_text().strip()
            
            # 【新属性】提取 Forums 用户 ID 并生成用户地址
            # 寻找形如 showuser=xxxx 的论坛链接
            forums_a = c3_div.find('a', href=re.compile(r'showuser=\d+'))
            if forums_a:
                href_str = forums_a.get('href')
                id_match = re.search(r'showuser=(\d+)', href_str)
                if id_match:
                    user_id = id_match.group(1)
                    user_forums_url = f"https://forums.e-hentai.org/index.php?showuser={user_id}"
                
        # 提取评论内容 (仅提取内部 HTML，不包含 c6 div 的包装器)
        c6_div = comment_div.find('div', id=f'comment_{comment_id}')
        if not c6_div:
            c6_div = comment_div.find('div', class_='c6')
        
        # 获取 c6_div 的内部 HTML 内容，而不是整个 div
        content_html = "".join(str(child) for child in c6_div.children) if c6_div else ""
        
        # 检查是否修改过 (通过 class="c8")
        c8_divs = comment_div.find_all('div', class_='c8')
        is_edited = len(c8_divs) > 0
        
        edit_history = []
        for c8 in c8_divs:
            c8_text = c8.get_text()
            edit_time_match = re.search(r'on\s+(.*)', c8_text)
            if edit_time_match:
                iso_edit_time = parse_time(edit_time_match.group(1).rstrip('.'))
            else:
                iso_edit_time = parse_time(c8_text.rstrip('.'))
            
            mongodb_edit_time = convert_to_mongodb_date(iso_edit_time)
            
            # 编辑历史中的内容应该是编辑时期的 c6 内容
            edit_history.append({
                "edit_time": mongodb_edit_time,
                "edit_content": content_html
            })
            
        # 封装数据字典
        comment_data = {
            "_id": comment_id,
            "username": username,
            "user_id": user_id,
            "user_forums_url": user_forums_url,
            "source_url": target_url,
            "is_edited": is_edited
        }
        
        # 如果有 post_time，添加到字典中
        if post_time:
            comment_data["post_time"] = post_time
        
        # 有编辑历史时不包含 content 字段；否则包含原有 content
        if not is_edited:
            comment_data["content"] = content_html
        
        # 添加编辑历史
        comment_data["edit_history"] = edit_history
        
        comments_list.append(comment_data)
        
    # 4. 导出文件
    if comments_list:
        save_to_mongodb_file(comments_list, gallery_id)
    else:
        print("未抓取到有效评论。请检查该画廊下是否有评论，或者确认你的 Cookies 是否已失效。")

def save_to_mongodb_file(data_list, gallery_id: str):
    """
    自动创建 comments 文件夹，并将数据以 '画廊id-时间戳.json' 格式保存。
    格式为标准 JSON 数组，包含所有抓取的文档。
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(current_dir, "comments")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    timestamp = int(time.time())
    filename = f"{gallery_id}-{timestamp}.json"
    file_path = os.path.join(output_dir, filename)
    
    # 写入文件：标准 JSON 数组格式，所有文档在一个数组中
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)

    print(f"数据已成功存储至: {file_path}")
    print(f"可使用 mongoimport 导入: mongoimport --db <db> --jsonArray --collection comments --file {file_path}")

# ----------------- 测试运行 -----------------
if __name__ == "__main__":
    # 交互模式：用户输入网址
    print("=" * 50)
    print("E-Hentai 评论爬虫 - 交互模式")
    print("=" * 50)
    
    while True:
        user_input = input("\n请输入 E-Hentai/ExHentai 画廊网址（或输入 'quit' 退出）:\n> ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("程序已退出。")
            break
        
        if not user_input:
            print("错误：请输入有效的网址。")
            continue
        
        print()
        crawl_comments(user_input)
        print()