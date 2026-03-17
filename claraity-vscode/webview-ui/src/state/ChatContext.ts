/**
 * React Context for shared chat values that many components need.
 *
 * Avoids threading postMessage, toolCards, subagents, etc. through
 * 20+ props in ChatHistory. Components that need these values can
 * use useChatContext() instead of receiving them as props.
 */
import { createContext, useContext } from "react";
import type { ToolStateData, WebViewMessage } from "../types";
import type { SubagentInfo } from "./state";

export interface ChatContextValue {
  postMessage: (msg: WebViewMessage) => void;
  toolCards: Record<string, ToolStateData>;
  toolOrder: string[];
  toolCardOwners: Record<string, string>;
  subagents: Record<string, SubagentInfo>;
  promotedApprovals: Record<string, { data: ToolStateData; subagentId: string }>;
  onDismissApproval: (callId: string) => void;
}

export const ChatContext = createContext<ChatContextValue | null>(null);

export function useChatContext(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within ChatContext.Provider");
  return ctx;
}
