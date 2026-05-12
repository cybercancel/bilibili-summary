"""
B站视频总结系统 v2.0
核心模块包

使用懒加载以便在没有安装所有依赖时也能导入基础模块
"""

__version__ = "2.0.0"

__all__ = [
    "VideoDownloader",
    "SubtitleExtractor",
    "Transcriber",
    "TextMerger",
    "DeepSeekSummarizer",
    "TextChunker",
    "Notifier",
]


def __getattr__(name):
    """懒加载各模块"""
    lazy_imports = {
        "VideoDownloader": ".downloader",
        "SubtitleExtractor": ".subtitle",
        "Transcriber": ".transcriber",
        "TextMerger": ".merger",
        "DeepSeekSummarizer": ".summarizer",
        "TextChunker": ".chunker",
        "Notifier": ".notifier",
    }

    if name in lazy_imports:
        import importlib
        module = importlib.import_module(lazy_imports[name], package=__name__)
        return getattr(module, name)

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
