import { useEffect, useState } from 'react'
import { fetchMine, saveSkin, previewSkin, restoreSiteSkin } from '../api/skin'
import { useAuth } from '../auth/auth-context'
import { SKIN_HANDLES, SKIN_HANDLE_NAMES } from '../skinHandles'
import { joinSkin, splitSkin, type SkinOptions } from '../skinOptions'
import { ui } from '../ui'
import { IconCheck } from './icons'
import SkinPicker from './SkinPicker'

/**
 * 블로그 스킨 편집기 — 사이트 외형을 바꾼다. 두 층이다.
 *
 *   위: 눌러서 꾸미기(SkinPicker) — CSS를 몰라도 된다
 *   아래: 직접 쓴 CSS — 위층보다 **뒤에** 붙으므로 언제든 덮어쓴다
 *
 * 두 층은 저장될 때 문자열 하나로 합쳐진다(src/skinOptions.ts의 joinSkin).
 * 서버는 이 구분을 모르고 그냥 CSS로 받는다 — 그래서 백엔드가 안 바뀌었다.
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
    name: 'velog풍 (카드 격자)',
    hint: '초록 강조 + 목록을 2열 카드 격자로. 커버 이미지가 많은 블로그에 맞는다',
    css: `:root {
  --color-accent: #20c997;
  --color-accent-hi: #12b886;
  --color-canvas: #f8f9fa;
  --radius-card: .5rem;
}

/* 목록 → 카드 격자. 기본 화면이 목록이라 이쪽이 '배치를 바꾸는' 스킨이다. */
[data-skin="post-grid"] {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.25rem;
  border-bottom: 0;
}
[data-skin="post-grid"] > * { border-top: 0 }
[data-skin="post-card"] {
  display: block;
  padding: 1.25rem;
  border: 1px solid color-mix(in oklab, var(--color-ink) 10%, transparent);
  border-radius: var(--radius-card);
}
[data-skin="post-thumb"] { width: 100%; margin-bottom: .75rem }`,
  },
  {
    name: 'D2풍',
    hint: '민트 강조 · 모서리 없음 · 썸네일과 제목을 키운다. 기본 목록 형태를 그대로 쓴다',
    css: `:root {
  --color-accent: #00c9b7;
  --color-accent-hi: #00b3a3;
  --color-accent-2: #00c9b7;
  --color-accent-3: #7bd8cf;
  --color-canvas: #ffffff;
  --radius-card: 0;
  --radius-field: 0;
  --radius-btn: 0;
}

/* 목록은 기본값 그대로다. 줄 간격과 제목만 키운다. */
[data-skin="post-card"] { padding: 1.75rem 0 }
[data-skin="post-title"] { font-size: 1.6rem; line-height: 1.35 }

/* 머리말 구역에서 사이트가 넣은 두 줄만 지운다.
   전에는 hero를 통째로 display:none 했는데 그건 너무 넓었다 — 내가 쓴 머리말도
   같이 사라지고, /@주소 화면에서는 글쓴이 이름과 핸들까지 지워진다.
   자식만 지목하면 내 문장은 남는다. */
[data-skin="hero"] > h1,
[data-skin="hero"] > p { display: none }
[data-skin="hero"] { border-bottom: 0; padding-bottom: 0 }`,
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
  // 주인이 저장한 것만 '사이트 스킨'이다. 그 사람 것만 캐시에 남긴다
  // (api/skin.ts의 remember 주석 — 아니면 자기 브라우저에서만 /blog가 자기 색이 된다).
  const { user } = useAuth()
  const isSite = user?.role === 'admin'

  const [draft, setDraft] = useState('')
  const [saved, setSaved] = useState('') // 서버에 저장돼 있는 값 (떠날 때 되돌릴 기준)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    fetchMine()
      .then(({ css }) => {
        setDraft(css)
        setSaved(css)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '스킨을 못 불러왔어'))
      .finally(() => setLoading(false))
  }, [])

  // 이 화면을 떠나면 **사이트 스킨**으로 되돌린다(미리보기가 다른 화면에 남지 않게).
  // 전에는 '내가 저장한 것'으로 되돌렸는데, 주인이 아닌 글쓴이에게는 그게 틀렸다 —
  // 자기 색이 사이트에 적용된 것처럼 보인다. 내 스킨은 `/@handle`에서 확인한다.
  useEffect(() => restoreSiteSkin, [])

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
      const { css } = await saveSkin(draft, isSite)
      setSaved(css)
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
  // **상태는 CSS 문자열 하나뿐이다.** 체크박스 값을 따로 들고 있으면 손으로 CSS를
  // 고쳤을 때 둘이 어긋난다. 매번 갈라 읽는 편이 어긋날 자리가 없다.
  const { options, custom, generated } = splitSkin(draft)
  const setOptions = (next: SkinOptions) => edit(joinSkin(next, custom))
  const setCustom = (css: string) => edit(joinSkin(options, css))

  return (
    <section className={`${ui.card} mt-6`}>
      <h2 className="text-lg font-semibold tracking-tight">블로그 스킨</h2>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        눌러서 바꿔. 지금 보고 있는 이 화면이 곧 미리보기야 — 누르는 즉시 바뀌고,
        저장하지 않고 다른 화면으로 가면 저장된 스킨으로 되돌아가.
      </p>

      <SkinPicker value={options} onChange={setOptions} />

      {/* 눌러서 만든 것이 CSS로는 어떻게 생겼는지 보여준다. 접어 두는 이유는
          이걸 몰라도 되는 게 이 화면의 요점이기 때문이고, 그래도 두는 이유는
          여기가 CSS를 배우는 제일 짧은 입구이기 때문이다. */}
      {generated && (
        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-gray-500 select-none dark:text-gray-400">
            눌러서 만들어진 CSS 보기
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-field bg-black/[0.04] p-3 font-mono text-[11px] leading-relaxed dark:bg-white/5">
            {generated}
          </pre>
        </details>
      )}

      <h3 className="mt-6 border-t border-black/[0.06] pt-5 text-sm font-semibold dark:border-white/10">
        직접 쓰기 <span className="font-normal text-gray-500 dark:text-gray-400">(CSS를 아는 경우)</span>
      </h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        여기 쓴 건 위에서 누른 것보다 <strong>뒤에</strong> 붙어. 그래서 클릭으로 만든 값도
        여기서 덮어쓸 수 있어.
        <br />
        쓸 수 있는 변수: <code>--color-accent</code> <code>--color-accent-hi</code>{' '}
        <code>--color-canvas</code> <code>--color-ink</code> <code>--radius-card</code>{' '}
        <code>--radius-field</code> <code>--radius-btn</code>
        <br />
        아래 '내 문장'에 쓴 <code>class</code>도 여기서 잡힌다.
      </p>

      {/* 잡을 수 있는 자리. 스물다섯 개라 한 줄에 늘어놓으면 벽이 되고, 접어두면
          있는 줄도 모른다 — 그래서 묶어서 편다. 목록은 src/skinHandles.ts 하나에서
          온다(마크업·index.css 주석과 어긋나면 테스트가 잡는다). */}
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-gray-500 select-none dark:text-gray-400">
          잡을 수 있는 자리 {SKIN_HANDLE_NAMES.length}개 — <code>[data-skin="이름"]</code>
        </summary>
        <div className="mt-2 space-y-1.5">
          {SKIN_HANDLES.map((g) => (
            <div key={g.group} className="flex flex-wrap items-baseline gap-x-2 text-xs">
              <span className="w-14 shrink-0 text-gray-500 dark:text-gray-400">{g.group}</span>
              <span className="flex flex-wrap gap-x-2 gap-y-0.5">
                {g.names.map((n) => (
                  <code key={n}>{n}</code>
                ))}
              </span>
            </div>
          ))}
        </div>
      </details>

      <div className="mt-3 flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.name}
            type="button"
            title={p.hint}
            onClick={() => setCustom(p.css)}
            className={ui.btnGhost}
          >
            {p.name}
          </button>
        ))}
        <button
          type="button"
          onClick={() => edit('')}
          title="누른 것까지 전부 지운다"
          className={ui.btnGhost}
        >
          전부 기본으로
        </button>
      </div>

      <textarea
        value={custom}
        onChange={(e) => setCustom(e.target.value)}
        spellCheck={false}
        rows={10}
        placeholder={':root {\n  --color-accent: #20c997;\n}'}
        className={`${ui.input} mt-3 font-mono text-xs leading-relaxed`}
      />

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

      {!isSite && (
        <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
          이 스킨은 <strong>내 블로그(/@주소)</strong>에 걸려. 사이트 첫 화면의 색은 주인이 정해.
        </p>
      )}

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
