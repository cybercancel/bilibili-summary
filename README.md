# B站视频总结系统 v2.0

[![Python Version](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

一个自动化的 B站视频内容总结工具，支持视频下载、字幕提取、语音转录和 AI 智能总结。

---

## ✨ 功能特性

- **多源字幕获取**：B站 API 字幕 → yt-dlp 下载字幕 → faster-whisper 语音转录（三级降级）
- **GPU 加速**：支持 NVIDIA GPU 加速转录（需安装 PyTorch CUDA 版本）
- **批量处理**：通过配置文件批量处理多个视频
- **断点续传**：支持中断后继续处理，避免重复工作
- **智能分块**：长文本自动分块，适配 API 长度限制
- **多种通知**：支持 Webhook、邮件等多种完成通知方式

---

## 📦 安装

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/bilibili-summary.git
cd bilibili-summary
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装 FFmpeg

**Windows**:
1. 下载 FFmpeg：https://ffmpeg.org/download.html
2. 解压到任意目录（如 `C:\ffmpeg`）
3. 将 `C:\ffmpeg\bin` 添加到系统 PATH

**macOS**:
```bash
brew install ffmpeg
```

**Linux**:
```bash
sudo apt update
sudo apt install ffmpeg
```

### 4. 配置

复制配置模板并填写：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`：
- 填写 DeepSeek API Key（[获取地址](https://platform.deepseek.com/)）
- 根据需要调整其他配置

---

## 🚀 使用方法

### 单视频处理

```bash
python main.py
```

按提示输入 B站视频 BV 号（如 `BV1xx411c7mD`）

### 批量处理

1. 编辑 `batch_config.yaml` 配置要处理的视频列表
2. 运行：

```bash
python batch_process.py
```

---

## ⚙️ 配置说明

###DeepSeek API Key

在 `config.yaml` 中配置：

```yaml
llm:
  api_key: "sk-your-key-here"  # 或直接填写 API Key
  # 或使用环境变量
  api_key: ${DEEPSEEK_API_KEY}
```

设置环境变量（推荐）：

```bash
# Linux/macOS
export DEEPSEEK_API_KEY="sk-your-key-here"

# Windows PowerShell
$env:DEEPSEEK_API_KEY="sk-your-key-here"
```

### Whisper 模型选择

在 `config.yaml` 中设置 `transcribe.model`：

| 模型 | 大小 | 速度 | 精度 | 推荐场景 |
|------|------|------|------|----------|
| tiny | 75 MB | ⭐⭐⭐⭐⭐ | ⭐ | 快速测试 |
| base | 140 MB | ⭐⭐⭐⭐ | ⭐⭐ | 日常使用（推荐）|
| small | 460 MB | ⭐⭐⭐ | ⭐⭐⭐ | 较高精度 |
| medium | 1.5 GB | ⭐⭐ | ⭐⭐⭐⭐ | 高精度 |
| large | 3.0 GB | ⭐ | ⭐⭐⭐⭐⭐ | 最高精度 |

### GPU 加速

安装 PyTorch CUDA 版本以启用 GPU 加速：

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

验证安装：

```bash
python -c "import torch; print(torch.cuda.is_available())"
# 输出: True
```

详见 `PYTORCH_CUDA安装指导.md`（中文）

---

## 📁 项目结构

```
bilibili-summary/
├── main.py                    # 主程序入口
├── batch_process.py           # 批量处理入口
├── config.yaml                # 配置文件（需自行创建）
├── config.example.yaml        # 配置模板
├── requirements.txt           # 依赖清单
│
├── core/                     # 核心模块
│   ├── downloader.py         # 视频/字幕下载
│   ├── subtitle.py           # B站字幕API
│   ├── transcriber.py        # Whisper 语音转录
│   ├── chunker.py            # 文本分块
│   ├── merger.py             # 文本合并
│   ├── summarizer.py         # AI 摘要生成
│   └── notifier.py          # 完成通知
│
├── videos/                   # 下载的视频（gitignore）
├── subtitles/               # 下载的字幕（gitignore）
├── transcripts/              # 转录文本（gitignore）
├── merged/                   # 合并文本（gitignore）
├── summaries/                # 最终摘要（gitignore）
└── logs/                     # 运行日志（gitignore）
```

---

## 🔧 工作原理

```
BV号输入
   ↓
[下载视频/字幕] → videos/*.m4a, subtitles/*.srt
   ↓
[获取字幕] → subtitle.py (B站API)
   ↓ (失败)
[语音转录] → transcriber.py (faster-whisper)
   ↓
[文本合并] → merger.py
   ↓
[AI 总结] → summarizer.py (DeepSeek API)
   ↓
[保存摘要] → summaries/*.md
```

---

## 📝 输出示例

生成的摘要文件（`summaries/BVxxx_summary.md`）包含：

- 视频标题
- 内容总结
- 关键要点
- 详细内容展开

---

## 🐛 常见问题

### Q1: `FFmpeg 未找到`

**解决**：安装 FFmpeg 并添加到 PATH（见上方安装步骤）

### Q2: `ModuleNotFoundError: No module named 'torch'`

**说明**：正常，PyTorch 仅用于 GPU 加速，CPU 模式不需要

### Q3: 转录速度太慢

**解决**：
1. 安装 PyTorch CUDA 版本启用 GPU 加速
2. 使用更小的 Whisper 模型（`tiny` 或 `base`）

### Q4: `nvidia-smi` 报错

**说明**：远程桌面会话中会阻断 NVML 访问，但不影响使用
**验证**：直接测试 `python -c "import torch; print(torch.cuda.is_available())"`

---

## 📄 许可证

MIT License. 详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 视频下载
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - 语音转录
- [DeepSeek](https://www.deepseek.com/) - AI 总结
- [PyTorch](https://pytorch.org/) - GPU 加速

---

## 📧 联系方式

如有问题或建议，欢迎提交 Issue 或 Pull Request！

---

**⭐ 如果这个项目对你有帮助，欢迎 Star！**
