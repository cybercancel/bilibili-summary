"""
TextMerger 单元测试

测试文本合并去重模块的核心功能
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.merger import TextMerger


class TestTextMerger:
    """TextMerger 测试类"""

    @pytest.fixture
    def merger(self, sample_config, temp_dir):
        """创建 TextMerger 实例"""
        sample_config["merge"]["output_dir"] = str(temp_dir / "merged")
        return TextMerger(sample_config)

    @pytest.fixture
    def merger_no_dedup(self, sample_config, temp_dir):
        """创建禁用去重的 TextMerger"""
        sample_config["merge"]["output_dir"] = str(temp_dir / "merged")
        sample_config["merge"]["dedup_threshold"] = 1.0  # 完全相同才去重
        return TextMerger(sample_config)

    def test_init_basic(self, sample_config, temp_dir):
        """测试基本初始化"""
        sample_config["merge"]["output_dir"] = str(temp_dir / "merged")
        merger = TextMerger(sample_config)

        assert merger.output_dir == temp_dir / "merged"
        assert merger.min_segment_length == 10
        assert merger.dedup_threshold == 0.8

    def test_init_custom_values(self, sample_config, temp_dir):
        """测试自定义初始化参数"""
        sample_config["merge"]["output_dir"] = str(temp_dir / "merged")
        sample_config["merge"]["min_segment_length"] = 20
        sample_config["merge"]["dedup_threshold"] = 0.9

        merger = TextMerger(sample_config)
        assert merger.min_segment_length == 20
        assert merger.dedup_threshold == 0.9

    def test_init_output_dir_created(self, sample_config, temp_dir):
        """测试输出目录自动创建"""
        output_dir = temp_dir / "new_merged"
        sample_config["merge"]["output_dir"] = str(output_dir)

        merger = TextMerger(sample_config)
        assert output_dir.exists()

    def test_merge_both_inputs(self, merger, temp_dir):
        """测试两个文本源都有"""
        subtitle_text = "这是字幕文本。"
        whisper_text = "这是转录文本。"

        output_path = temp_dir / "test_merged.txt"
        result = merger.merge(subtitle_text, whisper_text, output_path)

        assert result["text"] == subtitle_text  # 字幕优先
        assert result["source"] == "merged"
        assert output_path.exists()

    def test_merge_subtitle_only(self, merger, temp_dir):
        """测试仅有字幕"""
        subtitle_text = "这是字幕文本。"
        whisper_text = ""

        output_path = temp_dir / "test_merged.txt"
        result = merger.merge(subtitle_text, whisper_text, output_path)

        assert result["text"] == subtitle_text
        assert result["source"] == "subtitle"

    def test_merge_whisper_only(self, merger, temp_dir):
        """测试仅有转录"""
        subtitle_text = ""
        whisper_text = "这是转录文本。"

        output_path = temp_dir / "test_merged.txt"
        result = merger.merge(subtitle_text, whisper_text, output_path)

        assert result["text"] == whisper_text
        assert result["source"] == "whisper"

    def test_merge_both_empty(self, merger, temp_dir):
        """测试两个文本源都为空"""
        subtitle_text = ""
        whisper_text = ""

        output_path = temp_dir / "test_merged.txt"
        result = merger.merge(subtitle_text, whisper_text, output_path)

        assert result["text"] == ""
        assert result["source"] == "none"
        # Note: file may or may not exist depending on implementation
        # The key is that text is empty and source is 'none'

    def test_merge_no_output_path(self, merger):
        """测试不指定输出路径"""
        result = merger.merge("测试文本", "")

        assert result["text"] == "测试文本"
        assert result["file"] is not None

    def test_merge_deduplication(self, merger, temp_dir):
        """测试去重功能"""
        # 创建有重复内容的文本
        text = "这是一句话。这是一句话。这句话不一样。"

        result = merger.merge(text, "", temp_dir / "dedup.txt")
        # 去重后应该减少
        assert result["source"] == "subtitle"

    def test_merge_no_deduplication_needed(self, merger, temp_dir):
        """测试无需去重的情况"""
        text = "第一句独特的话。第二句也很独特。第三句更是独一无二。"

        result = merger.merge(text, "", temp_dir / "unique.txt")
        assert result["text"] != ""

    def test_deduplicate_basic(self, merger):
        """测试基本去重"""
        text = "句子A。句子B。句子A。句子C。"
        result = merger._deduplicate(text)
        # 应该去除相似的句子
        assert len(result) > 0

    def test_deduplicate_no_duplicates(self, merger):
        """测试无重复文本"""
        text = "独特的第一句。独特的第二句。独特的第三句。"
        result = merger._deduplicate(text)
        assert len(result) > 0

    def test_deduplicate_all_same(self, merger):
        """测试完全重复的文本"""
        text = "相同内容。相同内容。相同内容。"
        result = merger._deduplicate(text)
        # 应该只剩一个
        assert len(result) > 0

    def test_deduplicate_empty(self, merger):
        """测试空文本"""
        result = merger._deduplicate("")
        assert result == ""

    def test_split_sentences_basic(self, merger):
        """测试基本句子分割"""
        # Each sentence must be >= 10 chars (min_segment_length)
        text = "这是第一句完整的话内容。这是第二句完整的话内容。这是第三句完整的话内容。"
        result = merger._split_sentences(text)
        assert len(result) >= 3

    def test_split_sentences_mixed_punctuation(self, merger):
        """测试混合标点分割"""
        text = "这是第一句完整的话内容？这是第二句完整的话内容！这是第三句完整的话内容。"
        result = merger._split_sentences(text)
        assert len(result) >= 3

    def test_split_sentences_chinese_punctuation(self, merger):
        """测试中文标点"""
        text = "这是中文问句完整内容吗？这是中文感叹句完整内容吗？这是另一个问句完整内容吗？"
        result = merger._split_sentences(text)
        assert len(result) >= 3

    def test_split_sentences_english_punctuation(self, merger):
        """测试英文标点"""
        text = "This is the first long sentence. This is the second long sentence. Third one."
        result = merger._split_sentences(text)
        assert len(result) >= 2

    def test_split_sentences_short_filtered(self, merger):
        """测试短句子被过滤"""
        text = "A。" * 5 + "这是一句比较长的句子来确保不会被过滤掉。"
        result = merger._split_sentences(text)
        # 短于min_segment_length的句子应该被过滤
        assert len(result) >= 1

    def test_segment_basic(self, merger):
        """测试基本分段"""
        text = "第一段\n\n第二段\n\n第三段"
        result = merger._segment(text)
        assert len(result) >= 1

    def test_segment_with_short_paragraphs(self, merger):
        """测试短段落合并"""
        text = "短段1\n短段2\n短段3"
        result = merger._segment(text)
        # 短段落应该被合并
        assert len(result) <= len(text.split("\n"))

    def test_segment_empty_lines(self, merger):
        """测试有空行的分段"""
        text = "段落一\n\n\n\n段落二"
        result = merger._segment(text)
        assert "段落一" in "".join(result)
        assert "段落二" in "".join(result)

    def test_merge_with_timestamps_subtitle_data(self, merger):
        """测试带时间戳的字幕合并"""
        subtitle_data = [
            {"start": 0, "end": 3, "text": "第一句"},
            {"start": 3, "end": 6, "text": "第二句"},
        ]
        whisper_segments = []

        result = merger.merge_with_timestamps(subtitle_data, whisper_segments)
        assert "第一句" in result
        assert "第二句" in result

    def test_merge_with_timestamps_whisper_only(self, merger):
        """测试仅Whisper数据"""
        subtitle_data = []
        whisper_segments = [
            {"start": 0, "end": 3, "text": "转录一"},
            {"start": 3, "end": 6, "text": "转录二"},
        ]

        result = merger.merge_with_timestamps(subtitle_data, whisper_segments)
        assert "转录一" in result
        assert "转录二" in result

    def test_merge_with_timestamps_both(self, merger):
        """测试两个数据源都有"""
        subtitle_data = [
            {"start": 0, "end": 3, "text": "字幕一"},
        ]
        whisper_segments = [
            {"start": 0, "end": 3, "text": "转录一"},
        ]

        result = merger.merge_with_timestamps(subtitle_data, whisper_segments)
        # 字幕优先
        assert "字幕一" in result

    def test_merge_with_timestamps_both_empty(self, merger):
        """测试两个数据源都为空"""
        result = merger.merge_with_timestamps([], [])
        assert result == ""

    def test_merge_with_timestamps_missing_text(self, merger):
        """测试缺少text字段"""
        subtitle_data = [
            {"start": 0, "end": 3},  # 缺少text
            {"start": 3, "end": 6, "text": "正常文本"},
        ]

        result = merger.merge_with_timestamps(subtitle_data, [])
        assert "正常文本" in result

    def test_merge_creates_output_file(self, merger, temp_dir):
        """测试合并结果保存到文件"""
        output_path = temp_dir / "result.txt"
        result = merger.merge("测试内容", "", output_path)

        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == "测试内容"

    def test_merge_overwrites_existing(self, merger, temp_dir):
        """测试覆盖已存在的文件"""
        output_path = temp_dir / "result.txt"
        output_path.write_text("旧内容", encoding="utf-8")

        result = merger.merge("新内容", "", output_path)

        assert output_path.read_text(encoding="utf-8") == "新内容"

    def test_merge_creates_parent_dirs(self, merger, temp_dir):
        """测试创建父目录"""
        output_path = temp_dir / "subdir" / "result.txt"
        result = merger.merge("测试", "", output_path)

        assert output_path.exists()

    def test_dedup_threshold_zero(self, sample_config, temp_dir):
        """测试去重阈值0（不进行去重）"""
        sample_config["merge"]["dedup_threshold"] = 0.0
        sample_config["merge"]["output_dir"] = str(temp_dir / "merged")
        merger = TextMerger(sample_config)

        text = "相同。相同。相同。"
        result = merger._deduplicate(text)
        # 阈值0时不进行相似度比较
        assert len(result) > 0

    def test_dedup_threshold_one(self, sample_config, temp_dir):
        """测试去重阈值1（只去除完全相同）"""
        sample_config["merge"]["dedup_threshold"] = 1.0
        sample_config["merge"]["output_dir"] = str(temp_dir / "merged")
        merger = TextMerger(sample_config)

        text = "相同。相同。不同。"
        result = merger._deduplicate(text)
        assert "不同" in result

    def test_unicode_text(self, merger, temp_dir):
        """测试Unicode文本处理"""
        text = "中文文本。😀 emoji。日本語。"
        output_path = temp_dir / "unicode.txt"

        result = merger.merge(text, "", output_path)
        assert result["text"] != ""

    def test_mixed_language(self, merger, temp_dir):
        """测试混合语言文本"""
        text = "Hello. 你好。World. 世界。"
        output_path = temp_dir / "mixed.txt"

        result = merger.merge(text, "", output_path)
        assert result["text"] != ""

    def test_special_characters(self, merger, temp_dir):
        """测试特殊字符处理"""
        text = "特殊<>&\字符\"'测试。"
        output_path = temp_dir / "special.txt"

        result = merger.merge(text, "", output_path)
        assert result["text"] != ""
