# E-Hentai 评论爬虫 - Config 功能说明

## 新增功能

程序现已支持 config.json 配置文件读取功能。

## 使用方式

### 首次运行
程序启动时会询问您的配置方案选择：

```
==================================================
E-Hentai 评论与画廊信息爬虫 - 交互模式
==================================================

请选择 Cookie 配置方案：
1 - 使用 config.json 配置（用户自定义 Cookie）
2 - 使用程序默认配置
输入 'exit' 或 'quit' 退出程序

>
```

### 选项说明

**选项 1：使用 config.json 配置**
- 首次选择此项时，程序会自动创建 `config.json` 文件（如不存在）
- `config.json` 与 `crawler.py` 位于同一目录
- 您可以编辑 `config.json` 来自定义您的 Cookie（igneous, ipb_member_id, ipb_pass_hash）

**选项 2：使用程序默认配置**
- 使用 `crawler.py` 中内置的默认 Cookie 值
- 无需创建或编辑配置文件

**退出**
- 输入 `exit` 或 `quit` 可退出程序

## 配置文件格式

### 自动创建的 config.json

如果 `config.json` 不存在，程序首次选择选项 1 时会自动创建，默认内容为：

```json
{
  "igneous": "mystery",
  "ipb_member_id": "0",
  "ipb_pass_hash": "0"
}
```

### 手动编辑 config.json

可参考 `config.example.json` 的格式，替换为您的实际 Cookie 值：

```json
{
  "igneous": "your_igneous_value_here",
  "ipb_member_id": "your_member_id_here",
  "ipb_pass_hash": "your_pass_hash_here"
}
```

## 工作流程

1. 运行 `python crawler.py`
2. 选择配置方案（1 或 2）
3. 如选 1，程序会自动处理 config.json 的创建和加载
4. 选择完成后，输入 E-Hentai/ExHentai 画廊网址开始爬取
5. 输入 `quit` 或 `exit` 退出爬虫任务

## 特点

- ✓ 配置文件自动创建（首次选择时）
- ✓ 支持自定义 Cookie 配置
- ✓ 支持随时切换配置方案（重新运行程序）
- ✓ 配置文件与程序同目录，便于管理
- ✓ 支持 exit/quit 命令快速退出
