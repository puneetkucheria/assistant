import React from "react";

/**
 * Renders an inline badge describing a tool call the LLM made.
 *
 * Used by ChatWindow to slot between the user's message and the assistant's
 * reply so the user can see exactly which ADO action the agent took.
 */

export type ToolCallStatus = "running" | "done" | "error";

export type ToolCallInfo = {
  id: string;
  name: string;
  args?: string | object;
  output?: string;
  status: ToolCallStatus;
};

const TOOL_GLYPHS: Record<string, string> = {
  get_work_item: "🔍",
  search_work_items: "🔎",
  update_work_item: "✏️",
  create_work_item: "➕",
  add_work_item_comment: "💬",
};

const TOOL_LABELS: Record<string, string> = {
  get_work_item: "Get work item",
  search_work_items: "Search work items",
  update_work_item: "Update work item",
  create_work_item: "Create work item",
  add_work_item_comment: "Add comment",
};

const STATUS_COLORS: Record<ToolCallStatus, string> = {
  running: "bg-amber-100 text-amber-800 border-amber-300",
  done: "bg-emerald-100 text-emerald-800 border-emerald-300",
  error: "bg-rose-100 text-rose-800 border-rose-300",
};

function shortArgs(args: unknown): string {
  if (!args) return "";
  if (typeof args === "string") {
    // JSON-ish args string — try to parse for nicer rendering
    try {
      const parsed = JSON.parse(args);
      return JSON.stringify(parsed);
    } catch {
      return args;
    }
  }
  try {
    return JSON.stringify(args);
  } catch {
    return "";
  }
}

export const ToolCallBadge: React.FC<{ tool: ToolCallInfo }> = ({ tool }) => {
  const glyph = TOOL_GLYPHS[tool.name] ?? "🛠️";
  const label = TOOL_LABELS[tool.name] ?? tool.name;
  const statusColor = STATUS_COLORS[tool.status];
  const argsStr = shortArgs(tool.args);
  const outputStr = tool.output ? truncate(tool.output, 240) : "";

  return (
    <div className={`text-xs border rounded-md px-2 py-1 my-1 inline-block ${statusColor}`}>
      <span className="font-mono">
        {glyph} {label}
        {tool.status === "running" ? (
          <span className="ml-1">
            <span className="dot-1">•</span>
            <span className="dot-2">•</span>
            <span className="dot-3">•</span>
          </span>
        ) : tool.status === "done" ? (
          <span className="ml-1">✓</span>
        ) : (
          <span className="ml-1">✗</span>
        )}
      </span>
      {argsStr ? (
        <div className="mt-1 font-mono opacity-80 break-words">args: {argsStr}</div>
      ) : null}
      {outputStr ? (
        <div className="mt-1 font-mono opacity-80 break-words">→ {outputStr}</div>
      ) : null}
    </div>
  );
};

function truncate(s: string, n: number): string {
  return s.length >= n ? s.slice(0, n - 1) + "…" : s;
}
