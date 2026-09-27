"""HEAPs 语法模块:词法、语法、解释。

语言模型:图灵机风格,多堆共存,各堆独立指针(默认最右)。
每次 run 前完全重置:零个堆、无宏、无位表。

本次新增:
  - to=?        堆转进制,abcd 表示 2/10/8/16,转换后指针最右
  - Lp?/Rp?     左侧/右侧增减格数,? 范围 -100~100,负数减少
  - Lip'?       创建静态位表
  - deLip'?     删除位表
  - neLip'?     更新静态位表,活动位表报错
  - aLip'?*n    创建活动位表,每 n 毫秒自动刷新
  - pLip'?      输出位表内容

设计:
  - 位表和活动位表共用编号空间
  - 活动位表在每条指令执行后检查是否该刷新
  - run() 结束时清空位表,活动位表停止更新
  - 快照记录:堆数量、编号、指针、进制、长度、数值、对该堆的操作历史
"""

import re
import time


# ============================================================
# 错误类
# ============================================================

class HeapvError(Exception):
    def __init__(self, msg, line=None):
        self.line = line
        prefix = f"第 {line} 行: " if line is not None else ""
        super().__init__(prefix + msg)


# ============================================================
# 堆
# ============================================================

class Heap:
    """一个堆:固定长度,指针默认最右。"""

    def __init__(self, heap_id, length, base):
        self.id = heap_id
        self.length = length
        self.base = base
        self.cells = [0] * length
        self.ptr = length - 1
        self.history = []          # 对该堆做过的操作记录

    @property
    def max_value(self):
        return self.base - 1

    def log(self, op):
        self.history.append(op)

    def get(self):
        return self.cells[self.ptr]

    def set(self, v):
        if not (0 <= v <= self.max_value):
            raise HeapvError(
                f"堆 {self.id} 当前格值 {v} 超出范围 0~{self.max_value}"
            )
        self.cells[self.ptr] = v

    def inc(self):
        if self.cells[self.ptr] >= self.max_value:
            raise HeapvError(
                f"堆 {self.id} 当前格已满(最大值 {self.max_value})"
            )
        self.cells[self.ptr] += 1

    def dec(self):
        if self.cells[self.ptr] <= 0:
            raise HeapvError(f"堆 {self.id} 当前格已为 0,无法再减")
        self.cells[self.ptr] -= 1

    def add(self, n):
        """带进位的加法:把堆看成 base 进制大整数,当前指针指向最低位。"""
        if n < 0:
            return self.sub(-n)
        if n == 0:
            return
        i = self.ptr
        carry = n
        while carry > 0:
            if i < 0:
                raise HeapvError(
                    f"堆 {self.id} 最高位溢出,无法继续进位"
                )
            total = self.cells[i] + carry
            self.cells[i] = total % self.base
            carry = total // self.base
            i -= 1
        if carry > 0:
            raise HeapvError(f"堆 {self.id} 最高位溢出,无法继续进位")

    def sub(self, n):
        """带借位的减法:把堆看成 base 进制大整数,当前指针指向最低位。"""
        if n < 0:
            return self.add(-n)
        if n == 0:
            return
        i = self.ptr
        borrow = n
        while borrow > 0:
            if i < 0:
                raise HeapvError(
                    f"堆 {self.id} 最高位借位失败,值不足"
                )
            total = self.cells[i] - borrow
            if total >= 0:
                self.cells[i] = total
                borrow = 0
            else:
                self.cells[i] = total % self.base
                borrow = (-total + self.base - 1) // self.base
                i -= 1
        if borrow > 0:
            raise HeapvError(f"堆 {self.id} 最高位借位失败,值不足")

    def move_left(self, n):
        self.ptr = max(0, self.ptr - n)

    def move_right(self, n):
        self.ptr = min(self.length - 1, self.ptr + n)

    def to_decimal(self):
        val = 0
        for c in self.cells:
            val = val * self.base + c
        return val

    def to_base_string(self, base):
        """按指定进制输出大写字符串。"""
        val = self.to_decimal()
        if val == 0:
            return "0"
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if base > len(digits):
            raise HeapvError(f"不支持输出 {base} 进制")
        out = ""
        while val > 0:
            out = digits[val % base] + out
            val //= base
        return out

    def convert_base(self, new_base):
        """转换进制,总数值不变。位数不够报错,指针移到最右。"""
        v = self.to_decimal()
        # 算新进制下需要多少格
        if v == 0:
            need = 1
        else:
            need = 0
            tmp = v
            while tmp > 0:
                need += 1
                tmp //= new_base
        if need > self.length:
            raise HeapvError(
                f"堆 {self.id} 转 {new_base} 进制需要 {need} 格,"
                f"当前只有 {self.length} 格"
            )
        self.base = new_base
        # 从右往左填
        tmp = v
        for i in range(self.length - 1, -1, -1):
            if tmp > 0:
                self.cells[i] = tmp % new_base
                tmp //= new_base
            else:
                self.cells[i] = 0
        self.ptr = self.length - 1
        self.log(f"to={new_base}")

    def add_left(self, n):
        """左侧增加 n 格(负数减少)。指针保持指向原来的格。"""
        if n == 0:
            return
        if n > 0:
            self.cells = [0] * n + self.cells
            self.length += n
            self.ptr += n
        else:
            m = -n
            if m > self.ptr:
                raise HeapvError(
                    f"堆 {self.id} 左侧减少 {m} 格会删掉指针指向的格"
                )
            self.cells = self.cells[m:]
            self.length -= m
            self.ptr -= m
        self.log(f"Lp{n}")

    def add_right(self, n):
        """右侧增加 n 格(负数减少)。指针不变。"""
        if n == 0:
            return
        if n > 0:
            self.cells = self.cells + [0] * n
            self.length += n
        else:
            m = -n
            if m > self.length - 1 - self.ptr:
                raise HeapvError(
                    f"堆 {self.id} 右侧减少 {m} 格会删掉指针指向的格"
                )
            self.cells = self.cells[:self.length - m]
            self.length -= m
        self.log(f"Rp{n}")

    def __repr__(self):
        return f"Heap(id={self.id}, base={self.base}, len={self.length}, ptr={self.ptr})"


# ============================================================
# 位表 / 活动位表
# ============================================================

class Snapshot:
    """一个位表或活动位表。"""

    def __init__(self, snap_id, is_active=False, interval_ms=0):
        self.id = snap_id
        self.is_active = is_active
        self.interval_ms = interval_ms
        self.last_refresh = 0.0
        self.data = []          # 快照内容:list[dict]

    def capture(self, heaps, current):
        """抓取当前所有堆的状态。"""
        data = []
        for hid in sorted(heaps):
            h = heaps[hid]
            data.append({
                "id": hid,
                "base": h.base,
                "length": h.length,
                "ptr": h.ptr,
                "cells": list(h.cells),
                "value": h.to_decimal(),
                "history": list(h.history),
                "current": (hid == current),
            })
        self.data = data
        self.last_refresh = time.monotonic()

    def format(self):
        """格式化成可读文本。"""
        if not self.data:
            return "(空)"
        lines = []
        for d in self.data:
            cur = " ★" if d["current"] else ""
            lines.append(f"堆 #{d['id']}{cur}")
            lines.append(f"  进制: {d['base']}  长度: {d['length']}  指针: {d['ptr']}")
            lines.append(f"  数值: {d['value']}")
            cells_repr = []
            for i, c in enumerate(d["cells"]):
                if i == d["ptr"]:
                    cells_repr.append(f"<{c}>")
                else:
                    cells_repr.append(f"[{c}]")
            lines.append("  " + " ".join(cells_repr))
            if d["history"]:
                lines.append(f"  操作: {' | '.join(d['history'])}")
            lines.append("")
        return "\n".join(lines)


# ============================================================
# 词法 / 语法
# ============================================================

BASE_MAP = {"a": 2, "b": 10, "c": 8, "d": 16}
BASE_REV = {2: "a", 10: "b", 8: "c", 16: "d"}


class Lexer:
    def __init__(self, source: str):
        self.source = source

    def tokenize(self):
        return self.source.splitlines()


class Parser:
    def __init__(self, lines):
        self.lines = lines

    def parse(self):
        return [(i, line) for i, line in enumerate(self.lines, 1)]


# ============================================================
# 解释器
# ============================================================

class Interpreter:
    def __init__(self):
        self.heaps = {}
        self.current = None
        self.macros = {}
        self.macro_names = set()
        self.snapshots = {}          # 编号 -> Snapshot
        self.call_stack = []
        self.max_depth = 1000
        self.step_budget = 10_000_000
        self.max_heap_length = 1_000_000
        self.max_snapshot_id = 999999
        self.max_interval_ms = 3_600_000

    # ---------------- 对外入口 ----------------
    def run(self, program):
        self.heaps = {}
        self.current = None
        self.macros = {}
        self.macro_names = set()
        self.snapshots = {}
        self.call_stack = []

        lines = self._preprocess(program)
        try:
            self._exec_block(lines, 0, len(lines))
        finally:
            # 运行结束:位表保留,活动位表停止更新
            for snap in self.snapshots.values():
                snap.is_active = False

    # ---------------- 预处理 ----------------
    def _preprocess(self, program):
        result = []
        for line_no, raw in program:
            text = raw.strip()
            if not text:
                continue
            if "#" in text:
                text = text.split("#", 1)[0].strip()
                if not text:
                    continue
            result.append((line_no, text))
        return result

    # ---------------- 执行块 ----------------
    def _exec_block(self, lines, start, end):
        i = start
        steps = 0
        while i < end:
            steps += 1
            if steps > self.step_budget:
                raise HeapvError("执行步数超出上限,可能存在死循环")

            line_no, text = lines[i]

            if text == "{":
                close = self._find_matching(lines, i)
                if close is None:
                    raise HeapvError("缺少配对的 }", line_no)
                while True:
                    self._exec_block(lines, i + 1, close)
                    if self._current_cell() != 0:
                        break
                i = close + 1
                continue

            if text == "}":
                return

            self._exec_line(line_no, text)
            self._refresh_active_snapshots()
            i += 1

    def _find_matching(self, lines, start):
        depth = 0
        for i in range(start, len(lines)):
            _, text = lines[i]
            if text == "{":
                depth += 1
            elif text == "}":
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _current_cell(self):
        if self.current is None:
            return 0
        heap = self.heaps.get(self.current)
        return heap.get() if heap else 0

    def _refresh_active_snapshots(self):
        """检查所有活动位表,到时间就刷新。"""
        now = time.monotonic()
        for snap in self.snapshots.values():
            if not snap.is_active:
                continue
            if (now - snap.last_refresh) * 1000 >= snap.interval_ms:
                snap.capture(self.heaps, self.current)

    # ---------------- 单行执行 ----------------
    def _exec_line(self, line_no, text):
        if text in self.macros:
            try:
                self._call_macro(line_no, text, [])
            except HeapvError:
                raise
            except Exception as e:
                raise HeapvError(f"内部错误: {e}", line_no)
            return
        parts = text.split()
        if parts and parts[0] in self.macros:
            try:
                self._call_macro(line_no, parts[0], parts[1:])
            except HeapvError:
                raise
            except Exception as e:
                raise HeapvError(f"内部错误: {e}", line_no)
            return

        try:
            self._dispatch(line_no, text)
        except HeapvError as e:
            if e.line is None:
                raise HeapvError(str(e).split(": ", 1)[-1], line_no)
            raise
        except Exception as e:
            raise HeapvError(f"内部错误: {e}", line_no)

    # ---------------- 指令分派 ----------------
    def _dispatch(self, line_no, text):
        if text.startswith("D:"):
            self._op_define(line_no, text); return
        if text.startswith("I:"):
            self._op_if(line_no, text); return
        if text.startswith("P'"):
            self._op_new_heap(line_no, text); return
        if text.startswith("De'"):
            self._op_del_heap(line_no, text); return
        if text.startswith("T'"):
            self._op_switch(line_no, text); return
        if text.startswith("to="):
            self._op_to_base(line_no, text); return
        if text.startswith("Lp"):
            self._op_add_left(line_no, text); return
        if text.startswith("Rp"):
            self._op_add_right(line_no, text); return
        if text.startswith("deLip'"):
            self._op_delete_snapshot(line_no, text); return
        if text.startswith("neLip'"):
            self._op_update_snapshot(line_no, text); return
        if text.startswith("aLip'"):
            self._op_create_active(line_no, text); return
        if text.startswith("Lip'"):
            self._op_create_snapshot(line_no, text); return
        if text.startswith("pLip'"):
            self._op_print_snapshot(line_no, text); return
        if text.startswith("Ns*"):
            self._op_section(line_no, text); return
        if text.startswith("<"):
            self._op_move(line_no, text, left=True); return
        if text.startswith(">"):
            self._op_move(line_no, text, left=False); return
        if text == "u.":
            self._op_out_uint(line_no); return
        if text == "s.":
            self._op_out_ascii(line_no); return
        if text == "b.":
            self._op_out_base16(line_no); return
        if text == "i=":
            self._op_in_num(line_no); return
        if text == "s=":
            self._op_in_ascii(line_no); return
        if text.startswith("+"):
            self._op_inc(line_no, text); return
        if text.startswith("-"):
            self._op_dec(line_no, text); return
        if text == "[]":
            return
        if text in ("{", "}"):
            return
        raise HeapvError(f"无法识别的指令: {text!r}", line_no)

    # ---------------- 宏定义解析 ----------------

    def _parse_macro_define(self, body, line_no):
        if ";" not in body:
            raise HeapvError("宏定义缺少 ; 分隔宏体和宏名", line_no)
        steps_part, name = body.rsplit(";", 1)
        steps_part = steps_part.strip()
        name = name.strip()

        if not name:
            raise HeapvError("宏名不能为空", line_no)

        steps = []
        i = 0
        n = len(steps_part)
        while i < n:
            if steps_part[i].isspace():
                i += 1
                continue
            if steps_part[i] != "(":
                raise HeapvError(
                    f"宏体步骤必须以 ( 开头,位置 {i}: {steps_part[i:]!r}",
                    line_no,
                )
            depth = 0
            j = i
            while j < n:
                if steps_part[j] == "(":
                    depth += 1
                elif steps_part[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n:
                raise HeapvError(
                    f"宏体步骤缺少配对的 ): {steps_part[i:]!r}",
                    line_no,
                )
            inner = steps_part[i + 1:j].strip()
            if not inner:
                raise HeapvError("宏体步骤不能为空", line_no)
            steps.append(inner)
            i = j + 1

        if not steps:
            raise HeapvError("宏体至少需要一个步骤", line_no)

        return steps, name

    def _op_define(self, line_no, text):
        if not text.endswith("."):
            raise HeapvError("宏定义必须以 . 结束", line_no)
        body = text[2:-1].strip()
        steps, name = self._parse_macro_define(body, line_no)

        if name in self.macro_names or self._looks_like_instruction(name):
            raise HeapvError("您似乎创建了重名的代码宏。", line_no)

        self.macros[name] = steps
        self.macro_names.add(name)

    def _looks_like_instruction(self, name):
        prefixes = ("D:", "I:", "P'", "De'", "T'", "to=", "Lp", "Rp",
                    "Lip'", "deLip'", "neLip'", "aLip'", "pLip'",
                    "Ns*", "<", ">", "u.", "s.", "b.", "i=", "s=",
                    "+", "-", "#", "[", "]", "{", "}")
        return any(name == p or name.startswith(p) for p in prefixes)

    # ---------------- 宏调用 ----------------

    def _call_macro(self, line_no, name, args):
        if len(self.call_stack) >= self.max_depth:
            raise HeapvError(f"宏递归深度超过 {self.max_depth},可能无限递归", line_no)

        steps = self.macros[name]

        bindings = {}
        for a in args:
            if "_" not in a or not a.startswith("@"):
                raise HeapvError(f"参数格式错误: {a!r}(应为 @n_值)", line_no)
            key, val = a.split("_", 1)
            bindings[key] = val

        used = set()
        for step in steps:
            used.update(re.findall(r"@[0-9A-Za-z]", step))

        for key in used:
            if key not in bindings:
                raise HeapvError(f"参数 {key} 未被赋值", line_no)
        extra = set(bindings) - used
        if extra:
            raise HeapvError(f"多传了参数: {', '.join(sorted(extra))}", line_no)

        self.call_stack.append(name)
        try:
            for step in steps:
                expanded = re.sub(
                    r"@[0-9A-Za-z]",
                    lambda m: bindings[m.group(0)],
                    step,
                )
                sub_lines = []
                for sub in expanded.split(";"):
                    sub = sub.strip()
                    if sub:
                        sub_lines.append((line_no, sub))
                if sub_lines:
                    self._exec_block(sub_lines, 0, len(sub_lines))
        finally:
            self.call_stack.pop()

    # ---------------- 其他指令 ----------------

    def _op_if(self, line_no, text):
        if not text.endswith("."):
            raise HeapvError("I: 指令必须以 . 结束", line_no)
        body = text[2:-1]
        if ";" not in body:
            raise HeapvError("I: 缺少 ; ", line_no)
        cond, code = body.split(";", 1)
        cond, code = cond.strip(), code.strip()

        if "=" not in cond:
            raise HeapvError("I: 条件缺少 = ", line_no)
        heap_id_s, val_s = cond.split("=", 1)
        try:
            heap_id = int(heap_id_s.strip())
        except ValueError:
            raise HeapvError(f"I: 堆号不是整数: {heap_id_s!r}", line_no)
        try:
            val = int(val_s.strip())
        except ValueError:
            raise HeapvError(f"I: 值不是整数: {val_s!r}", line_no)

        if heap_id not in self.heaps:
            raise HeapvError(f"堆 {heap_id} 不存在", line_no)

        if self.heaps[heap_id].get() == val:
            sub = [(line_no, s.strip()) for s in code.split(";") if s.strip()]
            self._exec_block(sub, 0, len(sub))

    def _op_new_heap(self, line_no, text):
        m = re.fullmatch(r"P'(\d+)\"([abcd])\*(\d+)", text)
        if not m:
            raise HeapvError("P' 格式错误,应为 P'长度\"进制*编号", line_no)
        length = int(m.group(1))
        base = BASE_MAP[m.group(2)]
        heap_id = int(m.group(3))

        if length <= 0:
            raise HeapvError("堆长度必须大于 0", line_no)
        if length > self.max_heap_length:
            raise HeapvError(f"堆长度超过上限 {self.max_heap_length}", line_no)
        if heap_id in self.heaps:
            raise HeapvError("你已经创建过该编号了", line_no)

        self.heaps[heap_id] = Heap(heap_id, length, base)
        if self.current is None:
            self.current = heap_id

    def _op_del_heap(self, line_no, text):
        m = re.fullmatch(r"De'(\d+)", text)
        if not m:
            raise HeapvError("De' 格式错误", line_no)
        heap_id = int(m.group(1))
        if heap_id not in self.heaps:
            raise HeapvError(f"堆 {heap_id} 不存在", line_no)
        del self.heaps[heap_id]
        if self.current == heap_id:
            self.current = next(iter(self.heaps), None)

    def _op_switch(self, line_no, text):
        m = re.fullmatch(r"T'(\d+)", text)
        if not m:
            raise HeapvError("T' 格式错误", line_no)
        heap_id = int(m.group(1))
        if heap_id not in self.heaps:
            raise HeapvError(f"堆 {heap_id} 不存在", line_no)
        self.current = heap_id
        self.heaps[heap_id].log(f"T'{heap_id}")

    def _op_section(self, line_no, text):
        return

    def _op_move(self, line_no, text, left):
        m = re.fullmatch(r"[<>](\d*)", text)
        if not m:
            raise HeapvError("移动指令格式错误", line_no)
        n = int(m.group(1)) if m.group(1) else 1
        heap = self._require_heap(line_no)
        if left:
            heap.move_left(n)
        else:
            heap.move_right(n)
        heap.log(text)

    def _op_to_base(self, line_no, text):
        m = re.fullmatch(r"to=([abcd])", text)
        if not m:
            raise HeapvError("to= 格式错误,应为 to=a/b/c/d", line_no)
        new_base = BASE_MAP[m.group(1)]
        heap = self._require_heap(line_no)
        if heap.base == new_base:
            return
        heap.convert_base(new_base)

    def _op_add_left(self, line_no, text):
        m = re.fullmatch(r"Lp(-?\d+)", text)
        if not m:
            raise HeapvError("Lp 格式错误,应为 Lp? (? 为整数)", line_no)
        n = int(m.group(1))
        if not (-100 <= n <= 100):
            raise HeapvError("Lp 的数值必须在 -100 ~ 100 之间", line_no)
        heap = self._require_heap(line_no)
        new_len = heap.length + n
        if new_len <= 0:
            raise HeapvError(f"Lp{n} 后堆长度会变成 {new_len},不允许", line_no)
        if new_len > self.max_heap_length:
            raise HeapvError(f"Lp{n} 后堆长度超过上限 {self.max_heap_length}", line_no)
        heap.add_left(n)

    def _op_add_right(self, line_no, text):
        m = re.fullmatch(r"Rp(-?\d+)", text)
        if not m:
            raise HeapvError("Rp 格式错误,应为 Rp? (? 为整数)", line_no)
        n = int(m.group(1))
        if not (-100 <= n <= 100):
            raise HeapvError("Rp 的数值必须在 -100 ~ 100 之间", line_no)
        heap = self._require_heap(line_no)
        new_len = heap.length + n
        if new_len <= 0:
            raise HeapvError(f"Rp{n} 后堆长度会变成 {new_len},不允许", line_no)
        if new_len > self.max_heap_length:
            raise HeapvError(f"Rp{n} 后堆长度超过上限 {self.max_heap_length}", line_no)
        heap.add_right(n)

    # ---------------- 位表 / 活动位表 ----------------

    def _parse_snapshot_id(self, s, line_no):
        try:
            sid = int(s)
        except ValueError:
            raise HeapvError(f"位表编号不是整数: {s!r}", line_no)
        if not (0 <= sid <= self.max_snapshot_id):
            raise HeapvError(f"位表编号必须在 0 ~ {self.max_snapshot_id}", line_no)
        return sid

    def _op_create_snapshot(self, line_no, text):
        m = re.fullmatch(r"Lip'(\d+)", text)
        if not m:
            raise HeapvError("Lip' 格式错误,应为 Lip'编号", line_no)
        sid = self._parse_snapshot_id(m.group(1), line_no)
        if sid in self.snapshots:
            raise HeapvError(f"位表编号 {sid} 已存在", line_no)
        snap = Snapshot(sid, is_active=False)
        snap.capture(self.heaps, self.current)
        self.snapshots[sid] = snap

    def _op_delete_snapshot(self, line_no, text):
        m = re.fullmatch(r"deLip'(\d+)", text)
        if not m:
            raise HeapvError("deLip' 格式错误,应为 deLip'编号", line_no)
        sid = self._parse_snapshot_id(m.group(1), line_no)
        if sid not in self.snapshots:
            raise HeapvError(f"位表编号 {sid} 不存在", line_no)
        del self.snapshots[sid]

    def _op_update_snapshot(self, line_no, text):
        m = re.fullmatch(r"neLip'(\d+)", text)
        if not m:
            raise HeapvError("neLip' 格式错误,应为 neLip'编号", line_no)
        sid = self._parse_snapshot_id(m.group(1), line_no)
        if sid not in self.snapshots:
            raise HeapvError(f"位表编号 {sid} 不存在", line_no)
        snap = self.snapshots[sid]
        if snap.is_active:
            raise HeapvError("你试图更新的位表是活动位表，不能被更新", line_no)
        snap.capture(self.heaps, self.current)

    def _op_create_active(self, line_no, text):
        m = re.fullmatch(r"aLip'(\d+)\*(\d+)", text)
        if not m:
            raise HeapvError("aLip' 格式错误,应为 aLip'编号*间隔", line_no)
        sid = self._parse_snapshot_id(m.group(1), line_no)
        interval = int(m.group(2))
        if interval <= 0:
            raise HeapvError("活动位表的间隔不能为 0", line_no)
        if interval > self.max_interval_ms:
            raise HeapvError(f"间隔超过上限 {self.max_interval_ms} ms", line_no)
        if sid in self.snapshots:
            raise HeapvError(f"位表编号 {sid} 已存在", line_no)
        snap = Snapshot(sid, is_active=True, interval_ms=interval)
        snap.capture(self.heaps, self.current)
        self.snapshots[sid] = snap

    def _op_print_snapshot(self, line_no, text):
        m = re.fullmatch(r"pLip'(\d+)", text)
        if not m:
            raise HeapvError("pLip' 格式错误,应为 pLip'编号", line_no)
        sid = self._parse_snapshot_id(m.group(1), line_no)
        if sid not in self.snapshots:
            raise HeapvError(f"位表编号 {sid} 不存在", line_no)
        snap = self.snapshots[sid]
        kind = "活动位表" if snap.is_active else "静态位表"
        print(f"=== 位表 #{sid} ({kind}) ===")
        print(snap.format())

    # ---------------- 输出 / 输入 ----------------

    def _op_out_uint(self, line_no):
        heap = self._require_heap(line_no)
        print(heap.to_decimal())
        heap.log("u.")

    def _op_out_ascii(self, line_no):
        heap = self._require_heap(line_no)
        code = heap.to_decimal()
        if not (0 <= code <= 0x10FFFF):
            raise HeapvError(f"值 {code} 不是合法码位", line_no)
        if 0xD800 <= code <= 0xDFFF:
            raise HeapvError(f"值 {code} 落在代理区,无法作为字符输出", line_no)
        print(chr(code))
        heap.log("s.")

    def _op_out_base16(self, line_no):
        heap = self._require_heap(line_no)
        if heap.base != 16:
            raise HeapvError(
                f"b. 只能用于 16 进制堆,当前堆 {heap.id} 是 {heap.base} 进制",
                line_no,
            )
        print(heap.to_base_string(16))
        heap.log("b.")

    def _op_in_num(self, line_no):
        heap = self._require_heap(line_no)
        s = input()
        if not s.lstrip("-").isdigit():
            raise HeapvError("输入必须是数字", line_no)
        v = int(s)
        if not (0 <= v <= heap.max_value):
            raise HeapvError(f"输入 {v} 超出当前格范围 0~{heap.max_value}", line_no)
        heap.set(v)
        heap.log("i=")

    def _op_in_ascii(self, line_no):
        heap = self._require_heap(line_no)
        s = input()
        if len(s) != 1:
            raise HeapvError("请输入单个字符", line_no)
        v = ord(s)
        if v > heap.max_value:
            raise HeapvError(f"字符码 {v} 超出当前格范围", line_no)
        heap.set(v)
        heap.log("s=")

    def _op_inc(self, line_no, text):
        m = re.fullmatch(r"\+(\d*)", text)
        if not m:
            raise HeapvError("+ 指令格式错误", line_no)
        n = int(m.group(1)) if m.group(1) else 1
        if n <= 0:
            raise HeapvError("+ 的数值必须大于 0", line_no)
        heap = self._require_heap(line_no)
        heap.add(n)
        heap.log(text)

    def _op_dec(self, line_no, text):
        m = re.fullmatch(r"-(\d*)", text)
        if not m:
            raise HeapvError("- 指令格式错误", line_no)
        n = int(m.group(1)) if m.group(1) else 1
        if n <= 0:
            raise HeapvError("- 的数值必须大于 0", line_no)
        heap = self._require_heap(line_no)
        heap.sub(n)
        heap.log(text)

    def _require_heap(self, line_no):
        if self.current is None:
            raise HeapvError("当前没有堆,请先用 P' 创建并 T' 切换", line_no)
        return self.heaps[self.current]
