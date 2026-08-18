import { useEffect, useRef, useState } from 'react'
import { fetchSkin, saveSkin, previewSkin } from '../api/skin'
import { ui } from '../ui'
import { IconCheck } from './icons'

/**
 * 블로그 스킨 편집기 — CSS 변수를 고쳐 사이트 외형을 바꾼다.
 *
 * 미리보기는 별도 창이 아니라 **지금 보고 있는 이 화면**에 바로 바른다. 스킨이
 * 바꾸는 건 전역 CSS 변수라 미리보기 틀 안에 가둘 수가 없고, 가두면 정작 확인하고
 * 싶은 것(헤더·카드·버튼이 같이 어떻게 보이는지)을 못 본다.
 *
 * 그래서 **떠날 때 되돌린다.** 저장하지 않고 다른 화면으로 가면 원래 스킨으로
 * 돌아간다. 이게 없으면 실험하다 만 CSS가 새로고침 전까지 사이트에 남는다.
 */

// 프리셋 — 변수 몇 줄이 전부다. 이게 이 구조의 요점이라 예시도 그만큼만 보여준다.
const PRESETS: { name: string; hint: string; css: string }[] = [
  {
    name: 'velog풍',
    hint: '초록 강조 · 살짝 둥근 카드 · 각진 버튼',
    css: `:root {
  --color-accent: #20c997;
  --color-accent-hi: #12b886;
  --color-canvas: #f8f9fa;
  --radius-card: .5rem;
  --radius-btn: .25rem;
}
.dark { --color-accent: #38d9a9; --color-accent-hi: #20c997 }`,
  },
  {
    name: 'D2풍 (배치까지)',
    hint: '카드 격자 → 한 줄 리스트 + 우측 썸네일. 색만이 아니라 배치를 바꾼다',
    css: `/* 색 */
:root {
  --color-accent: #00c9b7;
  --color-accent-hi: #00b3a3;
  --color-accent-2: #00c9b7;
  --color-accent-3: #7bd8cf;
  --color-canvas: #ffffff;
  --radius-card: 0;
  --radius-field: 0;
  --radius-btn: 0;
}

/* 배치 — 카드 격자를 한 줄짜리 리스트로 바꾼다 */
[data-skin="hero"] { display: none }

[data-skin="post-grid"] { display: block }

[data-skin="post-card"] {
  display: grid;
  grid-template-columns: 1fr 200px;
  grid-template-rows: repeat(4, auto);
  column-gap: 28px;
  padding: 30px 0;
  border: 0;
  /* 글자색을 따라가는 구분선 — 검정으로 고정하면 다크모드에서 안 보인다 */
  border-bottom: 1px solid color-mix(in oklab, var(--color-ink) 14%, transparent);
  border-radius: 0;
  box-shadow: none;
  background: transparent;
  transform: none;
}
[data-skin="post-card"]:hover { box-shadow: none; transform: none }

[data-skin="post-thumb"] {
  grid-column: 2;
  grid-row: 1 / -1;
  align-self: start;
  margin: 0;
  border-radius: 0;
}
[data-skin="post-title"] { grid-column: 1; font-size: 1.6rem; line-height: 1.35 }
[data-skin="post-excerpt"] { grid-column: 1 }
[data-skin="post-tags"] { grid-column: 1 }
[data-skin="post-meta"] { grid-column: 1; border-top: 0; padding-top: .5rem }`,
  },
  {
    name: '네이버풍',
    hint: '초록 강조 · 각진 카드 · 알약 버튼',
    css: `:root {
  --color-accent: #03c75a;
  --color-accent-hi: #02b350;
  --color-canvas: #f5f6f7;
  --radius-card: .25rem;
  --radius-btn: 1.5rem;
}`,
  },
]

function SkinEditor() {
  const [draft, setDraft] = useState('')
  const [saved, setSaved] = useState('') // 서버에 저장돼 있는 값 (떠날 때 되돌릴 기준)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  // 언마운트 정리에서 읽어야 하는데 state를 그대로 읽으면 첫 렌더의 값(빈 문자열)에
  // 갇힌다 — 저장한 스킨이 있는데도 떠날 때 기본색으로 되돌아간다.
  const savedRef = useRef('')

  useEffect(() => {
    fetchSkin()
      .then((css) => {
        setDraft(css)
        setSaved(css)
        savedRef.current = css
      })
      .catch((e) => setError(e instanceof Error ? e.message : '스킨을 못 불러왔어'))
      .finally(() => setLoading(false))
  }, [])

  // 이 화면을 떠나면 저장된 스킨으로 되돌린다(미리보기가 사이트에 남지 않게).
  useEffect(() => {
    return () => previewSkin(savedRef.current)
  }, [])

  function edit(css: string) {
    setDraft(css)
    previewSkin(css) // 타이핑하는 대로 화면이 바뀐다
    setMsg('')
  }

  async function handleSave() {
    setBusy(true)
    setError('')
    setMsg('')
    try {
      const css = await saveSkin(draft)
      setSaved(css)
      savedRef.current = css
      setMsg(css ? '스킨을 저장했어. 방문자에게도 이대로 보여.' : '기본 스킨으로 되돌렸어.')
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    } finally {
      setBusy(false)
    }
  }

  function handleRevert() {
    edit(saved)
    setMsg('저장된 스킨으로 되돌렸어(아직 저장 전 상태는 버렸어).')
  }

  if (loading) return null

  const dirty = draft !== saved

  return (
    <section className={`${ui.card} mt-6`}>
      <h2 className="text-lg font-semibold tracking-tight">블로그 스킨</h2>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        CSS 변수를 고치면 링크·버튼·태그·포커스 링·그라데이션이 한꺼번에 따라 바뀌어.
        <br />
        <span className="text-xs">
          쓸 수 있는 변수: <code>--color-accent</code> <code>--color-accent-hi</code>{' '}
          <code>--color-canvas</code> <code>--color-ink</code> <code>--radius-card</code>{' '}
          <code>--radius-field</code> <code>--radius-btn</code>
        </span>
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.name}
            type="button"
            title={p.hint}
            onClick={() => edit(p.css)}
            className={ui.btnGhost}
          >
            {p.name}
          </button>
        ))}
        <button type="button" onClick={() => edit('')} className={ui.btnGhost}>
          기본으로
        </button>
      </div>

      <textarea
        value={draft}
        onChange={(e) => edit(e.target.value)}
        spellCheck={false}
        rows={12}
        placeholder={':root {\n  --color-accent: #20c997;\n}'}
        className={`${ui.input} mt-4 font-mono text-xs leading-relaxed`}
      />

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        지금 이 화면이 곧 미리보기야 — 타이핑하는 대로 바뀌어. 저장하지 않고 다른 화면으로
        가면 저장된 스킨으로 되돌아가.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button type="button" onClick={handleSave} disabled={busy || !dirty} className={ui.btnPrimary}>
          {busy ? '저장 중…' : dirty ? '저장' : '저장됨'}
        </button>
        {dirty && (
          <button type="button" onClick={handleRevert} className={ui.btnGhost}>
            되돌리기
          </button>
        )}
      </div>

      {msg && (
        <p className="mt-3 inline-flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
          <IconCheck className="h-4 w-4" />
          {msg}
        </p>
      )}
      {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
    </section>
  )
}

export default SkinEditor
