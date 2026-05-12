# bilibili-summary
一个用于自动爬取并总结 B 站视频内容的工具，支持自动生成 Markdown 笔记。
整个流程分 3 步：装依赖 → 填配置 → 跑起来。

第一步：安装依赖
打开终端，进入项目目录，执行：

bash
复制
cd C:\Users\22508\WorkBuddy\2026-05-12-task-9\bilibili-summary

# 核心依赖（必须装）
pip install yt-dlp curl_cffi pyyaml requests openai tqdm

# Whisper 转录（可选，没有字幕时才需要）
pip install faster-whisper

# 如果你有 NVIDIA 显卡想加速转录
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
最小可用：只装 pip install yt-dlp curl_cffi pyyaml requests openai tqdm 就行。Whisper 和 PyTorch 只在没有字幕的视频才用到，可以后面按需装。

第二步：配置 DeepSeek API Key
你有两种方式提供 API Key：

方式 A — 环境变量（推荐）

bash
复制
# 临时生效（当前终端窗口）
set DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# 永久生效（加到系统环境变量，重启终端生效）
setx DEEPSEEK_API_KEY "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
方式 B — 直接写配置文件

编辑 config.yaml，把 api_key: null 改成你的 Key：

yaml
复制
llm:
  model_name: "deepseek-chat"
  api_key: "sk-xxxxxxxxxxxxxxxxxxxxxxxx"  # ← 填这里
  base_url: "https://api.deepseek.com"
第三步：运行
单视频处理
bash
复制
python main.py --url "https://www.bilibili.com/video/BV1xxxxxxxxx"
处理完成后，总结文件会输出到 summaries/ 目录下，格式为 BV号_summary.md。

常用参数
bash
复制
# 指定自定义配置文件
python main.py --url "https://www.bilibili.com/video/BVxxxxx" --config my_config.yaml

# 强制用 CPU 转录（默认 auto，有显卡用显卡）
python main.py --url "https://www.bilibili.com/video/BVxxxxx" --device cpu

# 选 Whisper 模型大小（base 速度/质量平衡，small 更准但更慢）
python main.py --url "https://www.bilibili.com/video/BVxxxxx" --whisper small

# 关闭断点续传（从头处理）
python main.py --url "https://www.bilibili.com/video/BVxxxxx" --no-resume

# 开启详细日志（调试用）
python main.py --url "https://www.bilibili.com/video/BVxxxxx" --verbose
批量处理
创建一个 urls.txt 文件，每行一个视频链接（# 开头是注释，会被忽略）：
# 示例视频列表
https://www.bilibili.com/video/BV1xxxxxxx
https://www.bilibili.com/video/BV2xxxxxxx
https://www.bilibili.com/video/BV3xxxxxxx
运行：
bash
复制
python batch_process.py -f urls.txt
批量处理也支持 --whisper、--device、--no-resume、--verbose 等参数，还额外有：

bash
复制
# 限制最多处理 5 个视频
python batch_process.py -f urls.txt --max-videos 5

# 视频之间间隔 10 秒（避免请求太频繁）
python batch_process.py -f urls.txt --delay 10

# 遇到错误继续处理（不停下来）
# 默认就是继续，所以不需要额外设置
config.yaml 各项说明速查
配置项	说明	建议值
download.impersonate	伪装浏览器绕反爬	"chrome"（别改）
download.cookies_browser	从浏览器提取 cookies	"chrome" 或 "edge"（遇到登录视频时有用）
subtitle.auto_fallback	字幕提取失败自动降级到 Whisper	true（推荐）
transcribe.model	Whisper 模型	base（平衡）/ small（更准）
transcribe.device	运行设备	auto（自动选）
llm.model_name	DeepSeek 模型	deepseek-chat
llm.temperature	创造性（越低越保守）	0.3（总结用低值）
llm.chunk.max_chars	分块大小	6000（一般不用改）
resume.enabled	断点续传	true（推荐）
常见问题
Q: 下载报 412 错误？ → 确保 curl_cffi 已安装，且 config.yaml 里 impersonate: "chrome" 没被改掉。

Q: 下载报 403 / 需要登录？ → 设置 download.cookies_browser: "chrome"，程序会自动读取你 Chrome 的登录 cookies。

Q: 不想装 Whisper，只靠字幕？ → 不装 faster-whisper 就行，程序在字幕提取失败时会跳过转录步骤（但可能无法总结纯口述无字幕的视频）。

Q: 想看看处理到哪一步了？ → 查看 summaries/BV号.status.json 文件，里面记录了每一步的状态。或者加 --verbose 开详细日志。