"""面试报告导出为 PDF。"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fpdf import FPDF

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyh.ttf"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


def _pick_font() -> Path | None:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None


class ReportPdf(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Body", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"{self.page_no()}", align="C")


def build_report_pdf(report: dict, meta: dict) -> bytes:
    font_path = _pick_font()
    pdf = ReportPdf(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    if font_path is None:
        # 无中文字体时退化为英文提示，避免崩溃
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 8, "Chinese font not found. Please install Microsoft YaHei / Noto Sans CJK.")
        return bytes(pdf.output())

    pdf.add_font("Body", style="", fname=str(font_path))
    pdf.add_font("Body", style="B", fname=str(font_path))

    pdf.set_font("Body", style="B", size=18)
    pdf.set_text_color(2, 132, 199)
    pdf.cell(0, 10, "AI 模拟面试报告", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Body", size=9)
    pdf.set_text_color(113, 113, 122)
    pdf.cell(
        0,
        6,
        f"面试形态：{meta.get('mode_label', '')} · 生成时间：{meta.get('created_at', '')}",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    dims = report.get("dimension_scores") or {}
    if dims:
        total = sum(float(v) for v in dims.values()) / max(len(dims), 1)
        pdf.set_font("Body", style="B", size=14)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 8, f"综合评分：{total:.1f} / 10", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Body", size=10)
        for k, v in dims.items():
            pdf.cell(0, 6, f"· {k}：{v} / 10", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    def section(title: str) -> None:
        pdf.set_font("Body", style="B", size=12)
        pdf.set_text_color(2, 132, 199)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(39, 39, 42)
        pdf.set_font("Body", size=10)

    section("总体评价")
    pdf.multi_cell(0, 6, str(report.get("summary") or "（无）"))
    pdf.ln(2)

    per_question = report.get("per_question") or []
    if per_question:
        section("逐题作答详情")
        for i, q in enumerate(per_question):
            pdf.set_font("Body", style="B", size=10)
            pdf.multi_cell(0, 6, f"第 {i + 1} 题 · {q.get('topic', '')}（{q.get('score', '-')}/10）")
            pdf.set_font("Body", size=10)
            pdf.multi_cell(0, 5.5, f"问题：{q.get('question', '')}")
            answers = q.get("my_answers") or []
            if answers:
                pdf.multi_cell(0, 5.5, "我的作答：")
                for a in answers:
                    pdf.multi_cell(0, 5.5, f"· {a}")
            if q.get("feedback"):
                pdf.multi_cell(0, 5.5, f"AI 点评：{q.get('feedback')}")
            pdf.ln(1)

    for title, key in (("优点", "strengths"), ("待提升", "weaknesses"), ("提升建议", "suggestions")):
        items = report.get(key) or []
        if not items:
            continue
        section(title)
        for item in items:
            pdf.multi_cell(0, 5.5, f"· {item}")
        pdf.ln(1)

    return bytes(pdf.output())
