"""
文本分块模块

处理长文本分块，用于LLM总结
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TextChunker:
    """文本分块器"""

    def __init__(self, max_chars: int = 6000, overlap: int = 500):
        """
        初始化分块器

        Args:
            max_chars: 每个块的最大字符数
            overlap: 相邻块之间的重叠字符数
        """
        self.max_chars = max_chars
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        """
        将文本分块

        Args:
            text: 原始文本

        Returns:
            文本块列表
        """
        if not text:
            return []

        if len(text) <= self.max_chars:
            return [text]

        logger.info(f"文本长度 {len(text)} 超过限制 {self.max_chars}，开始分块")

        # 按段落分割
        paragraphs = self._split_by_paragraph(text)
        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para_length = len(para)

            # 如果单个段落就超过限制，继续分割
            if para_length > self.max_chars:
                # 先保存当前chunk
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # 分割长段落
                sub_chunks = self._split_long_paragraph(para)
                chunks.extend(sub_chunks)
                continue

            # 检查是否需要开始新块
            if current_length + para_length + 1 > self.max_chars:
                # 保存当前块
                if current_chunk:
                    chunks.append("\n".join(current_chunk))

                # 开始新块，保留overlap
                if self.overlap > 0 and current_chunk:
                    overlap_text = self._get_overlap_text(current_chunk)
                    current_chunk = [overlap_text, para]
                    current_length = len(overlap_text) + para_length + 1
                else:
                    current_chunk = [para]
                    current_length = para_length
            else:
                current_chunk.append(para)
                current_length += para_length + 1  # +1 for newline

        # 保存最后一个块
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        logger.info(f"文本被分成 {len(chunks)} 个块")
        return chunks

    def _split_by_paragraph(self, text: str) -> list[str]:
        """
        按段落分割文本

        Args:
            text: 原始文本

        Returns:
            段落列表
        """
        # 按换行符分割
        lines = text.split("\n")
        paragraphs = []
        current = []

        for line in lines:
            line = line.strip()
            if not line:
                if current:
                    para = " ".join(current)
                    if para:
                        paragraphs.append(para)
                    current = []
            else:
                current.append(line)

        # 处理最后一段
        if current:
            para = " ".join(current)
            if para:
                paragraphs.append(para)

        return paragraphs if paragraphs else [text]

    def _split_long_paragraph(self, text: str) -> list[str]:
        """
        分割过长的段落

        Args:
            text: 长段落文本

        Returns:
            子块列表
        """
        chunks = []
        start = 0

        while start < len(text):
            end = start + self.max_chars
            if end >= len(text):
                chunks.append(text[start:])
                break

            # 尝试在句子边界分割
            chunk = text[start:end]
            last_period = max(
                chunk.rfind("。"),
                chunk.rfind("."),
                chunk.rfind("！"),
                chunk.rfind("!"),
                chunk.rfind("？"),
                chunk.rfind("?"),
            )

            if last_period > self.max_chars * 0.5:
                chunk = chunk[: last_period + 1]
                end = start + len(chunk)

            chunks.append(chunk)
            start = end - self.overlap if self.overlap > 0 else end

        return chunks

    def _get_overlap_text(self, paragraphs: list[str]) -> str:
        """
        获取重叠文本

        Args:
            paragraphs: 段落列表

        Returns:
            重叠文本
        """
        text = "\n".join(paragraphs)
        if len(text) <= self.overlap:
            return text

        # 从末尾获取overlap长度的文本
        return text[-self.overlap:]
