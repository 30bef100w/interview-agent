"use client";

import Link from "next/link";

import { Card, btnCls } from "@/components/ui";

const FAQ = [
  {
    q: "支持什么格式的简历？",
    a: "目前仅支持文字版 PDF。扫描件/图片 PDF 无法可靠抽取文字，请先转成可选中文字的 PDF。",
  },
  {
    q: "面试怎么开始？",
    a: "先在「我的简历」上传并解析画像，再到「开始面试」选择全流程或专项、设置轮次即可开练。",
  },
  {
    q: "可以语音作答吗？",
    a: "可以。面试会话页提供语音输入，会转写为文字后再交给面试官追问。",
  },
  {
    q: "报告怎么导出？",
    a: "打开对应场次的报告页，可导出 Word 或 PDF，方便复盘存档。",
  },
  {
    q: "目标岗位 / 目标企业是什么？",
    a: "开练时可按已有岗位分类（后端 / AI / 前端等）和企业表选择。选定后本场出题会贴近该岗位与企业高频考点；也可根据简历一键采纳建议岗位。历史页可按岗位/企业筛选。",
  },
  {
    q: "简历分析是什么？",
    a: "在「我的简历」点「AI 分析简历」，会弹出分析报告弹窗，可导出 Word / PDF。分析在当面完成，不会推送到通知中心。",
  },
  {
    q: "通知中心什么时候会有消息？",
    a: "只用于后台异步完成的事项。你在页面上正在等待的结果（上传、分析、开面试）会直接展示，不会重复推通知。",
  },
  {
    q: "成长档案是什么？会不会影响下一场提问？",
    a: "「成长档案」汇总已出报告的场次：近因能力画像、短板标签、曲线与可选「下一场练什么」。主路径仍是独立模拟面试；针对性开练只预填本场焦点，不会自动把历史对话塞进下一场。",
  },
];

export default function HelpPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">帮助中心</h1>
        <p className="mt-1 text-sm text-zinc-500">常见问题与快速入口</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Link href="/resume/upload" className={btnCls("secondary", "sm")}>
          上传简历
        </Link>
        <Link href="/interview/new" className={btnCls("secondary", "sm")}>
          开始面试
        </Link>
        <Link href="/history" className={btnCls("secondary", "sm")}>
          面试记录
        </Link>
        <Link href="/growth" className={btnCls("secondary", "sm")}>
          成长档案
        </Link>
        <Link href="/notifications" className={btnCls("secondary", "sm")}>
          通知中心
        </Link>
      </div>

      <div className="flex flex-col gap-3">
        {FAQ.map((item) => (
          <Card key={item.q} className="px-5 py-4">
            <h2 className="text-sm font-semibold text-zinc-900">{item.q}</h2>
            <p className="mt-2 text-sm leading-7 text-zinc-500">{item.a}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
