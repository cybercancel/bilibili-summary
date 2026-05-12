"""
B站视频总结系统 v2.0 - 批量处理主程序

使用方法:
    python batch_process.py -f urls.txt
    python batch_process.py -f urls.txt --batch-config batch_config.yaml
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

from tqdm import tqdm

from core import (
    VideoDownloader,
    SubtitleExtractor,
    Transcriber,
    TextMerger,
    DeepSeekSummarizer,
    Notifier,
)


class BilibiliBatchProcessor:
    """B站视频批量处理器"""

    def __init__(self, config_path: str = "config.yaml", batch_config_path: str = "batch_config.yaml"):
        """
        初始化批量处理器

        Args:
            config_path: 主配置文件路径
            batch_config_path: 批量配置文件路径
        """
        self.config = self._load_config(config_path)
        self.batch_config = self._load_config(batch_config_path)
        self._setup_logging()
        self._init_modules()

        self.resume_enabled = self.batch_config.get("resume", {}).get("enabled", True)
        self.skip_done = self.batch_config.get("resume", {}).get("skip_done", True)
        self.delay_between = self.batch_config.get("input", {}).get("delay_between", 5)
        self.max_videos = self.batch_config.get("input", {}).get("max_videos")
        self.stop_on_error = self.batch_config.get("input", {}).get("stop_on_error", False)

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        config_file = Path(config_path)
        if not config_file.exists():
            logging.warning(f"配置文件不存在: {config_path}，使用默认配置")
            return {}

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
                    log_dir / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
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

        try:
            self.summarizer = DeepSeekSummarizer(self.config)
        except ValueError as e:
            logging.warning(f"LLM模块初始化失败: {e}")
            self.summarizer = None

        self.notifier = Notifier(self.config)

    def load_urls(self, url_file: str) -> list[str]:
        """
        加载URL列表

        Args:
            url_file: URL文件路径

        Returns:
            URL列表
        """
        url_path = Path(url_file)
        if not url_path.exists():
            raise FileNotFoundError(f"URL文件不存在: {url_file}")

        with open(url_path, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        logging.info(f"从文件加载了 {len(urls)} 个URL")
        return urls

    def process_batch(self, urls: list[str], resume: bool = True) -> dict:
        """
        批量处理视频

        Args:
            urls: URL列表
            resume: 是否启用断点续传

        Returns:
            批量处理结果
        """
        start_time = time.time()
        total = len(urls)
        success = 0
        failed = 0
        skipped = 0
        results = []

        logging.info("=" * 70)
        logging.info(f"开始批量处理: {total} 个视频")
        logging.info("=" * 70)

        # 创建进度条
        pbar = tqdm(urls, desc="处理进度", unit="视频")

        for i, url in enumerate(pbar):
            pbar.set_postfix({"当前": f"{i+1}/{total}", "成功": success, "失败": failed})

            try:
                # 检查是否跳过
                if resume and self.skip_done:
                    if self._is_url_done(url):
                        logging.info(f"跳过已完成的视频: {url}")
                        skipped += 1
                        continue

                # 处理单个视频
                result = self._process_single(url, resume)
                results.append(result)

                if result.get("status") == "done":
                    success += 1
                else:
                    failed += 1

            except Exception as e:
                logging.error(f"处理失败: {url} - {e}")
                failed += 1
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": str(e),
                })

                if self.stop_on_error:
                    logging.error("遇到错误停止批量处理")
                    break

            # 视频间隔
            if i < total - 1 and self.delay_between > 0:
                time.sleep(self.delay_between)

        elapsed = time.time() - start_time

        # 汇总结果
        summary = {
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "elapsed": elapsed,
            "results": results,
            "completed_at": datetime.now().isoformat(),
        }

        # 保存批量报告
        if self.batch_config.get("output", {}).get("batch_summary"):
            self._save_batch_summary(summary)

        # 发送通知
        if self.notifier.enabled:
            self.notifier.send_batch_complete(total, success, failed)

        logging.info("=" * 70)
        logging.info("批量处理完成!")
        logging.info(f"总计: {total}, 成功: {success}, 失败: {failed}, 跳过: {skipped}")
        logging.info(f"耗时: {elapsed:.1f} 秒")
        logging.info("=" * 70)

        return summary

    def _is_url_done(self, url: str) -> bool:
        """检查URL是否已处理完成"""
        import re
        bv_match = re.search(r"BV[\w]+", url)
        if not bv_match:
            return False

        bv_id = bv_match.group(0)
        status_dir = Path(self.batch_config.get("resume", {}).get("status_dir", "summaries"))
        status_file = status_dir / f"{bv_id}.status.json"

        if not status_file.exists():
            return False

        try:
            with open(status_file, "r", encoding="utf-8") as f:
                status = json.load(f)
            return status.get("status") == "done"
        except Exception:
            return False

    def _process_single(self, url: str, resume: bool = True) -> dict:
        """
        处理单个视频

        Args:
            url: 视频URL
            resume: 是否启用断点续传

        Returns:
            处理结果
        """
        import re
        bv_match = re.search(r"BV[\w]+", url)
        if not bv_match:
            raise ValueError(f"无法从URL提取BV号: {url}")
        bv_id = bv_match.group(0)

        logging.info(f"\n{'='*60}")
        logging.info(f"处理视频 {bv_id}: {url}")
        logging.info(f"{'='*60}")

        # 状态文件
        status_dir = Path(self.batch_config.get("resume", {}).get("status_dir", "summaries"))
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / f"{bv_id}.status.json"

        # 加载或初始化状态
        if resume and status_file.exists():
            with open(status_file, "r", encoding="utf-8") as f:
                status = json.load(f)
        else:
            status = self._init_status(bv_id, url)

        try:
            # Step 1: 下载
            if status["steps"]["download"]["status"] != "done":
                status = self._step_download(status, url)
                self._save_status(status_file, status)

            # Step 2: 字幕
            if status["steps"]["subtitle"]["status"] != "done":
                status = self._step_subtitle(status)
                self._save_status(status_file, status)

            # Step 3: 转录
            if status["steps"]["transcribe"]["status"] not in ["done", "skipped"]:
                status = self._step_transcribe(status)
                self._save_status(status_file, status)

            # Step 4: 合并
            if status["steps"]["merge"]["status"] != "done":
                status = self._step_merge(status)
                self._save_status(status_file, status)

            # Step 5: 总结
            if status["steps"]["summarize"]["status"] != "done":
                status = self._step_summarize(status)
                self._save_status(status_file, status)

            # 完成
            status["status"] = "done"
            status["updated_at"] = datetime.now().isoformat()
            self._save_status(status_file, status)

            return status

        except Exception as e:
            logging.error(f"处理失败: {e}")
            status["status"] = "failed"
            status["error"] = str(e)
            status["updated_at"] = datetime.now().isoformat()
            self._save_status(status_file, status)
            raise

    def _load_status(self, status_file: Path) -> dict:
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_status(self, status_file: Path, status: dict):
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

    def _init_status(self, bv_id: str, url: str) -> dict:
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
        logging.info("[Step 1/5] 下载视频...")
        output_dir = Path(self.config.get("download", {}).get("output_dir", "videos"))
        bv_id = status["bv_id"]
        output_path = output_dir / f"{bv_id}.mp4"
        result = self.downloader.download(url, output_path)
        status["steps"]["download"] = {"status": "done", "file": str(result["video_path"])}
        status["title"] = result["title"]
        status["current_step"] = "subtitle"
        return status

    def _step_subtitle(self, status: dict) -> dict:
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
        if result.get("source") == "fallback_whisper":
            status["steps"]["transcribe"] = {"status": "pending", "file": None, "reason": "subtitle fallback"}
        return status

    def _step_transcribe(self, status: dict) -> dict:
        logging.info("[Step 3/5] 语音转录...")
        video_path = Path(status["steps"]["download"]["file"])
        bv_id = status["bv_id"]
        output_dir = Path(self.config.get("transcribe", {}).get("output_dir", "transcripts"))
        output_path = output_dir / f"{bv_id}_transcript.txt"
        try:
            result = self.transcriber.transcribe_from_video(video_path, output_path)
            status["steps"]["transcribe"] = {"status": "done", "file": str(result["file"])}
        except Exception as e:
            logging.warning(f"转录失败: {e}")
            status["steps"]["transcribe"] = {"status": "failed", "file": None, "reason": str(e)}
        status["current_step"] = "merge"
        return status

    def _step_merge(self, status: dict) -> dict:
        logging.info("[Step 4/5] 合并文本...")
        bv_id = status["bv_id"]
        subtitle_text = ""
        subtitle_file = status["steps"]["subtitle"].get("file")
        if subtitle_file and Path(subtitle_file).exists():
            with open(subtitle_file, "r", encoding="utf-8") as f:
                subtitle_text = f.read()
        whisper_text = ""
        whisper_file = status["steps"]["transcribe"].get("file")
        if whisper_file and Path(whisper_file).exists():
            with open(whisper_file, "r", encoding="utf-8") as f:
                whisper_text = f.read()
        output_dir = Path(self.config.get("merge", {}).get("output_dir", "merged"))
        output_path = output_dir / f"{bv_id}_merged.txt"
        result = self.merger.merge(subtitle_text, whisper_text, output_path)
        status["steps"]["merge"] = {"status": "done", "file": str(result["file"]), "source": result["source"]}
        status["current_step"] = "summarize"
        return status

    def _step_summarize(self, status: dict) -> dict:
        logging.info("[Step 5/5] 生成总结...")
        if not self.summarizer:
            raise RuntimeError("LLM 模块未初始化")
        bv_id = status["bv_id"]
        title = status["title"]
        url = status["url"]
        merge_file = Path(status["steps"]["merge"]["file"])
        with open(merge_file, "r", encoding="utf-8") as f:
            text = f.read()
        output_dir = Path(self.config.get("output", {}).get("summary_dir", "summaries"))
        output_path = output_dir / f"{bv_id}_summary.md"
        summary = self.summarizer.summarize(text, title, url)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(summary, encoding="utf-8")
        status["steps"]["summarize"] = {"status": "done", "file": str(output_path)}
        status["current_step"] = "done"
        return status

    def _save_batch_summary(self, summary: dict):
        """保存批量处理报告"""
        output_dir = Path(self.config.get("output", {}).get("summary_dir", "summaries"))
        summary_file = output_dir / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logging.info(f"批量报告已保存: {summary_file}")

        # 同时生成 Markdown 报告
        md_file = summary_file.with_suffix(".md")
        self._save_batch_markdown(summary, md_file)

    def _save_batch_markdown(self, summary: dict, output_path: Path):
        """保存 Markdown 格式的批量报告"""
        lines = [
            "# 批量处理报告",
            "",
            f"- **处理时间**: {summary['completed_at']}",
            f"- **总耗时**: {summary['elapsed']:.1f} 秒",
            f"- **总计**: {summary['total']} 个视频",
            f"- **成功**: {summary['success']} 个",
            f"- **失败**: {summary['failed']} 个",
            f"- **跳过**: {summary['skipped']} 个",
            f"- **成功率**: {summary['success']/summary['total']*100:.1f}%",
            "",
            "## 详细结果",
            "",
            "| # | BV号 | 标题 | 状态 | 错误 |",
            "|---|------|------|------|------|",
        ]

        for i, result in enumerate(summary["results"], 1):
            bv_id = result.get("bv_id", "N/A")
            title = result.get("title", "N/A")[:30]
            status = result.get("status", "unknown")
            error = result.get("error", "")[:50] if result.get("error") else ""
            lines.append(f"| {i} | {bv_id} | {title} | {status} | {error} |")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        logging.info(f"Markdown 报告已保存: {output_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="B站视频总结系统 v2.0 - 批量处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-f", "--file",
        type=str,
        required=True,
        help="URL文件路径",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="主配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--batch-config",
        type=str,
        default="batch_config.yaml",
        help="批量配置文件路径 (默认: batch_config.yaml)",
    )
    parser.add_argument(
        "-w", "--whisper",
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
        "--notify",
        action="store_true",
        help="启用通知",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=None,
        help="视频之间延迟（秒）",
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
        "--max-videos",
        type=int,
        default=None,
        help="最大处理视频数",
    )

    args = parser.parse_args()

    # 加载配置
    if not Path(args.config).exists():
        print(f"主配置文件不存在: {args.config}")
        sys.exit(1)

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 命令行参数覆盖配置
    if args.whisper:
        config.setdefault("transcribe", {})["model"] = args.whisper
    if args.device:
        config.setdefault("transcribe", {})["device"] = args.device
    if args.verbose:
        config["verbose"] = True

    # 创建处理器
    processor = BilibiliBatchProcessor(args.config, args.batch_config)
    processor.config.update(config)

    # 覆盖批量配置
    if args.notify:
        processor.notifier.enabled = True
    if args.delay is not None:
        processor.delay_between = args.delay
    if args.max_videos is not None:
        processor.max_videos = args.max_videos

    # 加载URL
    try:
        urls = processor.load_urls(args.file)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)

    # 限制数量
    if processor.max_videos:
        urls = urls[: processor.max_videos]

    if not urls:
        print("没有可处理的URL")
        sys.exit(0)

    # 处理
    try:
        summary = processor.process_batch(urls, resume=not args.no_resume)
        print(f"\n批量处理完成!")
        print(f"成功: {summary['success']}/{summary['total']}")
        sys.exit(0 if summary['failed'] == 0 else 1)
    except Exception as e:
        print(f"\n批量处理失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
