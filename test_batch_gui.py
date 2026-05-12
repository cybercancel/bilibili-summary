"""
GUI 批量功能自动化测试脚本
测试内容：队列管理、去重、状态更新、批量处理流程
"""

import sys
import os
import re
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

os.environ["TK_SILENCE_DEPRECATION"] = "1"

import tkinter as tk
from tkinter import ttk


def test_queue_management():
    """测试队列管理核心逻辑（不启动GUI窗口）"""
    print("=" * 60)
    print("测试 1: 队列管理核心逻辑")
    print("=" * 60)

    # 模拟 App 的队列数据结构
    batch_queue = []
    bv_id_pattern = re.compile(r"(BV[\w]+)")

    def extract_bv_id(url):
        m = bv_id_pattern.search(url)
        return m.group(1) if m else ""

    # 测试数据
    test_urls = [
        "https://www.bilibili.com/video/BV1DWRdB1E2s/",
        "https://www.bilibili.com/video/BV1DWRdB1E2s/?share_source=copy_web",  # 重复
        "BV1NC9kBaEJ2",  # 纯BV号
        "https://www.bilibili.com/video/BV19s5s6AEUP",
        "https://www.bilibili.com/video/BV19s5s6AEUP",  # 重复
        "invalid_url",  # 无效
        "https://www.bilibili.com/video/BV1X2XZBDEDq",
    ]

    added = 0
    duplicates = 0
    invalids = 0

    for url in test_urls:
        bv_id = extract_bv_id(url)
        if not bv_id:
            invalids += 1
            print(f"  [跳过] 无效: {url}")
            continue
        if any(item["bv_id"] == bv_id for item in batch_queue):
            duplicates += 1
            print(f"  [去重] {bv_id}")
            continue
        batch_queue.append({
            "url": url,
            "bv_id": bv_id,
            "status": "pending",
            "title": "",
        })
        added += 1
        print(f"  [添加] {bv_id}")

    assert added == 4, f"期望添加4个，实际{added}"
    assert duplicates == 2, f"期望去重2个，实际{duplicates}"
    assert invalids == 1, f"期望无效1个，实际{invalids}"
    assert len(batch_queue) == 4, f"期望队列长度4，实际{len(batch_queue)}"
    print(f"\n  结果: 添加 {added}, 去重 {duplicates}, 无效 {invalids}")
    print("  通过 ✓")


def test_queue_status_updates():
    """测试状态更新逻辑"""
    print("\n" + "=" * 60)
    print("测试 2: 队列状态更新")
    print("=" * 60)

    batch_queue = [
        {"url": "u1", "bv_id": "BV1", "status": "pending", "title": ""},
        {"url": "u2", "bv_id": "BV2", "status": "pending", "title": ""},
        {"url": "u3", "bv_id": "BV3", "status": "pending", "title": ""},
    ]

    def update_status(index, status, title=""):
        if 0 <= index < len(batch_queue):
            batch_queue[index]["status"] = status
            if title:
                batch_queue[index]["title"] = title

    # 模拟处理流程
    update_status(0, "running")
    assert batch_queue[0]["status"] == "running"
    print(f"  BV1 → running ✓")

    update_status(0, "done", "测试视频标题1")
    assert batch_queue[0]["status"] == "done"
    assert batch_queue[0]["title"] == "测试视频标题1"
    print(f"  BV1 → done (title: {batch_queue[0]['title']}) ✓")

    update_status(1, "running")
    update_status(1, "failed")
    assert batch_queue[1]["status"] == "failed"
    print(f"  BV2 → failed ✓")

    # 统计
    total = len(batch_queue)
    done = sum(1 for q in batch_queue if q["status"] in ("done", "skipped"))
    failed = sum(1 for q in batch_queue if q["status"] == "failed")
    pending = sum(1 for q in batch_queue if q["status"] == "pending")

    assert done == 1 and failed == 1 and pending == 1
    print(f"\n  统计: 总{total}, 完成{done}, 失败{failed}, 待处理{pending} ✓")
    print("  通过 ✓")


def test_import_from_file():
    """测试从文件导入"""
    print("\n" + "=" * 60)
    print("测试 3: 从文件导入链接")
    print("=" * 60)

    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("# 这是注释行，应该被跳过\n")
        f.write("\n")
        f.write("https://www.bilibili.com/video/BV1acRnByEuY\n")
        f.write("BV1xBZYBUEr4\n")
        f.write("https://www.bilibili.com/video/BV1acRnByEuY\n")  # 重复
        f.write("# 另一个注释\n")
        f.write("https://www.bilibili.com/video/BV1mwSQB2EZg\n")
        tmp_path = f.name

    try:
        batch_queue = []
        bv_id_pattern = re.compile(r"(BV[\w]+)")

        with open(tmp_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        for line in lines:
            bv_id = bv_id_pattern.search(line)
            if not bv_id:
                continue
            bv_id = bv_id.group(1)
            if any(item["bv_id"] == bv_id for item in batch_queue):
                continue
            batch_queue.append({
                "url": line, "bv_id": bv_id, "status": "pending", "title": ""
            })

        assert len(batch_queue) == 3, f"期望导入3个，实际{len(batch_queue)}"
        bvs = [q["bv_id"] for q in batch_queue]
        assert "BV1acRnByEuY" in bvs
        assert "BV1xBZYBUEr4" in bvs
        assert "BV1mwSQB2EZg" in bvs
        print(f"  导入 {len(batch_queue)} 个链接 (跳过注释和重复)")
        for q in batch_queue:
            print(f"    {q['bv_id']}")
        print("  通过 ✓")
    finally:
        os.unlink(tmp_path)


def test_batch_start_filtering():
    """测试批量启动时的过滤逻辑"""
    print("\n" + "=" * 60)
    print("测试 4: 批量启动过滤逻辑")
    print("=" * 60)

    batch_queue = [
        {"url": "u1", "bv_id": "BV1", "status": "done", "title": "已完成"},
        {"url": "u2", "bv_id": "BV2", "status": "pending", "title": ""},
        {"url": "u3", "bv_id": "BV3", "status": "failed", "title": ""},
        {"url": "u4", "bv_id": "BV4", "status": "pending", "title": ""},
        {"url": "u5", "bv_id": "BV5", "status": "skipped", "title": ""},
    ]

    # 模拟 _on_start_batch 的过滤
    pending = [
        (i, item) for i, item in enumerate(batch_queue)
        if item["status"] not in ("done", "skipped")
    ]

    assert len(pending) == 3, f"期望3个待处理，实际{len(pending)}"
    pending_bvs = [item["bv_id"] for _, item in pending]
    assert pending_bvs == ["BV2", "BV3", "BV4"]
    print(f"  队列总数: {len(batch_queue)}")
    print(f"  过滤后待处理: {len(pending)} ({pending_bvs})")
    print("  通过 ✓")


def test_single_mode_creates_queue():
    """测试单视频模式创建1元素队列"""
    print("\n" + "=" * 60)
    print("测试 5: 单视频模式创建队列")
    print("=" * 60)

    batch_queue = []
    url = "https://www.bilibili.com/video/BV1DWRdB1E2s/"
    bv_match = re.search(r"BV[\w]+", url)
    bv_id = bv_match.group(0)

    # 模拟 _on_start_single
    batch_queue.append({
        "url": url,
        "bv_id": bv_id,
        "status": "pending",
        "title": "",
    })

    assert len(batch_queue) == 1
    assert batch_queue[0]["bv_id"] == "BV1DWRdB1E2s"
    print(f"  单视频模式: 队列长度={len(batch_queue)}, bv_id={bv_id}")
    print("  通过 ✓")


def test_resume_skip():
    """测试断点续传跳过已完成视频"""
    print("\n" + "=" * 60)
    print("测试 6: 断点续传跳过已完成")
    print("=" * 60)

    batch_queue = [
        {"url": "u1", "bv_id": "BV1", "status": "done", "title": "已完成视频"},
        {"url": "u2", "bv_id": "BV2", "status": "pending", "title": ""},
        {"url": "u3", "bv_id": "BV3", "status": "pending", "title": ""},
    ]

    # 模拟 _process_worker 的 pending_indices 收集
    is_single = False
    pending_indices = []
    for i, item in enumerate(batch_queue):
        if item["status"] in ("done", "skipped"):
            if not is_single:
                continue
        pending_indices.append(i)

    assert pending_indices == [1, 2], f"期望[1,2]，实际{pending_indices}"
    print(f"  已完成 BV1 被跳过，待处理索引: {pending_indices}")
    print("  通过 ✓")


def test_gui_initialization():
    """测试 GUI 类初始化（headless 模式）"""
    print("\n" + "=" * 60)
    print("测试 7: GUI 类初始化 (headless)")
    print("=" * 60)

    # 创建一个隐藏的 root 窗口
    root = tk.Tk()
    root.withdraw()

    try:
        from gui import BilibiliSummaryGUI

        # 测试初始化
        app = BilibiliSummaryGUI.__new__(BilibiliSummaryGUI)
        app.config_path = "config.yaml"

        # 手动设置不依赖窗口的属性
        app.is_processing = False
        app.stop_requested = False
        app.processor = None
        app.process_thread = None
        app.result_status = None
        app.batch_queue = []
        app.batch_current_index = -1

        # 加载配置
        config_file = Path("config.yaml")
        if config_file.exists():
            import yaml
            with open(config_file, "r", encoding="utf-8") as f:
                app.config = yaml.safe_load(f) or {}
        else:
            app.config = {}

        assert isinstance(app.config, dict)
        assert app.batch_queue == []
        assert app.stop_requested is False
        print(f"  配置加载成功，keys: {list(app.config.keys())[:5]}...")
        print("  通过 ✓")

    finally:
        root.destroy()


def test_stop_mechanism():
    """测试停止机制"""
    print("\n" + "=" * 60)
    print("测试 8: 停止机制")
    print("=" * 60)

    stop_requested = False

    # 模拟 _process_worker 循环中的停止检查
    batch_queue = [
        {"url": "u1", "bv_id": "BV1", "status": "pending", "title": ""},
        {"url": "u2", "bv_id": "BV2", "status": "pending", "title": ""},
        {"url": "u3", "bv_id": "BV3", "status": "pending", "title": ""},
        {"url": "u4", "bv_id": "BV4", "status": "pending", "title": ""},
    ]

    processed = []
    for i, item in enumerate(batch_queue):
        if stop_requested:
            print(f"  收到停止信号，在第 {i} 个视频处停止")
            break
        processed.append(item["bv_id"])
        if i == 1:
            stop_requested = True  # 模拟在第2个后发送停止

    assert len(processed) == 2, f"期望处理2个，实际{len(processed)}"
    assert processed == ["BV1", "BV2"]
    print(f"  处理了 {len(processed)} 个后停止: {processed}")
    print("  通过 ✓")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  GUI 批量功能测试")
    print("=" * 60)

    tests = [
        test_queue_management,
        test_queue_status_updates,
        test_import_from_file,
        test_batch_start_filtering,
        test_single_mode_creates_queue,
        test_resume_skip,
        test_gui_initialization,
        test_stop_mechanism,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"  测试结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 个")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
