import { Component, type ReactNode } from 'react'

// Catches lazy-route chunk-load failures. After a Railway redeploy, a returning
// tab still holds the OLD index.html, which references hashed chunk files that no
// longer exist on the server → the dynamic import() rejects and, with no boundary,
// the whole app white-screens ("broken link / empty page; reload fixes it"). We
// reload ONCE to pull the fresh index + chunk names. A sessionStorage guard stops
// a reload loop when the failure is genuine (offline, real runtime error).
const RELOAD_FLAG = 'hk-chunk-reload'

function isChunkLoadError(err: unknown): boolean {
  const msg = err instanceof Error ? `${err.name} ${err.message}` : String(err)
  return /ChunkLoadError|Loading chunk|Loading CSS chunk|dynamically imported module|Importing a module script failed|Failed to fetch dynamically imported module/i.test(
    msg,
  )
}

interface State {
  error: Error | null
  reloading: boolean
}

export class ChunkErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, reloading: false }

  static getDerivedStateFromError(error: Error): State {
    // Reading sessionStorage here is side-effect-free; the actual reload fires in
    // componentDidCatch. `reloading` lets render() show nothing (not a flash of the
    // fallback) while the reload is in flight.
    const reloading = isChunkLoadError(error) && !sessionStorage.getItem(RELOAD_FLAG)
    return { error, reloading }
  }

  componentDidCatch(error: Error) {
    if (isChunkLoadError(error) && !sessionStorage.getItem(RELOAD_FLAG)) {
      sessionStorage.setItem(RELOAD_FLAG, '1')
      window.location.reload()
    }
  }

  componentDidMount() {
    // Fresh mount with no error (incl. after a successful reload) → clear the guard
    // so a future stale-chunk event can reload again.
    if (!this.state.error) sessionStorage.removeItem(RELOAD_FLAG)
  }

  render() {
    if (this.state.reloading) return null
    if (this.state.error) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-4 px-6 text-center">
          <p className="text-sm text-muted">Diese Seite konnte nicht geladen werden.</p>
          <button
            onClick={() => {
              sessionStorage.removeItem(RELOAD_FLAG)
              window.location.reload()
            }}
            className="rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            Neu laden
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
