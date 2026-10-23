"use client";

import { useCallback, useEffect, useRef } from "react";

import { interviewWsUrl } from "@/lib/ws";

export type WsSnapshot = {
  session_id: number;
  status: string;
  stage: string;
  history: { role: "interviewer" | "candidate"; text: string }[];
  topics: string[];
  rounds_used: number;
  total_rounds: number;
  version: number;
  processing: boolean;
  last_submission_id?: string | null;
  current_coding?: unknown;
};

export type WsDone = {
  message: string;
  stage: string;
  status: string;
  finished: boolean;
  report?: unknown;
};

export type WsHandlers = {
  onSnapshot?: (data: WsSnapshot, checkpointSeq: number) => void;
  onToken?: (text: string) => void;
  onDone?: (data: WsDone) => void;
  onError?: (message: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
};

const HEARTBEAT_MS = 25_000;
const MAX_RETRIES = 6;
const BASE_DELAY = 1000;

export function useInterviewWebSocket(sessionId: string, handlers: WsHandlers, enabled: boolean) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const retryRef = useRef(0);
  const shouldConnectRef = useRef(false);
  const sendingRef = useRef(false);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const answerTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearAnswerTimeout = useCallback(() => {
    if (answerTimeoutRef.current) clearTimeout(answerTimeoutRef.current);
    answerTimeoutRef.current = null;
  }, []);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!enabled || !sessionId) return;
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return;
    shouldConnectRef.current = true;

    const ws = new WebSocket(interviewWsUrl(sessionId));
    wsRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      clearHeartbeat();
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, HEARTBEAT_MS);
      handlersRef.current.onOpen?.();
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as {
          type: string;
          data?: WsSnapshot | WsDone;
          message?: string;
          checkpoint_seq?: number;
        };
        switch (msg.type) {
          case "snapshot":
            if (msg.data) {
              handlersRef.current.onSnapshot?.(
                msg.data as WsSnapshot,
                Number(msg.checkpoint_seq ?? 0)
              );
            }
            break;
          case "token":
            handlersRef.current.onToken?.(String((msg as { data?: string }).data ?? ""));
            break;
          case "done":
            clearAnswerTimeout();
            sendingRef.current = false;
            if (msg.data) handlersRef.current.onDone?.(msg.data as WsDone);
            break;
          case "error":
            clearAnswerTimeout();
            sendingRef.current = false;
            handlersRef.current.onError?.(msg.message ?? "WebSocket 错误");
            break;
          case "pong":
            break;
          default:
            break;
        }
      } catch {
        clearAnswerTimeout();
        sendingRef.current = false;
        handlersRef.current.onError?.("服务端消息格式异常，提交结果尚未确认，请刷新进度");
      }
    };

    ws.onclose = (event) => {
      if (wsRef.current !== ws) return;
      wsRef.current = null;
      clearHeartbeat();
      clearAnswerTimeout();
      const interrupted = sendingRef.current;
      sendingRef.current = false;
      if (interrupted) handlersRef.current.onError?.("连接中断，提交结果尚未确认，请刷新进度后重试");
      handlersRef.current.onClose?.();
      if ([4401, 4403, 4404].includes(event.code)) {
        shouldConnectRef.current = false;
        return;
      }
      if (shouldConnectRef.current && retryRef.current < MAX_RETRIES) {
        const delay = BASE_DELAY * 2 ** retryRef.current;
        retryRef.current += 1;
        reconnectRef.current = setTimeout(() => {
          reconnectRef.current = null;
          if (shouldConnectRef.current) connect();
        }, delay);
      }
    };

    ws.onerror = () => {
      handlersRef.current.onClose?.();
    };
  }, [sessionId, enabled, clearHeartbeat, clearAnswerTimeout]);

  const disconnect = useCallback(() => {
    shouldConnectRef.current = false;
    retryRef.current = 0;
    sendingRef.current = false;
    if (reconnectRef.current) clearTimeout(reconnectRef.current);
    reconnectRef.current = null;
    clearAnswerTimeout();
    clearHeartbeat();
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [clearHeartbeat, clearAnswerTimeout]);

  const resync = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "resync" }));
      return true;
    }
    return false;
  }, []);

  const sendAnswer = useCallback((text: string, submissionId?: string, expectedVersion?: number) => {
    if (sendingRef.current || wsRef.current?.readyState !== WebSocket.OPEN) return false;
    sendingRef.current = true;
    wsRef.current.send(JSON.stringify({ type: "answer", text, submission_id: submissionId, expected_version: expectedVersion }));
    answerTimeoutRef.current = setTimeout(() => {
      if (sendingRef.current) wsRef.current?.close();
    }, 20 * 60 * 1000);
    return true;
  }, []);

  const isOpen = useCallback(
    () => wsRef.current?.readyState === WebSocket.OPEN,
    []
  );

  useEffect(() => {
    if (enabled) connect();
    return () => disconnect();
  }, [enabled, connect, disconnect]);

  return { connect, disconnect, resync, sendAnswer, isOpen };
}
