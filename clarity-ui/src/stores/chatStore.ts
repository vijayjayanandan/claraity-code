/**
 * Chat Store using Zustand
 * Manages chat messages, history, and streaming state
 */

import { create } from 'zustand';
import type { ChatMessage, ChatSession } from '../types/chat';

interface ChatState {
  // State
  messages: ChatMessage[];
  isStreaming: boolean;
  currentSessionId: string | null;
  sessions: ChatSession[];
  
  // Actions
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
  updateLastMessage: (content: string) => void;
  clearMessages: () => void;
  setStreaming: (isStreaming: boolean) => void;
  loadSession: (sessionId: string) => void;
  createNewSession: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  messages: [],
  isStreaming: false,
  currentSessionId: null,
  sessions: [],

  // Actions
  addMessage: (messageData) => {
    const message: ChatMessage = {
      ...messageData,
      id: crypto.randomUUID(),
      timestamp: new Date(),
    };
    
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  updateLastMessage: (content) => {
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        const lastMessage = messages[messages.length - 1];
        messages[messages.length - 1] = {
          ...lastMessage,
          content: lastMessage.content + content,
        };
      }
      return { messages };
    });
  },

  clearMessages: () => {
    set({ messages: [] });
  },

  setStreaming: (isStreaming) => {
    set({ isStreaming });
  },

  loadSession: (sessionId) => {
    const { sessions } = get();
    const session = sessions.find((s) => s.id === sessionId);
    if (session) {
      set({
        currentSessionId: sessionId,
        messages: session.messages,
      });
    }
  },

  createNewSession: () => {
    const sessionId = crypto.randomUUID();
    const newSession: ChatSession = {
      id: sessionId,
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    
    set((state) => ({
      currentSessionId: sessionId,
      sessions: [...state.sessions, newSession],
      messages: [],
    }));
  },
}));
