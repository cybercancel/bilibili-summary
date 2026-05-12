"""
SubtitleExtractor 单元测试

测试字幕提取模块，mock yt_dlp 和 requests
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.subtitle import SubtitleExtractor


class TestSubtitleExtractor:
    """SubtitleExtractor 测试类"""

    @pytest.fixture
    def extractor(self, sample_config, temp_dir):
        """创建 SubtitleExtractor 实例"""
        sample_config["subtitle"]["output_dir"] = str(temp_dir / "subtitles")
        return SubtitleExtractor(sample_config)

    def test_init_basic(self, sample_config, temp_dir):
        """测试基本初始化"""
        sample_config["subtitle"]["output_dir"] = str(temp_dir / "subtitles")
        extractor = SubtitleExtractor(sample_config)

        assert extractor.output_dir == temp_dir / "subtitles"
        assert extractor.languages == ["ai-zh", "zh-Hans"]
        assert extractor.auto_fallback is True

    def test_init_output_dir_created(self, sample_config, temp_dir):
        """测试输出目录自动创建"""
        output_dir = temp_dir / "new_subtitles"
        sample_config["subtitle"]["output_dir"] = str(output_dir)

        extractor = SubtitleExtractor(sample_config)
        assert output_dir.exists()

    def test_extract_bv_id_from_url(self, extractor):
        """测试从URL提取BV号"""
        urls = [
            ("https://www.bilibili.com/video/BV1xx411c7mD", "BV1xx411c7mD"),
            ("BV1xx411c7mD", "BV1xx411c7mD"),
            ("https://b23.tv/abc123", "abc123"),
        ]

        for url, expected in urls:
            result = extractor._extract_bv_id(url)
            assert result == expected

    def test_extract_bv_id_invalid_url(self, extractor):
        """测试无效URL返回None"""
        result = extractor._extract_bv_id("https://example.com")
        assert result is None

    def test_extract_bv_id_case_insensitive(self, extractor):
        """测试BV号大小写不敏感"""
        assert extractor._extract_bv_id("bv1xx411c7mD") == "bv1xx411c7mD"
        assert extractor._extract_bv_id("BV1XX411C7MD") == "BV1XX411C7MD"

    def test_extract_invalid_url_raises(self, extractor, temp_dir):
        """测试无效URL抛出异常"""
        video_path = temp_dir / "video.mp4"

        with pytest.raises(ValueError, match="无法从URL中提取BV号"):
            extractor.extract("https://example.com", video_path)

    @patch("yt_dlp.YoutubeDL")
    def test_extract_via_ytdlp_success(self, mock_ydl, extractor, temp_dir, sample_subtitle_vtt):
        """测试 yt-dlp 字幕提取成功"""
        # Mock yt-dlp
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance

        # 创建假的字幕文件
        subtitle_file = temp_dir / "subtitles" / "BV1test.ai-zh.vtt"
        subtitle_file.parent.mkdir(parents=True, exist_ok=True)
        subtitle_file.write_text(sample_subtitle_vtt, encoding="utf-8")

        output_path = temp_dir / "subtitles" / "BV1test"

        result = extractor._extract_via_ytdlp("https://www.bilibili.com/video/BV1test", output_path)

        assert result["text"] != ""
        assert result["source"] == "ytdlp"
        assert result["available"] is True

    @patch("yt_dlp.YoutubeDL")
    def test_extract_via_ytdlp_no_subtitle(self, mock_ydl, extractor, temp_dir):
        """测试 yt-dlp 未找到字幕"""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance

        output_path = temp_dir / "subtitles" / "BV1test"

        result = extractor._extract_via_ytdlp("https://www.bilibili.com/video/BV1test", output_path)

        assert result["text"] == ""
        assert result["available"] is False

    @patch("yt_dlp.YoutubeDL")
    def test_extract_via_ytdlp_exception(self, mock_ydl, extractor, temp_dir):
        """测试 yt-dlp 异常"""
        mock_ydl.side_effect = Exception("Network error")

        output_path = temp_dir / "subtitles" / "BV1test"

        result = extractor._extract_via_ytdlp("https://www.bilibili.com/video/BV1test", output_path)

        assert result["text"] == ""
        assert result["available"] is False

    @patch("requests.get")
    def test_extract_via_bilibili_api_success(self, mock_get, extractor, temp_dir, sample_bilibili_subtitle_json):
        """测试 B站API 字幕提取成功"""
        video_path = temp_dir / "video.mp4"

        # Mock API响应
        mock_cid_response = MagicMock()
        mock_cid_response.json.return_value = {
            "code": 0,
            "data": {"cid": "123456"}
        }
        mock_cid_response.raise_for_status = MagicMock()

        mock_subtitle_list_response = MagicMock()
        mock_subtitle_list_response.json.return_value = {
            "code": 0,
            "data": {
                "subtitle": {
                    "subtitles": [
                        {"lan": "ai-zh", "subtitle_url": "//example.com/subtitle.json"}
                    ]
                }
            }
        }
        mock_subtitle_list_response.raise_for_status = MagicMock()

        mock_subtitle_content = MagicMock()
        mock_subtitle_content.json.return_value = sample_bilibili_subtitle_json
        mock_subtitle_content.raise_for_status = MagicMock()

        mock_get.side_effect = [
            mock_cid_response,
            mock_subtitle_list_response,
            mock_subtitle_content,
        ]

        result = extractor._extract_via_bilibili_api("BV1test", video_path, "https://b23.tv/test")

        assert result["text"] != ""
        assert result["source"] == "bilibili_api"
        assert result["available"] is True

    @patch("requests.get")
    def test_extract_via_bilibili_api_no_cid(self, mock_get, extractor, temp_dir):
        """测试 B站API 无法获取CID"""
        video_path = temp_dir / "video.mp4"

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": -1}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # 应该回退到使用cid=0
        result = extractor._extract_via_bilibili_api("BV1test", video_path, "https://b23.tv/test")
        # 最终可能失败因为没有字幕列表
        assert result["source"] == "bilibili_api"

    @patch("requests.get")
    def test_extract_via_bilibili_api_network_error(self, mock_get, extractor, temp_dir):
        """测试 B站API 网络错误"""
        import requests
        mock_get.side_effect = requests.RequestException("Network error")

        video_path = temp_dir / "video.mp4"
        result = extractor._extract_via_bilibili_api("BV1test", video_path, "https://b23.tv/test")

        assert result["available"] is False

    @patch("requests.get")
    def test_get_cid_from_api_success(self, mock_get, extractor):
        """测试从API获取CID成功"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"cid": 123456789}
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = extractor._get_cid_from_api("BV1test")
        assert result == "123456789"

    @patch("requests.get")
    def test_get_cid_from_api_failure(self, mock_get, extractor):
        """测试从API获取CID失败"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": -1}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = extractor._get_cid_from_api("BV1test")
        assert result is None

    @patch("requests.get")
    def test_get_subtitle_list_success(self, mock_get, extractor):
        """测试获取字幕列表成功"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "subtitle": {
                    "subtitles": [
                        {"lan": "zh-Hans", "subtitle_url": "http://example.com"}
                    ]
                }
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = extractor._get_subtitle_list("BV1test", "123456")
        assert len(result) == 1
        assert result[0]["lan"] == "zh-Hans"

    @patch("requests.get")
    def test_get_subtitle_list_failure(self, mock_get, extractor):
        """测试获取字幕列表失败"""
        mock_get.side_effect = Exception("API error")
        result = extractor._get_subtitle_list("BV1test", "123456")
        assert result == []

    def test_parse_bilibili_subtitle(self, extractor, sample_bilibili_subtitle_json):
        """测试解析B站字幕JSON"""
        result = extractor._parse_bilibili_subtitle(sample_bilibili_subtitle_json)
        assert "B站字幕第一句" in result
        assert "B站字幕第二句" in result

    def test_parse_bilibili_subtitle_empty_body(self, extractor):
        """测试解析空body"""
        result = extractor._parse_bilibili_subtitle({"body": []})
        assert result == ""

    def test_parse_bilibili_subtitle_missing_content(self, extractor):
        """测试解析缺少content字段"""
        data = {"body": [{"content": ""}, {"other": "field"}]}
        result = extractor._parse_bilibili_subtitle(data)
        assert result == ""

    def test_parse_subtitle_vtt(self, extractor, temp_dir, sample_subtitle_vtt):
        """测试解析VTT字幕文件"""
        subtitle_file = temp_dir / "test.vtt"
        subtitle_file.write_text(sample_subtitle_vtt, encoding="utf-8")

        result = extractor._parse_subtitle(subtitle_file)
        assert "第一段字幕" in result
        assert "第二段字幕" in result

    def test_parse_subtitle_srt(self, extractor, temp_dir):
        """测试解析SRT字幕文件"""
        srt_content = """1
00:00:00,000 --> 00:00:03,000
这是SRT字幕

2
00:00:03,000 --> 00:00:06,000
这是第二句
"""
        subtitle_file = temp_dir / "test.srt"
        subtitle_file.write_text(srt_content, encoding="utf-8")

        result = extractor._parse_subtitle(subtitle_file)
        assert "SRT字幕" in result

    def test_parse_subtitle_nonexistent(self, extractor, temp_dir):
        """测试解析不存在的文件"""
        subtitle_file = temp_dir / "nonexistent.vtt"
        result = extractor._parse_subtitle(subtitle_file)
        assert result == ""

    def test_strip_subtitle_tags_vtt(self, extractor, sample_subtitle_vtt):
        """测试去除VTT标签"""
        result = extractor._strip_subtitle_tags(sample_subtitle_vtt)
        assert "WEBVTT" not in result
        assert "-->" not in result

    def test_strip_subtitle_tags_html(self, extractor):
        """测试去除HTML标签"""
        content = "<b>加粗</b>和<i>斜体</i>和普通文本"
        result = extractor._strip_subtitle_tags(content)
        assert "<b>" not in result
        assert "<i>" not in result
        assert "加粗" in result
        assert "斜体" in result

    def test_strip_subtitle_tags_inline(self, extractor):
        """测试去除行内标签"""
        content = "{style}文本内容"
        result = extractor._strip_subtitle_tags(content)
        assert "{" not in result
        assert "}" not in result

    def test_strip_subtitle_tags_empty_lines(self, extractor):
        """测试去除空行"""
        content = "文本\n\n\n文本"
        result = extractor._strip_subtitle_tags(content)
        assert "\n\n\n" not in result

    @patch("yt_dlp.YoutubeDL")
    def test_extract_full_flow_ytdlp_success(self, mock_ydl, extractor, temp_dir, sample_subtitle_vtt):
        """测试完整提取流程 - yt-dlp成功"""
        # Mock yt-dlp返回成功
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance

        # 创建字幕文件
        subtitle_file = temp_dir / "subtitles" / "BV1test.ai-zh.vtt"
        subtitle_file.parent.mkdir(parents=True, exist_ok=True)
        subtitle_file.write_text(sample_subtitle_vtt, encoding="utf-8")

        video_path = temp_dir / "video.mp4"
        url = "https://www.bilibili.com/video/BV1test"

        result = extractor.extract(url, video_path)

        assert result["text"] != ""
        assert result["source"] == "ytdlp"
        assert result["available"] is True

    @patch("yt_dlp.YoutubeDL")
    @patch("requests.get")
    def test_extract_full_flow_ytdlp_fails_bilibili_api_success(
        self, mock_get, mock_ydl, extractor, temp_dir, sample_bilibili_subtitle_json
    ):
        """测试完整提取流程 - yt-dlp失败，B站API成功"""
        # Mock yt-dlp失败
        mock_ydl.side_effect = Exception("yt-dlp error")

        # Mock B站API成功
        mock_cid_response = MagicMock()
        mock_cid_response.json.return_value = {"code": 0, "data": {"cid": 123}}
        mock_cid_response.raise_for_status = MagicMock()

        mock_subtitle_list_response = MagicMock()
        mock_subtitle_list_response.json.return_value = {
            "code": 0,
            "data": {
                "subtitle": {
                    "subtitles": [{"lan": "zh-Hans", "subtitle_url": "//example.com/sub.json"}]
                }
            }
        }
        mock_subtitle_list_response.raise_for_status = MagicMock()

        mock_subtitle_content = MagicMock()
        mock_subtitle_content.json.return_value = sample_bilibili_subtitle_json
        mock_subtitle_content.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_cid_response, mock_subtitle_list_response, mock_subtitle_content]

        video_path = temp_dir / "video.mp4"
        url = "https://www.bilibili.com/video/BV1test"

        result = extractor.extract(url, video_path)

        assert result["text"] != ""
        assert result["source"] == "bilibili_api"

    @patch("yt_dlp.YoutubeDL")
    @patch("requests.get")
    def test_extract_full_flow_all_fail_auto_fallback(
        self, mock_get, mock_ydl, extractor, temp_dir
    ):
        """测试完整提取流程 - 全部失败，启用自动降级"""
        mock_ydl.side_effect = Exception("yt-dlp error")
        mock_get.side_effect = Exception("API error")

        video_path = temp_dir / "video.mp4"
        url = "https://www.bilibili.com/video/BV1test"

        result = extractor.extract(url, video_path)

        assert result["text"] == ""
        assert result["source"] == "fallback_whisper"
        assert result["available"] is False

    @patch("yt_dlp.YoutubeDL")
    @patch("requests.get")
    def test_extract_full_flow_all_fail_no_fallback(
        self, mock_get, mock_ydl, sample_config, temp_dir
    ):
        """测试完整提取流程 - 全部失败，禁用自动降级"""
        sample_config["subtitle"]["auto_fallback"] = False
        sample_config["subtitle"]["output_dir"] = str(temp_dir / "subtitles")
        extractor = SubtitleExtractor(sample_config)

        mock_ydl.side_effect = Exception("yt-dlp error")
        mock_get.side_effect = Exception("API error")

        video_path = temp_dir / "video.mp4"
        url = "https://www.bilibili.com/video/BV1test"

        result = extractor.extract(url, video_path)

        assert result["text"] == ""
        assert result["source"] == "none"
        assert result["available"] is False

    def test_bilibili_api_disabled(self, sample_config, temp_dir):
        """测试B站API被禁用"""
        sample_config["subtitle"]["bilibili_api"]["enabled"] = False
        sample_config["subtitle"]["output_dir"] = str(temp_dir / "subtitles")
        extractor = SubtitleExtractor(sample_config)

        assert extractor.bilibili_api_enabled is False

    def test_extract_cid_via_yt_dlp(self, extractor, sample_video_url):
        """测试通过yt-dlp获取CID"""
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info.return_value = {
                "formats": [{"display_id": "12345", "cn": True}]
            }
            mock_ydl.return_value.__enter__.return_value = mock_instance

            video_path = Path("test.mp4")
            result = extractor._extract_cid(video_path, sample_video_url)

            assert result == "12345"

    def test_extract_cid_fallback_to_first_format(self, extractor, sample_video_url):
        """测试CID获取回退到第一个格式"""
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info.return_value = {
                "formats": [{"display_id": "67890"}]  # 没有cn标记
            }
            mock_ydl.return_value.__enter__.return_value = mock_instance

            video_path = Path("test.mp4")
            result = extractor._extract_cid(video_path, sample_video_url)

            assert result == "67890"

    def test_extract_cid_exception(self, extractor, sample_video_url):
        """测试CID获取异常"""
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl.side_effect = Exception("Error")
            video_path = Path("test.mp4")

            result = extractor._extract_cid(video_path, sample_video_url)
            assert result is None
