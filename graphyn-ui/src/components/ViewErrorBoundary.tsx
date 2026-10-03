import React from 'react'
import { buildCrashReport } from '../lib/crashReport'

/**
 * Per-view crash boundary. The app-level `ErrorBoundary` replaces the whole
 * shell (sidebar included) — one broken page then strands the user. This one
 * wraps only the main pane: the sidebar/header keep working, and navigating to
 * another view (`resetKey` changes) clears the error automatically.
 */
type Props = { children: React.ReactNode; resetKey: string; viewLabel: string }
type State = { error: Error | null; componentStack: string | null; copied: boolean; key: string }

export class ViewErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, componentStack: null, copied: false, key: this.props.resetKey }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey !== state.key) {
      return { key: props.resetKey, error: null, componentStack: null, copied: false }
    }
    return null
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ componentStack: info.componentStack ?? null })
    console.error(`[graphyn] ${this.props.viewLabel} view crashed`, error)
  }

  private report = async () => {
    const { error, componentStack } = this.state
    if (!error) return
    const text = buildCrashReport(this.props.viewLabel, error, componentStack || error.stack)
    try {
      await navigator.clipboard.writeText(text)
      this.setState({ copied: true })
    } catch {
      window.prompt('Copy this report and send it to your Graphyn admin:', text)
    }
  }

  render() {
    const { error, copied } = this.state
    if (!error) return this.props.children
    return (
      <div className="flex h-full min-h-0 items-start justify-center overflow-auto p-6" role="alert">
        <div className="w-full max-w-xl rounded-2xl border border-rose-200 bg-rose-50 p-5 shadow-sm">
          <h2 className="text-[15px] font-semibold tracking-tight text-rose-900">
            This page failed to load
          </h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-rose-800">
            The {this.props.viewLabel} page hit an unexpected error. The rest of the console still works —
            use the sidebar to go elsewhere, or try again.
          </p>
          <details className="mt-2 text-[12px] text-rose-700">
            <summary className="cursor-pointer select-none">Technical details</summary>
            <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px]">{error.message}</pre>
          </details>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={() => window.location.reload()}>
              Reload page
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => this.setState({ error: null, componentStack: null, copied: false })}
            >
              Try again
            </button>
            <button
              type="button"
              className="btn-secondary"
              title="Copy an error report to the clipboard"
              onClick={() => void this.report()}
            >
              {copied ? 'Report copied' : 'Report'}
            </button>
          </div>
        </div>
      </div>
    )
  }
}
