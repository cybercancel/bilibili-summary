"""
VideoDownloader 单元测试

测试视频下载模块，mock yt_dlp
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.downloader import VideoDownloader


class TestVideoDownloader:
    """VideoDownloader 测试类"""

    @pytest.fixture
    def downloader(self, sample_config, temp_dir):
        """创建 VideoDownloader 实例"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        return VideoDownloader(sample_config)

    def test_init_basic(self, sample_config, temp_dir):
        """测试基本初始化"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        downloader = VideoDownloader(sample_config)

        assert downloader.output_dir == temp_dir / "videos"
        assert downloader.impersonate == "chrome"
        assert downloader.format_spec == "bestaudio[ext=mp4]/bestaudio"

    def test_init_output_dir_created(self, sample_config, temp_dir):
        """测试输出目录自动创建"""
        output_dir = temp_dir / "new_videos"
        sample_config["download"]["output_dir"] = str(output_dir)

        downloader = VideoDownloader(sample_config)
        assert output_dir.exists()

    def test_init_custom_values(self, sample_config, temp_dir):
        """测试自定义初始化参数"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        sample_config["download"]["impersonate"] = None
        sample_config["download"]["format"] = "bestvideo+bestaudio"
        sample_config["download"]["max_filesize"] = "100M"

        downloader = VideoDownloader(sample_config)

        assert downloader.impersonate is None
        assert downloader.format_spec == "bestvideo+bestaudio"
        assert downloader.max_filesize == "100M"

    def test_extract_bv_id_basic(self, downloader):
        """测试基本BV号提取"""
        urls = [
            ("https://www.bilibili.com/video/BV1xx411c7mD", "BV1xx411c7mD"),
            ("https://b23.tv/abc123", "abc123"),
            ("BV1xx411c7mD", "BV1xx411c7mD"),
        ]

        for url, expected in urls:
            assert downloader._extract_bv_id(url) == expected

    def test_extract_bv_id_case_insensitive(self, downloader):
        """测试BV号大小写处理"""
        assert downloader._extract_bv_id("bv1xx411c7mD") == "bv1xx411c7mD"
        assert downloader._extract_bv_id("BV1XX411C7MD") == "BV1XX411C7MD"

    def test_extract_bv_id_invalid_url(self, downloader):
        """测试无效URL"""
        assert downloader._extract_bv_id("https://example.com") is None
        assert downloader._extract_bv_id("") is None
        assert downloader._extract_bv_id("not-a-bilibili-url") is None

    def test_extract_bv_id_full_url_pattern(self, downloader):
        """测试完整URL模式匹配"""
        url = "https://www.bilibili.com/video/BV1test123456"
        result = downloader._extract_bv_id(url)
        assert result == "BV1test123456"

    def test_download_invalid_url(self, downloader, temp_dir):
        """测试无效URL下载"""
        with pytest.raises(ValueError, match="无法从URL中提取BV号"):
            downloader.download("https://example.com")

    @patch("yt_dlp.YoutubeDL")
    def test_download_success(self, mock_ydl, downloader, temp_dir):
        """测试下载成功"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance

        # Mock返回的视频信息
        video_info = {
            "title": "测试视频",
            "duration": 300,
            "extractor": "bilibili",
        }
        mock_instance.extract_info.return_value = video_info
        mock_instance.prepare_filename.return_value = str(temp_dir / "videos" / "BV1test.mp4")

        # 确保输出目录存在
        (temp_dir / "videos").mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / "videos" / "BV1test.mp4"
        output_path.touch()  # 创建文件模拟下载

        result = downloader.download("https://www.bilibili.com/video/BV1test", output_path)

        assert result["title"] == "测试视频"
        assert result["bv_id"] == "BV1test"
        assert result["duration"] == 300
        assert result["url"] == "https://www.bilibili.com/video/BV1test"

    @patch("yt_dlp.YoutubeDL")
    def test_download_with_custom_output_path(self, mock_ydl, downloader, temp_dir):
        """测试自定义输出路径"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance

        video_info = {
            "title": "Custom Video",
            "duration": 120,
        }
        mock_instance.extract_info.return_value = video_info
        mock_instance.prepare_filename.return_value = str(temp_dir / "custom.mp4")

        output_path = temp_dir / "custom.mp4"
        output_path.touch()

        result = downloader.download("https://www.bilibili.com/video/BV1test", output_path)

        assert result["video_path"] == output_path

    @patch("yt_dlp.YoutubeDL")
    def test_download_yt_dlp_error(self, mock_ydl, downloader, temp_dir):
        """测试yt-dlp下载错误"""
        import yt_dlp

        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = yt_dlp.utils.DownloadError("Download failed")

        output_path = temp_dir / "videos" / "BV1test.mp4"

        with pytest.raises(yt_dlp.utils.DownloadError):
            downloader.download("https://www.bilibili.com/video/BV1test", output_path)

    @patch("yt_dlp.YoutubeDL")
    def test_download_generic_error(self, mock_ydl, downloader, temp_dir):
        """测试通用错误"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = Exception("Unknown error")

        output_path = temp_dir / "videos" / "BV1test.mp4"

        with pytest.raises(Exception):
            downloader.download("https://www.bilibili.com/video/BV1test", output_path)

    def test_build_yt_dlp_opts_basic(self, downloader):
        """测试基本选项构建"""
        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "format" in opts
        assert "outtmpl" in opts
        assert "extractor_args" in opts
        assert opts["quiet"] is False
        assert opts["no_warnings"] is False

    def test_build_yt_dlp_opts_chrome_impersonate(self, downloader):
        """测试Chrome模拟选项"""
        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "http_headers" in opts
        assert "User-Agent" in opts["http_headers"]
        assert "Chrome" in opts["http_headers"]["User-Agent"]

    def test_build_yt_dlp_opts_no_impersonate(self, sample_config, temp_dir):
        """测试不模拟浏览器"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        sample_config["download"]["impersonate"] = None
        downloader = VideoDownloader(sample_config)

        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "http_headers" not in opts

    def test_build_yt_dlp_opts_cookies_browser(self, sample_config, temp_dir):
        """测试从浏览器读取cookies"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        sample_config["download"]["cookies_browser"] = "chrome"
        downloader = VideoDownloader(sample_config)

        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "cookies_from_browser" in opts
        assert opts["cookies_from_browser"] == ("chrome",)

    def test_build_yt_dlp_opts_cookies_file(self, sample_config, temp_dir):
        """测试从文件读取cookies"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        sample_config["download"]["cookies_file"] = "cookies.txt"
        downloader = VideoDownloader(sample_config)

        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "cookiefile" in opts
        assert opts["cookiefile"] == "cookies.txt"

    def test_build_yt_dlp_opts_max_filesize(self, sample_config, temp_dir):
        """测试文件大小限制"""
        sample_config["download"]["output_dir"] = str(temp_dir / "videos")
        sample_config["download"]["max_filesize"] = "500M"
        downloader = VideoDownloader(sample_config)

        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "max_filesize" in opts
        assert opts["max_filesize"] == "500M"

    def test_build_yt_dlp_opts_bilibili_settings(self, downloader):
        """测试B站特定设置"""
        output_path = Path("test.mp4")
        opts = downloader._build_yt_dlp_opts(output_path)

        assert "extractor_args" in opts
        assert "bilibili" in opts["extractor_args"]
        assert opts["extractor_args"]["bilibili"]["embed_dash_manifest"] is False
        assert opts["extractor_args"]["bilibili"]["embed_subtitle"] is False

    @patch("yt_dlp.YoutubeDL")
    def test_get_video_info_success(self, mock_ydl, downloader):
        """测试获取视频信息成功"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance

        video_info = {
            "title": "测试视频",
            "duration": 600,
            "thumbnail": "https://example.com/thumb.jpg",
            "description": "视频描述",
        }
        mock_instance.extract_info.return_value = video_info

        result = downloader.get_video_info("https://www.bilibili.com/video/BV1test")

        assert result["title"] == "测试视频"
        assert result["duration"] == 600
        assert result["thumbnail"] == "https://example.com/thumb.jpg"
        assert result["description"] == "视频描述"

    @patch("yt_dlp.YoutubeDL")
    def test_get_video_info_error(self, mock_ydl, downloader):
        """测试获取视频信息错误"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = Exception("Info extraction failed")

        with pytest.raises(Exception):
            downloader.get_video_info("https://www.bilibili.com/video/BV1test")

    @patch("yt_dlp.YoutubeDL")
    def test_get_video_info_skips_download(self, mock_ydl, downloader):
        """测试get_video_info不下载"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.return_value = {"title": "test", "duration": 100}

        downloader.get_video_info("https://www.bilibili.com/video/BV1test")

        # 验证不会真正下载
        mock_instance.extract_info.assert_called_once()
        call_args = mock_instance.extract_info.call_args
        assert call_args[1].get("download", True) is not True or \
               (len(call_args[0]) >= 1 and call_args[0][1] is False or
                call_args.kwargs.get("download") is False)

    def test_output_dir_format(self, downloader):
        """测试输出目录格式化"""
        assert str(downloader.output_dir).endswith("videos")

    def test_format_spec_from_config(self, downloader):
        """测试格式规范从配置读取"""
        assert downloader.format_spec == "bestaudio[ext=mp4]/bestaudio"

    def test_bv_id_extraction_order(self, downloader):
        """测试BV号提取顺序 - 应该优先匹配分组"""
        # 带分组的URL
        url = "https://www.bilibili.com/video/BV1test123"
        result = downloader._extract_bv_id(url)
        assert result == "BV1test123"

    def test_short_bv_id(self, downloader):
        """测试短BV号"""
        result = downloader._extract_bv_id("BV1a")
        assert result == "BV1a"

    def test_bv_id_with_query_params(self, downloader):
        """测试带查询参数的URL"""
        url = "https://www.bilibili.com/video/BV1test?p=1&spm_id_from=333.788"
        result = downloader._extract_bv_id(url)
        assert result == "BV1test"
