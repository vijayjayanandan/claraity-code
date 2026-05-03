/**
 * Chat input box with @file mentions, file attachments, image paste, and send/interrupt.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import type { FileAttachment, ImageAttachment, SkillInfo, WebViewMessage } from "../types";
import { SkillPicker } from "./SkillPicker";

interface InputBoxProps {
  isStreaming: boolean;
  connected: boolean;
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
  // Prompt Enrichment
  enrichmentEnabled: boolean;
  enrichmentLoading: boolean;
  enrichedPreview: string | null;
  enrichedOriginal: string | null;
  onToggleEnrichment: (enabled: boolean) => void;
  onRequestEnrichment: (content: string) => void;
  onClearEnrichment: () => void;
  draft: string;
  onDraftChange: (draft: string) => void;
  // Skills
  skillsList: SkillInfo[];
  activeSkill: string | null;
  onSelectSkill: (skillId: string) => void;
  onRequestSkills: () => void;
  onCreateSkill: () => void;
}

const MAX_IMAGES = 5;
const MAX_FILES = 10;
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;   // 10MB
const MAX_FILE_SIZE = 1 * 1024 * 1024;     // 1MB for text file reads
const MAX_TEXT_LENGTH = 100_000; // 100KB max input to prevent UI freeze

/** MIME types we can meaningfully read as text. */
const TEXT_MIME_PREFIXES = ["text/", "application/json", "application/xml", "application/javascript", "application/typescript", "application/x-yaml", "application/toml"];
function isTextFile(file: File): boolean {
  if (TEXT_MIME_PREFIXES.some((p) => file.type.startsWith(p))) return true;
  // Fallback: check common text extensions when MIME is empty (common for .log, .yaml, etc.)
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return ["ts", "tsx", "js", "jsx", "py", "json", "yaml", "yml", "toml", "xml", "csv", "log", "txt", "md", "sh", "bat", "cfg", "ini", "env", "sql", "html", "css", "scss", "less", "svelte", "vue", "rs", "go", "java", "kt", "c", "cpp", "h", "hpp", "rb", "php", "swift", "r", "m", "ps1"].includes(ext);
}

export function InputBox({
  isStreaming,
  connected,
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
  enrichmentEnabled,
  enrichmentLoading,
  enrichedPreview,
  enrichedOriginal,
  onToggleEnrichment,
  onRequestEnrichment,
  onClearEnrichment,
  draft,
  onDraftChange,
  skillsList,
  activeSkill,
  onSelectSkill,
  onRequestSkills,
  onCreateSkill,
}: InputBoxProps) {
  const text = draft;
  const setText = onDraftChange;
  const [showMentions, setShowMentions] = useState(false);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  const [showSkillPicker, setShowSkillPicker] = useState(false);
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

  // Local state for editing the enriched preview
  const [editedPreview, setEditedPreview] = useState<string | null>(null);
  useEffect(() => {
    if (enrichedPreview !== null) setEditedPreview(enrichedPreview);
  }, [enrichedPreview]);

  // Send the enriched (possibly edited) prompt
  const handleSendEnriched = useCallback(() => {
    const content = editedPreview ?? enrichedPreview ?? "";
    if (!content.trim()) return;
    onSend(content, attachments.length > 0 ? attachments : undefined, images.length > 0 ? images : undefined);
    setText("");
    onClearEnrichment();
  }, [editedPreview, enrichedPreview, onSend, attachments, images, onClearEnrichment]);

  // Handle send — intercept for enrichment when enabled
  const handleSend = useCallback(() => {
    if (isStreaming) {
      onInterrupt();
      return;
    }
    // Block while enrichment LLM is running (spinner is visible)
    if (enrichmentLoading) return;

    // If enrichment preview is showing, send the enriched (possibly edited) text
    // (checked before the empty-input guard since the original draft may be empty)
    if (enrichedPreview) {
      handleSendEnriched();
      return;
    }

    const trimmed = text.trim();
    if (!trimmed && images.length === 0 && attachments.length === 0) return;

    // If enrichment is ON and no preview yet, request enrichment instead of sending
    if (enrichmentEnabled) {
      onRequestEnrichment(trimmed);
      return;
    }

    onSend(trimmed, attachments.length > 0 ? attachments : undefined, images.length > 0 ? images : undefined);
    setText("");
  }, [text, isStreaming, onSend, onInterrupt, attachments, images, enrichmentEnabled, enrichedPreview, enrichmentLoading, onRequestEnrichment, handleSendEnriched]);

  // Cancel enrichment preview
  const handleCancelEnrichment = useCallback(() => {
    onClearEnrichment();
    setEditedPreview(null);
    textareaRef.current?.focus();
  }, [onClearEnrichment]);

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

  // Drag-and-drop state — use a counter to prevent flicker when hovering child elements
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounter = useRef(0);
  const [dropWarning, setDropWarning] = useState<string | null>(null);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    setIsDragOver(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) setIsDragOver(false);
  }, []);

  // Show a brief warning then auto-dismiss (with cleanup to avoid stale timers)
  const warningTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const showWarning = useCallback((msg: string) => {
    if (warningTimerRef.current) clearTimeout(warningTimerRef.current);
    setDropWarning(msg);
    warningTimerRef.current = setTimeout(() => setDropWarning(null), 3000);
  }, []);
  useEffect(() => () => { if (warningTimerRef.current) clearTimeout(warningTimerRef.current); }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setIsDragOver(false);
      const files = e.dataTransfer?.files;
      if (!files) return;
      let imgCount = images.length;
      let fileCount = attachments.length;
      for (const file of files) {
        if (file.type.startsWith("image/")) {
          if (imgCount >= MAX_IMAGES) { showWarning(`Max ${MAX_IMAGES} images allowed`); continue; }
          if (file.size > MAX_IMAGE_SIZE) { showWarning("Image too large (max 10MB)"); continue; }
          imgCount++;
          const reader = new FileReader();
          reader.onload = () => {
            onAddImage({
              data: reader.result as string,
              mimeType: file.type,
              name: file.name || "dropped-image",
            });
          };
          reader.onerror = () => showWarning(`Failed to read ${file.name}`);
          reader.readAsDataURL(file);
        } else if (isTextFile(file)) {
          if (fileCount >= MAX_FILES) { showWarning(`Max ${MAX_FILES} files allowed`); continue; }
          if (file.size > MAX_FILE_SIZE) { showWarning("File too large (max 1MB)"); continue; }
          fileCount++;
          const reader = new FileReader();
          reader.onload = () => {
            onAddAttachment({
              path: "",
              name: file.name || "dropped-file",
              content: reader.result as string,
            });
          };
          reader.onerror = () => showWarning(`Failed to read ${file.name}`);
          reader.readAsText(file);
        } else {
          showWarning(`Unsupported file type: ${file.name}`);
        }
      }
    },
    [images.length, attachments.length, onAddImage, onAddAttachment, showWarning],
  );

  // Handle paste (images + files)
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      let imgCount = images.length;
      let fileCount = attachments.length;
      for (const item of items) {
        if (item.kind !== "file") continue;
        const file = item.getAsFile();
        if (!file) continue;
        if (item.type.startsWith("image/")) {
          if (imgCount >= MAX_IMAGES) continue;
          if (file.size > MAX_IMAGE_SIZE) continue;
          e.preventDefault();
          imgCount++;
          const reader = new FileReader();
          reader.onload = () => {
            onAddImage({
              data: reader.result as string,
              mimeType: item.type,
              name: file.name || "pasted-image",
            });
          };
          reader.onerror = () => { /* silent on paste */ };
          reader.readAsDataURL(file);
        } else if (isTextFile(file)) {
          if (fileCount >= MAX_FILES) continue;
          if (file.size > MAX_FILE_SIZE) continue;
          e.preventDefault();
          fileCount++;
          const reader = new FileReader();
          reader.onload = () => {
            onAddAttachment({
              path: "",
              name: file.name || "pasted-file",
              content: reader.result as string,
            });
          };
          reader.onerror = () => { /* silent on paste */ };
          reader.readAsText(file);
        }
      }
    },
    [images.length, attachments.length, onAddImage, onAddAttachment],
  );

  return (
    <div
      className={`input-container${isDragOver ? " drag-over" : ""}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragOver && (
        <div className="drag-overlay">
          <i className="codicon codicon-cloud-upload" />
          <span>Drop files here</span>
        </div>
      )}
      {/* Drop warning */}
      {dropWarning && (
        <div className="drop-warning">{dropWarning}</div>
      )}
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

      {/* Active skill badge */}
      {activeSkill && skillsList.find((s) => s.id === activeSkill) && (
        <div className="skill-badge-bar">
          <span className="skill-badge" title={skillsList.find((s) => s.id === activeSkill)!.description}>
            <i className="codicon codicon-lightbulb" />
            {skillsList.find((s) => s.id === activeSkill)!.name}
            <span className="skill-badge-remove" onClick={() => onSelectSkill(activeSkill)}>x</span>
          </span>
        </div>
      )}

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

      {/* Enrichment loading indicator */}
      {enrichmentLoading && (
        <div className="enrichment-loading">
          <i className="codicon codicon-loading codicon-modifier-spin" />
          <span>Enriching prompt...</span>
        </div>
      )}

      {/* Enrichment preview area */}
      {enrichedPreview && !enrichmentLoading && (
        <div className="enrichment-preview">
          {enrichedOriginal && (
            <div className="enrichment-original">
              <div className="enrichment-original-label">Original</div>
              <div className="enrichment-original-text">{enrichedOriginal}</div>
            </div>
          )}
          <div className="enrichment-preview-header">
            <span className="enrichment-preview-label">
              <i className="codicon codicon-sparkle" />
              Enriched Prompt
            </span>
          </div>
          <textarea
            className="enrichment-preview-textarea"
            value={editedPreview ?? enrichedPreview}
            onChange={(e) => setEditedPreview(e.target.value)}
            rows={6}
          />
          <div className="enrichment-preview-actions">
            <button className="enrichment-btn enrichment-btn-send" onClick={handleSendEnriched}>
              Send
            </button>
            <button className="enrichment-btn enrichment-btn-cancel" onClick={handleCancelEnrichment}>
              Cancel
            </button>
          </div>
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
          placeholder={connected ? "Ask ClarAIty..." : "Disconnected from server..."}
          rows={1}
          disabled={!connected}
          aria-label="Message input"
          aria-autocomplete="list"
          aria-controls={showMentions ? "mention-listbox" : undefined}
          aria-activedescendant={showMentions && mentionResults.length > 0 ? `mention-${mentionIndex}` : undefined}
        />
      </div>
      <div className="input-toolbar">
        <button
          className={`input-icon-btn${enrichmentEnabled ? " enrichment-active" : ""}`}
          title={enrichmentEnabled ? "Prompt Enrichment ON" : "Prompt Enrichment OFF"}
          onClick={() => onToggleEnrichment(!enrichmentEnabled)}
          disabled={isStreaming}
        >
          <i className="codicon codicon-sparkle" />
        </button>
        <div className="skill-wrapper">
          <button
            className={`input-icon-btn${activeSkill ? " skills-active" : ""}`}
            title={activeSkill ? `Skill active: ${skillsList.find(s => s.id === activeSkill)?.name || activeSkill}` : "Skills"}
            onClick={() => setShowSkillPicker((v) => !v)}
            disabled={isStreaming}
          >
            <i className="codicon codicon-lightbulb" />
          </button>
          {showSkillPicker && (
            <SkillPicker
              skills={skillsList}
              activeSkill={activeSkill}
              onSelect={onSelectSkill}
              onRequestRefresh={onRequestSkills}
              onCreateSkill={() => { setShowSkillPicker(false); onCreateSkill(); }}
              onClose={() => setShowSkillPicker(false)}
            />
          )}
        </div>
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
          title={isStreaming ? "Stop" : connected ? "Send" : "Disconnected"}
          disabled={!connected && !isStreaming}
        >
          <i className={`codicon ${isStreaming ? "codicon-debug-stop" : "codicon-arrow-up"}`} />
        </button>
      </div>
    </div>
  );
}
