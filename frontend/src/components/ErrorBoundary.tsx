import { Component, type ErrorInfo, type ReactNode } from 'react'

// 렌더 도중 예외가 나면 앱 전체가 언마운트돼 '검은 화면'이 된다.
// 에러 경계가 그 예외를 잡아 화면에 메시지를 띄우고(진단), 앱이 통째로 죽는 걸 막는다.
interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
  info: string
}

class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: '' }

  // 렌더 중 에러가 던져지면 React가 이걸 호출 → fallback UI로 전환
  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  // 에러 + 컴포넌트 스택 기록 (화면 표시 + 콘솔)
  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info: info.componentStack ?? '' })
    console.error('[ErrorBoundary]', error, info)
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    return (
      <div className="mx-auto mt-16 max-w-lg rounded-2xl border border-red-200 bg-white p-6 text-sm dark:border-red-500/30 dark:bg-white/[0.06]">
        <p className="text-base font-semibold text-red-600 dark:text-red-400">문제가 생겨서 화면을 그리지 못했어</p>
        <p className="mt-2 text-gray-600 dark:text-gray-300">
          아래 메시지를 알려주면 원인을 바로 잡을 수 있어.
        </p>
        {/* 실제 에러 메시지 — 진단의 핵심 */}
        <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-black/[0.04] p-3 text-xs text-red-700 dark:bg-white/10 dark:text-red-300">
          {error.message}
          {info ? `\n${info.split('\n').slice(0, 4).join('\n')}` : ''}
        </pre>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 inline-flex items-center justify-center rounded-full bg-[#0071e3] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#0077ed] dark:bg-[#0a84ff]"
        >
          새로고침
        </button>
      </div>
    )
  }
}

export default ErrorBoundary
