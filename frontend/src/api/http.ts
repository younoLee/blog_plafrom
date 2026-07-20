/**
 * 호출별 타임아웃이 붙은 fetch.
 *
 * 왜 필요한가: 이 블로그는 비용 습관상 서버(EC2)를 안 쓸 때 꺼둔다. 그러면
 * CloudFront가 오리진을 기다리다 504를 주는데, 오리진 타임아웃이 60초라
 * 방문자는 1분을 멍하니 기다린 뒤 빨간 에러를 본다 — 절전인데 고장으로 보인다.
 *
 * 그 60초는 AI 초안 생성(실측 ~10초, 모델에 따라 더)에 필요해서 인프라에서
 * 낮출 수 없다. 그래서 '호출별로' 다르게 준다: 목록·상태는 짧게 끊어 빨리
 * 안내하고, AI 초안만 길게 기다린다.
 */

/** 화면 조회용 기본 상한. 서버가 깨어 있으면 이보다 훨씬 빨리 온다. */
export const QUICK_TIMEOUT_MS = 8000

/** 서버가 안 깨어 있어 응답이 없는 경우. 일반 실패와 구분해 안내를 다르게 하려고 따로 둔다. */
export class ServerAsleepError extends Error {
  constructor() {
    super('서버가 절전 중이야')
    this.name = 'ServerAsleepError'
  }
}

/** 504/503도 오리진이 안 뜬 상태라 절전으로 본다(꺼둔 서버의 실제 응답이 504다). */
export function isAsleepStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504
}

export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs: number = QUICK_TIMEOUT_MS,
): Promise<Response> {
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: ac.signal })
    if (isAsleepStatus(res.status)) throw new ServerAsleepError()
    return res
  } catch (e) {
    // abort = 시간 안에 응답이 없음 → 켜지는 중이거나 꺼져 있음
    if (e instanceof DOMException && e.name === 'AbortError') throw new ServerAsleepError()
    throw e
  } finally {
    clearTimeout(timer)
  }
}
