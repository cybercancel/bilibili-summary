"""
字幕提取模块

优先使用 yt-dlp 内置字幕下载（带 cookies 登录态获取 AI 字幕），
B站 player/v2 API 作为备选（使用 curl_cffi 绕过反爬）。

B站字幕获取机制：
- CC 字幕（UP主上传）：不需要登录
- AI 字幕（B站自动生成）：需要登录态（SESSDATA Cookie）才能获取
- yt-dlp 无 cookies 时：只能获取 CC 字幕，AI 字幕返回空列表
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# URL 提取工具函数（模块级，供所有入口调用）
# ──────────────────────────────────────────────

def extract_bilibili_url(text: str) -> Optional[str]:
    """
    从任意文本中提取干净的 B站视频 URL。

    支持的输入格式：
    - 纯 URL: "https://www.bilibili.com/video/BV1DWRdB1E2s/?share_source=copy_web"
    - 带标题: "【标题】 https://www.bilibili.com/video/BV1DWRdB1E2s/?share_source=copy_web"
    - 短链:   "https://b23.tv/xxxxxx"
    - BV号:   "BV1DWRdB1E2s"

    返回:
        干净的 URL（去除查询参数），如 "https://www.bilibili.com/video/BV1DWRdB1E2s"
        或 None（未找到有效链接）
    """
    if not text:
        return None

    text = text.strip()

    # 1. 尝试匹配完整 B站视频 URL（含 b23.tv 短链）
    url_patterns = [
        r"https?://(?:www\.)?bilibili\.com/video/(BV[\w]+)",
        r"https?://b23\.tv/(\w+)",
        r"https?://(?:www\.)?bilibili\.com/video/(AV[\w]+)",
    ]
    for pattern in url_patterns:
        match = re.search(pattern, text)
        if match:
            if "b23.tv" in pattern:
                # 短链无法直接使用，返回原始短链让 yt-dlp 处理重定向
                url_start = text.find("http")
                url_end = len(text)
                for sep in [" ", "\t", "\n", "\r"]:
                    idx = text.find(sep, url_start)
                    if idx != -1 and idx < url_end:
                        url_end = idx
                return text[url_start:url_end].strip()
            # 标准视频 URL — 提取 BV/AV 号，构造干净 URL
            video_id = match.group(1)
            return f"https://www.bilibili.com/video/{video_id}"

    # 2. 尝试直接匹配 BV/AV 号
    id_match = re.search(r"(BV[\w]+|AV[\w]+)", text, re.IGNORECASE)
    if id_match:
        video_id = id_match.group(1)
        # 统一为大写 BV 前缀
        if video_id.upper().startswith("BV"):
            video_id = "BV" + video_id[2:] if video_id[:2] == "bv" else video_id
        return f"https://www.bilibili.com/video/{video_id}"

    return None


class SubtitleExtractor:
    """字幕提取器，支持 yt-dlp 和 B站 API 两种方式"""

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

        # Cookie 配置
        self.cookies_browser = self.download_config.get("cookies_browser")
        self.cookies_file = self.download_config.get("cookies_file")
        self._sessdata_config = self.download_config.get("sessdata")

        # 尝试提取 SESSDATA（用于 B站 API 调用）
        # 优先级：config.sessdata > cookies_file > cookies_browser > 环境变量
        self._sessdata = self._extract_sessdata()

    def _extract_sessdata(self) -> Optional[str]:
        """提取 B站 SESSDATA（优先级：config > cookies_file > 浏览器 > 环境变量）"""
        # 1. 配置文件直接填写（优先级最高）
        if self._sessdata_config:
            return self._sessdata_config
        if self.cookies_file:
            # 从 cookies.txt 文件读取
            try:
                with open(self.cookies_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or not line:
                            continue
                        parts = line.split("\t")
                        if len(parts) >= 7 and parts[5].strip().lower() == "bilibili.com" and parts[6].strip() == "SESSDATA":
                            return parts[7].strip()
                        # Netscape 格式: domain  flag  path  secure  expires  name  value
                        if len(parts) >= 8 and "bilibili" in parts[0].lower() and parts[6].strip() == "SESSDATA":
                            return parts[7].strip()
            except Exception as e:
                logger.debug(f"从 cookies 文件读取 SESSDATA 失败: {e}")

        if self.cookies_browser:
            # 从浏览器 Cookie 数据库中提取
            try:
                sessdata = self._get_sessdata_from_browser(self.cookies_browser)
                if sessdata:
                    return sessdata
            except Exception as e:
                logger.debug(f"从浏览器提取 SESSDATA 失败: {e}")

        # 环境变量兜底
        return os.environ.get("BILIBILI_SESSDATA")

    def _get_sessdata_from_browser(self, browser: str) -> Optional[str]:
        """
        从浏览器 Cookie 数据库中提取 B站 SESSDATA

        Args:
            browser: 浏览器名称 (chrome/edge/brave/firefox)

        Returns:
            SESSDATA 值或 None
        """
        import sqlite3
        import shutil
        import tempfile

        browser_paths = {
            "chrome": {
                "win": Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Default" / "Network" / "Cookies",
                "linux": Path.home() / ".config" / "google-chrome" / "Default" / "Network" / "Cookies",
                "mac": Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Network" / "Cookies",
            },
            "edge": {
                "win": Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data" / "Default" / "Network" / "Cookies",
            },
            "brave": {
                "win": Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Network" / "Cookies",
            },
        }

        paths = browser_paths.get(browser, {})
        cookie_path = None
        for os_name, path in paths.items():
            if path.exists():
                cookie_path = path
                break

        if not cookie_path:
            return None

        # 复制 Cookie 数据库（避免被浏览器锁定）
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            shutil.copy2(cookie_path, tmp_path)

            conn = sqlite3.connect(str(tmp_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM cookies WHERE host_key LIKE '%bilibili%' AND name = 'SESSDATA' LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()
            tmp_path.unlink(missing_ok=True)

            if row and row[0]:
                # Chrome 加密的 Cookie 需要解密（Windows 上使用 DPAPI）
                value = row[0]
                if len(value) > 20 and value.startswith("v10") or value.startswith("v11"):
                    try:
                        value = self._decrypt_chrome_cookie(value, browser)
                    except Exception:
                        value = row[0]  # 解密失败返回原始值
                return value
        except Exception as e:
            logger.debug(f"读取浏览器 Cookie 数据库失败: {e}")

        return None

    def _decrypt_chrome_cookie(self, encrypted_value: bytes, browser: str) -> str:
        """
        解密 Chrome/Edge 加密的 Cookie（Windows DPAPI）

        Args:
            encrypted_value: 加密的 Cookie 值
            browser: 浏览器名称

        Returns:
            解密后的 Cookie 值
        """
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        # Chrome 加密 Cookie 前缀 "v10" 或 "v11"
        if isinstance(encrypted_value, str):
            encrypted_value = encrypted_value.encode("utf-8")
        if encrypted_value[:3] in (b"v10", b"v11"):
            encrypted_value = encrypted_value[3:]

        blob_in = DATA_BLOB()
        blob_in.cbData = len(encrypted_value)
        blob_in.pbData = ctypes.create_string_buffer(encrypted_value)

        blob_out = DATA_BLOB()

        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return decrypted.decode("utf-8", errors="replace")
        else:
            raise RuntimeError("DPAPI decryption failed")

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

    def _build_ytdlp_opts(self, extra_opts: dict = None) -> dict:
        """构建 yt-dlp 选项，包含 Cookie 和反爬配置"""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        # 添加模拟 chrome 绕过反爬
        if self.download_config.get("impersonate") == "chrome":
            opts["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

        # Cookie 配置 — 字幕提取必须带登录态
        if self.cookies_browser:
            opts["cookies_from_browser"] = (self.cookies_browser,)
        elif self.cookies_file:
            opts["cookiefile"] = str(self.cookies_file)
        elif self._sessdata:
            # 直接配置了 sessdata，生成临时 Netscape 格式 cookie 文件给 yt-dlp
            # Netscape 格式: domain  flag  path  secure  expires  name  value
            cookie_content = (
                f"# Netscape HTTP Cookie File\n"
                f".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t{self._sessdata}\n"
            )
            tmp_cookie = self.output_dir / ".yt-dlp-sessdata-cookies.txt"
            tmp_cookie.write_text(cookie_content, encoding="utf-8")
            opts["cookiefile"] = str(tmp_cookie)

        if extra_opts:
            opts.update(extra_opts)

        return opts

    def _build_curl_session(self):
        """构建 curl_cffi 请求会话，带反爬和 Cookie"""
        try:
            import curl_cffi.requests as cffi_req
        except ImportError:
            logger.warning("curl_cffi 未安装，B站 API 备选方案不可用")
            return None, None

        session = cffi_req.Session(impersonate="chrome")
        session.timeout = self.api_timeout

        # 添加 Cookie（如果有 SESSDATA）
        if self._sessdata:
            session.cookies.set("SESSDATA", self._sessdata, domain=".bilibili.com")

        return session, cffi_req

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

        if not self.cookies_browser and not self.cookies_file and not self._sessdata:
            logger.info("未配置 sessdata / cookies_browser / cookies_file，AI 字幕可能无法获取")

        # 优先尝试 yt-dlp（带 cookies 获取 AI 字幕）
        result = self._extract_via_ytdlp(url, output_path)
        if result.get("text"):
            logger.info(f"yt-dlp 字幕提取成功，长度: {len(result['text'])} 字符")
            self._save_subtitle_text(bv_id, result["text"])
            return result

        # yt-dlp 失败，尝试 B站 API（curl_cffi 绕过反爬 + Cookie）
        if self.bilibili_api_enabled:
            logger.info("yt-dlp 字幕提取失败，尝试 B站 API...")
            result = self._extract_via_bilibili_api(bv_id, video_path, url)
            if result.get("text"):
                logger.info(f"B站 API 字幕提取成功，长度: {len(result['text'])} 字符")
                self._save_subtitle_text(bv_id, result["text"])
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

        extra_opts = {
            "skip_download": True,
            "write_sub": True,
            "write_auto_sub": True,
            "sub_langs": "all",  # 请求所有语言，避免遗漏
            "sub_format": "vtt",
            "outtmpl": output_template,
        }

        opts = self._build_ytdlp_opts(extra_opts)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # 检查 yt-dlp 获取到的字幕信息
                subtitles = info.get("subtitles", {})
                auto_captions = info.get("automatic_captions", {})
                logger.debug(f"yt-dlp subtitles: {list(subtitles.keys())}")
                logger.debug(f"yt-dlp auto_captions: {list(auto_captions.keys())}")

                # 尝试通过 yt-dlp 内置下载字幕
                if subtitles or auto_captions:
                    try:
                        ydl.process_info(info)
                    except Exception as e:
                        logger.debug(f"yt-dlp process_info 异常（可忽略）: {e}")

            # 查找生成的字幕文件（检查所有可能的语言名）
            # yt-dlp 可能使用 "zh-Hans", "ai-zh", "zh", "zh-CN" 等
            possible_langs = ["ai-zh", "zh-Hans", "zh", "zh-CN", "zh-TW", "en", "cn"]
            # 也检查 yt-dlp 实际使用的语言
            checked = set()
            for lang in possible_langs + list(subtitles.keys()) + list(auto_captions.keys()):
                if lang in checked:
                    continue
                checked.add(lang)
                for ext in ["vtt", "srt", "ass", "srv3"]:
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
                            logger.debug(f"字幕文件存在但内容为空: {subtitle_file}")

            # 如果 yt-dlp 没有写入文件但有字幕 URL，手动下载
            all_subs = {**subtitles, **auto_captions}
            for lang, sub_list in all_subs.items():
                for sub in sub_list:
                    sub_url = sub.get("url")
                    if not sub_url:
                        continue
                    try:
                        import requests as req_lib
                        resp = req_lib.get(sub_url, timeout=self.api_timeout)
                        resp.raise_for_status()
                        content = resp.text
                        if content.strip():
                            text = self._strip_subtitle_tags(content)
                            if text.strip():
                                # 保存到文件
                                out_file = Path(f"{output_template}.{lang}.vtt")
                                out_file.write_text(content, encoding="utf-8")
                                return {
                                    "text": text,
                                    "source": "ytdlp",
                                    "file": out_file,
                                    "available": True,
                                }
                    except Exception as e:
                        logger.debug(f"手动下载字幕失败 ({lang}): {e}")

        except Exception as e:
            logger.warning(f"yt-dlp 字幕提取失败: {e}")

        return {"text": "", "source": "ytdlp", "file": None, "available": False}

    def _extract_via_bilibili_api(self, bv_id: str, video_path: Path, url: str) -> dict:
        """
        通过 B站 API 直接获取字幕

        使用 curl_cffi 绕过 B站反爬，支持 SESSDATA Cookie 获取 AI 字幕

        Args:
            bv_id: BV号
            video_path: 视频文件路径
            url: 视频URL

        Returns:
            字幕结果字典
        """
        session, cffi_req = self._build_curl_session()
        if session is None:
            return {"text": "", "source": "bilibili_api", "file": None, "available": False}

        try:
            # 获取 CID
            cid = self._get_cid_from_api(bv_id, session)
            if not cid:
                # 尝试从 URL 解析
                cid_match = re.search(r"cid=(\d+)", url)
                if cid_match:
                    cid = cid_match.group(1)
                else:
                    logger.warning(f"无法获取 CID: {bv_id}")
                    return {"text": "", "source": "bilibili_api", "file": None, "available": False}

            # 获取字幕列表
            subtitle_list = self._get_subtitle_list(bv_id, cid, session)
            if not subtitle_list:
                if self._sessdata:
                    logger.info("B站 API 返回空字幕列表，该视频可能没有可用字幕")
                else:
                    logger.info("B站 API 返回空字幕列表（未配置 SESSDATA，AI 字幕不可用）")
                return {"text": "", "source": "bilibili_api", "file": None, "available": False}

            logger.info(f"B站 API 发现 {len(subtitle_list)} 条字幕")

            # 选择字幕（优先 AI 中文字幕）
            preferred_lans = ["ai-zh", "zh-Hans", "zh-CN", "zh", "en"]
            selected_sub = None
            for lan in preferred_lans:
                for sub in subtitle_list:
                    if sub.get("lan", "").lower() == lan.lower() or sub.get("lan") == lan:
                        selected_sub = sub
                        break
                if selected_sub:
                    break

            if not selected_sub:
                selected_sub = subtitle_list[0]

            # 下载字幕内容
            subtitle_url = selected_sub.get("subtitle_url")
            if not subtitle_url:
                return {"text": "", "source": "bilibili_api", "file": None, "available": False}

            # 修正 URL
            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url

            # 用 curl_cffi 下载字幕内容（绕过反爬）
            resp = session.get(subtitle_url, timeout=self.api_timeout)
            resp.raise_for_status()

            subtitle_data = resp.json()
            content = self._parse_bilibili_subtitle(subtitle_data)

            if content:
                # 保存字幕文件
                output_file = self.output_dir / f"{bv_id}_api.json"
                output_file.write_text(json.dumps(subtitle_data, ensure_ascii=False, indent=2), encoding="utf-8")

                lan_doc = selected_sub.get("lan_doc", selected_sub.get("lan", ""))
                logger.info(f"成功获取字幕: {lan_doc}，长度: {len(content)} 字符")

                return {
                    "text": content,
                    "source": "bilibili_api",
                    "file": output_file,
                    "available": True,
                }

        except Exception as e:
            logger.warning(f"B站 API 字幕提取异常: {e}")
        finally:
            try:
                session.close()
            except Exception:
                pass

        return {"text": "", "source": "bilibili_api", "file": None, "available": False}

    def _get_cid_from_api(self, bv_id: str, session) -> Optional[str]:
        """从 B站 API 获取 CID"""
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
            resp = session.get(url, timeout=self.api_timeout)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0 and data.get("data"):
                cid = data["data"].get("cid")
                if cid:
                    return str(cid)

        except Exception as e:
            logger.warning(f"获取 CID 失败: {e}")

        return None

    def _get_subtitle_list(self, bv_id: str, cid: str, session) -> list:
        """获取字幕列表"""
        try:
            url = f"https://api.bilibili.com/x/player/v2?bvid={bv_id}&cid={cid}"
            resp = session.get(url, timeout=self.api_timeout)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0:
                subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
                return subtitles

        except Exception as e:
            logger.warning(f"获取字幕列表失败: {e}")

        return []

    def _parse_bilibili_subtitle(self, subtitle_data: dict) -> str:
        """
        解析 B站字幕 JSON

        Args:
            subtitle_data: 字幕 JSON 数据

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
        解析字幕文件（支持 VTT、SRT 和 ASS）

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
            # 跳过 WEBVTT 等标签行
            if line.startswith("WEBVTT") or line.startswith("STYLE") or line.startswith("NOTE"):
                continue
            # 去除 HTML 标签
            line = re.sub(r"<[^>]+>", "", line)
            # 去除行内标签
            line = re.sub(r"\{[^}]+\}", "", line)
            # 跳过纯空白行
            if line.strip():
                result_lines.append(line.strip())

        return " ".join(result_lines)

    def _save_subtitle_text(self, bv_id: str, text: str):
        """将提取到的纯文本字幕保存为 .txt 文件，供后续 merge 步骤直接读取"""
        text_file = self.output_dir / f"{bv_id}.txt"
        text_file.write_text(text, encoding="utf-8")
        logger.debug(f"字幕纯文本已保存: {text_file}")
