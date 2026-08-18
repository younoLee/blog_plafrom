/**
 * 블로그 스킨 — 주인이 저장한 CSS를 받아 화면에 얹는다.
 *
 * 얹는 방식: <head> 맨 뒤에 <style id="blog-skin">을 하나 두고 그 안에 넣는다.
 * 앱 스타일시트보다 뒤에 오므로 같은 우선순위면 스킨이 이긴다. 스킨이 하는 일은
 * 보통 index.css의 @theme 변수를 다시 정의하는 것이고, 그 변수 하나가 링크·버튼·
 * 태그칩·포커스 링·그라데이션까지 한꺼번에 바꾼다.
 *
 * **왜 localStorage에 캐시하는가** — 이 사이트는 서버(EC2)를 평소 꺼둔다. 스킨을
 * 서버에서만 받으면 **평상시에는 항상 기본색으로 그려진다.** 즉 기능이 있는데
 * 대부분의 방문에서 안 보이는 상태가 된다. 그래서 받은 값을 저장해 두고 다음
 * 방문에는 그것부터 즉시 바르고, 서버가 답하면 갱신한다.
 *
 * 부수 효과로 '기본색이 잠깐 보였다가 스킨으로 바뀌는' 깜빡임도 없어진다 —
 * 캐시 적용은 fetch를 기다리지 않고 첫 페인트 전에 동기로 끝난다.
 */
import { fetchWithTimeout, apiFetch } from './http'
import { authHeaders } from './session'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'
const CACHE_KEY = 'blog_skin_css'
const STYLE_ID = 'blog-skin'

/** <style id="blog-skin">의 내용을 갈아끼운다. 없으면 만들어 <head> 맨 뒤에 붙인다. */
function paint(css: string) {
  let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null
  if (!el) {
    el = document.createElement('style')
    el.id = STYLE_ID
    document.head.appendChild(el)
  }
  // **textContent로 넣는다(innerHTML 아님).** 텍스트 노드는 HTML로 파싱되지 않아서
  // 값에 `</style>`이 들어 있어도 태그가 닫히지 않는다. 서버도 입구에서 '<'를
  // 막지만(schemas/user.py의 SkinUpdate), 두 겹으로 막아 둔다 — 서버 검사는
  // 나중에 완화될 수 있고 그때 여기가 마지막 방어선이다.
  el.textContent = css
}

/** 저장해 둔 스킨을 즉시 바른다. 앱 렌더 전에 부른다(깜빡임 방지). */
export function applyCachedSkin(): void {
  try {
    const css = localStorage.getItem(CACHE_KEY)
    if (css) paint(css)
  } catch {
    // 사파리 프라이빗 모드 등에서 localStorage가 막힐 수 있다. 스킨은 장식이므로
    // 여기서 던지면 안 된다 — 화면 전체가 안 뜨는 것보다 기본색이 훨씬 낫다.
  }
}

/** 서버에서 최신 스킨을 받아 바르고 캐시를 갱신한다. 실패하면 조용히 넘어간다. */
export async function refreshSkin(): Promise<void> {
  try {
    const res = await fetchWithTimeout(`${BASE}/skin`)
    if (!res.ok) return
    const { css } = (await res.json()) as { css: string }
    paint(css)
    // 빈 문자열도 저장한다. '스킨을 지웠다'는 사실이 캐시에 반영돼야 다음 방문에
    // 옛 스킨이 되살아나지 않는다 — 되돌리기가 서버에서만 되고 화면에선 안 되는
    // 상태가 이 저장소가 반복해 밟은 '만들어져 있는데 연결이 없는' 모양이다.
    try {
      localStorage.setItem(CACHE_KEY, css)
    } catch {
      /* 저장 실패는 무시 — 이번 방문에는 이미 발려 있다 */
    }
  } catch {
    // 절전·네트워크 실패. 캐시가 이미 발려 있으니 화면은 멀쩡하다.
  }
}

/** 지금 적용 중인 스킨 CSS(설정 화면이 편집기에 채울 값). */
export async function fetchSkin(): Promise<string> {
  const res = await fetchWithTimeout(`${BASE}/skin`)
  if (!res.ok) throw new Error('스킨을 못 불러왔어')
  const { css } = (await res.json()) as { css: string }
  return css
}

/** 스킨을 저장한다(주인만). 빈 문자열을 보내면 기본 스킨으로 되돌아간다. */
export async function saveSkin(css: string): Promise<string> {
  const res = await apiFetch(`${BASE}/skin`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ custom_css: css }),
  })
  if (!res.ok) {
    // 422는 CSS 검사에 걸린 것 — 어느 문자가 걸렸는지 서버가 알려준다.
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    const msg = Array.isArray(detail) ? detail[0]?.msg : detail
    throw new Error(msg || '스킨 저장 실패')
  }
  const { css: saved } = (await res.json()) as { css: string }
  try {
    localStorage.setItem(CACHE_KEY, saved)
  } catch {
    /* 무시 */
  }
  paint(saved)
  return saved
}

/** 미리보기 — 저장하지 않고 화면에만 발라본다. */
export function previewSkin(css: string): void {
  paint(css)
}
