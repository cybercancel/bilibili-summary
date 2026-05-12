# B站视频总结系统 v2.0 — 项目交接文档

> 本文档供新接手的程序员或 AI Agent 快速理解项目全貌。
> 最后更新：2026-05-12

---

## 一、项目概述

**项目名称**：B站视频总结系统 v2.0  
**功能**：输入 B站 BV 号 → 自动下载视频/字幕 → Whisper 语音转录（无字幕时）→ 文本合并 → DeepSeek AI 生成摘要 → 保存 Markdown 报告

**核心特性**：
- 三级字幕降级策略：B站API字幕 → yt-dlp 下载字幕 → faster-whisper 语音转录
- 支持 GPU 加速（需安装 PyTorch CUDA 版）
- 批量处理模式（通过 `batch_config.yaml` 配置）
- 完整的日志和状态追踪

---

## 二、项目结构

```
bilibili-summary/
├── main.py                    # 主程序入口（单视频处理）
├── batch_process.py           # 批量处理入口
├── config.yaml                # 主配置文件
├── batch_config.yaml          # 批量处理配置文件
├── requirements.txt           # Python 依赖清单
├── setup.bat                 # Windows 一键安装脚本
│
├── core/                     # 核心模块包
│   ├── __init__.py
│   ├── downloader.py         # 视频/字幕下载（yt-dlp）
│   ├── subtitle.py           # B站字幕API获取
│   ├── transcriber.py        # faster-whisper 语音转录
│   ├── chunker.py            # 长文本分块（适配API限制）
│   ├── merger.py             # 字幕与转录文本合并
│   ├── summarizer.py         # DeepSeek AI 摘要生成
│   └── notifier.py          # 完成通知（可选）
│
├── videos/                   # 下载的原始视频存放目录
├── transcripts/              # Whisper 转录文本存放目录
├── merged/                   # 合并后的文本存放目录
├── summaries/                # 最终摘要 MD 文件存放目录
│
├── tests/                    # 单元测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_downloader.py
│   ├── test_subtitle.py
│   ├── test_transcriber.py
│   ├── test_chunker.py
│   ├── test_merger.py
│   ├── test_summarizer.py
│   └── test_notifier.py
│
├── logs/                     # 运行日志目录
│   └── single_YYYYMMDD_HHMMSS.log
│
└── PYTORCH_CUDA_安装指导.md  # GPU 加速安装指南（用户文档）
```

---

## 三、核心模块说明

### 3.1 `main.py` — 主程序入口

**职责**：单视频处理流程编排

**处理流程**：
```
BV号输入 → 下载视频/字幕 → 获取字幕 → 转录(可选) → 合并文本 → AI摘要 → 保存
```

**关键函数**：
- `main()`：主流程控制
- `_step_download()`：调用 downloader
- `_step_subtitle()`：调用 subtitle
- `_step_transcribe()`：调用 transcriber
- `_step_merge()`：调用 merger
- `_step_summarize()`：调用 summarizer

**状态文件**：`summaries/{BV号}.status.json`（记录每步结果）

---

### 3.2 `core/downloader.py` — 视频下载

**依赖**：`yt-dlp`

**功能**：
- 下载 B站视频音频（`.m4a` 格式）
- 尝试下载字幕文件（`.srt` / `.vtt`）
- 保存到 `videos/` 目录

**输出**：`{"video_path": str, "subtitle_path": str|None}`

---

### 3.3 `core/subtitle.py` — B站字幕API

**功能**：
- 通过 B站 API 获取官方字幕（`wbi` 签名认证）
- 支持多语言字幕选择
- 解析 XML/JSON 格式字幕为纯文本

**输出**：`{"text": str, "source": "bilibili_api"}`

---

### 3.4 `core/transcriber.py` — 语音转录

**依赖**：`faster-whisper`（基于 CTranslate2，不需要 PyTorch 也能运行）

**功能**：
- 使用 Whisper 模型将音频转为文字
- 自动选择设备：`cuda`（GPU）> `cpu`
- 模型大小可配置（`tiny` / `base` / `small` / `medium` / `large`）

**GPU 加速**：需安装 `torch` CUDA 版本（见 `PYTORCH_CUDA_安装指导.md`）

**输出**：`{"text": str, "source": "whisper", "language": str}`

---

### 3.5 `core/merger.py` — 文本合并

**功能**：
- 合并字幕文本和 Whisper 转录文本
- 优先使用字幕（质量更高）
- 如果两者都为空，抛出 `ValueError`

**输出**：`{"text": str, "source": str, "file": str|None}`

---

### 3.6 `core/chunker.py` — 文本分块

**功能**：
- 将长文本按 token 限制分块
- 适应 DeepSeek API 的上下文长度限制
- 支持按句子/段落边界切割

---

### 3.7 `core/summarizer.py` — AI 摘要生成

**依赖**：DeepSeek API（需配置 `DEEPSEEK_API_KEY` 环境变量）

**功能**：
- 调用 DeepSeek API 生成视频内容摘要
- 支持自定义提示词模板
- 输出 Markdown 格式摘要

**输出**：摘要文本（Markdown 格式）

---

### 3.8 `core/notifier.py` — 完成通知

**功能**（可选）：
- 处理完成后发送通知
- 支持系统通知 / 邮件 / Webhook

---

## 四、配置文件说明

### 4.1 `config.yaml`

```yaml
# DeepSeek API 配置
deepseek:
  api_key: "${DEEPSEEK_API_KEY}"   # 从环境变量读取
  model: "deepseek-chat"
  temperature: 0.3

# Whisper 转录配置
transcribe:
  model_size: "base"               # tiny / base / small / medium / large
  device: "auto"                   # auto / cuda / cpu
  compute_type: "int8"             # int8 / float16 / float32
  language: "zh"                   # 目标语言

# 下载配置
download:
  output_dir: "./videos"
  subtitle_dir: "./subtitles"
  format: "bestaudio/best"

# 摘要配置
summary:
  max_chunk_tokens: 4000
  prompt_template: "请总结以下视频内容...\n\n{text}"
```

### 4.2 `batch_config.yaml`

```yaml
# 批量处理配置
videos:
  - bv_id: "BV1xx411c7mD"
    title: "可选：自定义标题"
  - bv_id: "BV1xx411c7mE"

# 全局设置（覆盖 config.yaml）
settings:
  transcribe:
    model_size: "small"
```

---

## 五、环境依赖

### 5.1 Python 依赖（`requirements.txt`）

```
yt-dlp>=2024.1.0
faster-whisper>=0.10.0
openai>=1.0.0          # DeepSeek API 兼容 OpenAI 格式
pyyaml>=6.0
requests>=2.31.0
```

### 5.2 系统依赖

- **FFmpeg**：用于音频处理（Whisper 需要）
  - 已安装在：`C:\ffmpeg\bin\ffmpeg.exe`
  - 已添加到系统 PATH

- **PyTorch**（可选，用于 GPU 加速）
  - 安装方式见 `PYTORCH_CUDA_安装指导.md`
  - CPU 模式无需安装

---

## 六、使用方法

### 6.1 单视频处理

```powershell
cd C:\Users\22508\WorkBuddy\2026-05-12-task-9\bilibili-summary
python main.py
```

按提示输入 BV 号（如 `BV1xBZYBUEr4`）

### 6.2 批量处理

```powershell
python batch_process.py
```

需提前配置 `batch_config.yaml`

### 6.3 环境变量

```powershell
# 设置 DeepSeek API Key
$env:DEEPSEEK_API_KEY="sk-your-key-here"

# 永久设置（Windows）
[System.Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-your-key-here", "User")
```

---

## 七、已知问题与修复记录

### 7.1 `FileNotFoundError: merged\*.txt`

**问题**：merger.py 在字幕和转录都为空时，仍返回不存在的文件路径

**修复**：修改 `merger.py`，当结果为空时抛出 `ValueError`

**状态**：✅ 已修复

---

### 7.2 `ModuleNotFoundError: No module named 'torch'`

**问题**：`transcriber.py` 无条件 `import torch`，导致没有安装 PyTorch 时崩溃

**修复**：改为 `try/except ImportError`，未安装时自动降级到 CPU

**状态**：✅ 已修复

---

### 7.3 FFmpeg 未找到

**问题**：Whisper 转录时需要 FFmpeg，但系统未安装

**修复**：手动下载 FFmpeg，解压到 `C:\ffmpeg\`，添加 `C:\ffmpeg\bin` 到 PATH

**状态**：✅ 已修复

---

### 7.4 `nvidia-smi` 报错 `Failed to initialize NVML`

**问题**：远程桌面 (RDP) 会话中会阻断 NVML 访问

**解决**：不影响实际使用，`torch.cuda.is_available()` 仍可正常检测

**状态**：⚠️ 已知限制，非阻塞

---

## 八、待完成事项

- [ ] 安装 PyTorch CUDA 版本以启用 GPU 加速（见 `PYTORCH_CUDA_安装指导.md`）
- [ ] 配置 `DEEPSEEK_API_KEY` 环境变量
- [ ] 测试批量处理模式
- [ ] 完善单元测试覆盖率
- [ ] 添加错误处理和重试机制（API 调用失败时）

---

## 九、关键代码片段

### 9.1 transcriber.py — 设备自动检测

```python
if self.device == "auto":
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        logger.info("torch 未安装，默认使用 CPU")
        device = "cpu"
```

### 9.2 merger.py — 空结果处理

```python
if not result_text:
    logger.error("字幕和转录文本均为空，无法生成总结")
    raise ValueError("字幕和转录文本均为空，无法继续处理。...")
```

---

## 十、联系与参考

- **PyTorch 官网**：https://pytorch.org/get-started/locally/
- **faster-whisper 文档**：https://github.com/guillaumekln/faster-whisper
- **yt-dlp 文档**：https://github.com/yt-dlp/yt-dlp
- **DeepSeek API 文档**：https://platform.deepseek.com/docs

---

_本文档由 WorkBuddy AI 自动生成，如有遗漏请联系维护者补充。_
