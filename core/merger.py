"""
文本合并去重模块

合并字幕文本和Whisper转录文本，进行去重和智能分段
"""

import difflib
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TextMerger:
    """文本合并器"""

    def __init__(self, config: dict):
        """
        初始化合并器

        Args:
            config: 配置字典
        """
        self.config = config.get("merge", {})
        self.output_dir = Path(self.config.get("output_dir", "merged"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.min_segment_length = self.config.get("min_segment_length", 10)
        self.dedup_threshold = self.config.get("dedup_threshold", 0.8)

    def merge(self, subtitle_text: str, whisper_text: str, output_path: Optional[Path] = None) -> dict:
        """
        合并文本

        合并策略：
        1. 仅有字幕 -> 直接返回字幕
        2. 仅有转录 -> 直接返回转录
        3. 两者都有 -> 字幕优先，转录补缺

        Args:
            subtitle_text: 字幕文本
            whisper_text: Whisper转录文本
            output_path: 输出路径（可选）

        Returns:
            包含 text, source, file 的字典
        """
        logger.info("开始合并文本")
        logger.info(f"字幕文本长度: {len(subtitle_text) if subtitle_text else 0} 字符")
        logger.info(f"转录文本长度: {len(whisper_text) if whisper_text else 0} 字符")

        # 决策：使用哪个文本源
        if subtitle_text and whisper_text:
            # 两者都有 - 字幕优先
            result_text = subtitle_text
            source = "merged"
            logger.info("两者都有，使用字幕优先策略")
        elif subtitle_text:
            result_text = subtitle_text
            source = "subtitle"
            logger.info("仅有字幕文本")
        elif whisper_text:
            result_text = whisper_text
            source = "whisper"
            logger.info("仅有转录文本")
        else:
            result_text = ""
            source = "none"
            logger.warning("两个文本源都为空")

        # 去重处理
        if result_text:
            original_length = len(result_text)
            result_text = self._deduplicate(result_text)
            new_length = len(result_text)
            logger.info(f"去重: {original_length} -> {new_length} 字符")

        # 保存结果
        if output_path is None and source != "none":
            bv_id = "merged_text"
            output_path = self.output_dir / f"{bv_id}.txt"

        result_file = None
        if output_path and result_text:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result_text, encoding="utf-8")
            logger.info(f"合并结果已保存: {output_path}")
            result_file = str(output_path)
        elif source == "none":
            logger.error("字幕和转录文本均为空，无法生成总结")
            raise ValueError("字幕和转录文本均为空，无法继续处理。请确保视频有字幕，或安装 FFmpeg 后使用 Whisper 转录。")

        return {
            "text": result_text,
            "source": source,
            "file": result_file,
        }

    def _deduplicate(self, text: str) -> str:
        """
        文本去重

        使用相似度匹配去除重复段落

        Args:
            text: 原始文本

        Returns:
            去重后的文本
        """
        # 按句子分割
        sentences = self._split_sentences(text)
        if not sentences:
            return text

        # 去重
        unique_sentences = []
        for sentence in sentences:
            is_duplicate = False
            for existing in unique_sentences:
                similarity = difflib.SequenceMatcher(
                    None, sentence, existing
                ).ratio()
                if similarity >= self.dedup_threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_sentences.append(sentence)

        return " ".join(unique_sentences)

    def _split_sentences(self, text: str) -> list[str]:
        """
        按句子分割文本

        Args:
            text: 原始文本

        Returns:
            句子列表
        """
        # 按常见分隔符分割
        # 包括：句号、问号、感叹号、中文句号等
        import re
        pattern = r'[。！？\.!\?]+'
        sentences = re.split(pattern, text)

        # 过滤空句子和过短的句子
        return [s.strip() for s in sentences if len(s.strip()) >= self.min_segment_length]

    def _segment(self, text: str) -> list[str]:
        """
        智能分段

        按段落和语义进行分段

        Args:
            text: 原始文本

        Returns:
            段落列表
        """
        # 按换行分段
        paragraphs = text.split("\n")

        # 合并短段落
        merged_paragraphs = []
        current = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                if current:
                    merged_paragraphs.append(" ".join(current))
                    current = []
                continue

            current.append(para)

            # 如果当前段落足够长，就单独成段
            if len(" ".join(current)) > 500:
                merged_paragraphs.append(" ".join(current))
                current = []

        # 处理最后一段
        if current:
            merged_paragraphs.append(" ".join(current))

        return merged_paragraphs

    def merge_with_timestamps(self, subtitle_data: list, whisper_segments: list) -> str:
        """
        合并带时间戳的字幕和Whisper结果

        Args:
            subtitle_data: 字幕数据列表 [{start, end, text}]
            whisper_segments: Whisper段落列表 [{start, end, text}]

        Returns:
            合并后的文本
        """
        # 如果有字幕时间戳数据，优先使用
        if subtitle_data:
            texts = [item.get("text", "") for item in subtitle_data if item.get("text")]
            return " ".join(texts)

        # 否则使用Whisper结果
        if whisper_segments:
            texts = [seg.get("text", "") for seg in whisper_segments if seg.get("text")]
            return " ".join(texts)

        return ""
