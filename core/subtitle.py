"""
字幕提取模块

优先使用 yt-dlp 内置字幕下载，B站字幕API直接调用作为备选
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional, Union

import requests
import yt_dlp

logger = logging.getLogger(__name__)


class SubtitleExtractor:
    """字幕提取器，支持 yt-dlp 和 B站API两种方式"""

    def __init__(self, config: dict):
        """
        初始化字幕提取器

        Args:
            config: 配置字典
        """
        self.config = config.get("subtitle", {})
        self.output_dir = Path(self.config.get("output_dir", "subtitles"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.languages = self.config.get("languages", ["ai-zh", "zh-Hans"])
        self.auto_fallback = self.config.get("auto_fallback", True)
        self.bilibili_api_config = self.config.get("bilibili_api", {})
        self.bilibili_api_enabled = self.bilibili_api_config.get("enabled", True)
        self.api_timeout = self.bilibili_api_config.get("timeout", 30)
        self.download_config = config.get("download", {})

    def _extract_bv_id(self, url: str) -> Optional[str]:
        """从URL中提取BV号"""
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

    def _extract_cid(self, video_path: Path, url: str) -> Optional[str]:
        """
        从视频文件或URL获取CID

        Args:
            video_path: 视频文件路径
            url: 视频URL

        Returns:
            CID字符串或None
        """
        # 尝试通过 yt-dlp 获取cid
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
        }

        if self.download_config.get("impersonate") == "chrome":
            ydl_opts["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                # B站视频信息中通常包含cid
                formats = info.get("formats", [])
                for fmt in formats:
                    if "cn" in fmt:
                        return str(fmt.get("display_id", ""))
                # 尝试获取第一个格式的display_id
                if formats:
                    return str(formats[0].get("display_id", ""))
        except Exception as e:
            logger.warning(f"获取CID失败: {e}")

        return None

    def extract(self, url: str, video_path: Path, output_path: Optional[Path] = None) -> dict:
        """
        提取字幕

        Args:
            url: 视频URL
            video_path: 视频文件路径
            output_path: 输出路径（可选）

        Returns:
            包含 text, source, file 的字典
        """
        bv_id = self._extract_bv_id(url)
        if not bv_id:
            raise ValueError(f"无法从URL中提取BV号: {url}")

        if output_path is None:
            output_path = self.output_dir / f"{bv_id}"

        logger.info(f"开始提取字幕: {bv_id}")

        # 优先尝试 yt-dlp
        result = self._extract_via_ytdlp(url, output_path)
        if result.get("text"):
            logger.info(f"yt-dlp 字幕提取成功，长度: {len(result['text'])} 字符")
            return result

        # yt-dlp 失败，尝试 B站API
        if self.bilibili_api_enabled:
            logger.info("yt-dlp 字幕提取失败，尝试 B站API...")
            result = self._extract_via_bilibili_api(bv_id, video_path, url)
            if result.get("text"):
                logger.info(f"B站API 字幕提取成功，长度: {len(result['text'])} 字符")
                return result

        # 降级到 Whisper 或返回空
        if self.auto_fallback:
            logger.warning("字幕提取失败，将降级到 Whisper 转录")
            return {
                "text": "",
                "source": "fallback_whisper",
                "file": None,
                "available": False,
            }
        else:
            logger.error("字幕提取失败，且未启用自动降级")
            return {
                "text": "",
                "source": "none",
                "file": None,
                "available": False,
            }

    def _extract_via_ytdlp(self, url: str, output_path: Path) -> dict:
        """
        通过 yt-dlp 提取字幕

        Args:
            url: 视频URL
            output_path: 输出路径

        Returns:
            字幕结果字典
        """
        output_template = str(output_path.parent / output_path.stem)

        opts = {
            "skip_download": True,
            "write_sub": True,
            "write_auto_sub": True,
            "sub_langs": ",".join(self.languages),
            "sub_format": "vtt",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
        }

        # 添加模拟chrome
        if self.download_config.get("impersonate") == "chrome":
            opts["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=False)

            # 查找生成的字幕文件
            for lang in self.languages:
                for ext in ["vtt", "srt", "ass"]:
                    subtitle_file = Path(f"{output_template}.{lang}.{ext}")
                    if subtitle_file.exists():
                        text = self._parse_subtitle(subtitle_file)
                        if text.strip():
                            return {
                                "text": text,
                                "source": "ytdlp",
                                "file": subtitle_file,
                                "available": True,
                            }
                        else:
                            logger.warning(f"字幕文件存在但内容为空: {subtitle_file}")

        except Exception as e:
            logger.warning(f"yt-dlp 字幕提取失败: {e}")

        return {"text": "", "source": "ytdlp", "file": None, "available": False}

    def _extract_via_bilibili_api(self, bv_id: str, video_path: Path, url: str) -> dict:
        """
        通过 B站API 直接获取字幕

        Args:
            bv_id: BV号
            video_path: 视频文件路径
            url: 视频URL

        Returns:
            字幕结果字典
        """
        try:
            # 获取视频信息以获取CID
            cid = self._get_cid_from_api(bv_id)
            if not cid:
                # 尝试从URL解析或使用默认
                cid_match = re.search(r"cid=(\d+)", url)
                if cid_match:
                    cid = cid_match.group(1)
                else:
                    cid = "0"  # 使用默认值尝试

            # 获取字幕列表
            subtitle_list = self._get_subtitle_list(bv_id, cid)
            if not subtitle_list:
                return {"text": "", "source": "bilibili_api", "file": None, "available": False}

            # 选择字幕（优先AI字幕）
            selected_sub = None
            for sub in subtitle_list:
                if sub.get("lan") in ["ai-zh", "zh-Hans", "zh-Hans", "zh"]:
                    selected_sub = sub
                    break

            if not selected_sub and subtitle_list:
                selected_sub = subtitle_list[0]

            if not selected_sub:
                return {"text": "", "source": "bilibili_api", "file": None, "available": False}

            # 下载字幕内容
            subtitle_url = selected_sub.get("subtitle_url")
            if not subtitle_url:
                return {"text": "", "source": "bilibili_api", "file": None, "available": False}

            # 修正URL
            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url

            response = requests.get(subtitle_url, timeout=self.api_timeout)
            response.raise_for_status()

            subtitle_data = response.json()
            content = self._parse_bilibili_subtitle(subtitle_data)

            if content:
                # 保存字幕文件
                output_file = self.output_dir / f"{bv_id}_api.json"
                output_file.write_text(json.dumps(subtitle_data, ensure_ascii=False, indent=2), encoding="utf-8")

                return {
                    "text": content,
                    "source": "bilibili_api",
                    "file": output_file,
                    "available": True,
                }

        except requests.RequestException as e:
            logger.warning(f"B站API请求失败: {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"字幕JSON解析失败: {e}")
        except Exception as e:
            logger.warning(f"B站API字幕提取异常: {e}")

        return {"text": "", "source": "bilibili_api", "file": None, "available": False}

    def _get_cid_from_api(self, bv_id: str) -> Optional[str]:
        """从B站API获取CID"""
        try:
            # 先获取视频基本信息
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com",
            }
            response = requests.get(url, headers=headers, timeout=self.api_timeout)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0 and data.get("data"):
                cid = data["data"].get("cid")
                if cid:
                    return str(cid)

        except Exception as e:
            logger.warning(f"获取CID失败: {e}")

        return None

    def _get_subtitle_list(self, bv_id: str, cid: str) -> list:
        """获取字幕列表"""
        try:
            url = f"https://api.bilibili.com/x/player/v2?bvid={bv_id}&cid={cid}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com",
            }
            response = requests.get(url, headers=headers, timeout=self.api_timeout)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0:
                subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
                return subtitles

        except Exception as e:
            logger.warning(f"获取字幕列表失败: {e}")

        return []

    def _parse_bilibili_subtitle(self, subtitle_data: dict) -> str:
        """
        解析B站字幕JSON

        Args:
            subtitle_data: 字幕JSON数据

        Returns:
            纯文本内容
        """
        body = subtitle_data.get("body", [])
        if not body:
            return ""

        lines = []
        for item in body:
            content = item.get("content", "")
            if content:
                lines.append(content)

        return "\n".join(lines)

    def _parse_subtitle(self, subtitle_file: Path) -> str:
        """
        解析字幕文件（支持VTT和SRT）

        Args:
            subtitle_file: 字幕文件路径

        Returns:
            纯文本内容
        """
        try:
            content = subtitle_file.read_text(encoding="utf-8")
            return self._strip_subtitle_tags(content)
        except Exception as e:
            logger.warning(f"字幕文件解析失败: {e}")
            return ""

    def _strip_subtitle_tags(self, content: str) -> str:
        """
        去除字幕文件中的标签和时间戳

        Args:
            content: 原始字幕内容

        Returns:
            纯文本内容
        """
        lines = content.split("\n")
        result_lines = []

        for line in lines:
            line = line.strip()
            # 跳过时间轴行
            if "-->" in line:
                continue
            # 跳过WEBVTT等标签行
            if line.startswith("WEBVTT") or line.startswith("STYLE") or line.startswith("NOTE"):
                continue
            # 去除HTML标签
            import re
            line = re.sub(r"<[^>]+>", "", line)
            # 去除行内标签
            line = re.sub(r"\{[^}]+\}", "", line)
            # 跳过纯空白行
            if line.strip():
                result_lines.append(line.strip())

        return " ".join(result_lines)
