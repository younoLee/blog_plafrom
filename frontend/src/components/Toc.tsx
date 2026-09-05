import { useEffect, useMemo, useState } from 'react'

// 마크다운 본문에서 소제목(##, ###)을 뽑아 목차를 만든다.
//
// id는 rehype-slug가 렌더된 heading에 붙이는 것과 같은 규칙으로 만들어야 링크가 맞는다.
// rehype-slug는 github-slugger를 쓴다 — 소문자화, 공백은 '-', 일부 기호 제거, 한글은 유지.
// 여기선 그 규칙을 따라 하되, 중복 제목은 slugger처럼 '-1', '-2'를 붙여 맞춘다.

export type Heading = { depth: number; text: string; id: string }

// 마크다운 원문의 HTML 엔티티를 푼다.
//
// **왜 필요한가 (2026-08-18에 화면에서 잡았다)** — 개발일지에 이런 소제목이 있다:
//     ## 5. 첫 번째 사고 — 화면에 &#39;가 글자로 보였다
// 본문은 react-markdown이 `'`로 풀어서 그리고, id를 붙이는 rehype-slug도 **풀린 글자**를
// 기준으로 만든다. 그런데 이 목차는 원문을 그대로 읽으므로 `39`라는 숫자가 남아
// **id가 서로 달라졌다.** 즉 그 항목은 눌러도 아무 데도 안 갔고, 글자도 `&#39;`로 보였다.
// 목차가 본문 위 한 덩어리였을 때는 스크롤하면 사라져서 티가 안 났다.
//
// 전부 다루지 않는다 — 이 저장소의 글에 실제로 쓰이는 것(따옴표·앰퍼샌드·부등호)과
// 숫자 참조만 푼다. 엔티티 표를 통째로 들고 오는 건 목차 하나에 과하다.
function decodeEntities(text: string): string {
  return text
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(Number(dec)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    // &amp; 는 **맨 마지막**이다. 먼저 풀면 `&amp;#39;`가 `&#39;`가 됐다가 위 규칙에
    // 다시 걸려 따옴표로 바뀐다(이중 해제).
    .replace(/&amp;/g, '&')
}

// github-slugger의 핵심 동작만 옮긴 것.
// (전체 구현은 유니코드 표를 들고 다녀서 무겁다 — 우리 제목은 한글·영문·숫자·기호 몇 개뿐)
function slug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[\s\t\n]+/g, '-') // 공백류 → 하이픈
    // 문자·**십진**숫자·하이픈·밑줄만 남긴다(한글 유지).
    //
    // `\p{Nd}`이지 `\p{N}`이 아니다 — 2026-08-18에 화면에서 잡은 차이다.
    // `①②③`은 유니코드에서 숫자(No)로 분류되므로 `\p{N}`은 그걸 남기는데,
    // rehype-slug는 지운다. 개발일지 소제목에 `## ① 소제목에 id는 있는데…`가
    // 실제로 있어서 id가 이렇게 갈렸다:
    //     목차  ①-소제목에-id는-있는데-…
    //     본문   -소제목에-id는-있는데-…   ← ①이 사라지고 앞 하이픈만 남는다
    // 한 글 10개 소제목 중 3개가 그래서 **눌러도 안 가는 링크**였다.
    //
    // 앞에 남는 하이픈을 다듬지 않는 것도 의도다. rehype-slug가 안 다듬으므로
    // 여기서 다듬으면 다시 어긋난다 — 맞춰야 할 상대는 '예쁜 문자열'이 아니라 그쪽이다.
    .replace(/[^\p{L}\p{Nd}\-_]/gu, '')
}

// Toc 내부 전용(외부 미사용) → export 안 함. 컴포넌트 파일이 컴포넌트만 export하게
// 해서 fast-refresh(react-refresh/only-export-components)를 만족시킨다.
function extractHeadings(markdown: string): Heading[] {
  const out: Heading[] = []
  const seen = new Map<string, number>()
  let inFence = false

  for (const line of markdown.split('\n')) {
    // 코드블록 안의 '#'은 주석이지 제목이 아니다
    if (/^\s*```/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue

    const m = /^(#{2,3})\s+(.+?)\s*#*\s*$/.exec(line)
    if (!m) continue

    // 제목에 남은 마크다운 강조 기호는 벗긴다 (**굵게** → 굵게)
    // 강조 기호를 벗기고 엔티티를 푼다 — 본문(rehype-slug)이 보는 글자와 같게 맞춘다
    const text = decodeEntities(m[2].replace(/[*_`]/g, '')).trim()
    if (!text) continue

    const base = slug(text)
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    out.push({ depth: m[1].length, text, id: n === 0 ? base : `${base}-${n}` })
  }
  return out
}

/** 지금 읽고 있는 절의 id. 화면에 걸친 소제목 중 **가장 위의 것**을 고른다.
 *
 *  왜 필요한가 — 목차를 옆에 고정해 두면 "어디를 읽고 있는지"를 표시해야 값을 한다.
 *  표시가 없으면 그냥 링크 목록이 계속 따라다니는 것뿐이고, 긴 글에서는 오히려
 *  눈에 걸린다.
 *
 *  왜 IntersectionObserver인가 — 스크롤마다 getBoundingClientRect를 도는 방법도 있지만
 *  그건 매 프레임 레이아웃을 강제로 계산시킨다. 관찰자는 브라우저가 알아서 묶어 준다.
 *
 *  rootMargin의 아래쪽이 큰 음수인 이유: 화면 위쪽 좁은 띠만 '읽는 중'으로 친다.
 *  안 그러면 화면에 걸친 소제목 서넛이 동시에 참이 되어 표시가 아래로 튄다.
 *  위쪽 -80px은 sticky 헤더에 가려지는 만큼이다.
 */
function useActiveHeading(ids: string[]): string {
  const [active, setActive] = useState('')

  useEffect(() => {
    if (!ids.length) return
    // 본문은 react-markdown이 그리므로 이 훅이 처음 도는 시점에 아직 없을 수 있다.
    const nodes = ids.map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[]
    if (!nodes.length) return

    const seen = new Map<string, boolean>()
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) seen.set(e.target.id, e.isIntersecting)
        // ids 순서대로 훑어 첫 번째로 보이는 것 = 화면 맨 위의 소제목
        const first = ids.find((id) => seen.get(id))
        if (first) setActive(first)
      },
      { rootMargin: '-80px 0px -70% 0px' },
    )
    nodes.forEach((n) => io.observe(n))
    return () => io.disconnect()
  }, [ids])

  return active
}

export function Toc({
  content,
  variant = 'inline',
}: {
  content: string
  /** inline = 본문 위 한 덩어리(좁은 화면) · aside = 왼쪽에 고정(넓은 화면) */
  variant?: 'inline' | 'aside'
}) {
  const headings = useMemo(() => extractHeadings(content), [content])
  const ids = useMemo(() => headings.map((h) => h.id), [headings])
  // 고정 목차에서만 '읽는 중' 표시를 쓴다. 본문 위 덩어리는 스크롤하면 어차피 사라진다.
  const active = useActiveHeading(variant === 'aside' ? ids : [])

  // 소제목이 2개 미만이면 목차가 의미 없다
  if (headings.length < 2) return null

  if (variant === 'aside') {
    return (
      <nav aria-label="목차" className="sticky top-20 max-h-[calc(100vh-7rem)] overflow-y-auto pr-2">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">목차</h2>
        {/* 왼쪽 세로선을 기준으로 항목을 건다. 지금 읽는 절만 그 선이 강조색이 된다 —
            테두리 상자를 두는 것보다 조용하고, 본문 옆에서 시선을 덜 뺏는다. */}
        <ol className="space-y-1 border-l border-black/[0.08] dark:border-white/10">
          {headings.map((h) => {
            const on = h.id === active
            return (
              <li key={h.id}>
                <a
                  href={`#${h.id}`}
                  aria-current={on ? 'true' : undefined}
                  className={`-ml-px block border-l py-1 text-sm leading-snug transition ${
                    h.depth === 3 ? 'pl-6' : 'pl-3'
                  } ${
                    on
                      ? 'border-accent font-medium text-accent'
                      : 'border-transparent text-gray-500 hover:text-ink dark:text-gray-400 dark:hover:text-white'
                  }`}
                >
                  {h.text}
                </a>
              </li>
            )
          })}
        </ol>
      </nav>
    )
  }

  return (
    <nav
      aria-label="목차"
      className="my-6 rounded-card border border-black/[0.07] bg-black/[0.02] p-4 dark:border-white/10 dark:bg-white/[0.03]"
    >
      <h2 className="mb-2 text-sm font-semibold tracking-tight">목차</h2>
      <ol className="space-y-1">
        {headings.map((h) => (
          <li key={h.id} className={h.depth === 3 ? 'ml-4' : ''}>
            <a
              href={`#${h.id}`}
              className="text-sm text-gray-600 transition hover:text-accent dark:text-gray-300"
            >
              {h.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  )
}
