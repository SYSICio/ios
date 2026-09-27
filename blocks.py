"""图形区积木模型:脚本 <-> 积木 双向转换。"""

import re

BASE_MAP = {"a": 2, "b": 10, "c": 8, "d": 16}
BASE_NAME = {2: "a(二进制)", 10: "b(十进制)", 8: "c(八进制)", 16: "d(十六进制)"}


class Block:
    def __init__(self, kind, text, section=None, original_line=None):
        self.kind = kind
        self.text = text
        self.section = section
        self.original_line = original_line if original_line is not None else text

    def __repr__(self):
        return f"Block({self.kind!r}, {self.text!r}, section={self.section!r})"


# ---------- 指令面板数据 ----------
# 每项: (显示名, kind, 默认文本, 参数提示)
# 参数提示用于弹窗输入,格式: (字段名, 默认值, 说明)
INSTRUCTION_PANEL = {
    "堆操作": [
        ("新建堆", "new_heap", "P'3\"b*1",
         [("length", "3", "长度"), ("base", "b", "进制 a/b/c/d"), ("id", "1", "编号")]),
        ("删除堆", "del_heap", "De'1", [("id", "1", "编号")]),
        ("切换堆", "switch", "T'1", [("id", "1", "编号")]),
        ("转进制", "to_base", "to=b", [("base", "b", "目标进制 a/b/c/d")]),
        ("左侧增减", "add_left", "Lp1", [("n", "1", "格数 -100~100")]),
        ("右侧增减", "add_right", "Rp1", [("n", "1", "格数 -100~100")]),
    ],
    "指针": [
        ("左移", "move_left", "<", [("n", "1", "格数")]),
        ("右移", "move_right", ">", [("n", "1", "格数")]),
    ],
    "数值": [
        ("加", "add", "+1", [("n", "1", "数值,>0")]),
        ("减", "sub", "-1", [("n", "1", "数值,>0")]),
    ],
    "输出": [
        ("输出十进制", "out_uint", "u.", []),
        ("输出 ASCII", "out_ascii", "s.", []),
        ("输出 16 进制", "out_base16", "b.", []),
    ],
    "输入": [
        ("输入数字", "in_num", "i=", []),
        ("输入字符", "in_ascii", "s=", []),
    ],
    "控制": [
        ("循环开始", "loop_start", "{", []),
        ("循环结束", "loop_end", "}", []),
        ("条件", "if", "I:1=0;u.", [("raw", "I:1=0;u.", "整行")]),
        ("空帧", "nop", "[]", []),
    ],
    "宏": [
        ("定义宏", "define", "D:(+);加一.", [("raw", "D:(+);加一.", "整行")]),
        ("调用宏", "call", "加一", [("raw", "加一", "宏名")]),
    ],
    "位表": [
        ("创建位表", "create_snapshot", "Lip'1", [("id", "1", "编号")]),
        ("删除位表", "delete_snapshot", "deLip'1", [("id", "1", "编号")]),
        ("更新位表", "update_snapshot", "neLip'1", [("id", "1", "编号")]),
        ("活动位表", "create_active", "aLip'1*500",
         [("id", "1", "编号"), ("interval", "500", "间隔 ms")]),
        ("输出位表", "print_snapshot", "pLip'1", [("id", "1", "编号")]),
    ],
}


def _count_macro_steps(body):
    if ";" not in body:
        return 0
    steps_part = body.rsplit(";", 1)[0]
    depth = 0
    count = 0
    for ch in steps_part:
        if ch == "(":
            depth += 1
            if depth == 1:
                count += 1
        elif ch == ")":
            depth -= 1
    return count


def classify(text):
    t = text.strip()

    if t.startswith("Ns*"):
        return ("section", f"分区 {t[3:]}", {"name": t[3:]})

    m = re.fullmatch(r"P'(\d+)\"([abcd])\*(\d+)", t)
    if m:
        base = BASE_MAP[m.group(2)]
        return ("new_heap",
                f"新建堆 编号{m.group(3)} 长度{m.group(1)} {BASE_NAME[base]}",
                {"length": m.group(1), "base": m.group(2), "id": m.group(3)})

    m = re.fullmatch(r"De'(\d+)", t)
    if m:
        return ("del_heap", f"删除堆 编号{m.group(1)}", {"id": m.group(1)})

    m = re.fullmatch(r"T'(\d+)", t)
    if m:
        return ("switch", f"切换堆 编号{m.group(1)}", {"id": m.group(1)})

    m = re.fullmatch(r"to=([abcd])", t)
    if m:
        base = BASE_MAP[m.group(1)]
        return ("to_base", f"转进制 → {BASE_NAME[base]}", {"base": m.group(1)})

    m = re.fullmatch(r"Lp(-?\d+)", t)
    if m:
        n = int(m.group(1))
        if n > 0:
            return ("add_left", f"左侧加 {n} 格", {"n": m.group(1)})
        elif n < 0:
            return ("add_left", f"左侧减 {-n} 格", {"n": m.group(1)})
        else:
            return ("add_left", "左侧加 0 格(无操作)", {"n": m.group(1)})

    m = re.fullmatch(r"Rp(-?\d+)", t)
    if m:
        n = int(m.group(1))
        if n > 0:
            return ("add_right", f"右侧加 {n} 格", {"n": m.group(1)})
        elif n < 0:
            return ("add_right", f"右侧减 {-n} 格", {"n": m.group(1)})
        else:
            return ("add_right", "右侧加 0 格(无操作)", {"n": m.group(1)})

    m = re.fullmatch(r"Lip'(\d+)", t)
    if m:
        return ("create_snapshot", f"创建位表 #{m.group(1)}", {"id": m.group(1)})

    m = re.fullmatch(r"deLip'(\d+)", t)
    if m:
        return ("delete_snapshot", f"删除位表 #{m.group(1)}", {"id": m.group(1)})

    m = re.fullmatch(r"neLip'(\d+)", t)
    if m:
        return ("update_snapshot", f"更新位表 #{m.group(1)}", {"id": m.group(1)})

    m = re.fullmatch(r"aLip'(\d+)\*(\d+)", t)
    if m:
        return ("create_active",
                f"创建活动位表 #{m.group(1)} 间隔 {m.group(2)}ms",
                {"id": m.group(1), "interval": m.group(2)})

    m = re.fullmatch(r"pLip'(\d+)", t)
    if m:
        return ("print_snapshot", f"输出位表 #{m.group(1)}", {"id": m.group(1)})

    m = re.fullmatch(r"<(\d*)", t)
    if m:
        n = m.group(1) or "1"
        return ("move_left", f"左移 {n} 格", {"n": n})

    m = re.fullmatch(r">(\d*)", t)
    if m:
        n = m.group(1) or "1"
        return ("move_right", f"右移 {n} 格", {"n": n})

    m = re.fullmatch(r"\+(\d*)", t)
    if m:
        n = m.group(1) or "1"
        if n == "0":
            return ("invalid", "加 0(运行时会报错)", {"n": n})
        return ("add", f"加 {n}", {"n": n})

    m = re.fullmatch(r"-(\d*)", t)
    if m:
        n = m.group(1) or "1"
        if n == "0":
            return ("invalid", "减 0(运行时会报错)", {"n": n})
        return ("sub", f"减 {n}", {"n": n})

    if t == "u.":
        return ("out_uint", "输出十进制", {})
    if t == "s.":
        return ("out_ascii", "输出 ASCII 字符", {})
    if t == "b.":
        return ("out_base16", "输出 16 进制(大写)", {})
    if t == "i=":
        return ("in_num", "输入数字", {})
    if t == "s=":
        return ("in_ascii", "输入 ASCII 字符", {})

    if t.startswith("I:"):
        return ("if", f"条件 {t}", {"raw": t})

    if t.startswith("D:"):
        body = t[2:-1] if t.endswith(".") else t[2:]
        n = _count_macro_steps(body)
        return ("define", f"定义宏 ({n} 步) {t}", {"raw": t})

    if t == "{":
        return ("loop_start", "循环开始 {", {})
    if t == "}":
        return ("loop_end", "循环结束 }", {})
    if t == "[]":
        return ("nop", "空帧 []", {})

    return ("call", f"调用 {t}", {"raw": t})


def script_to_blocks(source: str):
    blocks = []
    current_section = None

    for raw in source.splitlines():
        original = raw
        text = raw.strip()
        if not text:
            continue
        if "#" in text:
            text = text.split("#", 1)[0].strip()
            if not text:
                continue

        kind, label, params = classify(text)
        if kind == "section":
            current_section = params["name"]
            blocks.append(Block("section", text, section=current_section,
                                original_line=original))
        else:
            blocks.append(Block(kind, text, section=current_section,
                                original_line=original))

    return blocks


def blocks_to_script(blocks):
    lines = []
    for b in blocks:
        lines.append(b.original_line)
    return "\n".join(lines) + ("\n" if lines else "")
