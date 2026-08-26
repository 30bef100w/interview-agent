import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

type Props = {
  content: string;
  className?: string;
};

const components: Components = {
  a: ({ ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-zinc-900/90 px-3 py-2 text-[13px] leading-relaxed text-zinc-100 dark:bg-zinc-950">
      {children}
    </pre>
  ),
  code: ({ className, children, ...props }) => {
    const inline = !className;
    if (inline) {
      return (
        <code
          className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[0.9em] text-zinc-800 dark:bg-zinc-800 dark:text-zinc-100"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code className={`font-mono text-[13px] ${className ?? ""}`} {...props}>
        {children}
      </code>
    );
  },
};

/** 题面 / 参考答案 Markdown 渲染（GFM：表格、代码块、列表） */
export default function MarkdownRenderer({ content, className }: Props) {
  return (
    <div className={`markdown-body text-sm leading-relaxed ${className ?? ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
