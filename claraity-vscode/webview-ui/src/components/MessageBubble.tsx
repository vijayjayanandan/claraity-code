/**
 * Individual chat message bubble with markdown rendering.
 *
 * Strips <project_context>...</project_context> blocks from user messages
 * (injected by the extension for LLM context, not meant to be displayed).
 *
 * When a user message has file or image attachments, renders them as
 * compact pill chips above the text content (matching Claude Code style).
 * - File chips with path: click opens in VS Code editor
 * - File chips without path (pasted/dropped): click shows content in modal
 * - Image chips: click opens full preview overlay
 */
import { useMemo, memo, useState, useEffect, useCallback } from "react";
import type { ChatMessage } from "../state/reducer";
import type { FileAttachment, ImageAttachment } from "../types";
import { renderMarkdown } from "../utils/markdown";
import { stripProjectContext } from "../utils/text";
import { useChatContext } from "../state/ChatContext";

interface MessageBubbleProps {
  message: ChatMessage;
  attachments?: FileAttachment[];
  images?: ImageAttachment[];
  searchQuery?: string;
}

/**
 * Decode an image data-URL to measure its natural width x height.
 * Returns null while loading or on error.
 */
function useImageDimensions(dataUrl: string | undefined): { w: number; h: number } | null {
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    if (!dataUrl) { setDims(null); return; }
    let cancelled = false;
    const img = new Image();
    img.onload = () => { if (!cancelled) setDims({ w: img.naturalWidth, h: img.naturalHeight }); };
    img.onerror = () => { if (!cancelled) setDims(null); };
    img.src = dataUrl;
    return () => { cancelled = true; };
  }, [dataUrl]);
  return dims;
}

/** Single image chip — shows icon, name, and dimensions once loaded. */
const ImageChip = memo(function ImageChip({
  image,
  onClick,
}: {
  image: ImageAttachment;
  onClick: () => void;
}) {
  const dims = useImageDimensions(image.data);
  const label = image.name || "image";
  return (
    <button className="attachment-chip image-chip" onClick={onClick} title={label}>
      <i className="codicon codicon-file-media" />
      <span className="chip-name">{label}</span>
      {dims && <span className="chip-dims">{dims.w}x{dims.h}</span>}
    </button>
  );
});

export const MessageBubble = memo(function MessageBubble({ message, attachments, images, searchQuery }: MessageBubbleProps) {
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [previewFileContent, setPreviewFileContent] = useState<{ name: string; content: string } | null>(null);
  const { postMessage } = useChatContext();

  const html = useMemo(() => {
    const displayContent = message.role === "user"
      ? stripProjectContext(message.content)
      : message.content;
    const rendered = renderMarkdown(displayContent);
    if (!searchQuery?.trim()) return rendered;
    const escaped = searchQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(?![^<]*>)(${escaped})`, "gi");
    return rendered.replace(re, '<mark class="search-highlight">$1</mark>');
  }, [message.content, message.role, searchQuery]);

  // Dismiss overlays on Escape key
  const dismissOverlays = useCallback(() => {
    setPreviewImage(null);
    setPreviewFileContent(null);
  }, []);
  useEffect(() => {
    if (!previewImage && !previewFileContent) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") dismissOverlays(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [previewImage, previewFileContent, dismissOverlays]);

  const hasChips = (attachments && attachments.length > 0) || (images && images.length > 0);

  const handleFileClick = (att: FileAttachment) => {
    if (att.content) {
      // Has inline content (pasted/dropped, or replayed from JSONL) — show original version
      setPreviewFileContent({ name: att.name, content: att.content });
    } else if (att.path) {
      // File from picker (current session, no inline content) — open in VS Code editor
      postMessage({ type: "openFile", path: att.path });
    }
  };

  return (
    <>
      <div className={`message ${message.role}`}>
        {hasChips && (
          <div className="attachment-chips">
            {attachments?.map((att, i) => (
              <button
                key={`file-${i}`}
                className={`attachment-chip file-chip${!att.path && !att.content ? " chip-inactive" : ""}`}
                onClick={() => handleFileClick(att)}
                disabled={!att.path && !att.content}
                title={att.path || att.name}
              >
                <i className="codicon codicon-file" />
                <span className="chip-name">{att.name}</span>
              </button>
            ))}
            {images?.map((img, i) => (
              <ImageChip
                key={`img-${i}`}
                image={img}
                onClick={() => setPreviewImage(img.data)}
              />
            ))}
          </div>
        )}
        <div
          className="content"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>

      {/* Image preview overlay */}
      {previewImage && (
        <div className="image-preview-overlay" onClick={() => setPreviewImage(null)}>
          <button className="preview-close" onClick={() => setPreviewImage(null)}>
            <i className="codicon codicon-close" />
          </button>
          <img src={previewImage} alt="Preview" onClick={(e) => e.stopPropagation()} />
        </div>
      )}

      {/* File content preview overlay */}
      {previewFileContent && (
        <div className="image-preview-overlay" onClick={() => setPreviewFileContent(null)}>
          <div className="file-content-modal" onClick={(e) => e.stopPropagation()}>
            <div className="file-content-header">
              <span className="file-content-title">{previewFileContent.name}</span>
              <button className="preview-close" onClick={() => setPreviewFileContent(null)}>
                <i className="codicon codicon-close" />
              </button>
            </div>
            <pre className="file-content-body">{previewFileContent.content}</pre>
          </div>
        </div>
      )}
    </>
  );
});
