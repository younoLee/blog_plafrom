import { useMemo } from 'react'

// 마크다운 본문에서 소제목(##, ###)을 뽑아 목차를 만든다.
//
// id는 rehype-slug가 렌더된 heading에 붙이는 것과 같은 규칙으로 만들어야 링크가 맞는다.
// rehype-slug는 github-slugger를 쓴다 — 소문자화, 공백은 '-', 일부 기호 제거, 한글은 유지.
// 여기선 그 규칙을 따라 하되, 중복 제목은 slugger처럼 '-1', '-2'를 붙여 맞춘다.

export type Heading = { depth: number; text: string; id: string }

// github-slugger의 핵심 동작만 옮긴 것.
// (전체 구현은 유니코드 표를 들고 다녀서 무겁다 — 우리 제목은 한글·영문·숫자·기호 몇 개뿐)
function slug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[\s\t\n]+/g, '-') // 공백류 → 하이픈
    .replace(/[^\p{L}\p{N}\-_]/gu, '') // 문자·숫자·하이픈·밑줄만 남김(한글 유지)
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
    const text = m[2].replace(/[*_`]/g, '').trim()
    if (!text) continue

    const base = slug(text)
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    out.push({ depth: m[1].length, text, id: n === 0 ? base : `${base}-${n}` })
  }
  return out
}

export function Toc({ content }: { content: string }) {
  const headings = useMemo(() => extractHeadings(content), [content])

  // 소제목이 2개 미만이면 목차가 의미 없다
  if (headings.length < 2) return null

  return (
    <nav
      aria-label="목차"
      className="my-6 rounded-2xl border border-black/[0.07] bg-black/[0.02] p-4 dark:border-white/10 dark:bg-white/[0.03]"
    >
      <h2 className="mb-2 text-sm font-semibold tracking-tight">목차</h2>
      <ol className="space-y-1">
        {headings.map((h) => (
          <li key={h.id} className={h.depth === 3 ? 'ml-4' : ''}>
            <a
              href={`#${h.id}`}
              className="text-sm text-gray-600 transition hover:text-[#0071e3] dark:text-gray-300 dark:hover:text-[#0a84ff]"
            >
              {h.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  )
}
