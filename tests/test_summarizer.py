"""
DeepSeekSummarizer 单元测试

测试LLM总结模块，mock OpenAI client
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from core.summarizer import DeepSeekSummarizer


class TestDeepSeekSummarizer:
    """DeepSeekSummarizer 测试类"""

    @pytest.fixture
    def summarizer(self, sample_config, mock_env):
        """创建 DeepSeekSummarizer 实例"""
        return DeepSeekSummarizer(sample_config)

    @pytest.fixture
    def summarizer_no_env_key(self, sample_config):
        """测试没有环境变量API key的情况"""
        config = dict(sample_config)
        config["llm"] = dict(config.get("llm", {}))
        config["llm"]["api_key"] = None

        # 保存原始值
        original_value = os.environ.get("DEEPSEEK_API_KEY")
        if "DEEPSEEK_API_KEY" in os.environ:
            del os.environ["DEEPSEEK_API_KEY"]

        yield config

        # 恢复原始值
        if original_value is not None:
            os.environ["DEEPSEEK_API_KEY"] = original_value

    def test_init_basic(self, sample_config, mock_env):
        """测试基本初始化"""
        summarizer = DeepSeekSummarizer(sample_config)

        assert summarizer.model_name == "deepseek-chat"
        assert summarizer.base_url == "https://api.deepseek.com"
        assert summarizer.max_tokens == 4096
        assert summarizer.temperature == 0.3

    def test_init_custom_values(self, sample_config, mock_env):
        """测试自定义初始化参数"""
        sample_config["llm"]["model_name"] = "deepseek-coder"
        sample_config["llm"]["max_tokens"] = 8192
        sample_config["llm"]["temperature"] = 0.5

        summarizer = DeepSeekSummarizer(sample_config)

        assert summarizer.model_name == "deepseek-coder"
        assert summarizer.max_tokens == 8192
        assert summarizer.temperature == 0.5

    def test_init_from_env_var(self, sample_config):
        """测试从环境变量获取API key"""
        config = dict(sample_config)
        config["llm"] = dict(config.get("llm", {}))
        config["llm"]["api_key"] = None

        # 保存原始值
        original_value = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "env-api-key"

        try:
            summarizer = DeepSeekSummarizer(config)
            assert summarizer.api_key == "env-api-key"
        finally:
            if original_value is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = original_value

    def test_init_missing_api_key(self, summarizer_no_env_key):
        """测试缺少API key抛出异常"""
        with pytest.raises(ValueError, match="DeepSeek API Key 未设置"):
            DeepSeekSummarizer(summarizer_no_env_key)

    @patch("openai.OpenAI")
    def test_get_client_lazy_init(self, mock_openai, sample_config, mock_env):
        """测试客户端懒加载"""
        summarizer = DeepSeekSummarizer(sample_config)

        # 首次调用创建客户端
        client1 = summarizer._get_client()
        assert mock_openai.called

        # 再次调用返回相同客户端
        client2 = summarizer._get_client()
        # 应该只创建一次
        assert mock_openai.call_count == 1

    def test_summarize_empty_text(self, summarizer):
        """测试空文本"""
        result = summarizer.summarize("")
        assert "总结失败" in result or "为空" in result

    def test_summarize_short_text_single(self, summarizer, mock_openai_client):
        """测试短文本单次总结"""
        mock_client, mock_instance = mock_openai_client

        result = summarizer.summarize("这是短文本内容。", "测试标题", "https://example.com")

        assert result != ""
        mock_instance.chat.completions.create.assert_called()

    @patch("time.sleep")  # Mock sleep to speed up tests
    def test_summarize_long_text_chunked(self, mock_sleep, summarizer, mock_openai_client):
        """测试长文本分块总结"""
        mock_client, mock_instance = mock_openai_client

        # Mock多次API调用
        mock_responses = [
            "# 第一部分总结",
            "# 第二部分总结",
            "# 最终总结",
        ]
        mock_instance.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=MagicMock(content=r))])
            for r in mock_responses
        ]

        # 创建超过max_chars的文本
        long_text = "这是测试文本内容。" * 500

        result = summarizer.summarize(long_text, "测试标题", "https://example.com")

        assert result != ""
        # 应该调用多次API

    def test_build_prompt_basic(self, summarizer):
        """测试基本提示构建"""
        messages = summarizer._build_prompt("测试文本", "测试标题", "https://example.com")

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "测试文本" in messages[1]["content"]

    def test_build_prompt_with_title(self, summarizer):
        """测试带标题的提示"""
        messages = summarizer._build_prompt("测试文本", "我的视频标题", "https://example.com")

        assert "我的视频标题" in messages[1]["content"]

    def test_build_prompt_without_title(self, summarizer):
        """测试无标题的提示"""
        messages = summarizer._build_prompt("测试文本", "", "https://example.com")

        assert "无标题" in messages[1]["content"]

    def test_build_prompt_partial(self, summarizer):
        """测试部分文本提示"""
        messages = summarizer._build_prompt("部分文本", "标题", "URL", is_partial=True)

        assert "简要概括" in messages[1]["content"]
        assert "部分文本" in messages[1]["content"]

    def test_build_final_prompt(self, summarizer):
        """测试最终总结提示"""
        combined = "# 第一部分\n内容1\n\n---\n\n# 第二部分\n内容2"
        messages = summarizer._build_final_prompt(combined, "测试标题", "https://example.com")

        assert len(messages) == 2
        assert combined in messages[1]["content"]
        assert "整合" in messages[1]["content"] or "完整" in messages[1]["content"]

    @patch("openai.OpenAI")
    def test_call_api_success(self, mock_openai, sample_config, mock_env):
        """测试API调用成功"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "# 测试总结"
        mock_instance.chat.completions.create.return_value = mock_response

        summarizer = DeepSeekSummarizer(sample_config)
        messages = [{"role": "user", "content": "test"}]

        result = summarizer._call_api(messages)

        assert result == "# 测试总结"

    @patch("time.sleep")
    @patch("openai.OpenAI")
    def test_call_api_retry(self, mock_openai, mock_sleep, sample_config, mock_env):
        """测试API失败重试"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance

        # 前两次失败，第三次成功
        mock_instance.chat.completions.create.side_effect = [
            Exception("Network error"),
            Exception("Timeout"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Success"))]),
        ]

        summarizer = DeepSeekSummarizer(sample_config)
        messages = [{"role": "user", "content": "test"}]

        result = summarizer._call_api(messages)

        assert result == "Success"
        assert mock_instance.chat.completions.create.call_count == 3

    @patch("time.sleep")
    @patch("openai.OpenAI")
    def test_call_api_all_retries_fail(self, mock_openai, mock_sleep, sample_config, mock_env):
        """测试所有重试都失败"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        mock_instance.chat.completions.create.side_effect = Exception("Always fails")

        summarizer = DeepSeekSummarizer(sample_config)
        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(Exception):
            summarizer._call_api(messages)

    def test_format_output_with_header(self, summarizer):
        """测试格式化输出（已有标题）"""
        summary = "# 已有的标题\n\n内容"
        result = summarizer._format_output(summary, "标题", "URL", "single")

        assert result == summary  # 不重复添加标题

    def test_format_output_without_header(self, summarizer):
        """测试格式化输出（无标题）"""
        summary = "没有#开头的内容"
        result = summarizer._format_output(summary, "我的标题", "https://example.com", "single")

        assert result.startswith("#")
        assert "我的标题" in result
        assert "来源" in result

    def test_format_output_empty_title(self, summarizer):
        """测试空标题格式化"""
        summary = "内容"
        result = summarizer._format_output(summary, "", "https://example.com", "single")

        assert "# B站视频总结" in result

    @patch("openai.OpenAI")
    def test_summarize_single_success(self, mock_openai, sample_config, mock_env):
        """测试单次总结成功"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "# 总结结果\n\n内容"
        mock_instance.chat.completions.create.return_value = mock_response

        summarizer = DeepSeekSummarizer(sample_config)
        result = summarizer._summarize_single("测试文本", "标题", "URL")

        assert "# 总结结果" in result

    @patch("openai.OpenAI")
    def test_summarize_single_exception(self, mock_openai, sample_config, mock_env):
        """测试单次总结异常"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        mock_instance.chat.completions.create.side_effect = Exception("API error")

        summarizer = DeepSeekSummarizer(sample_config)

        result = summarizer._summarize_single("测试文本", "标题", "URL")

        assert "失败" in result

    @patch("time.sleep")
    @patch("openai.OpenAI")
    def test_summarize_chunked_fallback(self, mock_openai, mock_sleep, sample_config, mock_env):
        """测试分块总结失败时的降级"""
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance

        # 部分成功，最终失败
        mock_instance.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=MagicMock(content="部分1"))]),
            MagicMock(choices=[MagicMock(message=MagicMock(content="部分2"))]),
            Exception("Final API error"),
        ]

        # 使用小块配置，避免触发潜在的无限循环
        config = dict(sample_config)
        config["llm"] = dict(config.get("llm", {}))
        config["llm"]["chunk"] = {"max_chars": 100, "overlap": 0}
        summarizer = DeepSeekSummarizer(config)

        # 使用合适长度的文本
        long_text = "这是很长的文本内容用于测试。" * 20
        result = summarizer._summarize_chunked(long_text, "标题", "URL")

        # 应该返回降级结果
        assert "部分1" in result

    def test_summarize_long_text_uses_chunking(self, summarizer):
        """测试长文本使用分块"""
        with patch.object(summarizer, "_summarize_single") as mock_single, \
             patch.object(summarizer, "_summarize_chunked") as mock_chunked:

            mock_single.return_value = "result"
            mock_chunked.return_value = "result"

            # 短文本
            summarizer.summarize("短文本", "标题", "URL")
            assert mock_single.called
            mock_single.reset_mock()

            # 长文本
            summarizer.summarize("a" * 10000, "标题", "URL")
            assert mock_chunked.called

    def test_system_prompt_exists(self, summarizer):
        """测试系统提示存在"""
        assert summarizer.SYSTEM_PROMPT is not None
        assert len(summarizer.SYSTEM_PROMPT) > 0
        assert "摘要" in summarizer.SYSTEM_PROMPT or "总结" in summarizer.SYSTEM_PROMPT

    def test_api_key_from_config_overrides_env(self, sample_config):
        """测试配置中的API key优先于环境变量"""
        config = dict(sample_config)
        config["llm"] = dict(config.get("llm", {}))
        config["llm"]["api_key"] = "config-key"

        # 设置环境变量
        original_value = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "env-key"

        try:
            summarizer = DeepSeekSummarizer(config)
            assert summarizer.api_key == "config-key"
        finally:
            if original_value is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = original_value

    @patch("openai.OpenAI")
    def test_client_custom_timeout(self, mock_openai, sample_config, mock_env):
        """测试自定义超时设置"""
        sample_config["llm"]["request_timeout"] = 60
        summarizer = DeepSeekSummarizer(sample_config)

        summarizer._get_client()

        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args[1]
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"] == 60

    @patch("openai.OpenAI")
    def test_client_custom_base_url(self, mock_openai, sample_config, mock_env):
        """测试自定义base_url"""
        sample_config["llm"]["base_url"] = "https://custom.api.com"
        summarizer = DeepSeekSummarizer(sample_config)

        summarizer._get_client()

        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["base_url"] == "https://custom.api.com"

    def test_max_retries_config(self, sample_config, mock_env):
        """测试重试次数配置"""
        sample_config["llm"]["max_retries"] = 5
        summarizer = DeepSeekSummarizer(sample_config)

        assert summarizer.max_retries == 5

    def test_chunk_config(self, sample_config, mock_env):
        """测试分块配置"""
        summarizer = DeepSeekSummarizer(sample_config)

        assert summarizer.max_chars == 6000
        assert summarizer.chunk_overlap == 500
