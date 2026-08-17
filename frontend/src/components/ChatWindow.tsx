import React, { useEffect, useRef } from "react";
import {
  AssistantInfo,
  streamChat,
  ChatEvent,
} from "../api";
import {
  ToolCallInfo,
  ToolCallBadge,
  ToolCallStatus,
} from "./ToolCallBadge";

/**
 * The streaming chat window + state machine for one conversation.
 */

export type Role = "user" | "assistant";

export type Message = {
  id: string;
  role: Role;
  content: string;
  toolCalls: ToolCallInfo[];
  streaming?: boolean;
  error?: boolean;
};

type Props = {
  assistant: AssistantInfo;
  onError: (err: string) => void;
};

const STORAGE_KEY_PREFIX = "assistant.history.";

export const ChatWindow: React.FC<Props> = ({ assistant }) => {
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [streaming, setStreaming] = React.useState(false);
  const [input, setInput] = React.useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const messageIdCounter = useRef(0);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  // Reset chat when the assistant changes (separate histories persisted on localStorage per assistant).
  useEffect(() => {
    const key = STORAGE_KEY_PREFIX + assistant.name;
    try {
      const stored = localStorage.getItem(key);
      const parsed = stored ? (JSON.parse(stored) as { messages: Message[]; conversationId: string | null }) : null;
      if (parsed) {
        setMessages(parsed.messages);
        setConversationId(parsed.conversationId);
        return;
      }
    } catch { /* swallow */ }
    setMessages([{ id: "intro", role: "assistant", content: `Hi — I'm ${assistant.title}. ${assistant.description}`, toolCalls: [] }]);
    setConversationId(null);
  }, [assistant]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const persist = (nextMessages: Message[], nextConvId: string | null): void => {
    try {
      localStorage.setItem(
        STORAGE_KEY_PREFIX + assistant.name,
        JSON.stringify({ messages: nextMessages, conversationId: nextConvId }),
      );
    } catch { /* storage may be full or unavailable */ }
  };

  const send = async (): Promise<void> => {
    const text = input.trim();
    if (!text || streaming) return;

    messageIdCounter.current++;
    const userMsg: Message = { id: String(messageIdCounter.current), role: "user", content: text, toolCalls: [] };
    const assistantId = String(messageIdCounter.current + 1);
    const assistantMsg: Message = { id: assistantId, role: "assistant", content: "", toolCalls: [], streaming: true };
    const next = [...messages, userMsg, assistantMsg];
    setMessages(next);
    persist(next, conversationId);
    setInput("");
    setStreaming(true);

    const handleEvent = (event: ChatEvent): void => {
      if (event.type === "token") {
        setMessages((cur) => patchMessage(cur, assistantId, (m) => ({ ...m, content: m.content + event.text })));
      } else if (event.type === "tool_start") {
        const newTool: ToolCallInfo = {
          id: event.id,
          name: event.name,
          args: event.args,
          status: "running",
        };
        setMessages((cur) => patchMessage(cur, assistantId, (m) => ({ ...m, toolCalls: [...m.toolCalls, newTool] })));
      } else if (event.type === "tool_end") {
        setMessages((cur) =>
          patchMessage(cur, assistantId, (m) => ({
            ...m,
            toolCalls: m.toolCalls.map((t) =>
              t.id === event.id ? { ...t, status: (event.output?.startsWith("Error") ? "error" : "done") as ToolCallStatus, output: event.output } : t,
            ),
          })),
        );
      } else if (event.type === "session") {
        setConversationId(event.conversation_id);
      } else if (event.type === "done") {
        setMessages((cur) => patchMessage(cur, assistantId, (m) => ({ ...m, streaming: false })));
      } else if (event.type === "error") {
        setMessages((cur) =>
          patchMessage(cur, assistantId, (m) => ({ ...m, streaming: false, error: true, content: `⚠️ ${event.message}\n\n${m.content}` })),
        );
      }
    };

    try {
      await streamChat(
        { assistant: assistant.name, conversation_id: conversationId, message: text },
        (e) => {
          handleEvent(e);
          if (e.type === "session") setConversationId(e.conversation_id);
        },
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((cur) =>
        patchMessage(cur, assistantId, (m) => ({ ...m, streaming: false, error: true, content: `⚠️ Network error: ${msg}\n\n${m.content}` })),
      );
    } finally {
      setStreaming(false);
      // Persist final state with the (possibly new) conversationId resolved
      setConversationId((cid) => {
        setMessages((cur) => {
          persist(cur, cid);
          return cur;
        });
        return cid;
      });
    }
  };

  // Reset conversation
  const reset = (): void => {
    localStorage.removeItem(STORAGE_KEY_PREFIX + assistant.name);
    setConversationId(null);
    setMessages([{ id: "intro", role: "assistant", content: `Hi — I'm ${assistant.title}. New conversation started.`, toolCalls: [] }]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
    if (e.key === "l" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      reset();
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-2 bg-slate-50"
      >
        {messages.map((m) => (
          <MessageRow key={m.id} msg={m} />
        ))}
      </div>
      <div className="border-t bg-white px-3 py-2 flex gap-2 items-end">
        <textarea
          ref={textAreaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={streaming}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder={streaming ? "Assistant is responding…" : `Message ${assistant.title}…  (Enter to send, Ctrl+L to reset)`}
          className="flex-1 resize-none border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-100"
        />
        <button
          type="button"
          onClick={send}
          disabled={streaming || !input.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-40"
        >
          Send
        </button>
        <button
          type="button"
          onClick={reset}
          title="Start a new conversation (Ctrl+L)"
          className="px-3 py-2 bg-slate-200 text-slate-700 rounded-md text-sm font-medium hover:bg-slate-300"
        >
          Reset
        </button>
      </div>
    </div>
  );
};

const MessageRow: React.FC<{ msg: Message }> = ({ msg }) => {
  const isUser = msg.role === "user";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={[
          "max-w-[85%] px-3 py-2 rounded-lg text-sm agent-stream",
          msg.error ? "border border-rose-300 bg-rose-50 text-rose-900" : isUser ? "bg-blue-600 text-white" : "bg-white border border-slate-200 text-slate-900",
        ].join(" ")}
      >
        {msg.content || (msg.streaming ? (
          <span className="opacity-50">
            <span className="dot-1">•</span> <span className="dot-2">•</span> <span className="dot-3">•</span>
          </span>
        ) : "")}
      </div>
      {msg.toolCalls.length > 0 ? (
        <div className="flex flex-col items-start gap-1 mt-1">
          {msg.toolCalls.map((t, i) => (
            <ToolCallBadge key={`${t.id}-${i}`} tool={t} />
          ))}
        </div>
      ) : null}
    </div>
  );
};

function patchMessage(messages: Message[], id: string, fn: (m: Message) => Message): Message[] {
  return messages.map((m) => (m.id === id ? fn(m) : m));
}
