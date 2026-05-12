"""
视频下载模块

使用 yt-dlp 下载 B站视频，支持 cookies 登录和 chrome 模拟
"""

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)


class VideoDownloader:
    """视频下载器，使用 yt-dlp 实现"""

    def __init__(self, config: dict):
        """
        初始化下载器

        Args:
            config: 配置字典
        """
        self.config = config.get("download", {})
        self.output_dir = Path(self.config.get("output_dir", "videos"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.impersonate = self.config.get("impersonate", "chrome")
        self.cookies_browser = self.config.get("cookies_browser")
        self.cookies_file = self.config.get("cookies_file")
        self.format_spec = self.config.get("format", "bestaudio[ext=mp4]/bestaudio")
        self.max_filesize = self.config.get("max_filesize")

    def _extract_bv_id(self, url: str) -> Optional[str]:
        """
        从URL中提取BV号

        Args:
            url: B站视频URL

        Returns:
            BV号或None
        """
        patterns = [
            r"BV[\w]+",
            r"bv[\w]+",
            r"https?://www\.bilibili\.com/video/(BV[\w]+)",
            r"https?://b23\.tv/(\w+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1) if match.lastindex else match.group(0)
        return None

    def download(self, url: str, output_path: Optional[Path] = None) -> dict:
        """
        下载视频

        Args:
            url: 视频URL
            output_path: 输出路径（可选）

        Returns:
            包含 video_path, title, bv_id, duration 的字典
        """
        bv_id = self._extract_bv_id(url)
        if not bv_id:
            raise ValueError(f"无法从URL中提取BV号: {url}")

        if output_path is None:
            output_path = self.output_dir / f"{bv_id}.%(ext)s"

        ydl_opts = self._build_yt_dlp_opts(output_path)

        logger.info(f"开始下载视频: {url}")
        logger.info(f"BV号: {bv_id}")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_path = Path(ydl.prepare_filename(info))
                
                result = {
                    "video_path": video_path,
                    "title": info.get("title", bv_id),
                    "bv_id": bv_id,
                    "duration": info.get("duration", 0),
                    "url": url,
                }
                
                logger.info(f"下载完成: {result['title']}")
                logger.info(f"视频路径: {video_path}")
                logger.info(f"时长: {result['duration']} 秒")
                
                return result

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"下载失败: {e}")
            raise
        except Exception as e:
            logger.error(f"下载异常: {e}")
            raise

    def _build_yt_dlp_opts(self, output_path: Path) -> dict:
        """
        构建 yt-dlp 选项

        Args:
            output_path: 输出路径

        Returns:
            yt-dlp 选项字典
        """
        opts = {
            "format": self.format_spec,
            "outtmpl": str(output_path.parent / output_path.stem) + ".%(ext)s",
            "quiet": False,
            "no_warnings": False,
            "extract_flat": False,
            # B站特定设置
            "extractor_args": {
                "bilibili": {
                    "embed_dash_manifest": False,
                    "embed_subtitle": False,
                }
            },
        }

        # 添加模拟chrome以绕过反爬
        if self.impersonate == "chrome":
            opts["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

        # Cookies 配置
        if self.cookies_browser:
            opts["cookies_from_browser"] = (self.cookies_browser,)
            logger.info(f"从浏览器 {self.cookies_browser} 读取 cookies")
        elif self.cookies_file:
            opts["cookiefile"] = self.cookies_file
            logger.info(f"从文件读取 cookies: {self.cookies_file}")

        # 文件大小限制
        if self.max_filesize:
            opts["max_filesize"] = self.max_filesize

        return opts

    def get_video_info(self, url: str) -> dict:
        """
        获取视频信息（不下载）

        Args:
            url: 视频URL

        Returns:
            视频信息字典
        """
        ydl_opts = self._build_yt_dlp_opts(Path("dummy"))
        ydl_opts["skip_download"] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    "title": info.get("title"),
                    "bv_id": self._extract_bv_id(url),
                    "duration": info.get("duration", 0),
                    "thumbnail": info.get("thumbnail"),
                    "description": info.get("description"),
                }
        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            raise
