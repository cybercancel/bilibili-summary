"""
Transcriber 单元测试

测试语音转录模块，mock faster_whisper 和 torch
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys


class TestTranscriber:
    """Transcriber 测试类"""

    @pytest.fixture
    def transcriber(self, sample_config, temp_dir):
        """创建 Transcriber 实例"""
        sample_config["transcribe"]["output_dir"] = str(temp_dir / "transcripts")
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(),
            "torch": MagicMock(),
            "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            return Transcriber(sample_config)

    def _setup_mock_modules(self):
        """预注入 mock 模块到 sys.modules"""
        mock_fw = MagicMock()
        mock_torch = MagicMock()
        mock_torch.cuda = MagicMock()
        mock_torch.cuda.is_available = MagicMock(return_value=False)
        mock_torch.cuda.empty_cache = MagicMock()
        sys.modules["faster_whisper"] = mock_fw
        sys.modules["torch"] = mock_torch
        sys.modules["torch.cuda"] = mock_torch.cuda
        return mock_fw, mock_torch, mock_torch.cuda

    def test_init_basic(self, sample_config, temp_dir):
        """测试基本初始化"""
        sample_config["transcribe"]["output_dir"] = str(temp_dir / "transcripts")
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(), "torch": MagicMock(), "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            transcriber = Transcriber(sample_config)
        assert transcriber.model_name == "base"
        assert transcriber.device == "cpu"
        assert transcriber.language == "zh"

    def test_init_output_dir_created(self, sample_config, temp_dir):
        """测试输出目录自动创建"""
        output_dir = temp_dir / "new_transcripts"
        sample_config["transcribe"]["output_dir"] = str(output_dir)
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(), "torch": MagicMock(), "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            Transcriber(sample_config)
        assert output_dir.exists()

    def test_init_custom_values(self, sample_config, temp_dir):
        """测试自定义初始化参数"""
        sample_config["transcribe"]["output_dir"] = str(temp_dir / "transcripts")
        sample_config["transcribe"]["model"] = "medium"
        sample_config["transcribe"]["device"] = "cuda"
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(), "torch": MagicMock(), "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            t = Transcriber(sample_config)
        assert t.model_name == "medium"
        assert t.device == "cuda"

    def test_load_model_cpu(self, transcriber):
        """测试CPU模式加载模型"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        result = transcriber._load_model()
        assert result == mock_instance
        mock_fw.WhisperModel.assert_called_once()

    def test_load_model_cuda(self, sample_config, temp_dir):
        """测试CUDA模式加载模型"""
        sample_config["transcribe"]["output_dir"] = str(temp_dir / "transcripts")
        sample_config["transcribe"]["device"] = "cuda"
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(), "torch": MagicMock(), "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            import faster_whisper, torch.cuda
            t = Transcriber(sample_config)
            torch.cuda.is_available = MagicMock(return_value=True)
            mock_instance = MagicMock()
            faster_whisper.WhisperModel = MagicMock(return_value=mock_instance)
            t._load_model()
            call_kwargs = faster_whisper.WhisperModel.call_args[1]
            assert call_kwargs["device"] == "cuda"

    def test_load_model_auto_device(self, sample_config, temp_dir):
        """测试自动设备选择"""
        sample_config["transcribe"]["device"] = "auto"
        sample_config["transcribe"]["output_dir"] = str(temp_dir / "transcripts")
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(), "torch": MagicMock(), "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            import faster_whisper, torch.cuda
            t = Transcriber(sample_config)
            torch.cuda.is_available = MagicMock(return_value=True)
            faster_whisper.WhisperModel = MagicMock(return_value=MagicMock())
            t._load_model()
            call_kwargs = faster_whisper.WhisperModel.call_args[1]
            assert call_kwargs["device"] == "cuda"

    def test_load_model_lazy_loading(self, transcriber):
        """测试模型懒加载"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        r1 = transcriber._load_model()
        r2 = transcriber._load_model()
        assert r1 == r2
        mock_fw.WhisperModel.assert_called_once()

    def test_load_model_import_error(self, transcriber):
        """测试模块未安装错误"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_fw.WhisperModel = MagicMock(side_effect=ImportError("not installed"))
        with pytest.raises(ImportError):
            transcriber._load_model()

    def test_load_model_generic_error(self, transcriber):
        """测试模型加载通用错误"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_fw.WhisperModel = MagicMock(side_effect=Exception("failed"))
        with pytest.raises(Exception):
            transcriber._load_model()

    def test_release_model(self, sample_config, temp_dir):
        """测试释放模型"""
        sample_config["transcribe"]["output_dir"] = str(temp_dir / "transcripts")
        sample_config["transcribe"]["device"] = "cuda"
        with patch.dict("sys.modules", {
            "faster_whisper": MagicMock(), "torch": MagicMock(), "torch.cuda": MagicMock(),
        }):
            from core.transcriber import Transcriber
            import faster_whisper, torch.cuda
            t = Transcriber(sample_config)
            torch.cuda.is_available = MagicMock(return_value=True)
            torch.cuda.empty_cache = MagicMock()
            faster_whisper.WhisperModel = MagicMock(return_value=MagicMock())
            t._load_model()
            t._release_model()
            assert t._model is None

    def test_transcribe_file_not_found(self, transcriber, temp_dir):
        """测试音频文件不存在"""
        with pytest.raises(FileNotFoundError):
            transcriber.transcribe(temp_dir / "nonexistent.wav")

    def test_transcribe_success(self, transcriber, temp_dir):
        """测试转录成功"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_segments = [MagicMock(text="第一段。", start=0.0, end=3.0)]
        mock_info = MagicMock(language="zh", duration=3.0)
        mock_instance.transcribe.return_value = (mock_segments, mock_info)
        audio = temp_dir / "test.wav"
        audio.touch()
        output = temp_dir / "transcript.txt"
        result = transcriber.transcribe(audio, output)
        assert "第一段。" in result["text"]
        assert result["language"] == "zh"

    def test_transcribe_default_output_path(self, transcriber, temp_dir):
        """测试默认输出路径"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_instance.transcribe.return_value = ([MagicMock(text="x", start=0, end=1)], MagicMock(language="zh", duration=1))
        audio = temp_dir / "my_audio.wav"
        audio.touch()
        result = transcriber.transcribe(audio)
        assert result["file"] == temp_dir / "transcripts" / "my_audio_transcript.txt"

    def test_transcribe_segments_structure(self, transcriber, temp_dir):
        """测试段落结构"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_segments = [MagicMock(text="第一段。", start=0.0, end=2.0), MagicMock(text="第二段。", start=2.0, end=4.0)]
        mock_instance.transcribe.return_value = (mock_segments, MagicMock(language="zh", duration=4.0))
        audio = temp_dir / "test.wav"
        audio.touch()
        result = transcriber.transcribe(audio)
        assert len(result["segments"]) == 2

    def test_transcribe_error(self, transcriber, temp_dir):
        """测试转录错误"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_instance.transcribe.side_effect = Exception("fail")
        audio = temp_dir / "test.wav"
        audio.touch()
        with pytest.raises(Exception):
            transcriber.transcribe(audio)

    @patch("subprocess.run")
    def test_extract_audio_success(self, mock_run, transcriber, temp_dir):
        """测试音频提取成功"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        video = temp_dir / "test.mp4"
        video.touch()
        result = transcriber._extract_audio(video, temp_dir / "test.wav")
        assert result == temp_dir / "test.wav"

    @patch("subprocess.run")
    def test_extract_audio_ffmpeg_error(self, mock_run, transcriber, temp_dir):
        """测试FFmpeg错误"""
        mock_run.return_value = MagicMock(returncode=1, stderr="err")
        video = temp_dir / "test.mp4"
        video.touch()
        with pytest.raises(RuntimeError, match="音频提取失败"):
            transcriber._extract_audio(video, temp_dir / "test.wav")

    @patch("subprocess.run")
    def test_extract_audio_timeout(self, mock_run, transcriber, temp_dir):
        """测试音频提取超时"""
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("ffmpeg", 600)
        video = temp_dir / "test.mp4"
        video.touch()
        with pytest.raises(RuntimeError, match="音频提取超时"):
            transcriber._extract_audio(video)

    def test_extract_audio_ffmpeg_not_found(self, transcriber, temp_dir):
        """测试FFmpeg未找到"""
        import subprocess
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("not found")):
            video = temp_dir / "test.mp4"
            video.touch()
            with pytest.raises(RuntimeError, match="FFmpeg 未找到"):
                transcriber._extract_audio(video)

    def test_transcribe_from_video_file_not_found(self, transcriber, temp_dir):
        """测试从视频转录 - 文件不存在"""
        with pytest.raises(FileNotFoundError):
            transcriber.transcribe_from_video(temp_dir / "no.mp4")

    def test_transcribe_no_segments(self, transcriber, temp_dir):
        """测试转录无段落结果"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_instance.transcribe.return_value = ([], MagicMock(language="zh", duration=0))
        audio = temp_dir / "empty.wav"
        audio.touch()
        result = transcriber.transcribe(audio)
        assert result["text"] == ""

    def test_transcribe_creates_parent_dirs(self, transcriber, temp_dir):
        """测试转录创建父目录"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_instance.transcribe.return_value = ([MagicMock(text="x")], MagicMock(language="zh", duration=1))
        audio = temp_dir / "audio.wav"
        audio.touch()
        output = temp_dir / "sub" / "out.txt"
        transcriber.transcribe(audio, output)
        assert output.exists()

    def test_transcribe_vad_filter(self, transcriber, temp_dir):
        """测试VAD过滤器参数"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_instance.transcribe.return_value = ([MagicMock(text="x")], MagicMock(language="zh", duration=1))
        audio = temp_dir / "test.wav"
        audio.touch()
        transcriber.transcribe(audio)
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["vad_filter"] is True

    def test_transcribe_beam_size(self, transcriber, temp_dir):
        """测试beam_size参数"""
        mock_fw, _, _ = self._setup_mock_modules()
        mock_instance = MagicMock()
        mock_fw.WhisperModel = MagicMock(return_value=mock_instance)
        mock_instance.transcribe.return_value = ([MagicMock(text="x")], MagicMock(language="zh", duration=1))
        audio = temp_dir / "test.wav"
        audio.touch()
        transcriber.transcribe(audio)
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["beam_size"] == 5
