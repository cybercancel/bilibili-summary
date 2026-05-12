"""
语音转录模块

使用 faster-whisper 进行语音识别，支持 GPU 加速
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Transcriber:
    """语音转录器，使用 faster-whisper"""

    def __init__(self, config: dict):
        """
        初始化转录器

        Args:
            config: 配置字典
        """
        self.config = config.get("transcribe", {})
        self.output_dir = Path(self.config.get("output_dir", "transcripts"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model_name = self.config.get("model", "base")
        self.device = self.config.get("device", "auto")
        self.language = self.config.get("language", "zh")
        self.compute_type = self.config.get("compute_type", "float16")
        self._model = None

    def _load_model(self):
        """懒加载模型"""
        if self._model is not None:
            return self._model

        logger.info(f"加载 Whisper 模型: {self.model_name}")

        try:
            from faster_whisper import WhisperModel

            # 确定设备
            if self.device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    logger.info("torch 未安装，默认使用 CPU")
                    device = "cpu"
            else:
                device = self.device

            # 确定计算类型
            if device == "cpu":
                compute_type = "int8"
            else:
                compute_type = self.compute_type

            logger.info(f"使用设备: {device}, 计算类型: {compute_type}")

            self._model = WhisperModel(
                self.model_name,
                device=device,
                compute_type=compute_type,
            )

            logger.info("模型加载完成")
            return self._model

        except ImportError:
            logger.error("faster-whisper 未安装，请运行: pip install faster-whisper")
            raise
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            raise

    def _release_model(self):
        """释放模型显存"""
        if self._model is not None:
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            logger.info("模型已释放")

    def transcribe(self, audio_path: Path, output_path: Optional[Path] = None) -> dict:
        """
        转录音频

        Args:
            audio_path: 音频文件路径
            output_path: 输出路径（可选）

        Returns:
            包含 text, language, duration 的字典
        """
        if output_path is None:
            output_path = self.output_dir / f"{audio_path.stem}_transcript.txt"

        # 确保音频文件存在
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        logger.info(f"开始转录: {audio_path}")
        logger.info(f"使用模型: {self.model_name}")

        try:
            model = self._load_model()

            # 执行转录
            segments, info = model.transcribe(
                str(audio_path),
                language=self.language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            # 收集结果
            all_segments = []
            full_text = []

            for segment in segments:
                text = segment.text.strip()
                start = segment.start
                end = segment.end
                all_segments.append({
                    "start": start,
                    "end": end,
                    "text": text,
                })
                full_text.append(text)

            result_text = " ".join(full_text)

            # 保存转录结果
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result_text, encoding="utf-8")

            result = {
                "text": result_text,
                "language": info.language,
                "duration": info.duration,
                "file": output_path,
                "segments": all_segments,
            }

            logger.info(f"转录完成，文本长度: {len(result_text)} 字符")
            logger.info(f"转录结果已保存: {output_path}")

            return result

        except Exception as e:
            logger.error(f"转录失败: {e}")
            raise

    def _extract_audio(self, video_path: Path, output_path: Optional[Path] = None) -> Path:
        """
        从视频提取音频

        Args:
            video_path: 视频文件路径
            output_path: 输出路径（可选）

        Returns:
            音频文件路径
        """
        if output_path is None:
            output_path = video_path.with_suffix(".wav")

        logger.info(f"从视频提取音频: {video_path}")

        # 使用 FFmpeg 提取音频
        cmd = [
            "ffmpeg",
            "-y",  # 覆盖输出
            "-i", str(video_path),
            "-vn",  # 不要视频
            "-acodec", "pcm_s16le",  # PCM格式
            "-ar", "16000",  # 16kHz采样率
            "-ac", "1",  # 单声道
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10分钟超时
            )

            if result.returncode != 0:
                logger.error(f"FFmpeg 错误: {result.stderr}")
                raise RuntimeError(f"音频提取失败: {result.stderr}")

            logger.info(f"音频提取完成: {output_path}")
            return output_path

        except subprocess.TimeoutExpired:
            raise RuntimeError("音频提取超时")
        except FileNotFoundError:
            raise RuntimeError("FFmpeg 未找到，请确保已安装 FFmpeg")

    def transcribe_from_video(self, video_path: Path, output_path: Optional[Path] = None) -> dict:
        """
        从视频直接转录（自动提取音频）

        Args:
            video_path: 视频文件路径
            output_path: 输出路径（可选）

        Returns:
            包含 text, language, duration 的字典
        """
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        # 创建临时音频文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_audio = Path(tmp.name)

        try:
            self._extract_audio(video_path, tmp_audio)
            result = self.transcribe(tmp_audio, output_path)
            return result
        finally:
            # 清理临时文件
            if tmp_audio.exists():
                tmp_audio.unlink()

    def __del__(self):
        """析构时释放模型"""
        self._release_model()
