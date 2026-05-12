"""
B站视频总结系统 v2.0 - 单视频处理主程序

使用方法:
    python main.py --url "https://www.bilibili.com/video/BVxxxxxx"
    python main.py --url "https://www.bilibili.com/video/BVxxxxxx" --config custom_config.yaml
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from core import (
    VideoDownloader,
    SubtitleExtractor,
    Transcriber,
    TextMerger,
    DeepSeekSummarizer,
    Notifier,
)


class BilibiliVideoProcessor:
    """B站视频处理器"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        初始化处理器

        Args:
            config_path: 配置文件路径
        """
        self.config = self._load_config(config_path)
        self._setup_logging()
        self._init_modules()
        self.resume_config = self.config.get("resume", {})
        self.resume_enabled = self.resume_config.get("enabled", True)

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _setup_logging(self):
        """配置日志"""
        log_dir = Path(self.config.get("output", {}).get("log_dir", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)

        log_level = logging.DEBUG if self.config.get("verbose") else logging.INFO

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(
                    log_dir / f"single_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                    encoding="utf-8",
                ),
            ],
        )

    def _init_modules(self):
        """初始化各模块"""
        self.downloader = VideoDownloader(self.config)
        self.subtitle_extractor = SubtitleExtractor(self.config)
        self.transcriber = Transcriber(self.config)
        self.merger = TextMerger(self.config)
        self.notifier = Notifier(self.config)

        # 初始化LLM（可能需要较长初始化时间）
        try:
            self.summarizer = DeepSeekSummarizer(self.config)
        except ValueError as e:
            logging.warning(f"LLM模块初始化失败: {e}")
            self.summarizer = None

    def process(self, url: str, resume: bool = True) -> dict:
        """
        处理单个视频

        Args:
            url: 视频URL
            resume: 是否启用断点续传

        Returns:
            处理结果字典
        """
        start_time = time.time()
        logging.info("=" * 60)
        logging.info(f"开始处理视频: {url}")
        logging.info("=" * 60)

        # 提取BV号
        import re
        bv_match = re.search(r"BV[\w]+", url)
        if not bv_match:
            raise ValueError(f"无法从URL提取BV号: {url}")
        bv_id = bv_match.group(0)

        # 状态文件路径
        status_dir = Path(self.resume_config.get("status_dir", "summaries"))
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / f"{bv_id}.status.json"

        # 检查断点
        status = None
        if resume and status_file.exists():
            status = self._load_status(status_file)
            if status.get("status") == "done":
                logging.info(f"视频已处理完成，跳过: {bv_id}")
                return status

        # 初始化状态
        if not status:
            status = self._init_status(bv_id, url)

        try:
            # Step 1: 下载视频
            if status["steps"]["download"]["status"] != "done":
                status = self._step_download(status, url)
                self._save_status(status_file, status)

            # Step 2: 提取字幕
            if status["steps"]["subtitle"]["status"] != "done":
                status = self._step_subtitle(status)
                self._save_status(status_file, status)

            # Step 3: 语音转录（如果需要）
            if status["steps"]["transcribe"]["status"] != "skipped":
                if status["steps"]["transcribe"]["status"] != "done":
                    status = self._step_transcribe(status)
                    self._save_status(status_file, status)

            # Step 4: 合并文本
            if status["steps"]["merge"]["status"] != "done":
                status = self._step_merge(status)
                self._save_status(status_file, status)

            # Step 5: 生成总结
            if status["steps"]["summarize"]["status"] != "done":
                status = self._step_summarize(status)
                self._save_status(status_file, status)

            # 完成
            status["status"] = "done"
            status["updated_at"] = datetime.now().isoformat()
            status["current_step"] = "done"
            self._save_status(status_file, status)

            elapsed = time.time() - start_time
            logging.info("=" * 60)
            logging.info(f"视频处理完成！耗时: {elapsed:.1f} 秒")
            logging.info("=" * 60)

            # 发送通知
            if self.notifier.enabled:
                summary_file = Path(status["steps"]["summarize"]["file"])
                self.notifier.send_video_complete(
                    bv_id, status["title"], summary_file
                )

            return status

        except Exception as e:
            logging.error(f"处理失败: {e}")
            status["status"] = "failed"
            status["error"] = str(e)
            status["updated_at"] = datetime.now().isoformat()
            self._save_status(status_file, status)
            raise

    def _load_status(self, status_file: Path) -> dict:
        """加载状态文件"""
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_status(self, status_file: Path, status: dict):
        """保存状态文件"""
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

    def _init_status(self, bv_id: str, url: str) -> dict:
        """初始化状态"""
        return {
            "bv_id": bv_id,
            "url": url,
            "title": "",
            "status": "pending",
            "current_step": "download",
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "error": None,
            "steps": {
                "download": {"status": "pending", "file": None},
                "subtitle": {"status": "pending", "file": None},
                "transcribe": {"status": "pending", "file": None, "reason": None},
                "merge": {"status": "pending", "file": None},
                "summarize": {"status": "pending", "file": None},
            },
        }

    def _step_download(self, status: dict, url: str) -> dict:
        """下载视频步骤"""
        logging.info("[Step 1/5] 下载视频...")

        output_dir = Path(self.config.get("download", {}).get("output_dir", "videos"))
        bv_id = status["bv_id"]
        output_path = output_dir / f"{bv_id}.mp4"

        result = self.downloader.download(url, output_path)

        status["steps"]["download"] = {
            "status": "done",
            "file": str(result["video_path"]),
        }
        status["title"] = result["title"]
        status["current_step"] = "subtitle"
        status["updated_at"] = datetime.now().isoformat()

        return status

    def _step_subtitle(self, status: dict) -> dict:
        """提取字幕步骤"""
        logging.info("[Step 2/5] 提取字幕...")

        video_path = Path(status["steps"]["download"]["file"])
        url = status["url"]
        bv_id = status["bv_id"]

        output_dir = Path(self.config.get("subtitle", {}).get("output_dir", "subtitles"))
        output_path = output_dir / bv_id

        result = self.subtitle_extractor.extract(url, video_path, output_path)

        status["steps"]["subtitle"] = {
            "status": "done",
            "file": str(result["file"]) if result.get("file") else None,
            "source": result.get("source"),
            "available": result.get("available", False),
        }
        status["current_step"] = "transcribe"
        status["updated_at"] = datetime.now().isoformat()

        # 检查是否需要降级到Whisper
        if result.get("source") == "fallback_whisper":
            status["steps"]["transcribe"] = {
                "status": "pending",
                "file": None,
                "reason": "subtitle fallback",
            }
        elif not result.get("available") and not self.config.get("subtitle", {}).get("auto_fallback"):
            status["steps"]["transcribe"] = {
                "status": "skipped",
                "file": None,
                "reason": "subtitle available but empty",
            }

        return status

    def _step_transcribe(self, status: dict) -> dict:
        """语音转录步骤"""
        logging.info("[Step 3/5] 语音转录...")

        video_path = Path(status["steps"]["download"]["file"])
        bv_id = status["bv_id"]

        output_dir = Path(self.config.get("transcribe", {}).get("output_dir", "transcripts"))
        output_path = output_dir / f"{bv_id}_transcript.txt"

        try:
            result = self.transcriber.transcribe_from_video(video_path, output_path)

            status["steps"]["transcribe"] = {
                "status": "done",
                "file": str(result["file"]),
            }
        except Exception as e:
            logging.warning(f"转录失败: {e}")
            status["steps"]["transcribe"] = {
                "status": "failed",
                "file": None,
                "reason": str(e),
            }

        status["current_step"] = "merge"
        status["updated_at"] = datetime.now().isoformat()

        return status

    def _step_merge(self, status: dict) -> dict:
        """合并文本步骤"""
        logging.info("[Step 4/5] 合并文本...")

        bv_id = status["bv_id"]

        # 获取字幕文本
        subtitle_text = ""
        subtitle_file = status["steps"]["subtitle"].get("file")
        if subtitle_file and Path(subtitle_file).exists():
            with open(subtitle_file, "r", encoding="utf-8") as f:
                subtitle_text = f.read()

        # 获取转录文本
        whisper_text = ""
        whisper_file = status["steps"]["transcribe"].get("file")
        if whisper_file and Path(whisper_file).exists():
            with open(whisper_file, "r", encoding="utf-8") as f:
                whisper_text = f.read()

        output_dir = Path(self.config.get("merge", {}).get("output_dir", "merged"))
        output_path = output_dir / f"{bv_id}_merged.txt"

        result = self.merger.merge(subtitle_text, whisper_text, output_path)

        status["steps"]["merge"] = {
            "status": "done",
            "file": str(result["file"]),
            "source": result["source"],
        }
        status["current_step"] = "summarize"
        status["updated_at"] = datetime.now().isoformat()

        return status

    def _step_summarize(self, status: dict) -> dict:
        """生成总结步骤"""
        logging.info("[Step 5/5] 生成总结...")

        if not self.summarizer:
            raise RuntimeError("LLM 模块未初始化，无法生成总结")

        bv_id = status["bv_id"]
        title = status["title"]
        url = status["url"]

        # 读取合并后的文本
        merge_file = Path(status["steps"]["merge"]["file"])
        with open(merge_file, "r", encoding="utf-8") as f:
            text = f.read()

        output_dir = Path(self.config.get("output", {}).get("summary_dir", "summaries"))
        output_path = output_dir / f"{bv_id}_summary.md"

        summary = self.summarizer.summarize(text, title, url)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(summary, encoding="utf-8")

        status["steps"]["summarize"] = {
            "status": "done",
            "file": str(output_path),
        }
        status["current_step"] = "done"
        status["updated_at"] = datetime.now().isoformat()

        return status


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="B站视频总结系统 v2.0 - 单视频处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="B站视频URL",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--whisper",
        type=str,
        choices=["tiny", "base", "small", "medium"],
        default=None,
        help="Whisper模型选择",
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["auto", "cuda", "cpu"],
        default=None,
        help="设备选择",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="禁用断点续传",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出目录",
    )

    args = parser.parse_args()

    # 加载配置
    config_path = args.config
    if not Path(config_path).exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 命令行参数覆盖配置
    if args.whisper:
        config.setdefault("transcribe", {})["model"] = args.whisper
    if args.device:
        config.setdefault("transcribe", {})["device"] = args.device
    if args.verbose:
        config["verbose"] = True
    if args.output:
        config.setdefault("download", {})["output_dir"] = args.output

    # 处理视频
    processor = BilibiliVideoProcessor(args.config)
    processor.config.update(config)

    try:
        result = processor.process(args.url, resume=not args.no_resume)
        print("\n处理完成!")
        print(f"总结文件: {result['steps']['summarize']['file']}")
        sys.exit(0)
    except Exception as e:
        print(f"\n处理失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
