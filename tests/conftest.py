"""
pytest 共享 fixtures
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_env():
    """设置测试环境变量"""
    original_value = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = "test-api-key-12345"
    yield
    if original_value is None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    else:
        os.environ["DEEPSEEK_API_KEY"] = original_value


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config():
    """示例配置字典"""
    return {
        "download": {
            "output_dir": "videos",
            "format": "bestaudio[ext=mp4]/bestaudio",
            "impersonate": "chrome",
        },
        "subtitle": {
            "output_dir": "subtitles",
            "languages": ["ai-zh", "zh-Hans"],
            "auto_fallback": True,
            "bilibili_api": {
                "enabled": True,
                "timeout": 30,
            },
        },
        "transcribe": {
            "output_dir": "transcripts",
            "model": "base",
            "device": "cpu",
            "language": "zh",
            "compute_type": "int8",
        },
        "merge": {
            "output_dir": "merged",
            "min_segment_length": 10,
            "dedup_threshold": 0.8,
        },
        "llm": {
            "model_name": "deepseek-chat",
            "api_key": "test-api-key",
            "base_url": "https://api.deepseek.com",
            "max_tokens": 4096,
            "temperature": 0.3,
            "request_timeout": 120,
            "max_retries": 3,
            "chunk": {
                "max_chars": 6000,
                "overlap": 500,
            },
        },
        "output": {
            "summary_dir": "summaries",
            "log_dir": "logs",
            "format": "markdown",
        },
        "notify": {
            "enabled": True,
            "webhook_url": "https://example.com/webhook",
            "webhook_method": "POST",
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "sender": "test@example.com",
                "password": "test-password",
                "recipients": ["user@example.com"],
            },
        },
        "resume": {
            "enabled": True,
            "status_dir": "summaries",
        },
        "verbose": False,
    }


@pytest.fixture
def sample_config_disabled_notify(sample_config):
    """禁用通知的配置"""
    config = dict(sample_config)
    config["notify"] = dict(config.get("notify", {}))
    config["notify"]["enabled"] = False
    return config


@pytest.fixture
def mock_yt_dlp():
    """Mock yt_dlp 模块"""
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        yield mock_ydl, mock_instance


@pytest.fixture
def mock_requests():
    """Mock requests 模块"""
    with patch("requests.get") as mock_get, \
         patch("requests.post") as mock_post:
        yield mock_get, mock_post


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client"""
    with patch("openai.OpenAI") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance

        # Mock chat.completions.create
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "# 测试总结\n\n这是测试总结内容。"
        mock_instance.chat.completions.create.return_value = mock_response

        yield mock_client, mock_instance


@pytest.fixture
def mock_faster_whisper():
    """Mock faster_whisper 模块"""
    with patch("faster_whisper.WhisperModel") as mock_model:
        mock_instance = MagicMock()
        mock_model.return_value = mock_instance

        # Mock transcribe result
        mock_segments = [
            MagicMock(text="这是第一段话。", start=0.0, end=3.0),
            MagicMock(text="这是第二段话。", start=3.0, end=6.0),
            MagicMock(text="这是第三段话。", start=6.0, end=9.0),
        ]
        mock_info = MagicMock()
        mock_info.language = "zh"
        mock_info.duration = 9.0

        mock_instance.transcribe.return_value = (mock_segments, mock_info)
        yield mock_model, mock_instance


@pytest.fixture
def mock_smtplib():
    """Mock smtplib 模块"""
    with patch("smtplib.SMTP") as mock_smtp:
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance
        yield mock_smtp, mock_instance


@pytest.fixture
def sample_subtitle_vtt():
    """示例 VTT 字幕内容"""
    return """WEBVTT

00:00:00.000 --> 00:00:03.000
这是第一段字幕

00:00:03.000 --> 00:00:06.000
这是第二段字幕

00:00:06.000 --> 00:00:09.000
这是第三段字幕
"""


@pytest.fixture
def sample_bilibili_subtitle_json():
    """示例B站字幕JSON"""
    return {
        "body": [
            {"content": "这是B站字幕第一句"},
            {"content": "这是B站字幕第二句"},
            {"content": "这是B站字幕第三句"},
        ]
    }


@pytest.fixture
def sample_video_url():
    """示例视频URL"""
    return "https://www.bilibili.com/video/BV1xx411c7mD"
