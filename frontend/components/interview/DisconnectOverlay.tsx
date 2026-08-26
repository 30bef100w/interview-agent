"use client";

type Props = {
  visible: boolean;
  onRetry: () => void;
};

export default function DisconnectOverlay({ visible, onRetry }: Props) {
  if (!visible) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-zinc-900/45 px-4 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-2xl border border-zinc-200 bg-white p-6 text-center shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 text-amber-700">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 9v4m0 4h.01M5.07 19h13.86a2 2 0 0 0 1.74-3l-6.93-12a2 2 0 0 0-3.48 0l-6.93 12a2 2 0 0 0 1.74 3Z" strokeLinecap="round" />
          </svg>
        </div>
        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">连接中断</h3>
        <p className="mt-2 text-sm leading-6 text-zinc-500">
          与面试服务的连接已断开。你可以刷新会话状态后继续，未发送的回答仍在输入框中。
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 w-full rounded-xl bg-sky-600 py-2.5 text-sm font-medium text-white hover:bg-sky-500"
        >
          重新连接
        </button>
      </div>
    </div>
  );
}
