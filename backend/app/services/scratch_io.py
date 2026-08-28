"""手撕模式 IO：ACM/OJ 风格数字输入，而不是 JSON。"""
from __future__ import annotations

import json
from typing import Any


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def encode_value(v: Any) -> str:
    """把单个参数编成 stdin 文本（末尾带换行）。"""
    if isinstance(v, bool):
        return f"{1 if v else 0}\n"
    if isinstance(v, (int, float)):
        return f"{v}\n"
    if isinstance(v, str):
        return v + "\n"
    if isinstance(v, list):
        if not v:
            return "0\n"
        if isinstance(v[0], list):
            n = len(v)
            same_len = all(isinstance(row, list) and len(row) == len(v[0]) for row in v)
            if same_len:
                m = len(v[0])
                lines = [f"{n} {m}"]
                for row in v:
                    lines.append(" ".join(_scalar(x) for x in row))
                return "\n".join(lines) + "\n"
            lines = [str(n)]
            for row in v:
                row = row or []
                lines.append(f"{len(row)} " + " ".join(_scalar(x) for x in row) if row else "0")
            return "\n".join(lines) + "\n"
        if all(isinstance(x, str) for x in v):
            return str(len(v)) + "\n" + "".join(x + "\n" for x in v)
        return f"{len(v)}\n" + " ".join(_scalar(x) for x in v) + "\n"
    raise TypeError(f"不支持的手撕输入类型: {type(v).__name__}")


def encode_scratch_stdin(args: list[Any]) -> str:
    return "".join(encode_value(a) for a in args)


def encode_scratch_stdout(value: Any) -> str:
    """样例输出展示用：一维数组空格分隔，二维按行。"""
    if isinstance(value, bool):
        return "1\n" if value else "0\n"
    if isinstance(value, (int, float, str)):
        return f"{value}\n"
    if isinstance(value, list):
        if not value:
            return "\n"
        if isinstance(value[0], list):
            return "".join(" ".join(_scalar(x) for x in row) + "\n" for row in value)
        if all(isinstance(x, str) for x in value):
            return "".join(x + "\n" for x in value)
        return " ".join(_scalar(x) for x in value) + "\n"
    return json.dumps(value, ensure_ascii=False) + "\n"


def parse_scratch_stdout(stdout: str, return_type: str = "list[int]") -> Any:
    text = (stdout or "").strip()
    if not text:
        raise ValueError("标准输出为空")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    json_candidates: list[str] = []
    if return_type in ("int", "float", "bool", "str"):
        json_candidates.extend((lines[-1], text))
    else:
        if text.lstrip()[:1] in "[{":
            json_candidates.append(text)
        if lines[-1][:1] in "[{":
            json_candidates.append(lines[-1])
    seen: set[str] = set()
    for candidate in json_candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return _parse_oj(text, return_type)


def _parse_num(tok: str) -> int | float:
    if tok in ("true", "false"):
        return tok == "true"
    if "." in tok or "e" in tok or "E" in tok:
        return float(tok)
    return int(tok)


def _parse_oj(text: str, return_type: str) -> Any:
    if return_type == "str":
        return text.strip()
    if return_type == "list[str]":
        lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        if lines and lines[0].strip().isdigit() and int(lines[0]) == len(lines) - 1:
            return lines[1:]
        return lines
    tokens = text.split()
    if return_type == "void":
        return [_parse_num(t) for t in tokens]
    if return_type == "bool":
        if not tokens:
            raise ValueError("输出为空")
        t = tokens[0].lower()
        if t in ("1", "true"):
            return True
        if t in ("0", "false"):
            return False
        raise ValueError(f"无法解析布尔值: {tokens[0]}")
    if return_type in ("int", "float"):
        if not tokens:
            raise ValueError("输出为空")
        n = _parse_num(tokens[0])
        return int(n) if return_type == "int" else float(n)
    if return_type == "list[int]":
        return [int(_parse_num(t)) for t in tokens]
    if return_type == "list[float]":
        return [float(_parse_num(t)) for t in tokens]
    if return_type == "list[bool]":
        return [bool(int(_parse_num(t))) if t not in ("true", "false") else t == "true" for t in tokens]
    if return_type == "list[list[int]]":
        rows = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            rows.append([int(_parse_num(t)) for t in ln.split()])
        if len(rows) >= 2 and len(rows[0]) == 2 and all(len(r) == rows[0][1] for r in rows[1:]):
            # 可能是「n m + 矩阵」把头两行尺寸写进去了，去掉尺寸行
            n, m = rows[0]
            if n == len(rows) - 1:
                return rows[1:]
        return rows
    return [_parse_num(t) for t in tokens]


def scratch_return_type(cfg: dict | None) -> str:
    if not cfg:
        return "list[int]"
    from app.services.code_lang import method_types

    param_types, ret, is_void = method_types(cfg)
    if is_void and param_types:
        return param_types[0]
    return ret


def build_io_hint(cfg: dict) -> str:
    params = cfg.get("params") or []
    examples = cfg.get("examples") or []
    order = "，".join(params) if params else "见题面"
    head = (
        "手撕模式按 ACM/OJ 习惯喂数字，不是 JSON。\n"
        f"· 输入按参数顺序（{order}）：一维数组先给长度 n，再给 n 个数；单个数字单独一行。\n"
        "· 输出把数字用空格或换行分开即可（也兼容 JSON）。\n"
        "· 原地修改题：请输出修改后的数组。\n"
    )
    if not examples:
        return head + "头文件/常用库已预置，请自行编写完整逻辑与输入输出。"
    stdin = encode_scratch_stdin(examples[0]["args"]).rstrip("\n")
    stdout = encode_scratch_stdout(examples[0]["expected"]).rstrip("\n")
    return (
        head
        + f"· 第 1 组样例输入：\n{stdin}\n"
        + f"· 对应输出：\n{stdout}\n"
        + "头文件/常用库已预置，请自行编写完整逻辑与输入输出。"
    )
