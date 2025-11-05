/**
 * Chat Types for ClarAIty IDE
 */

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  metadata?: {
    taskId?: string;
    toolCalls?: ToolCall[];
    fileReferences?: string[];
  };
}

export interface ToolCall {
  name: string;
  args: Record<string, any>;
  result?: any;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

export interface ChatSession {
  id: string;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
}

export interface TaskSubmission {
  description: string;
  type: 'implement' | 'explain' | 'fix' | 'refactor' | 'test';
  context?: string;
}
