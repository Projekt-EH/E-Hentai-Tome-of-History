import os
import re
import json
import time
import requests
import hashlib  # 用于生成 SHA-256 摘要
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from datetime import datetime, timezone

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
        print("错误：输入的网址不在限定范围 (https://e-hentai.org/g/* 或 https://exhentai.org/g/*) 内。")
        return None, None
    
    # 从路径中提取画廊 ID，例如 /g/3707254/78bc70a6c6/ -> 3707254
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
    由于 E-Hentai 画廊主站网页文本写死的时间就是 UTC+0，直接解析并格式化输出。
    """
    time_str = time_str.strip()
    if "just now" in time_str.lower() or "刚刚" in time_str:
        # 显式用 replace(tzinfo=None) 抹除时区属性，避免 isoformat() 产生 +00:00Z 的双重后缀
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    
    # 尝试解析常见的时间格式
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
    edits_list = []  # 存放分离出来的编辑记录数据
    
    cdiv = soup.find('div', id='cdiv')
    if not cdiv:
        print("未在页面中找到评论区容器 (#cdiv)。请确认您的 Cookies 是否有效且拥有相应权限。")
        return
        
    uploader_comment = ""  # 用于存放上传者置顶评论内容
    anchors = cdiv.find_all('a', attrs={'name': re.compile(r'^c\d+$')})
    
    for anchor in anchors:
        anchor_name = anchor.get('name')
        
        # 严格过滤置顶评论 c0
        if anchor_name == 'c0':
            comment_div = anchor.find_next_sibling('div')
            if comment_div:
                c6_div = comment_div.find('div', id='comment_0')
                if not c6_div:
                    c6_div = comment_div.find('div', class_='c6')
                if c6_div:
                    uploader_comment = "".join(str(child) for child in c6_div.children)
            continue
            
        comment_id = anchor_name[1:] 
        comment_div = anchor.find_next_sibling('div')
        if not comment_div:
            continue
            
        # 提取发送人、原始发送时间以及论坛用户 ID (对应 class="c3")
        c3_div = comment_div.find('div', class_='c3')
        username = "Unknown"
        post_time = None
        
        extracted_user_id = None
        extracted_forums_url = None
        
        if c3_div:
            text_content = c3_div.get_text()
            time_match = re.search(r'Posted on\s+(.*?)\s+by:', text_content)
            if time_match:
                iso_time = parse_time(time_match.group(1))
                post_time = convert_to_mongodb_date(iso_time)
            
            user_a = c3_div.find('a')
            if user_a:
                username = user_a.get_text().strip()
            
            forums_a = c3_div.find('a', href=re.compile(r'showuser=\d+'))
            if forums_a:
                href_str = forums_a.get('href')
                id_match = re.search(r'showuser=(\d+)', href_str)
                if id_match:
                    extracted_user_id = id_match.group(1)
                    extracted_forums_url = f"https://forums.e-hentai.org/index.php?showuser={extracted_user_id}"
                
        # 提取当前评论分数 current_score
        score_span = comment_div.find('span', id=f'comment_score_{comment_id}')
        current_score = 0
        if score_span:
            try:
                current_score = int(score_span.get_text().strip())
            except ValueError:
                pass

        # 提取评论者基础权限分 power 与具体的投票列表 vote_list
        c7_div = comment_div.find('div', id=f'cvotes_{comment_id}')
        if not c7_div:
            c7_div = comment_div.find('div', class_='c7')
        
        power = 0
        vote_list = []
        if c7_div:
            c7_text = c7_div.get_text()
            base_match = re.search(r'Base\s+([+-]?\d+)', c7_text)
            if base_match:
                power = int(base_match.group(1))
            for span in c7_div.find_all('span'):
                span_text = span.get_text().strip()
                if "and" in span_text and "more" in span_text:
                    continue
                span_match = re.search(r'^(.*?)\s+([+-]?\d+)$', span_text, re.DOTALL)
                if span_match:
                    voter_name = span_match.group(1).strip()
                    voter_power = int(span_match.group(2))
                    vote_list.append({
                        "voter": voter_name,
                        "power": voter_power
                    })

        # 提取评论内容
        c6_div = comment_div.find('div', id=f'comment_{comment_id}')
        if not c6_div:
            c6_div = comment_div.find('div', class_='c6')
        
        content_html = "".join(str(child) for child in c6_div.children) if c6_div else ""
        
        # 检查是否修改过 (通过 class="c8")
        c8_divs = comment_div.find_all('div', class_='c8')
        is_edited = len(c8_divs) > 0
        
        # 收集分离出来的修改历史
        for c8 in c8_divs:
            c8_text = c8.get_text()
            edit_time_match = re.search(r'on\s+(.*)', c8_text)
            if edit_time_match:
                iso_edit_time = parse_time(edit_time_match.group(1).rstrip('.'))
            else:
                iso_edit_time = parse_time(c8_text.rstrip('.'))
            
            mongodb_edit_time = convert_to_mongodb_date(iso_edit_time)
            edit_content = content_html
            
            edits_list.append({
                "comment_id": comment_id,
                "edit_time": mongodb_edit_time,
                "edit_content": edit_content
            })
            
        # 封装评论主数据字典
        comment_data = {
            "_id": comment_id,
            "gallery_id": gallery_id,
            "username": username,
            "post_time": post_time,
            "source_url": target_url,
            "current_score": current_score,
            "power": power,
            "vote_list": vote_list,
            "is_edited": is_edited
        }
        
        if extracted_user_id:
            comment_data["user_id"] = extracted_user_id
        if extracted_forums_url:
            comment_data["user_forums_url"] = extracted_forums_url
        
        if not is_edited:
            comment_data["content"] = content_html
        
        comments_list.append(comment_data)
        
    # 在主体 DOM 树中独立提取画廊上传者信息
    gdn_div = soup.find('div', id='gdn')
    
    # 动态执行时间保持标准的 UTC+0 瞬间时间
    utc_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    
    # 优化点：初始化基础属性，排除 uploader_comment 和 comment_sha256
    uploader_data = {
        "gallery_id": gallery_id,
        "source_url": target_url,
        "time": convert_to_mongodb_date(utc_now_str)
    }
    
    # 仅在存在上传者置顶评论时，动态计算 SHA-256 并将其写入字典中
    if uploader_comment:
        comment_digest = hashlib.sha256(uploader_comment.encode('utf-8')).hexdigest()
        uploader_data["uploader_comment"] = uploader_comment
        uploader_data["comment_sha256"] = comment_digest
    
    if gdn_div:
        uploader_a = gdn_div.find('a', href=re.compile(r'/uploader/'))
        if uploader_a:
            uploader_data["uploader_name"] = uploader_a.get_text().strip()
            
        forums_a = gdn_div.find('a', href=re.compile(r'showuser=\d+'))
        if forums_a:
            id_match = re.search(r'showuser=(\d+)', forums_a.get('href', ''))
            if id_match:
                uploader_data["uploader_id"] = id_match.group(1)
        
    # 4. 导出文件
    if comments_list or uploader_data:
        save_all_data(comments_list, edits_list, uploader_data, gallery_id)
        
    if not comments_list:
        print("未抓取到有效评论。请检查该画廊下是否有评论，或者确认你的 Cookies 是否已失效。")

def save_all_data(comments_list, edits_list, uploader_data, gallery_id: str):
    """
    分别导出评论主数据、编辑历史数据与画廊上传者数据到对应的指定文件夹中。
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = int(time.time())
    filename = f"{gallery_id}-{timestamp}.json"
    filename_edit = f"{gallery_id}-{timestamp}-edits.json"
    filename_uploader = f"{gallery_id}-{timestamp}-uploader.json"
    
    # --- 1. 存储评论主数据 ---
    if comments_list:
        comments_dir = os.path.join(current_dir, "comments")
        if not os.path.exists(comments_dir):
            os.makedirs(comments_dir)
        comments_path = os.path.join(comments_dir, filename)
        
        with open(comments_path, "w", encoding="utf-8") as f:
            json.dump(comments_list, f, ensure_ascii=False, indent=2)
        print(f"评论主数据已存储至: {comments_path}")
    
    # --- 2. 存储编辑历史数据 ---
    if len(edits_list) > 0:
        edits_dir = os.path.join(current_dir, "comment_edits")
        if not os.path.exists(edits_dir):
            os.makedirs(edits_dir)
        edits_path = os.path.join(edits_dir, filename_edit)
        
        with open(edits_path, "w", encoding="utf-8") as f:
            json.dump(edits_list, f, ensure_ascii=False, indent=2)
        print(f"编辑历史数据已存储至: {edits_path}")
    else:
        print("没有编辑历史数据需要存储。")
        
    # --- 3. 存储画廊上传者信息数据 ---
    if uploader_data:
        uploader_dir = os.path.join(current_dir, "gallery_uploaders")
        if not os.path.exists(uploader_dir):
            os.makedirs(uploader_dir)
        uploader_path = os.path.join(uploader_dir, filename_uploader)
        
        with open(uploader_path, "w", encoding="utf-8") as f:
            json.dump([uploader_data], f, ensure_ascii=False, indent=2)
        print(f"画廊上传者评论数据已存储至: {uploader_path}")

# ----------------- 测试运行 -----------------
if __name__ == "__main__":
    print("=" * 50)
    print("E-Hentai 评论与画廊信息爬虫 - 交互模式")
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