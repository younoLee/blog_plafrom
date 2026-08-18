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
import {
  EMPTY_SLOTS,
  normalizeSlots,
  scrubSlots,
  setSlots,
  type Slots,
} from './slots'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'
const CACHE_KEY = 'blog_skin_css'
// 문장은 CSS와 **따로** 담는다. 한 칸에 합치면 예전 방문자의 캐시(문자열 CSS)가
// 새 코드에서 JSON 파싱에 걸려 통째로 버려진다 — 그 사람들은 다음 방문에 기본색을 본다.
const SLOTS_KEY = 'blog_skin_slots'
const STYLE_ID = 'blog-skin'

/** 서버가 한 응답에 실어 보내는 두 가지. */
export type Customization = { css: string; slots: Slots }

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

/**
 * 저장해 둔 스킨·문장을 즉시 얹는다. 앱 렌더 전에 부른다(깜빡임 방지).
 *
 * localStorage가 막혀 있어도(사파리 프라이빗 모드 등) 던지지 않는다 — 장식 하나
 * 때문에 화면 전체가 안 뜨는 것보다 기본 외형이 훨씬 낫다.
 */
export function applyCachedSkin(): void {
  wear(cached())
}

/** 화면에 얹는다(캐시는 안 건드린다). */
function wear(data: Customization): void {
  paint(data.css)
  setSlots(scrubSlots(data.slots))
}

/**
 * 캐시에 남긴다. **사이트 것일 때만** 부른다.
 *
 * 캐시는 '이 사이트의 기본 외형' 한 벌이다. 주인이 아닌 글쓴이가 저장한 값을 여기
 * 넣으면 그 사람 브라우저에서 `/blog`가 자기 색으로 보인다 — 남에게는 안 보이는
 * 화면이라 "저장이 됐다"고 잘못 믿게 만든다.
 */
function remember(data: Customization): void {
  try {
    // 빈 값도 저장한다. '지웠다'는 사실이 캐시에 반영돼야 다음 방문에 옛 것이
    // 되살아나지 않는다 — 되돌리기가 서버에서만 되고 화면에선 안 되는 상태가
    // 이 저장소가 반복해 밟은 '만들어져 있는데 연결이 없는' 모양이다.
    localStorage.setItem(CACHE_KEY, data.css)
    localStorage.setItem(SLOTS_KEY, JSON.stringify(data.slots))
  } catch {
    /* 저장 실패는 무시 — 이번 방문에는 이미 얹혀 있다 */
  }
}

/** 캐시에 있는 사이트 외형을 읽는다(없으면 기본). */
function cached(): Customization {
  try {
    const raw = localStorage.getItem(SLOTS_KEY)
    return {
      css: localStorage.getItem(CACHE_KEY) ?? '',
      slots: raw ? normalizeSlots(JSON.parse(raw)) : EMPTY_SLOTS,
    }
  } catch {
    return { css: '', slots: EMPTY_SLOTS }
  }
}

/**
 * 사이트 외형으로 되돌린다 — 미리보기를 끝낼 때 쓴다.
 *
 * 왜 '내가 저장한 것'이 아니라 사이트 것인가: 편집기를 떠난 뒤 보이는 화면은
 * `/blog`·글 목록 같은 **사이트 화면**이다. 거기에 내 스킨이 남으면, 주인이 아닌
 * 글쓴이는 자기 색이 사이트에 적용된 줄 안다. 내 것은 `/@handle`에서 보인다.
 */
export function restoreSiteSkin(): void {
  wear(cached())
}

/** 응답 본문 → 두 가지. 서버가 slots를 안 주는 옛 버전이어도 화면이 안 깨진다. */
function readCustomization(body: unknown): Customization {
  const b = (body ?? {}) as { css?: unknown; slots?: unknown }
  return {
    css: typeof b.css === 'string' ? b.css : '',
    slots: normalizeSlots(b.slots),
  }
}

/** 서버에서 최신 스킨·문장을 받아 얹고 캐시를 갱신한다. 실패하면 조용히 넘어간다. */
export async function refreshSkin(): Promise<void> {
  try {
    const res = await fetchWithTimeout(`${BASE}/skin`)
    if (!res.ok) return
    const data = readCustomization(await res.json())
    wear(data)
    remember(data)
  } catch {
    // 절전·네트워크 실패. 캐시가 이미 얹혀 있으니 화면은 멀쩡하다.
  }
}

/**
 * **내** 스킨과 문장(편집기가 채울 값).
 *
 * 사이트 스킨(`GET /skin`)이 아니라 내 것이다. 글쓴이가 편집기를 열었을 때 주인의
 * CSS가 채워지면, 저장하는 순간 자기 스킨이 남의 것 사본이 된다.
 */
export async function fetchMine(): Promise<Customization> {
  const res = await fetchWithTimeout(`${BASE}/skin/me`, { headers: authHeaders() })
  if (!res.ok) throw new Error('내 설정을 못 불러왔어')
  return readCustomization(await res.json())
}

/**
 * 어떤 사람의 블로그(`/@handle`)를 여는 동안 그 사람 스킨을 바른다.
 *
 * **캐시에 저장하지 않는다.** localStorage 캐시는 '이 사이트의 기본 외형' 한 벌이다.
 * 남의 블로그를 구경하고 나왔는데 그 색이 남아 있으면 안 되고, 방문한 블로그 수만큼
 * 캐시가 갈라지면 어느 게 사이트 스킨인지 알 수 없게 된다.
 *
 * 돌려주는 함수를 부르면 사이트 스킨으로 되돌아간다(화면을 떠날 때 쓴다).
 * 되돌릴 값은 **캐시**에서 읽는다 — 서버가 꺼져 있어도 되돌아가야 하기 때문이다.
 *
 * 스킨과 문장이 **함께** 바뀐다. 하나만 바꾸면 남의 색에 내 문장이 얹히거나 그 반대가
 * 되는데, 그건 어느 쪽 화면으로도 말이 안 된다.
 */
export async function applySkinFor(handle: string): Promise<() => void> {
  const restore = () => {
    try {
      wear(cached())
    } catch {
      wear({ css: '', slots: EMPTY_SLOTS })
    }
  }
  try {
    const res = await fetchWithTimeout(`${BASE}/skin?handle=${encodeURIComponent(handle)}`)
    if (res.ok) wear(readCustomization(await res.json()))
  } catch {
    // 절전·네트워크 실패. 사이트 스킨이 그대로 남는다.
  }
  return restore
}

/**
 * 저장 공통. `isSite`는 '저장한 사람이 곧 사이트 주인인가'다 — 그때만 캐시를 갱신한다.
 * 화면에 즉시 얹는 건 누구든 한다(저장했는데 안 바뀌는 것처럼 보이는 게 이 기능에서
 * 제일 헷갈리는 순간이다).
 */
async function put(
  path: string,
  body: unknown,
  fallback: string,
  isSite: boolean,
): Promise<Customization> {
  const res = await apiFetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    // 422는 입력 검사에 걸린 것 — 무엇이 걸렸는지 서버가 문장으로 알려준다.
    const parsed = await res.json().catch(() => null)
    const detail = parsed?.detail
    const msg = Array.isArray(detail) ? detail[0]?.msg : detail
    throw new Error(msg || fallback)
  }
  const saved = readCustomization(await res.json())
  wear(saved)
  if (isSite) remember(saved)
  return saved
}

/** 스킨(CSS)을 저장한다. 빈 문자열을 보내면 기본 스킨으로 되돌아간다. */
export async function saveSkin(css: string, isSite: boolean): Promise<Customization> {
  return put('/skin', { custom_css: css }, '스킨 저장 실패', isSite)
}

/**
 * '내 문장' 세 칸을 저장한다.
 *
 * ⚠️ 돌려받는 값은 **보낸 것과 다를 수 있다.** 서버가 허용 목록으로 다시 쓰기 때문이다
 * (`<script>`·`on*`·`<iframe>` 등이 사라진다). 편집기는 이 결과로 입력칸을 다시 채워야
 * 한다 — 그래야 무엇이 빠졌는지 사람이 눈으로 본다.
 */
export async function saveSlots(slots: Slots, isSite: boolean): Promise<Customization> {
  return put('/skin/slots', slots, '문장 저장 실패', isSite)
}

/** 미리보기 — 저장하지 않고 화면에만 얹어 본다. */
export function previewSkin(css: string): void {
  paint(css)
}

/** 문장 미리보기. 그리는 경로가 같도록 여기서도 씻는다. */
export function previewSlots(slots: Slots): void {
  setSlots(scrubSlots(slots))
}
