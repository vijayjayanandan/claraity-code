/**
 * Clarification interview widget.
 *
 * Renders dynamic questions with radio/checkbox/text options.
 * Supports single-choice, multi-choice, and open-ended questions.
 */
import { useState, useCallback } from "react";
import type { WebViewMessage } from "../types";

interface ClarifyQuestion {
  id?: string;
  label?: string;
  question?: string;
  type?: string;
  multi_select?: boolean;
  options?: Array<string | { id?: string; label?: string }>;
}

interface ClarifyWidgetProps {
  callId: string;
  questions: unknown[];
  context?: string;
  postMessage: (msg: WebViewMessage) => void;
}

export function ClarifyWidget({
  callId,
  questions: rawQuestions,
  context,
  postMessage,
}: ClarifyWidgetProps) {
  const questions = rawQuestions as ClarifyQuestion[];
  const [dismissed, setDismissed] = useState(false);
  const [responses, setResponses] = useState<Record<string, string | string[]>>(() => {
    const init: Record<string, string | string[]> = {};
    for (const q of questions) {
      const qId = q.id || q.label || `q${questions.indexOf(q)}`;
      const isMulti = q.multi_select === true || q.type === "multi_choice";
      init[qId] = isMulti ? [] : "";
    }
    return init;
  });

  const handleSubmit = useCallback(() => {
    postMessage({
      type: "clarifyResult",
      callId,
      submitted: true,
      responses: responses as Record<string, unknown>,
    });
    setDismissed(true);
  }, [callId, responses, postMessage]);

  const handleCancel = useCallback(() => {
    postMessage({
      type: "clarifyResult",
      callId,
      submitted: false,
      responses: null,
    });
    setDismissed(true);
  }, [callId, postMessage]);

  if (dismissed) {
    return (
      <div className="interactive-widget clarify-widget">
        <div className="widget-body" style={{ fontSize: 12, color: "var(--vscode-descriptionForeground)" }}>
          [Clarification {responses ? "submitted" : "cancelled"}]
        </div>
      </div>
    );
  }

  return (
    <div className="interactive-widget clarify-widget">
      <div className="widget-header">Clarification Needed</div>
      <div className="widget-body">
        {context && <div className="context-text">{context}</div>}

        {questions.map((q) => {
          const qId = q.id || q.label || `q${questions.indexOf(q)}`;
          const isMulti = q.multi_select === true || q.type === "multi_choice";
          const hasOptions = q.options && q.options.length > 0;

          return (
            <div key={qId} className="question-group">
              <div className="question-label">{q.question || q.label || ""}</div>

              {hasOptions ? (
                <>
                  {q.options!.map((opt) => {
                    const optValue = typeof opt === "string" ? opt : (opt.id || opt.label || "");
                    const optLabel = typeof opt === "string" ? opt : (opt.label || opt.id || "");
                    return (
                      <div key={optValue} className="option-row">
                        <input
                          type={isMulti ? "checkbox" : "radio"}
                          name={`clarify-${qId}`}
                          value={optValue}
                          checked={
                            isMulti
                              ? (responses[qId] as string[]).includes(optValue)
                              : responses[qId] === optValue
                          }
                          onChange={() => {
                            if (isMulti) {
                              setResponses((prev) => {
                                const arr = prev[qId] as string[];
                                return {
                                  ...prev,
                                  [qId]: arr.includes(optValue)
                                    ? arr.filter((v) => v !== optValue)
                                    : [...arr, optValue],
                                };
                              });
                            } else {
                              setResponses((prev) => ({
                                ...prev,
                                [qId]: optValue,
                              }));
                            }
                          }}
                        />
                        <label>{optLabel}</label>
                      </div>
                    );
                  })}
                  {/* Custom "Other" input */}
                  <div className="option-row" style={{ marginTop: 4 }}>
                    <input
                      type="text"
                      placeholder="Other (custom answer)..."
                      style={{
                        flex: 1,
                        background: "var(--vscode-input-background)",
                        color: "var(--vscode-input-foreground)",
                        border: "1px solid var(--vscode-input-border, transparent)",
                        borderRadius: 2,
                        padding: "3px 6px",
                        fontSize: 12,
                        fontFamily: "var(--vscode-font-family)",
                      }}
                      onChange={(e) => {
                        const val = e.target.value.trim();
                        if (isMulti) {
                          // Add custom value to existing checked options
                          setResponses((prev) => {
                            const arr = prev[qId] as string[];
                            // Remove any previous custom entry, then add new if non-empty
                            const knownOpts = new Set(
                              (q.options || []).map((o) => typeof o === "string" ? o : (o.id || o.label || "")),
                            );
                            const filtered = arr.filter((v) => knownOpts.has(v));
                            return {
                              ...prev,
                              [qId]: val ? [...filtered, val] : filtered,
                            };
                          });
                        } else {
                          // Single-choice: replace the selection with custom value
                          if (val) {
                            setResponses((prev) => ({ ...prev, [qId]: val }));
                          }
                        }
                      }}
                    />
                  </div>
                </>
              ) : (
                <textarea
                  placeholder="Your answer..."
                  onChange={(e) =>
                    setResponses((prev) => ({
                      ...prev,
                      [qId]: e.target.value,
                    }))
                  }
                />
              )}
            </div>
          );
        })}
      </div>

      <div className="widget-actions">
        <button className="btn-primary" onClick={handleSubmit}>
          Submit
        </button>
        <button className="btn-secondary" onClick={handleCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
