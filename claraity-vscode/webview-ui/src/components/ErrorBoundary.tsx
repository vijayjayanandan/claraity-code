/**
 * Top-level error boundary for the ClarAIty webview.
 *
 * Catches render errors in the React tree and displays a recovery UI
 * instead of a blank white panel.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ClarAIty] React error boundary caught:", error, info.componentStack);
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          style={{
            padding: 20,
            color: "var(--vscode-errorForeground, #f44)",
            fontFamily: "var(--vscode-font-family, sans-serif)",
            fontSize: "var(--vscode-font-size, 13px)",
          }}
        >
          <h3 style={{ margin: "0 0 8px" }}>Something went wrong</h3>
          <p style={{ margin: "0 0 12px", opacity: 0.8 }}>
            {this.state.error?.message || "An unexpected error occurred in the webview."}
          </p>
          <button
            onClick={this.handleReload}
            style={{
              padding: "6px 16px",
              background: "var(--vscode-button-background, #0078d4)",
              color: "var(--vscode-button-foreground, #fff)",
              border: "none",
              borderRadius: 2,
              cursor: "pointer",
              fontSize: "inherit",
            }}
          >
            Reload
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
