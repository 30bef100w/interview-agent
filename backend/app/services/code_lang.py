"""多语言模板与类型推断：根据示例参数/期望值生成 Python/Java/C++/Go 签名与字面量。"""
from __future__ import annotations

import re
from typing import Any

SUPPORTED_LANGS = ("python", "java", "cpp", "go")
CODING_MODES = ("function", "scratch")

LANG_META = {
    "python": {"label": "Python 3", "monaco": "python", "filename": "solution.py"},
    "java": {"label": "Java", "monaco": "java", "filename": "Solution.java"},
    "cpp": {"label": "C++", "monaco": "cpp", "filename": "solution.cpp"},
    "go": {"label": "Go", "monaco": "go", "filename": "solution.go"},
}

# 手撕模式文件名（Java 必须是 Main）
SCRATCH_FILENAME = {
    "python": "main.py",
    "java": "Main.java",
    "cpp": "main.cpp",
    "go": "main.go",
}

IO_HINT = (
    "手撕模式按 ACM/OJ 习惯喂数字，不是 JSON。\n"
    "· 输入：一维数组先给长度 n，再给 n 个数；单个数字单独一行。\n"
    "· 输出：数字用空格或换行分开即可（也兼容 JSON）。\n"
    "· 若为原地修改题：请输出修改后的数组。\n"
    "头文件/常用库已预置，请自行编写完整逻辑与输入输出。"
)


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "list[int]"
        inner = infer_type(value[0])
        # 混合类型时退化为 JSON 友好的 list[int]/list[str]
        for x in value[1:]:
            if infer_type(x) != inner:
                if all(isinstance(i, (int, float)) and not isinstance(i, bool) for i in value):
                    return "list[int]"
                if all(isinstance(i, str) for i in value):
                    return "list[str]"
                raise TypeError(f"不支持的混合列表类型: {value!r}")
        return f"list[{inner}]"
    raise TypeError(f"不支持的类型: {type(value).__name__}")


def detect_void(reference: str | None) -> bool:
    """参考解若没有 `return <值>`，视为原地修改（void）。"""
    if not reference:
        return False
    stripped = re.sub(r"#.*", "", reference)
    stripped = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", stripped)
    return re.search(r"\breturn\b\s+\S", stripped) is None


def method_types(cfg: dict) -> tuple[list[str], str, bool]:
    """返回 (param_types, return_type, is_void)。"""
    examples = cfg.get("examples") or []
    if not examples:
        params = cfg.get("params") or []
        return ["int"] * len(params), "int", False
    args = examples[0]["args"]
    expected = examples[0]["expected"]
    param_types = [infer_type(a) for a in args]
    is_void = detect_void(cfg.get("reference"))
    ret = "void" if is_void else infer_type(expected)
    return param_types, ret, is_void


# ---------- 类型名映射 ----------

def _java_type(t: str) -> str:
    return {
        "int": "int",
        "float": "double",
        "bool": "boolean",
        "str": "String",
        "void": "void",
        "list[int]": "int[]",
        "list[float]": "double[]",
        "list[bool]": "boolean[]",
        "list[str]": "String[]",
        "list[list[int]]": "int[][]",
        "list[list[str]]": "String[][]",
    }.get(t, "Object")


def _cpp_type(t: str, *, ref_for_list: bool = True) -> str:
    mapping = {
        "int": "int",
        "float": "double",
        "bool": "bool",
        "str": "string",
        "void": "void",
        "list[int]": "vector<int>",
        "list[float]": "vector<double>",
        "list[bool]": "vector<bool>",
        "list[str]": "vector<string>",
        "list[list[int]]": "vector<vector<int>>",
        "list[list[str]]": "vector<vector<string>>",
    }
    base = mapping.get(t, "int")
    if ref_for_list and base.startswith("vector"):
        return f"{base}&"
    return base


def _go_type(t: str) -> str:
    return {
        "int": "int",
        "float": "float64",
        "bool": "bool",
        "str": "string",
        "void": "",
        "list[int]": "[]int",
        "list[float]": "[]float64",
        "list[bool]": "[]bool",
        "list[str]": "[]string",
        "list[list[int]]": "[][]int",
        "list[list[str]]": "[][]string",
    }.get(t, "any")


def _py_hint(t: str) -> str:
    return {
        "int": "int",
        "float": "float",
        "bool": "bool",
        "str": "str",
        "void": "None",
        "list[int]": "list[int]",
        "list[float]": "list[float]",
        "list[bool]": "list[bool]",
        "list[str]": "list[str]",
        "list[list[int]]": "list[list[int]]",
        "list[list[str]]": "list[list[str]]",
    }.get(t, "Any")


# ---------- 模板 ----------

def build_templates(cfg: dict, mode: str = "function") -> dict[str, str]:
    """mode=function：力扣函数签名；mode=scratch：手撕完整程序（预置头文件/常用库）。"""
    if mode == "scratch":
        return _scratch_templates(cfg)
    return _function_templates(cfg)


def _function_templates(cfg: dict) -> dict[str, str]:
    params: list[str] = list(cfg.get("params") or [])
    method = cfg["method"]
    param_types, ret, is_void = method_types(cfg)
    while len(params) < len(param_types):
        params.append(f"arg{len(params)}")
    params = params[: len(param_types)]

    py_args = ", ".join(f"{n}: {_py_hint(t)}" for n, t in zip(params, param_types))
    py_ret = _py_hint(ret)
    python = f"class Solution:\n    def {method}(self, {py_args}) -> {py_ret}:\n        pass\n"

    java_args = ", ".join(f"{_java_type(t)} {n}" for n, t in zip(params, param_types))
    java = (
        f"class Solution {{\n"
        f"    public {_java_type(ret)} {method}({java_args}) {{\n"
        f"        \n"
        f"    }}\n"
        f"}}\n"
    )

    cpp_args = ", ".join(f"{_cpp_type(t)} {n}" for n, t in zip(params, param_types))
    cpp_ret = _cpp_type(ret, ref_for_list=False)
    cpp = (
        f"class Solution {{\npublic:\n"
        f"    {cpp_ret} {method}({cpp_args}) {{\n"
        f"        \n"
        f"    }}\n"
        f"}};\n"
    )

    go_args = ", ".join(f"{n} {_go_type(t)}" for n, t in zip(params, param_types))
    go_ret = _go_type(ret)
    go_sig = f"func {method}({go_args})" + (f" {go_ret}" if go_ret else "")
    go = f"{go_sig} {{\n    \n}}\n"

    _ = is_void
    return {"python": python, "java": java, "cpp": cpp, "go": go}


def _scratch_templates(cfg: dict) -> dict[str, str]:
    """手撕：预置头文件与常用集合/数学库，main 内自行完成 IO + 求解。"""
    method = cfg.get("method", "solve")
    params = ", ".join(cfg.get("params") or [])
    tip = f"本题参数顺序：{params or '见题面'}（方法名参考 {method}，可自建函数）"

    python = f'''\
import sys
import json
import math
import heapq
import bisect
import itertools
import functools
from collections import defaultdict, Counter, deque, OrderedDict
from typing import List, Optional, Tuple, Dict, Set, Any

# {tip}
# 判题：数组先 n 再 n 个数，其余参数各占一行；输出数字空格分隔

def main() -> None:
    # 请自行完成输入输出与求解
    pass


if __name__ == "__main__":
    main()
'''

    java = f'''\
import java.io.*;
import java.util.*;
import java.math.*;

// {tip}
// 判题：数组先 n 再 n 个数，其余参数各占一行；输出数字空格分隔
// 可用：List/Map/Set/Queue/Deque/PriorityQueue/Arrays/Collections/Math...

public class Main {{
    public static void main(String[] args) throws Exception {{
        // 请自行完成输入输出与求解
    }}
}}
'''

    cpp = f'''\
#include <bits/stdc++.h>
using namespace std;

// {tip}
// 判题：数组先 n 再 n 个数，其余参数各占一行；输出数字空格分隔
// 已含：vector/string/map/set/unordered_*/queue/stack/algorithm/cmath...

int main() {{
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    // 请自行完成输入输出与求解
    return 0;
}}
'''

    go = f'''\
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
)

// {tip}
// 判题：数组先 n 再 n 个数，其余参数各占一行；输出数字空格分隔

func main() {{
	_ = bufio.NewReader
	_ = json.Marshal
	_ = fmt.Println
	_ = math.MaxInt
	_ = os.Stdin
	_ = sort.Ints
	// 请自行完成输入输出与求解
}}
'''
    return {"python": python, "java": java, "cpp": cpp, "go": go}


# ---------- 字面量（嵌入 harness，避免各语言解析 JSON） ----------

def _py_literal(value: Any) -> str:
    return repr(value)


def _java_literal(value: Any, t: str) -> str:
    if t == "int":
        return str(int(value))
    if t == "float":
        return str(float(value))
    if t == "bool":
        return "true" if value else "false"
    if t == "str":
        return json_string(value)
    if t == "list[int]":
        inner = ", ".join(str(int(x)) for x in value)
        return f"new int[]{{{inner}}}"
    if t == "list[float]":
        inner = ", ".join(str(float(x)) for x in value)
        return f"new double[]{{{inner}}}"
    if t == "list[bool]":
        inner = ", ".join("true" if x else "false" for x in value)
        return f"new boolean[]{{{inner}}}"
    if t == "list[str]":
        inner = ", ".join(json_string(x) for x in value)
        return f"new String[]{{{inner}}}"
    if t == "list[list[int]]":
        rows = ", ".join(_java_literal(row, "list[int]") for row in value)
        return f"new int[][]{{{rows}}}"
    if t == "list[list[str]]":
        rows = ", ".join(_java_literal(row, "list[str]") for row in value)
        return f"new String[][]{{{rows}}}"
    raise TypeError(t)


def _cpp_literal(value: Any, t: str) -> str:
    if t == "int":
        return str(int(value))
    if t == "float":
        return str(float(value))
    if t == "bool":
        return "true" if value else "false"
    if t == "str":
        return json_string(value)
    if t.startswith("list[list["):
        inner_t = t[len("list[") : -1]
        rows = ", ".join(_cpp_literal(row, inner_t) for row in value)
        return f"{{{rows}}}"
    if t.startswith("list["):
        inner_t = t[len("list[") : -1]
        items = ", ".join(_cpp_literal(x, inner_t) for x in value)
        return f"{{{items}}}"
    raise TypeError(t)


def _go_literal(value: Any, t: str) -> str:
    if t == "int":
        return str(int(value))
    if t == "float":
        return str(float(value))
    if t == "bool":
        return "true" if value else "false"
    if t == "str":
        return json_string(value)
    if t.startswith("list["):
        inner_t = t[len("list[") : -1]
        items = ", ".join(_go_literal(x, inner_t) for x in value)
        return f"{_go_type(t)}{{{items}}}"
    raise TypeError(t)


def json_string(s: str) -> str:
    import json

    return json.dumps(s, ensure_ascii=False)


# ---------- 输出序列化辅助（harness 内） ----------

JAVA_DUMP = r'''
static String dump(int v) { return String.valueOf(v); }
static String dump(long v) { return String.valueOf(v); }
static String dump(double v) { return String.valueOf(v); }
static String dump(boolean v) { return v ? "true" : "false"; }
static String dump(Object v) {
    if (v == null) return "null";
    if (v instanceof int[]) {
        int[] a = (int[]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) { if (i>0) sb.append(","); sb.append(a[i]); }
        return sb.append("]").toString();
    }
    if (v instanceof long[]) {
        long[] a = (long[]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) { if (i>0) sb.append(","); sb.append(a[i]); }
        return sb.append("]").toString();
    }
    if (v instanceof double[]) {
        double[] a = (double[]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) { if (i>0) sb.append(","); sb.append(a[i]); }
        return sb.append("]").toString();
    }
    if (v instanceof boolean[]) {
        boolean[] a = (boolean[]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) { if (i>0) sb.append(","); sb.append(a[i] ? "true" : "false"); }
        return sb.append("]").toString();
    }
    if (v instanceof String[]) {
        String[] a = (String[]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) {
            if (i>0) sb.append(",");
            sb.append(jsonStr(a[i]));
        }
        return sb.append("]").toString();
    }
    if (v instanceof int[][]) {
        int[][] a = (int[][]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) { if (i>0) sb.append(","); sb.append(dump(a[i])); }
        return sb.append("]").toString();
    }
    if (v instanceof String[][]) {
        String[][] a = (String[][]) v;
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < a.length; i++) { if (i>0) sb.append(","); sb.append(dump(a[i])); }
        return sb.append("]").toString();
    }
    if (v instanceof String) return jsonStr((String) v);
    if (v instanceof Boolean) return ((Boolean) v) ? "true" : "false";
    return String.valueOf(v);
}
static String jsonStr(String s) {
    StringBuilder sb = new StringBuilder("\"");
    for (int i = 0; i < s.length(); i++) {
        char c = s.charAt(i);
        if (c == '"' || c == '\\') sb.append('\\').append(c);
        else if (c == '\n') sb.append("\\n");
        else sb.append(c);
    }
    return sb.append("\"").toString();
}
'''

CPP_DUMP = r'''
string dump(int v){ return to_string(v); }
string dump(double v){ ostringstream o; o<<v; return o.str(); }
string dump(bool v){ return v?"true":"false"; }
string dump(const string& s){
    string o="\"";
    for(char c:s){ if(c=='"'||c=='\\') o+='\\'; o+=c; }
    return o+"\"";
}
template<typename T> string dump(const vector<T>& a){
    string o="[";
    for(size_t i=0;i<a.size();i++){ if(i) o+=","; o+=dump(a[i]); }
    return o+"]";
}
'''

GO_DUMP = r'''
func dump(v any) string {
    b, err := json.Marshal(v)
    if err != nil { return "null" }
    return string(b)
}
'''


def build_java_harness(cfg: dict, cases: list[dict]) -> str:
    params: list[str] = list(cfg.get("params") or [])
    method = cfg["method"]
    param_types, ret, is_void = method_types(cfg)
    while len(params) < len(param_types):
        params.append(f"arg{len(params)}")
    params = params[: len(param_types)]

    case_blocks = []
    for i, c in enumerate(cases):
        args = c.get("args", [])
        decls = []
        call_args = []
        for j, (name, t) in enumerate(zip(params, param_types)):
            var = f"a{i}_{j}"
            decls.append(f"{_java_type(t)} {var} = {_java_literal(args[j], t)};")
            call_args.append(var)
        body = "\n            ".join(decls)
        joined = ", ".join(call_args)
        if is_void:
            run = (
                f"try {{\n"
                f"            {body}\n"
                f"            new Solution().{method}({joined});\n"
                f"            out.add(\"{{\\\"ok\\\":true,\\\"result\\\":\" + dump({call_args[0]}) + \"}}\");\n"
                f"        }} catch (Throwable e) {{\n"
                f"            out.add(\"{{\\\"ok\\\":false,\\\"error\\\":\" + jsonStr(e.toString()) + \"}}\");\n"
                f"        }}"
            )
        else:
            jret = _java_type(ret)
            run = (
                f"try {{\n"
                f"            {body}\n"
                f"            {jret} __r = new Solution().{method}({joined});\n"
                f"            out.add(\"{{\\\"ok\\\":true,\\\"result\\\":\" + dump(__r) + \"}}\");\n"
                f"        }} catch (Throwable e) {{\n"
                f"            out.add(\"{{\\\"ok\\\":false,\\\"error\\\":\" + jsonStr(e.toString()) + \"}}\");\n"
                f"        }}"
            )
        case_blocks.append(run)

    cases_code = "\n        ".join(case_blocks)
    return f"""\
import java.util.*;
public class Harness {{
{JAVA_DUMP}
    public static void main(String[] args) {{
        List<String> out = new ArrayList<>();
        {cases_code}
        System.out.println("[" + String.join(",", out) + "]");
    }}
}}
"""


def build_cpp_harness(cfg: dict, cases: list[dict], user_code: str) -> str:
    params: list[str] = list(cfg.get("params") or [])
    method = cfg["method"]
    param_types, ret, is_void = method_types(cfg)
    while len(params) < len(param_types):
        params.append(f"arg{len(params)}")
    params = params[: len(param_types)]

    case_blocks = []
    for i, c in enumerate(cases):
        args = c.get("args", [])
        decls = []
        call_args = []
        for j, (name, t) in enumerate(zip(params, param_types)):
            var = f"a{i}_{j}"
            ctype = _cpp_type(t, ref_for_list=False)
            decls.append(f"{ctype} {var} = {_cpp_literal(args[j], t)};")
            call_args.append(var)
        body = "\n        ".join(decls)
        joined = ", ".join(call_args)
        if is_void:
            run = f"""try {{
        {body}
        Solution().{method}({joined});
        out.push_back(string("{{\\\"ok\\\":true,\\\"result\\\":") + dump({call_args[0]}) + "}}");
    }} catch (exception& e) {{
        out.push_back(string("{{\\\"ok\\\":false,\\\"error\\\":") + dump(string(e.what())) + "}}");
    }} catch (...) {{
        out.push_back("{{\\\"ok\\\":false,\\\"error\\\":\\\"unknown error\\\"}}");
    }}"""
        else:
            run = f"""try {{
        {body}
        auto __r = Solution().{method}({joined});
        out.push_back(string("{{\\\"ok\\\":true,\\\"result\\\":") + dump(__r) + "}}");
    }} catch (exception& e) {{
        out.push_back(string("{{\\\"ok\\\":false,\\\"error\\\":") + dump(string(e.what())) + "}}");
    }} catch (...) {{
        out.push_back("{{\\\"ok\\\":false,\\\"error\\\":\\\"unknown error\\\"}}");
    }}"""
        case_blocks.append(run)

    cases_code = "\n    ".join(case_blocks)
    return f"""\
#include <bits/stdc++.h>
using namespace std;
{user_code}

{CPP_DUMP}
int main(){{
    vector<string> out;
    {cases_code}
    cout << "[";
    for(size_t i=0;i<out.size();i++){{ if(i) cout<<","; cout<<out[i]; }}
    cout << "]" << endl;
    return 0;
}}
"""


def build_go_harness(cfg: dict, cases: list[dict], user_code: str) -> str:
    params: list[str] = list(cfg.get("params") or [])
    method = cfg["method"]
    param_types, ret, is_void = method_types(cfg)
    while len(params) < len(param_types):
        params.append(f"arg{len(params)}")
    params = params[: len(param_types)]

    case_blocks = []
    for i, c in enumerate(cases):
        args = c.get("args", [])
        decls = []
        call_args = []
        for j, (name, t) in enumerate(zip(params, param_types)):
            var = f"a{i}_{j}"
            decls.append(f"{var} := {_go_literal(args[j], t)}")
            call_args.append(var)
        body = "\n\t\t".join(decls)
        joined = ", ".join(call_args)
        if is_void:
            run = f"""func() {{
\t\tdefer func() {{
\t\t\tif r := recover(); r != nil {{
\t\t\t\tout = append(out, map[string]any{{"ok": false, "error": fmt.Sprint(r)}})
\t\t\t}}
\t\t}}()
\t\t{body}
\t\t{method}({joined})
\t\tout = append(out, map[string]any{{"ok": true, "result": {call_args[0]}}})
\t}}()"""
        else:
            run = f"""func() {{
\t\tdefer func() {{
\t\t\tif r := recover(); r != nil {{
\t\t\t\tout = append(out, map[string]any{{"ok": false, "error": fmt.Sprint(r)}})
\t\t\t}}
\t\t}}()
\t\t{body}
\t\t__r := {method}({joined})
\t\tout = append(out, map[string]any{{"ok": true, "result": __r}})
\t}}()"""
        case_blocks.append(run)

    cases_code = "\n\t".join(case_blocks)
    # 用户代码可能已含 package，剥掉
    user = re.sub(r"^\s*package\s+\w+\s*", "", user_code.strip())
    return f"""\
package main

import (
\t"encoding/json"
\t"fmt"
)

{user}

func main() {{
\tout := make([]map[string]any, 0)
\t{cases_code}
\tb, _ := json.Marshal(out)
\tfmt.Println(string(b))
}}
"""
