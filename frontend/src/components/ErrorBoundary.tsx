import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time exceptions so a single malformed event or component throw
 * shows a recoverable fallback instead of blanking the whole app.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("UI crashed:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="banner warn" style={{ margin: 16 }}>
          <b>Something went wrong rendering the UI.</b>
          <div className="muted">{this.state.error.message}</div>
          <button
            className="primary"
            style={{ marginTop: 8 }}
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
