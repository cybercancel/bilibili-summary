"""
LLM总结模块

使用 DeepSeek API 生成结构化摘要
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DeepSeekSummarizer:
    """DeepSeek API 总结器"""

    SYSTEM_PROMPT = """你是一个专业的视频内容分析助手，负责为B站视频生成高质量的结构化摘要。

请严格按照以下格式生成摘要：

# {标题}

> 来源：{URL}
> 处理时间：{时间戳}
> 文本来源：{来源类型}

## 概述
请用2-3句话概括视频的核心内容和主题。

## 关键要点
请列出视频的主要观点或重要内容，使用项目符号格式：
- 要点1
- 要点2
- ...

## 详细内容
请详细展开视频的具体内容，包括：
- 讲解的主要话题
- 提供的重要信息
- 分析或讨论的关键点
- 演示或展示的重要内容

## 标签
请为视频生成3-5个相关标签，用逗号分隔。

请注意：
1. 使用中文回复
2. 内容要准确反映视频内容
3. 要点要简洁明了
4. 详细内容要全面但不过度冗长
"""

    def __init__(self, config: dict):
        """
        初始化总结器

        Args:
            config: 配置字典
        """
        self.config = config.get("llm", {})
        self.model_name = self.config.get("model_name", "deepseek-chat")
        self.api_key = self.config.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
        self.base_url = self.config.get("base_url", "https://api.deepseek.com")
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.temperature = self.config.get("temperature", 0.3)
        self.request_timeout = self.config.get("request_timeout", 120)
        self.max_retries = self.config.get("max_retries", 3)
        self.chunk_config = self.config.get("chunk", {})
        self.max_chars = self.chunk_config.get("max_chars", 6000)
        self.chunk_overlap = self.chunk_config.get("overlap", 500)

        if not self.api_key:
            raise ValueError("DeepSeek API Key 未设置，请检查配置或设置 DEEPSEEK_API_KEY 环境变量")

        self._client = None

    def _get_client(self):
        """获取 OpenAI 兼容客户端"""
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.request_timeout,
            )
            return self._client
        except ImportError:
            logger.error("openai 库未安装，请运行: pip install openai")
            raise

    def summarize(self, text: str, title: str = "", url: str = "") -> str:
        """
        生成总结

        Args:
            text: 待总结的文本
            title: 视频标题
            url: 视频URL

        Returns:
            格式化的总结文本
        """
        if not text:
            logger.warning("输入文本为空")
            return "# 总结失败\n\n输入文本为空，无法生成总结。"

        logger.info(f"开始生成总结，文本长度: {len(text)} 字符")

        # 检查是否需要分块
        if len(text) <= self.max_chars:
            return self._summarize_single(text, title, url)
        else:
            return self._summarize_chunked(text, title, url)

    def _summarize_single(self, text: str, title: str, url: str) -> str:
        """单次总结"""
        logger.info("单次总结")

        messages = self._build_prompt(text, title, url)

        try:
            response_text = self._call_api(messages)
            return self._format_output(response_text, title, url, "single")
        except Exception as e:
            logger.error(f"总结生成失败: {e}")
            return f"# 总结生成失败\n\n错误: {str(e)}"

    def _summarize_chunked(self, text: str, title: str, url: str) -> str:
        """分块总结"""
        logger.info("文本较长，使用分块总结策略")

        from .chunker import TextChunker

        chunker = TextChunker(self.max_chars, self.chunk_overlap)
        chunks = chunker.chunk(text)

        logger.info(f"文本分成 {len(chunks)} 个块")

        # 总结每个块
        chunk_summaries = []
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"总结第 {i}/{len(chunks)} 个块")
            messages = self._build_prompt(chunk, title, url, is_partial=True)
            try:
                summary = self._call_api(messages)
                chunk_summaries.append(summary)
                time.sleep(1)  # 避免请求过快
            except Exception as e:
                logger.warning(f"第 {i} 块总结失败: {e}")
                chunk_summaries.append(f"[第{i}块总结失败]")

        # 合并各块总结
        combined = "\n\n---\n\n".join(chunk_summaries)

        # 最终总结
        logger.info("生成最终综合总结")
        final_messages = self._build_final_prompt(combined, title, url)

        try:
            final_summary = self._call_api(final_messages)
            return self._format_output(final_summary, title, url, "chunked")
        except Exception as e:
            logger.error(f"最终总结生成失败: {e}")
            # 返回各块总结的合并
            return self._format_output(combined, title, url, "chunked_fallback")

    def _build_prompt(self, text: str, title: str, url: str, is_partial: bool = False) -> list[dict]:
        """
        构建提示

        Args:
            text: 文本内容
            title: 标题
            url: URL
            is_partial: 是否为部分文本

        Returns:
            消息列表
        """
        if is_partial:
            user_content = f"""请为以下视频内容片段生成简要总结。

{"视频标题: " + title if title else ""}
{"视频URL: " + url if url else ""}

内容片段：
{text}

请简要概括这个片段的主要内容（100-200字）。"""
        else:
            user_content = f"""请为以下B站视频内容生成结构化总结。

{"视频标题: " + title if title else "视频标题: 无标题"}
{"视频URL: " + url if url else ""}

视频内容：
{text}"""

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _build_final_prompt(self, combined_summaries: str, title: str, url: str) -> list[dict]:
        """构建最终总结提示"""
        user_content = f"""以下是视频各部分的总结，请整合成一份完整的结构化总结：

{combined_summaries}

{"视频标题: " + title if title else "视频标题: 无标题"}
{"视频URL: " + url if url else ""}

请基于以上各部分总结，生成一份完整的结构化总结，包括概述、关键要点、详细内容和标签。"""

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _call_api(self, messages: list[dict]) -> str:
        """
        调用 API

        Args:
            messages: 消息列表

        Returns:
            API 响应文本
        """
        client = self._get_client()

        for attempt in range(self.max_retries):
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                return response.choices[0].message.content

            except Exception as e:
                wait_time = 2 ** attempt  # 指数退避
                logger.warning(f"API调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise

        raise RuntimeError(f"API调用失败，已重试 {self.max_retries} 次")

    def _format_output(self, summary: str, title: str, url: str, source: str) -> str:
        """
        格式化输出

        Args:
            summary: 总结文本
            title: 标题
            url: URL
            source: 来源类型

        Returns:
            格式化后的文本
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 检查是否已包含标题和元信息
        if not summary.startswith("#"):
            header = f"""# {title or "B站视频总结"}

> 来源：{url or "未知"}
> 处理时间：{timestamp}
> 文本来源：{source}

"""
            return header + summary

        return summary
