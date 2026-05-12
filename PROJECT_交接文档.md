# B站视频总结系统 v2.0 — 项目交接文档

> 本文档供新接手的程序员或 AI Agent 快速理解项目全貌。
> 最后更新：2026-05-12

---

## 一、项目概述

**项目名称**：B站视频总结系统 v2.0
**功能**：输入 B站视频链接 → 自动下载音频/提取字幕 → Whisper 语音转录（无字幕时）→ 文本合并 → DeepSeek AI 生成摘要 → 保存 Markdown 报告

**三种使用方式**：
| 方式 | 入口文件 | 特点 |
|------|---------|------|
| 图形界面（GUI） | `gui.py` | tkinter 界面，支持单视频和批量处理，推荐日常使用 |
| 命令行（单视频） | `main.py` | 适合脚本调用、调试 |
| 命令行（批量） | `batch_process.py` | 通过 `batch_config.yaml` 配置，带 tqdm 进度条和断点续传 |

**核心特性**：
- 三级字幕降级策略：B站API AI字幕 → yt-dlp 下载字幕 → faster-whisper 语音转录
- B站反爬绕过（curl_cffi impersonate=chrome + cookies 登录态）
- 智能URL提取：支持完整链接、带分享文本、纯BV号、b23.tv 短链
- 支持 GPU 加速（需安装 PyTorch CUDA 版，默认 CPU 也能运行）
- GUI 批量处理：队列管理、去重、断点续传、软停止
- 完整的日志和状态追踪

---

## 二、项目结构

```
bilibili-summary/
├── gui.py                    # ★ 图形界面（tkinter，推荐入口）
├── main.py                   # 命令行单视频处理
├── batch_process.py          # 命令行批量处理
├── config.yaml               # 主配置文件（含敏感信息，已 gitignore）
├── config.example.yaml       # 配置模板（提交到 Git）
├── batch_config.yaml         # 批量处理配置
├── requirements.txt          # Python 依赖清单
├── setup.bat                 # Windows 一键安装脚本
├── test_batch_gui.py         # GUI 批量功能测试（8个用例）
│
├── core/                     # 核心模块包
│   ├── __init__.py           # 模块初始化
│   ├── downloader.py         # 视频下载（yt-dlp + curl_cffi 反爬）
│   ├── subtitle.py           # B站字幕提取（API + yt-dlp + Cookie 管理）
│   ├── transcriber.py        # faster-whisper 语音转录
│   ├── chunker.py            # 长文本分块（适配 API 上下文限制）
│   ├── merger.py             # 字幕与转录文本合并
│   ├── summarizer.py         # DeepSeek AI 摘要生成
│   └── notifier.py           # 完成通知（可选，默认禁用）
│
├── videos/                   # 下载的音频文件 (.m4a)
├── subtitles/                # 提取的字幕文件
├── transcripts/              # Whisper 转录文本
├── merged/                   # 合并后的文本
├── summaries/                # 最终摘要 + 状态文件
│   ├── {BV号}_summary.md     # 生成的 Markdown 摘要
│   └── {BV号}.status.json    # 处理状态（每步结果、时间戳）
│
├── tests/                    # 单元测试（228个用例）
│   ├── conftest.py
│   ├── test_downloader.py
│   ├── test_subtitle.py
│   ├── test_transcriber.py
│   ├── test_chunker.py
│   ├── test_merger.py
│   ├── test_summarizer.py
│   └── test_notifier.py
│
├── logs/                     # 运行日志
│
├── README.md                 # GitHub README
├── LICENSE                   # MIT 许可证
├── .gitignore                # Git 忽略规则
├── PYTORCH_CUDA_安装指导.md  # GPU 加速安装指南
└── PROJECT_交接文档.md        # 本文件
```

---

## 三、核心模块说明

### 3.1 `gui.py` — 图形界面（★ 推荐入口）

**启动**：`python gui.py` 或 `python gui.py --config custom_config.yaml`

**界面布局**：
- **顶部**：Notebook 双 Tab — 单视频输入 / 批量处理
- **中部左侧**：5步流程进度面板（下载 → 字幕 → 转录 → 合并 → 总结）
- **中部右侧**：实时日志输出区
- **底部**：总结结果展示区（支持复制、打开文件）

**批量处理 Tab**：
- 输入框支持粘贴多个链接（空格/换行分隔），回车自动添加
- "导入文件"按钮：从 `.txt` 文件批量导入（跳过 `#` 注释行）
- Treeview 队列列表：显示序号、BV号+标题、状态（带颜色标签）
- 操作按钮：开始批量处理 / 停止（软停止） / 删除选中 / 清空队列
- 自动去重、断点续传（跳过已完成的视频）

**技术要点**：
- `TextHandler(logging.Handler)` 将日志重定向到 GUI 文本框
- `StdoutRedirector` 捕获 Whisper 进度条等直接 stdout 输出
- 子线程运行处理逻辑，`root.after(0, callback)` 线程安全更新 UI
- 单视频模式复用批量管线（创建1元素队列）
- 统一数据结构：`list[dict]` with keys `url`, `bv_id`, `status`, `title`

### 3.2 `main.py` — 命令行单视频处理

**启动**：`python main.py` 或 `python main.py <URL/BV号>`

**核心类**：`BilibiliVideoProcessor`

```python
processor = BilibiliVideoProcessor("config.yaml")
result = processor.process(url, resume=True)  # resume=True 启用断点续传
```

**处理流程**：
```
URL 输入 → 智能提取干净URL → 下载音频 → 提取字幕 → 转录(可选) → 合并 → AI摘要
```

**步骤方法**：
| 方法 | 功能 | 输出 |
|------|------|------|
| `_step_download(status, url)` | yt-dlp 下载音频 | `status.steps.download` |
| `_step_subtitle(status)` | 字幕提取（B站API + yt-dlp） | `status.steps.subtitle` |
| `_step_transcribe(status)` | Whisper 语音转录 | `status.steps.transcribe` |
| `_step_merge(status)` | 文本合并 | `status.steps.merge` |
| `_step_summarize(status)` | DeepSeek AI 摘要 | `status.steps.summarize` |

**状态文件**：`summaries/{BV号}.status.json`

### 3.3 `batch_process.py` — 命令行批量处理

**启动**：`python batch_process.py`

- 通过 `batch_config.yaml` 配置视频列表
- tqdm 进度条、断点续传、错误处理

### 3.4 `core/subtitle.py` — 字幕提取（最复杂的模块）

**模块级函数**：
- `extract_bilibili_url(text)` — 从任意文本中提取干净的B站视频URL

**类**：`SubtitleExtractor`

**字幕获取策略**（按优先级）：
1. yt-dlp 带登录态下载字幕（CC字幕 + AI字幕）
2. B站 player API 通过 curl_cffi 获取 AI 字幕

**Cookie 获取方式**（按优先级）：
1. `config.yaml` 中 `download.sessdata` 直接填写
2. `config.yaml` 中 `download.cookies_file`（Netscape 格式 .txt）
3. `config.yaml` 中 `download.cookies_browser`（从 Chrome/Edge 数据库自动提取）
4. 环境变量 `BILIBILI_SESSDATA`

**关键方法**：
- `_extract_sessdata()` — 统一获取 SESSDATA（支持 DPAPI 解密）
- `extract(url, video_path, output_path)` — 主入口，协调两种提取方式
- `_extract_via_ytdlp()` — 通过 yt-dlp 下载字幕
- `_extract_via_bilibili_api()` — 通过 B站 API 获取（curl_cffi 绕过反爬）

### 3.5 `core/downloader.py` — 视频下载

**依赖**：yt-dlp + curl_cffi

**功能**：
- 下载 B站视频音频（`.m4a` 格式）
- 必须设置 `impersonate: "chrome"` 绕过 B站 412 反爬
- 支持 cookies 传递

### 3.6 `core/transcriber.py` — 语音转录

**依赖**：faster-whisper（基于 CTranslate2，不需要 PyTorch 也能运行）

**功能**：
- 使用 Whisper 模型将音频转为文字
- 实时进度条（百分比、已用时间、ETA）
- 设备自动选择：`auto` → 尝试 CUDA → 降级 CPU

### 3.7 `core/merger.py` — 文本合并

**优先级**：字幕纯文本（`{BV号}.txt`）> 转录文本
**空文本保护**：两者都为空时抛出 `ValueError`

### 3.8 `core/chunker.py` — 文本分块

将长文本按字符数限制分块（`max_chars: 6000`，`overlap: 500`），适配 API 上下文限制。

### 3.9 `core/summarizer.py` — AI 摘要生成

**依赖**：DeepSeek API（兼容 OpenAI SDK 格式）

**功能**：调用 DeepSeek API 生成视频内容摘要，输出 Markdown 格式。支持分块总结和长视频处理。

---

## 四、配置文件说明

### 4.1 `config.yaml`（完整配置）

```yaml
# 下载设置
download:
  output_dir: "videos"
  format: "bestaudio[ext=mp4]/bestaudio"
  cookies_browser: null          # "chrome" / "edge" / "brave"
  cookies_file: null             # Netscape 格式 cookies.txt
  sessdata: null                 # ★ 直接填写 SESSDATA（优先级最高）
  impersonate: "chrome"          # ★ 必须设置，绕过 B站 412 反爬

# 字幕设置
subtitle:
  languages: ["ai-zh", "zh-Hans"]
  auto_fallback: true

# 转录设置
transcribe:
  model: "base"                  # tiny/base/small/medium/large
  device: "auto"                 # auto/cuda/cpu
  compute_type: "float16"

# LLM 总结
llm:
  model_name: "deepseek-chat"
  api_key: null                  # DeepSeek API Key
  base_url: "https://api.deepseek.com"
  temperature: 0.3
  chunk:
    max_chars: 6000
    overlap: 500

# 断点续传
resume:
  enabled: true
  status_dir: "summaries"
```

### 4.2 `batch_config.yaml`

```yaml
videos:
  - bv_id: "BV1xx411c7mD"
    title: "可选标题"
  - bv_id: "BV1xx411c7mE"

settings:
  transcribe:
    model: "small"
```

---

## 五、环境依赖

### 5.1 系统要求

- Windows 10/11（已测试 Win11 + RTX 4060 Laptop GPU）
- Python 3.10+
- FFmpeg（必须）

### 5.2 系统依赖

| 依赖 | 安装位置 | 说明 |
|------|---------|------|
| FFmpeg | `C:\ffmpeg\bin\` | 已添加到系统 PATH |
| PyTorch CUDA（可选） | pip 安装 | GPU 加速用，CPU 模式不需要 |

### 5.3 Python 依赖（`requirements.txt`）

```
yt-dlp>=2024.0
faster-whisper>=1.1.0
curl_cffi>=0.5.10,<0.14       # B站反爬绕过
requests>=2.31.0
tqdm>=4.66.0
pyyaml>=6.0
openai>=1.0.0                  # DeepSeek API 兼容
```

**安装**：`pip install -r requirements.txt`

---

## 六、使用方法

### 6.1 图形界面（推荐）

```bash
cd C:\Users\22508\WorkBuddy\2026-05-12-task-9\bilibili-summary
python gui.py
```

- 切换"单视频"和"批量处理" Tab
- 批量模式下粘贴链接 → 回车添加 → 点击"开始批量处理"

### 6.2 命令行单视频

```bash
python main.py                      # 交互式输入
python main.py https://www.bilibili.com/video/BV1xx411c7mD/
python main.py BV1xx411c7mD         # 也支持纯BV号
```

### 6.3 命令行批量

```bash
# 编辑 batch_config.yaml 后运行
python batch_process.py
```

### 6.4 环境变量

```powershell
# DeepSeek API Key（也可在 config.yaml 中直接填写）
$env:DEEPSEEK_API_KEY = "sk-your-key-here"

# B站 SESSDATA（也可在 config.yaml 中填写）
$env:BILIBILI_SESSDATA = "your-sessdata-value"
```

---

## 七、已修复问题记录

| # | 问题 | 根因 | 修复 | 状态 |
|---|------|------|------|------|
| 1 | `FileNotFoundError: merged\*.txt` | merger 空文本时返回不存在的路径 | merger 抛出 ValueError，step_summarize 加文件检查 | ✅ |
| 2 | `ModuleNotFoundError: No module named 'torch'` | transcriber 无条件 import torch | try/except ImportError 降级到 CPU | ✅ |
| 3 | FFmpeg 未找到 | 系统未安装 | 安装到 `C:\ffmpeg\`，添加 PATH | ✅ |
| 4 | B站字幕提取失败（ConnectionReset） | requests 被反爬拦截 | 改用 curl_cffi impersonate=chrome | ✅ |
| 5 | B站 AI 字幕获取不到 | 需要登录态 SESSDATA | 支持 4 种方式获取 Cookie（详见 3.4 节） | ✅ |
| 6 | 字幕成功后仍执行 Whisper 转录 | `_step_subtitle` 未标记 transcribe 为 skipped | 字幕成功时标记 transcribe=skipped | ✅ |
| 7 | URL 输入不灵活 | 只支持纯BV号 | 新增 `extract_bilibili_url()` 支持多种格式 | ✅ |

---

## 八、已知限制

| 问题 | 说明 | 影响 |
|------|------|------|
| `nvidia-smi` NVML Unknown Error | RDP 远程桌面会话阻断 NVML | `torch.cuda.is_available()` 仍可正常检测，不影响使用 |
| B站视频标题可能与内容不匹配 | UP主更换视频内容但不改标题 | 这是B站本身的问题，脚本无法解决 |
| yt-dlp 频繁更新 | B站反爬策略变化可能导致下载失败 | `pip install -U yt-dlp` 更新即可 |

---

## 九、测试

### 9.1 单元测试

```bash
cd bilibili-summary
python -m pytest tests/ -v
```

共 228 个测试用例，覆盖所有 core 模块。

### 9.2 GUI 批量功能测试

```bash
python test_batch_gui.py
```

共 8 个测试用例，覆盖队列管理、去重、状态更新、断点续传、停止机制等。

---

## 十、Git 仓库状态

- **许可证**：MIT
- **`.gitignore`**：排除 config.yaml（敏感信息）、生成文件目录、IDE 文件、日志
- **敏感信息保护**：config.yaml 不提交，使用 config.example.yaml 作为模板
- **生成文件目录**：videos/、subtitles/、transcripts/、merged/、summaries/*.md、logs/ 均已忽略

---

## 十一、参考链接

- **PyTorch 官网**：https://pytorch.org/get-started/locally/
- **faster-whisper 文档**：https://github.com/guillaumekln/faster-whisper
- **yt-dlp 文档**：https://github.com/yt-dlp/yt-dlp
- **DeepSeek API 文档**：https://platform.deepseek.com/docs
- **curl_cffi 文档**：https://github.com/yifeikong/curl_cffi

---

_本文档最后更新于 2026-05-12，反映项目当前实际状态。_
