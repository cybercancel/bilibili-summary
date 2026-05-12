"""
B站视频总结系统 v2.0 - 图形化界面

使用方法:
    python gui.py
    python gui.py --config custom_config.yaml
"""

import argparse
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yaml

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


class TextHandler(logging.Handler):
    """将日志输出重定向到 tkinter Text 组件"""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget
        self.queue = Queue()
        self._running = True

        # 启动队列消费线程
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)

    def _poll(self):
        while self._running:
            try:
                msg = self.queue.get(timeout=0.1)
                self.text_widget.after(0, self._append, msg)
            except Exception:
                pass

    def _append(self, msg: str):
        self.text_widget.configure(state="normal")
        self.text_widget.insert(tk.END, msg + "\n")
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")

    def stop(self):
        self._running = False


class StdoutRedirector:
    """将 sys.stdout 重定向到 GUI，同时保留 Whisper 进度条效果"""

    def __init__(self, text_widget: tk.Text, original_stdout):
        self.text_widget = text_widget
        self.original = original_stdout
        self.queue = Queue()
        self._running = True
        self._last_progress_line = ""
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def write(self, text: str):
        if not text:
            return
        # 进度条行 (\r 开头) — 更新而非换行
        if "\r" in text:
            text = text.split("\r")[-1]
            self.queue.put(("progress", text.strip()))
        else:
            self.queue.put(("normal", text))

    def flush(self):
        pass

    def _poll(self):
        while self._running:
            try:
                kind, text = self.queue.get(timeout=0.1)
                if not text:
                    continue
                if kind == "progress":
                    self._last_progress_line = text
                    self.text_widget.after(0, self._update_progress, text)
                else:
                    if self._last_progress_line:
                        self._last_progress_line = ""
                    self.text_widget.after(0, self._append, text)
            except Exception:
                pass

    def _update_progress(self, text: str):
        self.text_widget.configure(state="normal")
        # 删除最后的进度行
        last_line_idx = self.text_widget.index("end-2c linestart")
        last_line = self.text_widget.get(last_line_idx, "end-1c")
        if last_line.startswith("  Whisper:"):
            self.text_widget.delete(last_line_idx, "end-1c")
        self.text_widget.insert(tk.END, text)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")

    def _append(self, text: str):
        for line in text.rstrip("\n").split("\n"):
            self.text_widget.configure(state="normal")
            self.text_widget.insert(tk.END, line + "\n")
            self.text_widget.see(tk.END)
            self.text_widget.configure(state="disabled")

    def stop(self):
        self._running = False


class BilibiliSummaryGUI:
    """B站视频总结系统图形界面"""

    # 步骤定义
    STEPS = [
        ("download", "下载视频"),
        ("subtitle", "提取字幕"),
        ("transcribe", "语音转录"),
        ("merge", "合并文本"),
        ("summarize", "生成总结"),
    ]

    STEP_ICONS = {
        "pending": "\u23f3",   # ⏳
        "running": "\u2699",   # ⚙
        "done": "\u2705",      # ✅
        "skipped": "\u23ed",   # ⏭
        "failed": "\u274c",    # ❌
    }

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)

        # 处理状态
        self.is_processing = False
        self.stop_requested = False
        self.processor = None
        self.process_thread = None
        self.result_status = None

        # 批量队列: list of {"url": str, "bv_id": str, "status": str, "title": str}
        self.batch_queue = []
        self.batch_current_index = -1

        self._build_ui()
        self._setup_logging()

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        config_file = Path(config_path)
        if not config_file.exists():
            return {}
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _build_ui(self):
        """构建界面"""
        self.root = tk.Tk()
        self.root.title("B站视频总结系统 v2.0")
        self.root.geometry("1100x800")
        self.root.minsize(900, 650)
        self.root.configure(bg="#1e1e2e")

        # 设置样式
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()

        # ── 顶部输入区 ──
        self._build_input_bar()

        # ── 中部：左侧步骤面板 + 右侧日志 ──
        self._build_main_area()

        # ── 底部：结果展示区 ──
        self._build_result_area()

    def _configure_styles(self):
        """配置 ttk 样式"""
        bg = "#1e1e2e"
        fg = "#cdd6f4"
        accent = "#89b4fa"
        card_bg = "#313244"
        entry_bg = "#45475a"

        self.style.configure("TFrame", background=bg)
        self.style.configure("Card.TFrame", background=card_bg)
        self.style.configure("TLabel", background=bg, foreground=fg, font=("Microsoft YaHei UI", 10))
        self.style.configure("Title.TLabel", background=bg, foreground=accent, font=("Microsoft YaHei UI", 14, "bold"))
        self.style.configure("Card.TLabel", background=card_bg, foreground=fg, font=("Microsoft YaHei UI", 10))
        self.style.configure("Step.TLabel", background=card_bg, foreground=fg, font=("Microsoft YaHei UI", 11))
        self.style.configure("StepActive.TLabel", background=card_bg, foreground="#f9e2af", font=("Microsoft YaHei UI", 11, "bold"))
        self.style.configure("StepDone.TLabel", background=card_bg, foreground="#a6e3a1", font=("Microsoft YaHei UI", 11))
        self.style.configure("StepFailed.TLabel", background=card_bg, foreground="#f38ba8", font=("Microsoft YaHei UI", 11))
        self.style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=6)
        self.style.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=8)
        self.style.configure("TCombobox", font=("Microsoft YaHei UI", 10))
        self.style.configure("TEntry", font=("Microsoft YaHei UI", 10))
        self.style.configure("TSeparator", background="#585b70")

        # Notebook (Tab) 样式
        self.style.configure("TNotebook", background=bg, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=card_bg, foreground=fg,
                             font=("Microsoft YaHei UI", 10), padding=[12, 4])
        self.style.map("TNotebook.Tab",
                       background=[("selected", "#45475a")],
                       foreground=[("selected", accent)])

        # Treeview (队列列表) 样式
        self.style.configure("Queue.Treeview",
                             background="#181825", foreground="#cdd6f4",
                             fieldbackground="#181825", font=("Microsoft YaHei UI", 10),
                             rowheight=28)
        self.style.configure("Queue.Treeview.Heading",
                             background="#313244", foreground="#89b4fa",
                             font=("Microsoft YaHei UI", 10, "bold"))
        self.style.map("Queue.Treeview",
                       background=[("selected", "#45475a")],
                       foreground=[("selected", "#cdd6f4")])

    # ────────────────────────────────────────────
    #  输入区
    # ────────────────────────────────────────────

    def _build_input_bar(self):
        """构建顶部输入区（包含单个/批量两个 Tab）"""
        bar = ttk.Frame(self.root, padding=(16, 12))
        bar.pack(fill=tk.X)

        # 标题行
        title_row = ttk.Frame(bar)
        title_row.pack(fill=tk.X)
        ttk.Label(title_row, text="B站视频总结系统", style="Title.TLabel").pack(side=tk.LEFT)

        # 选项行（放在标题右边）
        opt_frame = ttk.Frame(title_row)
        opt_frame.pack(side=tk.RIGHT)

        ttk.Label(opt_frame, text="Whisper:").pack(side=tk.LEFT)
        self.whisper_var = tk.StringVar(
            value=self.config.get("transcribe", {}).get("model", "base")
        )
        whisper_combo = ttk.Combobox(
            opt_frame, textvariable=self.whisper_var,
            values=["tiny", "base", "small", "medium"],
            width=6, state="readonly"
        )
        whisper_combo.pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(opt_frame, text="设备:").pack(side=tk.LEFT)
        self.device_var = tk.StringVar(
            value=self.config.get("transcribe", {}).get("device", "auto")
        )
        device_combo = ttk.Combobox(
            opt_frame, textvariable=self.device_var,
            values=["auto", "cuda", "cpu"],
            width=6, state="readonly"
        )
        device_combo.pack(side=tk.LEFT, padx=(2, 10))

        self.resume_var = tk.BooleanVar(
            value=self.config.get("resume", {}).get("enabled", True)
        )
        ttk.Checkbutton(opt_frame, text="断点续传", variable=self.resume_var).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Button(opt_frame, text="清空日志", command=self.clear_log).pack(side=tk.LEFT)

        # Notebook: 单个 / 批量
        self.notebook = ttk.Notebook(bar)
        self.notebook.pack(fill=tk.X, pady=(10, 0))

        self._build_single_tab()
        self._build_batch_tab()

    def _build_single_tab(self):
        """单个视频 Tab"""
        tab = ttk.Frame(self.notebook, padding=(0, 8))
        self.notebook.add(tab, text="  单个视频  ")

        row = ttk.Frame(tab)
        row.pack(fill=tk.X)

        ttk.Label(row, text="链接:").pack(side=tk.LEFT)

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(row, textvariable=self.url_var, font=("Consolas", 11))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self.url_entry.insert(0, "https://www.bilibili.com/video/")
        self.url_entry.bind("<Control-Return>", lambda e: self._on_start_single())

        self.start_btn = ttk.Button(
            row, text="开始总结", style="Accent.TButton", command=self._on_start_single
        )
        self.start_btn.pack(side=tk.LEFT, padx=(12, 4))

        self.stop_btn = ttk.Button(
            row, text="停止", command=self.stop_processing, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=4)

    def _build_batch_tab(self):
        """批量视频 Tab"""
        tab = ttk.Frame(self.notebook, padding=(0, 8))
        self.notebook.add(tab, text="  批量处理  ")

        # 上方：链接输入 + 按钮
        input_row = ttk.Frame(tab)
        input_row.pack(fill=tk.X)

        ttk.Label(input_row, text="链接:").pack(side=tk.LEFT)

        self.batch_url_var = tk.StringVar()
        self.batch_url_entry = ttk.Entry(
            input_row, textvariable=self.batch_url_var, font=("Consolas", 11)
        )
        self.batch_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self.batch_url_entry.insert(0, "粘贴链接，回车添加到队列")
        self.batch_url_entry.bind("<FocusIn>", lambda e: self._clear_placeholder())
        self.batch_url_entry.bind("<Return>", lambda e: self._add_url_to_queue())
        self.batch_url_entry.bind("<Control-Return>", lambda e: self._add_url_to_queue())

        ttk.Button(
            input_row, text="添加", command=self._add_url_to_queue
        ).pack(side=tk.LEFT, padx=(8, 4))

        ttk.Button(
            input_row, text="导入文件", command=self._import_urls_from_file
        ).pack(side=tk.LEFT, padx=4)

        # 中间：队列列表
        tree_frame = tk.Frame(tab, bg="#181825", bd=1, relief=tk.RIDGE)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        columns = ("idx", "bv_id", "status")
        self.queue_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=5,
            style="Queue.Treeview",
        )
        self.queue_tree.heading("idx", text="#")
        self.queue_tree.heading("bv_id", text="视频")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.column("idx", width=40, anchor=tk.CENTER, stretch=False)
        self.queue_tree.column("bv_id", width=500, anchor=tk.W)
        self.queue_tree.column("status", width=80, anchor=tk.CENTER, stretch=False)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=tree_scroll.set)
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 下方：操作按钮
        btn_row = ttk.Frame(tab)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        self.batch_start_btn = ttk.Button(
            btn_row, text="开始批量处理", style="Accent.TButton",
            command=self._on_start_batch
        )
        self.batch_start_btn.pack(side=tk.LEFT)

        self.batch_stop_btn = ttk.Button(
            btn_row, text="停止", command=self.stop_processing, state=tk.DISABLED
        )
        self.batch_stop_btn.pack(side=tk.LEFT, padx=(8, 4))

        ttk.Button(
            btn_row, text="删除选中", command=self._remove_selected_from_queue
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            btn_row, text="清空队列", command=self._clear_queue
        ).pack(side=tk.LEFT, padx=4)

        # 批量进度
        self.batch_progress_var = tk.StringVar(value="队列: 0 个视频")
        ttk.Label(btn_row, textvariable=self.batch_progress_var).pack(side=tk.RIGHT)

    # ────────────────────────────────────────────
    #  队列管理
    # ────────────────────────────────────────────

    def _clear_placeholder(self):
        """清空 placeholder"""
        current = self.batch_url_var.get()
        if current == "粘贴链接，回车添加到队列":
            self.batch_url_var.set("")

    def _extract_bv_id(self, url: str) -> str:
        """从 URL 提取 BV 号"""
        m = re.search(r"(BV[\w]+)", url)
        return m.group(1) if m else ""

    def _add_url_to_queue(self):
        """将输入框中的链接添加到队列"""
        raw = self.batch_url_var.get().strip()
        if not raw or raw == "粘贴链接，回车添加到队列":
            return

        from core.subtitle import extract_bilibili_url

        # 支持一行多个链接（空格/换行分隔）
        parts = re.split(r"[\n\s]+", raw)
        added = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue
            clean_url = extract_bilibili_url(part)
            if not clean_url:
                continue
            bv_id = self._extract_bv_id(clean_url)
            if not bv_id:
                continue
            # 去重
            if any(item["bv_id"] == bv_id for item in self.batch_queue):
                continue
            self.batch_queue.append({
                "url": clean_url,
                "bv_id": bv_id,
                "status": "pending",
                "title": "",
            })
            added += 1

        if added == 0:
            messagebox.showinfo("提示", "未识别到有效的B站链接")
        else:
            self.batch_url_var.set("")
            self._refresh_queue_tree()

    def _import_urls_from_file(self):
        """从文件导入链接"""
        file_path = filedialog.askopenfilename(
            title="选择URL文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        from core.subtitle import extract_bilibili_url

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

            added = 0
            for line in lines:
                clean_url = extract_bilibili_url(line)
                if not clean_url:
                    continue
                bv_id = self._extract_bv_id(clean_url)
                if not bv_id:
                    continue
                if any(item["bv_id"] == bv_id for item in self.batch_queue):
                    continue
                self.batch_queue.append({
                    "url": clean_url,
                    "bv_id": bv_id,
                    "status": "pending",
                    "title": "",
                })
                added += 1

            if added > 0:
                self._refresh_queue_tree()
                messagebox.showinfo("导入成功", f"已导入 {added} 个链接到队列")
            else:
                messagebox.showwarning("提示", "文件中未找到有效的B站链接")

        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _remove_selected_from_queue(self):
        """删除队列中选中的项"""
        selection = self.queue_tree.selection()
        if not selection:
            return
        indices_to_remove = sorted(
            [self.queue_tree.index(item) for item in selection], reverse=True
        )
        for idx in indices_to_remove:
            if 0 <= idx < len(self.batch_queue):
                del self.batch_queue[idx]
        self._refresh_queue_tree()

    def _clear_queue(self):
        """清空队列"""
        if self.is_processing:
            messagebox.showwarning("提示", "正在处理中，无法清空队列")
            return
        self.batch_queue.clear()
        self.batch_current_index = -1
        self._refresh_queue_tree()

    def _refresh_queue_tree(self):
        """刷新队列 Treeview"""
        # 保存选中
        selected_bv_ids = set()
        for item in self.queue_tree.selection():
            values = self.queue_tree.item(item, "values")
            if values:
                selected_bv_ids.add(values[1])

        self.queue_tree.delete(*self.queue_tree.get_children())

        status_display = {
            "pending": "\u23f3 等待中",
            "running": "\u2699 处理中",
            "done": "\u2705 完成",
            "skipped": "\u23ed 已跳过",
            "failed": "\u274c 失败",
        }
        status_fg = {
            "pending": "#6c7086",
            "running": "#f9e2af",
            "done": "#a6e3a1",
            "skipped": "#6c7086",
            "failed": "#f38ba8",
        }

        for i, item in enumerate(self.batch_queue):
            status_text = status_display.get(item["status"], item["status"])
            display = f"{item['bv_id']}  {item.get('title', '')}"
            if len(display) > 60:
                display = display[:57] + "..."
            iid = self.queue_tree.insert("", tk.END, values=(i + 1, display, status_text))
            self.queue_tree.set(iid, "tags", (item["status"],))

        # 配置 tag 颜色
        for st, color in status_fg.items():
            self.queue_tree.tag_configure(st, foreground=color)

        # 恢复选中
        for item in self.queue_tree.get_children():
            values = self.queue_tree.item(item, "values")
            if values and values[1] and any(bv in str(values[1]) for bv in selected_bv_ids):
                self.queue_tree.selection_add(item)

        # 更新进度文本
        total = len(self.batch_queue)
        done = sum(1 for q in self.batch_queue if q["status"] in ("done", "skipped"))
        failed = sum(1 for q in self.batch_queue if q["status"] == "failed")
        if total == 0:
            self.batch_progress_var.set("队列: 0 个视频")
        elif done + failed >= total:
            self.batch_progress_var.set(
                f"全部完成: {total} 个 (成功 {done}, 失败 {failed})"
            )
        else:
            self.batch_progress_var.set(
                f"队列: {total} 个视频 | 已完成 {done + failed}/{total}"
            )

    def _update_queue_item_status(self, index: int, status: str, title: str = ""):
        """更新队列中某个视频的状态"""
        if 0 <= index < len(self.batch_queue):
            self.batch_queue[index]["status"] = status
            if title:
                self.batch_queue[index]["title"] = title
            self.root.after(0, self._refresh_queue_tree)

    # ────────────────────────────────────────────
    #  主区域 & 结果区 (保持不变)
    # ────────────────────────────────────────────

    def _build_main_area(self):
        """构建中部主区域"""
        main = ttk.Frame(self.root, padding=(16, 4))
        main.pack(fill=tk.BOTH, expand=True)

        # ── 左侧：步骤面板 ──
        step_panel = tk.Frame(main, bg="#313244", bd=1, relief=tk.RIDGE, width=240)
        step_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        step_panel.pack_propagate(False)

        tk.Label(
            step_panel, text="处理步骤", bg="#313244", fg="#89b4fa",
            font=("Microsoft YaHei UI", 12, "bold"), anchor=tk.W, padx=12, pady=8
        ).pack(fill=tk.X)

        self.step_labels = {}
        self.step_widgets = {}

        for i, (key, label) in enumerate(self.STEPS):
            frame = tk.Frame(step_panel, bg="#313244", padx=12, pady=4)
            frame.pack(fill=tk.X)

            icon_label = tk.Label(
                frame, text="\u23f3", bg="#313244", fg="#6c7086",
                font=("Segoe UI Emoji", 14), width=2, anchor=tk.W
            )
            icon_label.pack(side=tk.LEFT)

            text_label = tk.Label(
                frame, text=f"{i+1}. {label}", bg="#313244", fg="#6c7086",
                font=("Microsoft YaHei UI", 11), anchor=tk.W
            )
            text_label.pack(side=tk.LEFT, padx=(4, 0))

            sep = tk.Frame(step_panel, bg="#45475a", height=1)
            sep.pack(fill=tk.X, padx=12)

            self.step_labels[key] = (icon_label, text_label)

        # 批量进度 (步骤面板底部)
        self.batch_info_label = tk.Label(
            step_panel, text="", bg="#313244", fg="#89b4fa",
            font=("Microsoft YaHei UI", 10), anchor=tk.W, padx=12, pady=4
        )
        self.batch_info_label.pack(fill=tk.X, side=tk.BOTTOM)

        # 耗时显示
        self.time_label = tk.Label(
            step_panel, text="耗时: --", bg="#313244", fg="#a6adc8",
            font=("Consolas", 10), anchor=tk.W, padx=12, pady=8
        )
        self.time_label.pack(fill=tk.X, side=tk.BOTTOM)

        # ── 右侧：日志输出 ──
        log_frame = tk.Frame(main, bg="#11111b", bd=1, relief=tk.RIDGE)
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_header = tk.Frame(log_frame, bg="#181825")
        log_header.pack(fill=tk.X)
        tk.Label(
            log_header, text="运行日志", bg="#181825", fg="#89b4fa",
            font=("Microsoft YaHei UI", 10, "bold"), anchor=tk.W, padx=8, pady=4
        ).pack(side=tk.LEFT)

        self.log_text = tk.Text(
            log_frame, wrap=tk.WORD, state=tk.DISABLED,
            bg="#11111b", fg="#cdd6f4", insertbackground="#cdd6f4",
            font=("Consolas", 9), padx=8, pady=4,
            selectbackground="#45475a", selectforeground="#cdd6f4",
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 配置日志标签颜色
        self.log_text.tag_configure("INFO", foreground="#cdd6f4")
        self.log_text.tag_configure("WARNING", foreground="#f9e2af")
        self.log_text.tag_configure("ERROR", foreground="#f38ba8")
        self.log_text.tag_configure("DEBUG", foreground="#6c7086")
        self.log_text.tag_configure("progress", foreground="#89b4fa")

    def _build_result_area(self):
        """构建底部结果展示区"""
        result_frame = tk.Frame(self.root, bg="#313244", bd=1, relief=tk.RIDGE)
        result_frame.pack(fill=tk.X, padx=16, pady=(4, 12))

        # 标题栏
        header = tk.Frame(result_frame, bg="#313244")
        header.pack(fill=tk.X)

        tk.Label(
            header, text="总结结果", bg="#313244", fg="#89b4fa",
            font=("Microsoft YaHei UI", 10, "bold"), anchor=tk.W, padx=8, pady=4
        ).pack(side=tk.LEFT)

        self.open_file_btn = ttk.Button(
            header, text="打开文件", command=self._open_result_file, state=tk.DISABLED
        )
        self.open_file_btn.pack(side=tk.RIGHT, padx=4, pady=2)

        self.copy_btn = ttk.Button(
            header, text="复制总结", command=self._copy_result, state=tk.DISABLED
        )
        self.copy_btn.pack(side=tk.RIGHT, padx=4, pady=2)

        # 结果文本
        self.result_text = tk.Text(
            result_frame, wrap=tk.WORD, state=tk.DISABLED,
            bg="#181825", fg="#cdd6f4", insertbackground="#cdd6f4",
            font=("Microsoft YaHei UI", 10), height=10, padx=8, pady=4,
            selectbackground="#45475a", selectforeground="#cdd6f4",
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
        result_scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=result_scrollbar.set)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        result_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._result_file_path = None

    # ────────────────────────────────────────────
    #  日志 & 步骤 UI 更新
    # ────────────────────────────────────────────

    def _setup_logging(self):
        """配置日志系统"""
        # 清除默认 handler
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # 设置日志级别
        log_level = logging.INFO
        root_logger.setLevel(log_level)

        # 输出到 GUI
        self.text_handler = TextHandler(self.log_text)
        self.text_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root_logger.addHandler(self.text_handler)

        # 同时输出到文件
        log_dir = Path(self.config.get("output", {}).get("log_dir", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / f"gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root_logger.addHandler(file_handler)

        # 重定向 stdout（捕获进度条等直接输出）
        self.stdout_redirector = StdoutRedirector(self.log_text, sys.stdout)
        sys.stdout = self.stdout_redirector

    def _append_log(self, msg: str, level: str = "INFO"):
        """直接向日志区域追加消息"""
        self.text_handler.emit(logging.LogRecord(
            name="GUI", level=getattr(logging, level), pathname="", lineno=0,
            msg=msg, args=(), exc_info=None
        ))

    def clear_log(self):
        """清空日志"""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _update_step(self, step_key: str, status: str):
        """更新步骤状态显示"""
        if step_key not in self.step_labels:
            return
        icon_label, text_label = self.step_labels[step_key]
        icon = self.STEP_ICONS.get(status, "\u23f3")

        if status == "running":
            icon_label.configure(fg="#f9e2af")
            text_label.configure(fg="#f9e2af")
        elif status == "done":
            icon_label.configure(fg="#a6e3a1")
            text_label.configure(fg="#a6e3a1")
        elif status == "failed":
            icon_label.configure(fg="#f38ba8")
            text_label.configure(fg="#f38ba8")
        elif status == "skipped":
            icon_label.configure(fg="#6c7086")
            text_label.configure(fg="#6c7086")
        else:
            icon_label.configure(fg="#6c7086")
            text_label.configure(fg="#6c7086")

        icon_label.configure(text=icon)

    def _reset_steps(self):
        """重置所有步骤到 pending 状态"""
        for key, _ in self.STEPS:
            self._update_step(key, "pending")
        self.time_label.configure(text="耗时: --")
        self.batch_info_label.configure(text="")

    def _open_result_file(self):
        """打开结果文件"""
        if self._result_file_path and Path(self._result_file_path).exists():
            os.startfile(str(self._result_file_path))

    def _copy_result(self):
        """复制总结结果到剪贴板"""
        self.result_text.configure(state="normal")
        content = self.result_text.get("1.0", tk.END)
        self.result_text.configure(state="disabled")
        if content.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self._append_log("已复制总结到剪贴板")

    def _show_result(self, content: str):
        """显示总结结果"""
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", content)
        self.result_text.configure(state="disabled")

    def _clear_result(self):
        """清空结果区"""
        self._result_file_path = None
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.configure(state="disabled")
        self.open_file_btn.configure(state=tk.DISABLED)
        self.copy_btn.configure(state=tk.DISABLED)

    # ────────────────────────────────────────────
    #  处理入口
    # ────────────────────────────────────────────

    def _on_start_single(self):
        """单个模式：开始处理"""
        url = self.url_var.get().strip()
        if not url or url == "https://www.bilibili.com/video/":
            messagebox.showwarning("提示", "请输入有效的B站视频链接")
            return

        from core.subtitle import extract_bilibili_url
        clean_url = extract_bilibili_url(url)
        if not clean_url:
            messagebox.showwarning("提示", "无法从输入中提取B站链接，请检查格式")
            return

        # 转为单元素批量
        self.batch_queue = [{
            "url": clean_url,
            "bv_id": self._extract_bv_id(clean_url),
            "status": "pending",
            "title": "",
        }]
        self.batch_current_index = -1
        self._start_processing(is_single=True)

    def _on_start_batch(self):
        """批量模式：开始处理队列"""
        # 过滤掉已完成的
        pending = [
            (i, item) for i, item in enumerate(self.batch_queue)
            if item["status"] not in ("done", "skipped")
        ]
        if not pending:
            messagebox.showinfo("提示", "队列为空或所有视频已处理完成")
            return

        self.batch_current_index = pending[0][0] - 1  # -1 因为循环会 +1
        self._start_processing(is_single=False)

    def _start_processing(self, is_single: bool = False):
        """通用处理启动"""
        if self.is_processing:
            return

        self.is_processing = True
        self.stop_requested = False

        # 禁用所有输入
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.url_entry.configure(state=tk.DISABLED)
        self.batch_start_btn.configure(state=tk.DISABLED)
        self.batch_stop_btn.configure(state=tk.NORMAL)
        self.batch_url_entry.configure(state=tk.DISABLED)

        self._reset_steps()
        self._clear_result()

        self.process_thread = threading.Thread(
            target=self._process_worker,
            args=(is_single,),
            daemon=True,
        )
        self.process_thread.start()

    def _on_process_done(self):
        """处理完成后的 UI 恢复"""
        self.is_processing = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.url_entry.configure(state=tk.NORMAL)
        self.batch_start_btn.configure(state=tk.NORMAL)
        self.batch_stop_btn.configure(state=tk.DISABLED)
        self.batch_url_entry.configure(state=tk.NORMAL)

    def stop_processing(self):
        """停止处理（软停止 — 当前视频完成后停止队列）"""
        if self.is_processing:
            self.stop_requested = True
            self._append_log("已发送停止信号（当前视频完成后停止）", "WARNING")
            self.stop_btn.configure(state=tk.DISABLED)
            self.batch_stop_btn.configure(state=tk.DISABLED)

    # ────────────────────────────────────────────
    #  工作线程
    # ────────────────────────────────────────────

    def _process_worker(self, is_single: bool):
        """工作线程：逐个处理队列中的视频"""
        start_time = time.time()
        logger = logging.getLogger("GUI")

        try:
            from main import BilibiliVideoProcessor

            # 构建 config 覆盖
            config_overrides = dict(self.config)
            config_overrides.setdefault("transcribe", {})
            config_overrides["transcribe"]["model"] = self.whisper_var.get()
            config_overrides["transcribe"]["device"] = self.device_var.get()

            processor = BilibiliVideoProcessor(self.config_path)
            processor.config.update(config_overrides)

            # 收集待处理的视频索引
            pending_indices = []
            for i, item in enumerate(self.batch_queue):
                if item["status"] in ("done", "skipped"):
                    if not is_single:
                        continue
                pending_indices.append(i)

            total_pending = len(pending_indices)
            success_count = 0
            fail_count = 0

            for seq, idx in enumerate(pending_indices):
                if self.stop_requested:
                    logger.info("收到停止信号，停止批量处理")
                    break

                queue_item = self.batch_queue[idx]
                url = queue_item["url"]
                bv_id = queue_item["bv_id"]

                # 更新队列状态
                self._update_queue_item_status(idx, "running")
                self.batch_current_index = idx

                # 批量模式：显示进度
                if not is_single:
                    self.root.after(
                        0, self.batch_info_label.configure,
                        {"text": f"({seq + 1}/{total_pending}) {bv_id}"},
                    )
                    logger.info(f"\n{'='*50}")
                    logger.info(f"[{seq+1}/{total_pending}] 处理: {bv_id}")
                    logger.info(f"{'='*50}")

                # 重置步骤面板
                self.root.after(0, self._reset_steps)

                # 执行单视频处理
                try:
                    result = self._process_single_video(processor, url, logger)
                    status_str = result.get("status", "failed")
                    title = result.get("title", "")

                    if status_str == "done":
                        success_count += 1
                        self._update_queue_item_status(idx, "done", title)
                    else:
                        fail_count += 1
                        self._update_queue_item_status(idx, "failed", title)

                    # 如果是单个模式，显示最后一个的结果
                    if is_single:
                        summary_file = result.get("steps", {}).get("summarize", {}).get("file")
                        if summary_file and Path(summary_file).exists():
                            with open(summary_file, "r", encoding="utf-8") as f:
                                summary_content = f.read()
                            self._result_file_path = summary_file
                            self.root.after(0, self._show_result, summary_content)
                            self.root.after(0, self.open_file_btn.configure, {"state": tk.NORMAL})
                            self.root.after(0, self.copy_btn.configure, {"state": tk.NORMAL})
                            logger.info(f"总结文件: {summary_file}")

                except Exception as e:
                    fail_count += 1
                    logger.error(f"处理失败 [{bv_id}]: {e}")
                    self._update_queue_item_status(idx, "failed")

            # 批量完成汇总
            if not is_single and total_pending > 1:
                elapsed = time.time() - start_time
                logger.info("=" * 50)
                logger.info(
                    f"批量处理完成! "
                    f"成功 {success_count}/{total_pending}, "
                    f"失败 {fail_count}, "
                    f"耗时 {elapsed:.1f}s"
                )
                logger.info("=" * 50)
                self.root.after(
                    0, self.batch_info_label.configure,
                    {"text": f"完成: {success_count}成功, {fail_count}失败"},
                )

        except Exception as e:
            logger.error(f"处理出错: {e}", exc_info=True)
            self.root.after(0, messagebox.showerror, "处理失败", str(e))
        finally:
            elapsed = time.time() - start_time
            self.root.after(0, self.time_label.configure, {"text": f"耗时: {elapsed:.1f}s"})
            self.root.after(0, self._on_process_done)

    def _process_single_video(self, processor, url: str, logger) -> dict:
        """在 worker 线程中处理单个视频（带步骤 UI 回调）"""
        import re as _re
        start_time = time.time()

        bv_match = _re.search(r"BV[\w]+", url)
        if not bv_match:
            raise ValueError(f"无法从URL提取BV号: {url}")
        bv_id = bv_match.group(0)

        status_dir = Path(processor.resume_config.get("status_dir", "summaries"))
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / f"{bv_id}.status.json"

        status = None
        if self.resume_var.get() and status_file.exists():
            status = processor._load_status(status_file)
            if status.get("status") == "done":
                logger.info(f"视频已处理完成，跳过: {bv_id}")
                return status

        if not status:
            status = processor._init_status(bv_id, url)

        step_methods = [
            ("download", processor._step_download, [status, url]),
            ("subtitle", processor._step_subtitle, [status]),
            ("transcribe", processor._step_transcribe, [status]),
            ("merge", processor._step_merge, [status]),
            ("summarize", processor._step_summarize, [status]),
        ]

        try:
            for i, (key, method, args) in enumerate(step_methods):
                if self.stop_requested:
                    break

                step_status = status["steps"][key]["status"]

                if step_status == "done":
                    self.root.after(0, self._update_step, key, "done")
                    logger.info(f"[Step {i+1}/5] {self.STEPS[i][1]} - 已完成，跳过")
                    continue
                elif step_status == "skipped":
                    self.root.after(0, self._update_step, key, "skipped")
                    logger.info(f"[Step {i+1}/5] {self.STEPS[i][1]} - 已跳过")
                    continue

                # 标记为运行中
                self.root.after(0, self._update_step, key, "running")
                logger.info(f"[Step {i+1}/5] {self.STEPS[i][1]}...")

                status = method(*args)
                processor._save_status(status_file, status)

                new_status = status["steps"][key]["status"]
                self.root.after(0, self._update_step, key, new_status)

            # 完成
            status["status"] = "done"
            status["updated_at"] = datetime.now().isoformat()
            status["current_step"] = "done"
            processor._save_status(status_file, status)

            elapsed = time.time() - start_time
            logger.info("=" * 60)
            logger.info(f"视频处理完成！耗时: {elapsed:.1f} 秒")
            logger.info("=" * 60)

            self.root.after(0, self.time_label.configure, {"text": f"耗时: {elapsed:.1f}s"})

            return status

        except Exception as e:
            logger.error(f"处理失败: {e}")
            status["status"] = "failed"
            status["error"] = str(e)
            status["updated_at"] = datetime.now().isoformat()
            processor._save_status(status_file, status)
            raise

    # ────────────────────────────────────────────
    #  窗口管理
    # ────────────────────────────────────────────

    def run(self):
        """启动 GUI"""
        # 窗口居中
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"+{x}+{y}")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        """关闭窗口"""
        self.stdout_redirector.stop()
        self.text_handler.stop()
        sys.stdout = self.stdout_redirector.original
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="B站视频总结系统 v2.0 - 图形化界面")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config_path = args.config
    if not Path(config_path).exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    app = BilibiliSummaryGUI(config_path)
    app.run()


if __name__ == "__main__":
    main()
