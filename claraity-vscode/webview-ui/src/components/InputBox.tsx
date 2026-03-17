/**
 * Chat input box with @file mentions, file attachments, image paste, and send/interrupt.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import type { FileAttachment, ImageAttachment, WebViewMessage } from "../types";

interface InputBoxProps {
  isStreaming: boolean;
  attachments: FileAttachment[];
  images: ImageAttachment[];
  mentionResults: Array<{ path: string; name: string; relativePath: string }>;
  onSend: (content: string, attachments?: FileAttachment[], images?: ImageAttachment[]) => void;
  onInterrupt: () => void;
  onAddAttachment: (attachment: FileAttachment) => void;
  onRemoveAttachment: (index: number) => void;
  onAddImage: (image: ImageAttachment) => void;
  onRemoveImage: (index: number) => void;
  onSearchFiles: (query: string) => void;
  postMessage: (msg: WebViewMessage) => void;
}

const MAX_IMAGES = 5;
const MAX_TEXT_LENGTH = 100_000; // 100KB max input to prevent UI freeze

export function InputBox({
  isStreaming,
  attachments,
  images,
  mentionResults,
  onSend,
  onInterrupt,
  onAddAttachment,
  onRemoveAttachment,
  onAddImage,
  onRemoveImage,
  onSearchFiles,
  postMessage,
}: InputBoxProps) {
  const [text, setText] = useState("");
  const [showMentions, setShowMentions] = useState(false);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const attachMenuRef = useRef<HTMLDivElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, [text]);

  // Close attach menu on outside click
  useEffect(() => {
    if (!showAttachMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (attachMenuRef.current && !attachMenuRef.current.contains(e.target as Node)) {
        setShowAttachMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showAttachMenu]);

  // Handle @mention detection — triggers on "@" alone or "@query"
  const handleChange = useCallback(
    (value: string) => {
      // Guard against massive pastes that would freeze the webview
      if (value.length > MAX_TEXT_LENGTH) {
        value = value.slice(0, MAX_TEXT_LENGTH);
      }
      setText(value);
      const atMatch = value.match(/@(\S*)$/);
      if (atMatch) {
        onSearchFiles(atMatch[1]);
        setShowMentions(true);
        setMentionIndex(0);
      } else {
        setShowMentions(false);
      }
    },
    [onSearchFiles],
  );

  // "Add context (@)" — insert @ and trigger mention search
  const handleAddContext = useCallback(() => {
    setShowAttachMenu(false);
    const el = textareaRef.current;
    if (el) {
      const pos = el.selectionStart ?? el.value.length;
      const before = el.value.slice(0, pos);
      const after = el.value.slice(pos);
      handleChange(before + "@" + after);
      el.focus();
      requestAnimationFrame(() => el.setSelectionRange(pos + 1, pos + 1));
    }
  }, [handleChange]);

  // "Upload from computer" — ask extension to open file picker
  const handlePickFile = useCallback(() => {
    setShowAttachMenu(false);
    postMessage({ type: "pickFile" } as WebViewMessage);
  }, [postMessage]);

  // Insert mention into text
  const insertMention = useCallback(
    (file: { path: string; name: string; relativePath: string }) => {
      const atMatch = text.match(/@(\S*)$/);
      if (atMatch) {
        const before = text.slice(0, text.length - atMatch[0].length);
        setText(before + "@" + file.relativePath + " ");
      }
      setShowMentions(false);
      textareaRef.current?.focus();
    },
    [text],
  );

  // Handle send
  const handleSend = useCallback(() => {
    if (isStreaming) {
      onInterrupt();
      return;
    }
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  }, [text, isStreaming, onSend, onInterrupt]);

  // Keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (showMentions && mentionResults.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setMentionIndex((i) => Math.min(i + 1, mentionResults.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setMentionIndex((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          insertMention(mentionResults[mentionIndex]);
          return;
        }
        if (e.key === "Escape") {
          setShowMentions(false);
          return;
        }
      }

      // Enter to send (Shift+Enter for newline)
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [showMentions, mentionResults, mentionIndex, insertMention, handleSend],
  );

  // Handle image paste
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/") && images.length < MAX_IMAGES) {
          e.preventDefault();
          const file = item.getAsFile();
          if (!file || file.size > 10 * 1024 * 1024) continue;
          const reader = new FileReader();
          reader.onload = () => {
            onAddImage({
              data: reader.result as string,
              mimeType: item.type,
              name: file.name || "pasted-image",
            });
          };
          reader.readAsDataURL(file);
        }
      }
    },
    [images.length, onAddImage],
  );

  return (
    <div className="input-container">
      {/* Mention dropdown */}
      <div
        className={`mention-dropdown ${showMentions && mentionResults.length > 0 ? "visible" : ""}`}
        role="listbox"
        id="mention-listbox"
        aria-label="File suggestions"
      >
        {mentionResults.map((file, i) => (
          <div
            key={file.path}
            id={`mention-${i}`}
            className={`mention-item ${i === mentionIndex ? "selected" : ""}`}
            onClick={() => insertMention(file)}
            role="option"
            aria-selected={i === mentionIndex}
          >
            <span className="mention-name">{file.name}</span>
            <span className="mention-path">{file.relativePath}</span>
          </div>
        ))}
      </div>

      {/* Attachment badges */}
      {attachments.length > 0 && (
        <div className="attachment-bar">
          {attachments.map((att, i) => (
            <span key={i} className="attachment-badge" title={att.path}>
              {att.name}
              <span style={{ cursor: "pointer", marginLeft: 4 }} onClick={() => onRemoveAttachment(i)}>
                x
              </span>
            </span>
          ))}
        </div>
      )}

      {/* Image previews */}
      {images.length > 0 && (
        <div className="image-preview-bar">
          {images.map((img, i) => (
            <div key={i} className="image-thumb">
              <img
                src={img.data}
                alt={img.name || "image"}
                onClick={() => setPreviewImage(img.data)}
                style={{ cursor: "pointer" }}
              />
              <button className="remove-img" onClick={() => onRemoveImage(i)}>
                x
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Image preview overlay */}
      {previewImage && (
        <div className="image-preview-overlay" onClick={() => setPreviewImage(null)}>
          <button className="preview-close" onClick={() => setPreviewImage(null)}>
            <i className="codicon codicon-close" />
          </button>
          <img src={previewImage} alt="Preview" onClick={(e) => e.stopPropagation()} />
        </div>
      )}

      {/* Input area */}
      <div className="input-area">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask ClarAIty..."
          rows={1}
          aria-label="Message input"
          aria-autocomplete="list"
          aria-controls={showMentions ? "mention-listbox" : undefined}
          aria-activedescendant={showMentions && mentionResults.length > 0 ? `mention-${mentionIndex}` : undefined}
        />
      </div>
      <div className="input-toolbar">
        <div className="attach-wrapper" ref={attachMenuRef}>
          <button
            className="input-icon-btn"
            title="Attach"
            onClick={() => setShowAttachMenu((v) => !v)}
          >
            <i className="codicon codicon-attach" />
          </button>

          {showAttachMenu && (
            <div className="attach-menu">
              <button className="attach-menu-item" onClick={handleAddContext}>
                <i className="codicon codicon-mention" />
                <span>Add context (@)</span>
              </button>
              <button className="attach-menu-item" onClick={handlePickFile}>
                <i className="codicon codicon-cloud-upload" />
                <span>Upload from computer</span>
              </button>
            </div>
          )}
        </div>
        <button
          className={`send-icon-btn ${isStreaming ? "streaming" : ""}`}
          onClick={handleSend}
          title={isStreaming ? "Stop" : "Send"}
        >
          <i className={`codicon ${isStreaming ? "codicon-debug-stop" : "codicon-arrow-up"}`} />
        </button>
      </div>
    </div>
  );
}
