/**
 * Streamed code block with language label and copy button.
 */
import { useState, useCallback } from "react";
import type { CodeBlock as CodeBlockType } from "../state/reducer";
import type { WebViewMessage } from "../types";

interface CodeBlockProps {
  block: CodeBlockType;
  postMessage: (msg: WebViewMessage) => void;
}

export function CodeBlock({ block, postMessage }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    postMessage({ type: "copyToClipboard", text: block.content });
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [block.content, postMessage]);

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="lang-label">{block.language || "code"}</span>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre>
        <code>{block.content}{!block.complete && "\u2588"}</code>
      </pre>
    </div>
  );
}
