/**
 * 눌러서 꾸미기 — 체크박스·색 고르기를 CSS로 옮긴다.
 *
 * 스킨 기능에는 지금까지 **CSS를 쓸 줄 아는 사람만 쓸 수 있는 문**밖에 없었다
 * (편집기의 textarea). 프리셋 세 개가 그 벽을 잠깐 낮춰주지만 프리셋은 고르는 것이지
 * 꾸미는 게 아니다. 여기는 CSS를 몰라도 되는 경로다.
 *
 * ## 저장 자리를 새로 만들지 않았다
 *
 * 옵션을 담을 컬럼을 추가하는 게 자연스러워 보이지만 그러면 마이그레이션 · 스키마 ·
 * 라우터 · 캐시 · 방문자 경로가 전부 따라 움직이고, 무엇보다 **서버를 배포해야** 한다.
 * 이 사이트는 서버(EC2)를 평소 꺼두므로 프론트만으로 끝나는 쪽이 실제로 닿는다.
 *
 * 그래서 옵션은 `custom_css` **안에** 산다. 저장되는 CSS는 두 부분이다:
 *
 *     /*@skin-options {"accent":"#20c997",...}*\/   ← 무엇을 눌렀는가 (다시 읽는 근거)
 *     :root { --color-accent: #20c997 }             ← 그 결과 (브라우저가 읽는 것)
 *     /*@skin-end*\/
 *     (여기부터 사람이 직접 쓴 CSS)
 *
 * 서버·방문자·캐시는 이걸 그냥 CSS로 본다. 아무것도 안 바꿔도 된다.
 *
 * ## 순서가 곧 권한이다
 *
 * 생성 블록이 **위**, 직접 쓴 CSS가 **아래**다. 같은 우선순위면 뒤가 이기므로
 * 손으로 쓴 한 줄은 언제나 클릭 결과를 덮을 수 있다. 반대로 두면 CSS를 아는 사람이
 * "왜 내가 쓴 게 안 먹지"에 갇힌다 — 클릭 UI가 상급자를 막는 물건이 되면 안 된다.
 */

export type Corner = 'round' | 'soft' | 'square'
export type ListShape = 'list' | 'grid'
/** 머리말 구역: 그대로 · 사이트가 넣은 두 줄만 숨김 · 통째로 숨김 */
export type HeroMode = 'show' | 'mine' | 'hide'

export type SkinOptions = {
  /** 강조색 hex. 빈 문자열이면 '기본값을 쓴다'는 뜻이라 CSS를 한 줄도 안 쓴다. */
  accent: string
  /** 바탕색 hex. 밝은 모드에만 먹는다(아래 canvas 주석). */
  canvas: string
  corner: Corner
  list: ListShape
  thumb: boolean
  excerpt: boolean
  tags: boolean
  meta: boolean
  sidebar: boolean
  hero: HeroMode
}

export const DEFAULT_OPTIONS: SkinOptions = {
  accent: '',
  canvas: '',
  corner: 'soft',
  list: 'list',
  thumb: true,
  excerpt: true,
  tags: true,
  meta: true,
  sidebar: true,
  hero: 'show',
}

const MARKER = /\/\*@skin-options\s*(\{[\s\S]*?\})\s*\*\//
const END = '/*@skin-end*/'

/* ------------------------------------------------------------------ 색 계산 */

const HEX = /^#[0-9a-f]{6}$/i

/** 두 색을 섞는다. `keep`은 앞 색을 남기는 비율(0~1). */
function mix(hex: string, toward: [number, number, number], keep: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const one = (c: number, t: number) =>
    Math.round(c * keep + t * (1 - keep))
      .toString(16)
      .padStart(2, '0')
  return `#${one(r, toward[0])}${one(g, toward[1])}${one(b, toward[2])}`
}

const BLACK: [number, number, number] = [0, 0, 0]
const WHITE: [number, number, number] = [255, 255, 255]

/**
 * 이 색 **위에** 얹을 글자색. WCAG 상대휘도로 고른다.
 *
 * 밝기를 눈대중(예: r+g+b 평균)으로 재면 안 된다 — 초록(#03c75a)과 파랑(#1c7ed6)은
 * 평균이 비슷한데 실제로 눈에 들어오는 밝기는 두 배 넘게 차이 난다. 대비 계산에
 * 쓰이는 값이 상대휘도이므로 고르는 기준도 그것이어야 한다.
 *
 * 경계 0.4는 흰 글자·검은 글자 중 **더 나은 쪽**이 갈리는 지점 근처다. 어느 쪽을
 * 골라도 4.5:1에 못 미치는 중간 밝기 색이 존재하는데, 그건 색을 고른 사람의 선택이라
 * 여기서 색을 바꾸지는 않는다 — 대신 항상 **덜 나쁜 쪽**을 준다.
 */
function onColor(hex: string): string {
  const ch = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  const lum = 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2)
  return lum > 0.4 ? '#111111' : '#ffffff'
}

/**
 * 강조색 하나에서 나머지 넷을 만든다.
 *
 * 사람에게 색을 다섯 개 고르라고 하면 안 된다 — 그건 CSS를 쓰라는 것과 난이도가
 * 같다. 그리고 강조색만 바꾸면 장식 그라데이션에 옛 색이 남아 반쯤만 먹은 것처럼
 * 보인다(index.css의 accent-2/3 주석에 그 이야기가 있다).
 *
 * hover가 **어두워지는** 쪽인 건 기본값이 그렇기 때문이다 — 잉크는 눌리면 진해진다.
 */
function accentVars(accent: string): string[] {
  return [
    `  --color-accent: ${accent};`,
    `  --color-accent-hi: ${mix(accent, BLACK, 0.82)};`,
    `  --color-accent-2: ${mix(accent, WHITE, 0.75)};`,
    `  --color-accent-3: ${mix(accent, WHITE, 0.45)};`,
    // 강조색과 그 위 글자색은 **짝**이다. 색만 바꾸고 글자를 두면 흰 바탕에 흰 글자가
    // 난다 — 예전엔 화면마다 `text-white`가 박혀 있어 스킨이 그걸 못 건드렸다.
    `  --color-on-accent: ${onColor(accent)};`,
  ]
}

const CORNERS: Record<Corner, string[] | null> = {
  // 'soft'가 기본값이라 한 줄도 안 쓴다. 기본값을 다시 적어두면 나중에 기본이
  // 바뀌었을 때 옛 값을 붙들고 있는 스킨이 된다.
  soft: null,
  round: [
    '  --radius-card: .75rem;',
    '  --radius-field: .5rem;',
    '  --radius-btn: .5rem;',
  ],
  square: ['  --radius-card: 0;', '  --radius-field: 0;', '  --radius-btn: 0;'],
}

/* ------------------------------------------------------------------ 생성 */

/**
 * 옵션 → CSS. 전부 기본값이면 **빈 문자열**이다.
 *
 * 빈 문자열이 중요한 이유: 그래야 '기본으로'가 정말 빈 스킨이 된다. 아무것도 안 바꾼
 * 상태에서도 표식과 블록이 남으면, 저장된 CSS가 비어 있지 않아서 서버가 NULL로
 * 되돌리지 못한다(라우터의 `css or None`).
 */
export function optionsToCss(o: SkinOptions): string {
  const vars: string[] = []
  if (HEX.test(o.accent)) vars.push(...accentVars(o.accent))
  if (HEX.test(o.canvas)) {
    // 밝은 모드에만 먹는다. 어두운 모드의 바탕·글자는 `:root.dark`가 (0,2,0)으로
    // 들고 있어서 이 `:root`(0,1,0)가 못 이긴다 — 일부러 그렇게 만들어 뒀다.
    // 클릭 UI에서 흰 바탕을 골랐다고 어두운 모드까지 하얘지면 글이 안 보인다.
    vars.push(`  --color-canvas: ${o.canvas};`)
  }
  const corner = CORNERS[o.corner]
  if (corner) vars.push(...corner)

  const rules: string[] = []
  if (vars.length) rules.push(`:root {\n${vars.join('\n')}\n}`)

  if (HEX.test(o.accent)) {
    // 어두운 모드에서는 같은 색이 바탕에 묻는다. 기본 스킨도 이 자리에서 밝은 쪽으로
    // 옮겨 쓴다. `:root.dark`로 쓰는 이유는 `:root`(위)를 이겨야 하기 때문 —
    // `:root:where(.dark)`는 우선순위가 0이라 위 블록에 진다.
    rules.push(
      `:root.dark {\n  --color-accent: ${mix(o.accent, WHITE, 0.55)};\n` +
        `  --color-accent-hi: ${mix(o.accent, WHITE, 0.38)};\n` +
        `  --color-on-accent: ${onColor(mix(o.accent, WHITE, 0.55))};\n}`,
    )
  }

  if (o.list === 'grid') {
    // 목록 → 2열 카드 격자. 격자 칸이 되는 건 PostRow가 아니라 그걸 감싼 요소라
    // (등장 애니메이션용) 선을 지우는 규칙이 `> *`에 붙는다.
    rules.push(
      '[data-skin="post-grid"] {\n' +
        '  display: grid;\n' +
        '  grid-template-columns: repeat(2, 1fr);\n' +
        '  gap: 1.25rem;\n' +
        '  border-bottom: 0;\n}',
      // ⚠️ `border-top`이 아니라 **양쪽**을 지운다. Tailwind의 `divide-y`가 실제로
      // 긋는 선은 bottom이다(`--tw-divide-y-reverse: 0` → top 0, bottom 1px).
      // top만 지우면 격자 칸마다 아래에 회색 줄이 한 줄 더 남는다.
      // `/@handle`에서는 Reveal 래퍼가 없어 post-card의 border가 우연히 덮어 멀쩡해
      // 보이는데, `/blog`에서는 Reveal이 한 겹 끼어 안 덮인다 — 그래서 눈으로 못 잡았다.
      '[data-skin="post-grid"] > * { border-block: 0 }',
      '[data-skin="post-card"] {\n' +
        '  display: block;\n' +
        '  padding: 1.25rem;\n' +
        '  border: 1px solid color-mix(in oklab, var(--color-ink) 12%, transparent);\n' +
        '  border-radius: var(--radius-card);\n}',
      '[data-skin="post-thumb"] { width: 100%; margin-bottom: .75rem }',
    )
  }

  if (!o.thumb) rules.push('[data-skin="post-thumb"] { display: none }')
  if (!o.excerpt) rules.push('[data-skin="post-excerpt"] { display: none }')
  if (!o.tags) rules.push('[data-skin="post-tags"] { display: none }')
  if (!o.meta) rules.push('[data-skin="post-meta"] { display: none }')

  if (!o.sidebar) {
    // 사이드바만 지우면 본문이 원래 폭(1fr)에 남아 오른쪽이 빈다. 격자를 한 단으로
    // 같이 접어야 '숨겼다'가 화면에서 말이 된다.
    rules.push(
      '[data-skin="sidebar"] { display: none }',
      '[data-skin="layout"] { grid-template-columns: 1fr }',
    )
  }

  if (o.hero === 'mine') {
    // 사이트가 넣은 제목·설명 두 줄만 지운다. hero를 통째로 숨기면 그 안에 있는
    // '내 문장'과 `/@주소` 화면의 글쓴이 이름까지 사라진다 — 실제로 그렇게 만들었다가
    // 고친 자리다.
    rules.push(
      '[data-skin="hero"] > h1,\n[data-skin="hero"] > p { display: none }',
      '[data-skin="hero"] { border-bottom: 0; padding-bottom: 0 }',
    )
  } else if (o.hero === 'hide') {
    rules.push('[data-skin="hero"] { display: none }')
  }

  return rules.join('\n\n')
}

/* ------------------------------------------------------------------ 읽고 쓰기 */

/** 서버·textarea가 뭘 주든 온전한 옵션 한 벌로 맞춘다. */
export function normalizeOptions(raw: unknown): SkinOptions {
  const src = (raw ?? {}) as Record<string, unknown>
  const str = (v: unknown, ok: string) =>
    typeof v === 'string' && HEX.test(v) ? v.toLowerCase() : ok
  const bool = (v: unknown, ok: boolean) => (typeof v === 'boolean' ? v : ok)
  const pick = <T extends string>(v: unknown, all: readonly T[], ok: T) =>
    all.includes(v as T) ? (v as T) : ok
  return {
    accent: str(src.accent, DEFAULT_OPTIONS.accent),
    canvas: str(src.canvas, DEFAULT_OPTIONS.canvas),
    corner: pick(src.corner, ['round', 'soft', 'square'] as const, DEFAULT_OPTIONS.corner),
    list: pick(src.list, ['list', 'grid'] as const, DEFAULT_OPTIONS.list),
    thumb: bool(src.thumb, DEFAULT_OPTIONS.thumb),
    excerpt: bool(src.excerpt, DEFAULT_OPTIONS.excerpt),
    tags: bool(src.tags, DEFAULT_OPTIONS.tags),
    meta: bool(src.meta, DEFAULT_OPTIONS.meta),
    sidebar: bool(src.sidebar, DEFAULT_OPTIONS.sidebar),
    hero: pick(src.hero, ['show', 'mine', 'hide'] as const, DEFAULT_OPTIONS.hero),
  }
}

export type SplitSkin = {
  options: SkinOptions
  /** 사람이 직접 쓴 CSS(생성 블록을 뺀 나머지). */
  custom: string
  /** 생성 블록의 CSS만. 편집기가 "눌러서 만든 게 이렇게 생겼다"를 보여줄 때 쓴다. */
  generated: string
}

/**
 * 저장된 CSS를 '눌러서 만든 것'과 '직접 쓴 것'으로 가른다.
 *
 * **표식이 없으면 전부 직접 쓴 것으로 본다.** 지금 저장돼 있는 스킨(프리셋을 눌러
 * 넣은 것 포함)이 다 그 경우이고, 그것들은 한 글자도 안 건드려야 한다.
 *
 * 표식은 있는데 끝이 없으면(손으로 반쯤 지웠다든가) 역시 전부 직접 쓴 것으로 본다.
 * 경계를 모르는 채로 잘라내면 남의 CSS를 먹는다 — 애매할 때는 아무것도 안 지운다.
 */
export function splitSkin(css: string): SplitSkin {
  const m = MARKER.exec(css)
  if (!m) return { options: { ...DEFAULT_OPTIONS }, custom: css, generated: '' }

  const bodyStart = m.index + m[0].length
  const endAt = css.indexOf(END, bodyStart)
  if (endAt === -1) return { options: { ...DEFAULT_OPTIONS }, custom: css, generated: '' }

  // 표식이 깨졌어도 블록 경계(끝 표식)는 멀쩡하다. 그럴 땐 옵션만 기본값으로 두고
  // 블록은 걷어낸다 — 안 그러면 저장할 때마다 새 블록이 하나씩 더 붙어 쌓인다.
  let parsed: unknown
  try {
    parsed = JSON.parse(m[1])
  } catch {
    parsed = null
  }

  // 표식 앞에 뭔가 있으면(사람이 위에 붙여 썼다면) 그것도 직접 쓴 것이다.
  //
  // ⚠️ 여기서 `.trim()`을 하면 안 된다. 이 함수는 편집기가 **매 렌더** 부르는데,
  // textarea가 controlled이라 잘린 값이 곧바로 화면에 되돌아온다 — 문서 끝에서
  // Enter가 아예 안 먹었다(2026-08-19 검사). 그래서 우리가 넣은 이음매만 걷어내고
  // 사람이 친 앞뒤 공백은 그대로 둔다. joinSkin의 `custom` 비-trim과 짝이다.
  const before = css.slice(0, m.index).replace(/\s+$/, '')
  const after = css.slice(endAt + END.length).replace(/^\n+/, '')
  return {
    options: normalizeOptions(parsed),
    custom: before && after ? `${before}\n\n${after}` : before || after,
    generated: css.slice(bodyStart, endAt).trim(),
  }
}

/**
 * 옵션과 직접 쓴 CSS를 한 벌로 합친다. splitSkin의 반대.
 *
 * ⚠️ **`custom`을 trim하지 않는다.** 전에는 했는데, 편집기의 textarea가 controlled이고
 * 그 값이 매 렌더 `splitSkin(draft).custom`으로 다시 계산되기 때문에 **키 하나 칠 때마다**
 * trim이 돌았다. 결과: 문서 끝에서 Enter를 눌러도 개행이 즉시 잘려 아무 일도 안 일어나고,
 * 첫 줄 들여쓰기도 안 들어간다 — 붙여넣기 말고는 CSS를 쓸 수 없었다(2026-08-19 검사).
 *
 * 저장할 값이 한 줄 길어지는 건 감수한다. 여기서 아끼는 몇 바이트보다 입력이 되는 게 낫다.
 */
export function joinSkin(o: SkinOptions, custom: string): string {
  const body = optionsToCss(o)
  const tail = custom
  // '비어 있다'의 판정만 공백을 무시한다. 공백뿐인 CSS는 안 쓴 것과 같고, 그래야
  // 서버가 NULL로 되돌린다(라우터의 `css or None`).
  if (!body) return tail.trim() ? tail : ''

  const head =
    `/*@skin-options ${JSON.stringify(o)}*/\n` +
    `/* 위 한 줄이 '눌러서 꾸미기'의 설정이고 아래는 그 결과다.\n` +
    `   저장할 때마다 다시 쓰이니 손으로 고쳐도 남지 않는다.\n` +
    `   직접 쓴 CSS는 @skin-end 아래에 둘 것 — 뒤에 오므로 여기를 이긴다. */\n` +
    `${body}\n${END}`
  return tail.trim() ? `${head}\n\n${tail}` : head
}

/** 기본값에서 한 칸이라도 달라졌는가. 편집기가 '되돌리기'를 띄울지 정할 때 쓴다. */
export function isDefaultOptions(o: SkinOptions): boolean {
  return optionsToCss(o) === ''
}
