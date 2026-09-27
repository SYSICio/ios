"""HEAPs IDE - Flet 版

跨平台: Windows / macOS / Linux / iOS / Android / Web

依赖:
    pip install flet

运行:
    flet run ui_flet.py
    或
    python ui_flet.py
"""

import io
import os
import threading
import traceback
import datetime

import flet as ft

from compiler import Compiler
from syntax import HeapvError
from blocks import (
    script_to_blocks, blocks_to_script, classify,
    INSTRUCTION_PANEL, Block,
)


# ============================================================
# 颜色
# ============================================================

BG_DARK = "#1a1a1a"
BG_PANEL = "#2a2a2a"
BG_OUTPUT = "#111111"
BG_HEAP = "#0d0d0d"
BG_SECTION = "#3a3a1a"
BG_INVALID = "#4a1a1a"
FG_TEXT = "#e0e0e0"
FG_GREEN = "#4ec9b0"
FG_YELLOW = "#dcdcaa"
FG_RED = "#f48771"
BTN_BLUE = "#1F6AA5"
BTN_GRAY = "#3a3a3a"
BTN_RED = "#7a2a2a"


# ============================================================
# 工具函数
# ============================================================

def build_text(kind, values):
    """生成脚本行文本,与桌面版一致。"""
    if kind == "new_heap":
        return f"P'{values['length']}\"{values['base']}*{values['id']}"
    if kind == "del_heap":
        return f"De'{values['id']}"
    if kind == "switch":
        return f"T'{values['id']}"
    if kind == "to_base":
        return f"to={values['base']}"
    if kind == "add_left":
        return f"Lp{values['n']}"
    if kind == "add_right":
        return f"Rp{values['n']}"
    if kind == "move_left":
        return f"<{values.get('n', '1')}"
    if kind == "move_right":
        return f">{values.get('n', '1')}"
    if kind == "add":
        return f"+{values.get('n', '1')}"
    if kind == "sub":
        return f"-{values.get('n', '1')}"
    if kind == "create_snapshot":
        return f"Lip'{values['id']}"
    if kind == "delete_snapshot":
        return f"deLip'{values['id']}"
    if kind == "update_snapshot":
        return f"neLip'{values['id']}"
    if kind == "create_active":
        return f"aLip'{values['id']}*{values['interval']}"
    if kind == "print_snapshot":
        return f"pLip'{values['id']}"
    if kind in ("if", "define", "call"):
        return values.get("raw", "")
    return ""


def validate_param(key, value):
    """返回 (ok, msg)。"""
    if value == "":
        return False, f"{key} 不能为空"
    if key == "base" and value not in ("a", "b", "c", "d"):
        return False, "进制必须是 a/b/c/d"
    if key in ("id", "n", "interval", "length"):
        if not value.lstrip("-").isdigit():
            return False, f"{key} 必须是整数"
    return True, ""


def _btn_style(color):
    return ft.ButtonStyle(
        bgcolor=color,
        color="white",
        shape=ft.RoundedRectangleBorder(radius=6),
    )


# ============================================================
# 主应用
# ============================================================

class HEAPsApp:

    def __init__(self, page: ft.Page):
        self.page = page
        self.compiler = Compiler()
        self.running = False
        self.blocks = []
        self._graphics_dirty = False
        self._current_page = "script"
        self.current_file = None

        # FilePicker 必须在 overlay 里注册
        self.file_picker = ft.FilePicker(on_result=self._on_file_result)
        self.page.overlay.append(self.file_picker)

        # 记录当前 FilePicker 操作是"打开"还是"保存"
        self._file_action = None

        self._setup_page()
        self._build_ui()
        self._refresh_heaps()

    # ---------------- 页面设置 ----------------

    def _setup_page(self):
        self.page.title = "HEAPs IDE"
        self.page.bgcolor = BG_DARK
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0
        self.page.window.width = 900
        self.page.window.height = 700

    # ---------------- 构建 UI ----------------

    def _build_ui(self):
        # 顶部工具栏
        self.toolbar = ft.Container(
            bgcolor=BG_PANEL,
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            content=ft.Row(
                controls=[
                    self._btn("▶ 运行", self.on_run, BTN_BLUE),
                    self._btn("清空", self.on_clear_output, BTN_GRAY),
                    self._btn("打开", self.on_open, BTN_GRAY),
                    self._btn("保存", self.on_save, BTN_GRAY),
                ],
                spacing=6,
            ),
        )

        # 分页栏
        self.btn_script = self._btn(
            "脚本", lambda e: self.switch_page("script"), BTN_BLUE)
        self.btn_graphics = self._btn(
            "图形", lambda e: self.switch_page("graphics"), BTN_GRAY)

        self.tab_bar = ft.Container(
            bgcolor=BG_DARK,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            content=ft.Row(
                controls=[self.btn_script, self.btn_graphics],
                spacing=6,
            ),
        )

        # ---------- 脚本页 ----------
        self.editor = ft.TextField(
            multiline=True,
            min_lines=8,
            max_lines=8,
            text_style=ft.TextStyle(
                font_family="Consolas", size=13, color=FG_TEXT),
            bgcolor=BG_PANEL,
            border_color=BG_PANEL,
            value="",
            expand=True,
        )

        self.output = ft.TextField(
            multiline=True,
            min_lines=6,
            max_lines=6,
            read_only=True,
            text_style=ft.TextStyle(
                font_family="Consolas", size=12, color=FG_GREEN),
            bgcolor=BG_OUTPUT,
            border_color=BG_OUTPUT,
            value="",
            expand=True,
        )

        self.heap_view = ft.TextField(
            multiline=True,
            min_lines=6,
            max_lines=6,
            read_only=True,
            text_style=ft.TextStyle(
                font_family="Consolas", size=11, color=FG_YELLOW),
            bgcolor=BG_HEAP,
            border_color=BG_HEAP,
            value="",
            expand=True,
        )

        self.script_page = ft.Column(
            controls=[
                ft.Text("脚本编辑器", color=FG_TEXT, size=12,
                        weight=ft.FontWeight.BOLD),
                self.editor,
                ft.Text("输出", color=FG_TEXT, size=12,
                        weight=ft.FontWeight.BOLD),
                self.output,
                ft.Text("堆与位表", color=FG_TEXT, size=12,
                        weight=ft.FontWeight.BOLD),
                self.heap_view,
            ],
            spacing=6,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        # ---------- 图形页 ----------
        self.blocks_list = ft.ListView(spacing=4, expand=True, padding=4)

        self.graphics_page = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        self._btn("插入指令", self.on_insert_instruction, BTN_BLUE),
                        self._btn("新建分区", self.on_new_section, BTN_GRAY),
                        self._btn("刷新", self.on_refresh_blocks, BTN_GRAY),
                    ],
                    spacing=6,
                ),
                self.blocks_list,
            ],
            spacing=6,
            expand=True,
            visible=False,
        )

        # ---------- 主布局 ----------
        self.page.add(
            ft.Column(
                controls=[
                    self.toolbar,
                    self.tab_bar,
                    ft.Container(
                        content=self.script_page,
                        expand=True,
                        padding=8,
                    ),
                    ft.Container(
                        content=self.graphics_page,
                        expand=True,
                        padding=8,
                    ),
                ],
                spacing=0,
                expand=True,
            )
        )

    def _btn(self, text, on_click, color):
        return ft.ElevatedButton(
            text=text,
            on_click=on_click,
            style=_btn_style(color),
            height=36,
        )

    def _set_btn_color(self, btn, color):
        btn.style = _btn_style(color)

    # ---------------- 分页 ----------------

    def switch_page(self, page):
        if page == self._current_page:
            return

        if page == "graphics":
            self._parse_script_to_blocks()
            self.script_page.visible = False
            self.graphics_page.visible = True
            self._set_btn_color(self.btn_script, BTN_GRAY)
            self._set_btn_color(self.btn_graphics, BTN_BLUE)
        else:
            if self._graphics_dirty:
                self._sync_blocks_to_editor()
                self._graphics_dirty = False
            self.script_page.visible = True
            self.graphics_page.visible = False
            self._set_btn_color(self.btn_script, BTN_BLUE)
            self._set_btn_color(self.btn_graphics, BTN_GRAY)

        self._current_page = page
        self.page.update()

    # ---------------- 脚本 <-> 积木 ----------------

    def _parse_script_to_blocks(self):
        self.blocks = script_to_blocks(self.editor.value or "")
        self._render_blocks()

    def _sync_blocks_to_editor(self):
        self.editor.value = blocks_to_script(self.blocks)
        self.page.update()

    def on_refresh_blocks(self, e):
        self._parse_script_to_blocks()

    def _render_blocks(self):
        self.blocks_list.controls.clear()

        if not self.blocks:
            self.blocks_list.controls.append(
                ft.Text("(无积木)", color="#888888")
            )
        else:
            for i, b in enumerate(self.blocks):
                self.blocks_list.controls.append(self._make_block_row(i, b))

        self.page.update()

    def _make_block_row(self, index, block):
        _, label, _ = classify(block.text)

        if block.kind == "section":
            bg = BG_SECTION
        elif block.kind == "invalid":
            bg = BG_INVALID
        else:
            bg = BG_PANEL

        return ft.Container(
            bgcolor=bg,
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(label, color=FG_TEXT, size=13),
                            ft.Text(block.text, color="#999999", size=11),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.EDIT,
                        icon_color=FG_TEXT,
                        icon_size=18,
                        on_click=lambda e, idx=index: self._edit_block(idx),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_UPWARD,
                        icon_color=FG_TEXT,
                        icon_size=18,
                        on_click=lambda e, idx=index: self._move_block(idx, -1),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_DOWNWARD,
                        icon_color=FG_TEXT,
                        icon_size=18,
                        on_click=lambda e, idx=index: self._move_block(idx, 1),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        icon_color=FG_RED,
                        icon_size=18,
                        on_click=lambda e, idx=index: self._delete_block(idx),
                    ),
                ],
                spacing=2,
            ),
        )

    # ---------------- 积木操作 ----------------

    def _edit_block(self, index):
        b = self.blocks[index]

        if b.kind == "section":
            field = ft.TextField(value=b.section or "", label="分区名")
        else:
            field = ft.TextField(value=b.text, label="脚本行")

        def on_ok(e):
            new = (field.value or "").strip()
            if new == "":
                return
            if b.kind == "section":
                b.text = f"Ns*{new}"
                b.section = new
                b.original_line = b.text
            else:
                kind, _, _ = classify(new)
                b.kind = kind
                b.text = new
                b.original_line = new
            self._graphics_dirty = True
            self._close_dialog()
            self._render_blocks()

        self._show_dialog("编辑积木", [field], on_ok)

    def _move_block(self, index, delta):
        new_index = index + delta
        if new_index < 0 or new_index >= len(self.blocks):
            return
        self.blocks[index], self.blocks[new_index] = \
            self.blocks[new_index], self.blocks[index]
        self._graphics_dirty = True
        self._render_blocks()

    def _delete_block(self, index):
        del self.blocks[index]
        self._graphics_dirty = True
        self._render_blocks()

    def on_new_section(self, e):
        field = ft.TextField(label="分区名")

        def on_ok(ev):
            name = (field.value or "").strip()
            if not name:
                return
            text = f"Ns*{name}"
            b = Block("section", text, section=name, original_line=text)
            self.blocks.append(b)
            self._graphics_dirty = True
            self._close_dialog()
            self._render_blocks()

        self._show_dialog("新建分区", [field], on_ok)

    # ---------------- 插入指令 ----------------

    def on_insert_instruction(self, e):
        all_items = []
        for cat, items in INSTRUCTION_PANEL.items():
            for it in items:
                all_items.append((cat, it))

        names = [f"{cat} / {it[0]}" for cat, it in all_items]

        def on_pick(idx):
            self._close_dialog()
            self._insert_instruction(all_items[idx])

        self._show_picker("插入指令", names, on_pick)

    def _insert_instruction(self, target):
        cat, item = target
        name, kind, default_text, params = item

        if not params:
            self._add_block(kind, default_text)
            return

        fields = {}
        controls = []
        for key, default, desc in params:
            f = ft.TextField(label=desc, value=default)
            fields[key] = f
            controls.append(f)

        error_text = ft.Text("", color=FG_RED, size=11)
        controls.append(error_text)

        def on_ok(e):
            values = {}
            for key, f in fields.items():
                v = (f.value or "").strip()
                ok, msg = validate_param(key, v)
                if not ok:
                    error_text.value = msg
                    self.page.update()
                    return
                values[key] = v

            text = build_text(kind, values)
            if not text:
                return
            self._close_dialog()
            self._add_block(kind, text)

        self._show_dialog(name, controls, on_ok)

    def _add_block(self, kind, text):
        b = Block(kind, text, original_line=text)
        self.blocks.append(b)
        self._graphics_dirty = True
        self._render_blocks()

    # ---------------- 通用弹窗 ----------------

    def _show_dialog(self, title, controls, on_ok):
        def close(e=None):
            self._close_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Column(controls, tight=True, spacing=8),
            actions=[
                ft.TextButton("取消", on_click=close),
                ft.TextButton("确定", on_click=on_ok),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dialog)

    def _close_dialog(self):
        if getattr(self.page, "dialog", None):
            self.page.close(self.page.dialog)

    def _show_picker(self, title, items, callback):
        list_view = ft.ListView(spacing=2, height=min(400, 40 * len(items)))

        def make_handler(idx):
            def handler(e):
                callback(idx)
            return handler

        for i, name in enumerate(items):
            list_view.controls.append(
                ft.ListTile(
                    title=ft.Text(name, color=FG_TEXT),
                    on_click=make_handler(i),
                )
            )

        def close(e=None):
            self._close_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Container(content=list_view, width=340),
            actions=[ft.TextButton("取消", on_click=close)],
        )
        self.page.open(dialog)

    # ---------------- 运行 ----------------

    def on_run(self, e):
        if self.running:
            return

        if self._graphics_dirty and self._current_page == "graphics":
            self._sync_blocks_to_editor()
            self._graphics_dirty = False

        code = self.editor.value or ""
        self.running = True
        self.output.value = f"--- 运行 @ {self._now()} ---\n"
        self.page.update()

        def worker():
            buf = io.StringIO()
            try:
                self.compiler.run(code, out=buf)
            except HeapvError as ex:
                buf.write(f"[错误] {ex}\n")
            except RecursionError:
                buf.write("[错误] 递归太深,可能无限递归\n")
            except Exception as ex:
                buf.write(f"[内部错误] {type(ex).__name__}: {ex}\n")
                buf.write(traceback.format_exc())
            finally:
                text = buf.getvalue()
                self.output.value = self.output.value + text
                self.running = False
                self._refresh_heaps()
                self.page.update()

        threading.Thread(target=worker, daemon=True).start()

    def on_clear_output(self, e):
        self.output.value = ""
        self.page.update()

    # ---------------- 堆与位表 ----------------

    def _refresh_heaps(self):
        interp = self.compiler.interpreter
        lines = []

        lines.append("===== 堆 =====")
        if not interp.heaps:
            lines.append("(当前没有堆)")
        else:
            for hid in sorted(interp.heaps):
                h = interp.heaps[hid]
                cur = " ★" if interp.current == hid else ""
                lines.append(f"堆 #{hid}{cur}")
                lines.append(f"  进制: {h.base}   长度: {h.length}   指针: {h.ptr}")
                cells_repr = []
                for i, c in enumerate(h.cells):
                    if i == h.ptr:
                        cells_repr.append(f"<{c}>")
                    else:
                        cells_repr.append(f"[{c}]")
                lines.append("  " + " ".join(cells_repr))
                if h.history:
                    lines.append(f"  操作: {' | '.join(h.history)}")
                lines.append("")

        lines.append("===== 位表 =====")
        if not interp.snapshots:
            lines.append("(当前没有位表)")
        else:
            for sid in sorted(interp.snapshots):
                snap = interp.snapshots[sid]
                if snap.is_active:
                    lines.append(
                        f"● 活动位表 #{sid} (间隔 {snap.interval_ms}ms)")
                else:
                    lines.append(f"○ 静态位表 #{sid}")
                if snap.data:
                    for d in snap.data:
                        cur = " ★" if d["current"] else ""
                        lines.append(
                            f"  堆 #{d['id']}{cur} 进制{d['base']} "
                            f"长度{d['length']} 指针{d['ptr']} 值{d['value']}")
                else:
                    lines.append("  (空)")
                lines.append("")

        self.heap_view.value = "\n".join(lines)
        self.page.update()

    # ---------------- 文件 ----------------

    def on_open(self, e):
        self._file_action = "open"
        self.file_picker.pick_files(
            allow_multiple=False,
            allowed_extensions=["hps", "txt", "py"],
        )

    def on_save(self, e):
        self._file_action = "save"
        # 默认文件名
        default_name = "untitled.hps"
        if self.current_file:
            default_name = os.path.basename(self.current_file)
        self.file_picker.save_file(
            file_name=default_name,
            allowed_extensions=["hps", "txt"],
        )

    def _on_file_result(self, e: ft.FilePickerResultEvent):
        """FilePicker 的回调。"""
        if self._file_action == "open":
            self._handle_open_result(e)
        elif self._file_action == "save":
            self._handle_save_result(e)
        self._file_action = None

    def _handle_open_result(self, e):
        if not e.files:
            return
        f = e.files[0]

        try:
            if f.path:
                with open(f.path, "r", encoding="utf-8") as fp:
                    content = fp.read()
                self.current_file = f.path
            elif f.bytes is not None:
                # Web / iOS 可能只给 bytes
                content = f.bytes.decode("utf-8", errors="replace")
                self.current_file = f.name
            else:
                content = ""
                self.current_file = None

            self.editor.value = content
            self.page.title = f"HEAPs IDE - {f.name}"
            if self._current_page == "graphics":
                self._parse_script_to_blocks()
            self._graphics_dirty = False
            self.page.update()
        except Exception as ex:
            self._show_dialog(
                "打开失败",
                [ft.Text(f"读取文件失败:\n{ex}")],
                lambda ev: self._close_dialog(),
            )

    def _handle_save_result(self, e):
        if not e.path:
            return
        try:
            with open(e.path, "w", encoding="utf-8") as fp:
                fp.write(self.editor.value or "")
            self.current_file = e.path
            self.page.title = f"HEAPs IDE - {os.path.basename(e.path)}"
            self.page.update()
        except Exception as ex:
            self._show_dialog(
                "保存失败",
                [ft.Text(f"写入文件失败:\n{ex}")],
                lambda ev: self._close_dialog(),
            )

    @staticmethod
    def _now():
        return datetime.datetime.now().strftime("%H:%M:%S")


# ============================================================
# 启动
# ============================================================

def main(page: ft.Page):
    HEAPsApp(page)


if __name__ == "__main__":
    ft.app(target=main)
