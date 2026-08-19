import type { ReactNode } from 'react'
import type { Corner, HeroMode, ListShape, SkinOptions } from '../skinOptions'
import { ui } from '../ui'

/**
 * 눌러서 꾸미기 — CSS를 몰라도 블로그 외형을 바꾼다.
 *
 * 스킨 편집기 위에 얹히고, 누른 결과는 편집기가 들고 있는 CSS의 **위쪽 블록**으로
 * 들어간다(변환은 src/skinOptions.ts). 그래서 여기는 상태를 스스로 안 갖는다 —
 * 진짜 값은 CSS 문자열 하나뿐이고 이 화면은 그걸 읽어 그린다. 두 벌로 나눠 갖고
 * 있으면 손으로 CSS를 고쳤을 때 체크박스가 거짓말을 한다.
 *
 * 미리보기는 따로 없다. 누르는 즉시 지금 보고 있는 이 화면이 바뀐다 —
 * 스킨은 전역 변수를 바꾸는 물건이라 틀 안에 가둘 수가 없다(SkinEditor 주석).
 */

type Props = {
  value: SkinOptions
  onChange: (next: SkinOptions) => void
}

/** 강조색 후보. 보라·분홍을 뺐다 — 그 조합이 '만들어진 티'의 큰 몫이었다(ui.ts). */
const ACCENTS: { name: string; hex: string }[] = [
  { name: '민트', hex: '#20c997' },
  { name: '초록', hex: '#03c75a' },
  { name: '파랑', hex: '#1c7ed6' },
  { name: '주황', hex: '#e8590c' },
  { name: '빨강', hex: '#c92a2a' },
  { name: '먹', hex: '#212529' },
]

const CANVASES: { name: string; hex: string }[] = [
  { name: '흰색', hex: '#ffffff' },
  { name: '연회색', hex: '#f5f6f7' },
  { name: '미색', hex: '#faf7f2' },
]

/* ------------------------------------------------------------------ 부속 */

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
      <div className="w-24 shrink-0">
        <span className="text-sm font-medium">{label}</span>
        {hint && <span className="block text-xs text-gray-500 dark:text-gray-400">{hint}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}

/** 셋 중 하나 고르기. `<select>`가 아니라 버튼인 이유: 선택지가 서너 개고, 한 번에
 *  다 보이면 무엇을 바꿀 수 있는지가 곧 설명이 된다. */
function Seg<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: { v: T; label: string; title?: string }[]
}) {
  return (
    <div className="inline-flex overflow-hidden rounded-field border border-black/10 dark:border-white/15">
      {options.map((o, i) => (
        <button
          key={o.v}
          type="button"
          title={o.title}
          aria-pressed={value === o.v}
          onClick={() => onChange(o.v)}
          className={`px-3 py-1.5 text-sm transition ${
            i > 0 ? 'border-l border-black/10 dark:border-white/15' : ''
          } ${
            value === o.v
              ? 'bg-accent text-white'
              : 'bg-white text-gray-700 hover:bg-black/[0.04] dark:bg-white/5 dark:text-gray-200 dark:hover:bg-white/10'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Check({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-1.5 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-accent"
      />
      {label}
    </label>
  )
}

/**
 * 바탕색 후보. 이쪽은 동그라미가 아니라 **이름표**다 — 셋 다 거의 흰색이라
 * 동그라미로 늘어놓으면 무엇이 무엇인지 구분이 안 된다(어두운 모드에서 특히).
 * 색으로 못 알아보는 것에는 색을 쓰지 않는다.
 */
function ChipColor({
  hex,
  label,
  active,
  onClick,
}: {
  hex: string
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-btn px-3 py-1.5 text-sm transition ${
        active
          ? 'bg-accent text-white'
          : 'bg-black/[0.06] text-gray-800 hover:bg-black/[0.1] dark:bg-white/10 dark:text-gray-100 dark:hover:bg-white/20'
      }`}
    >
      <span
        style={{ background: hex }}
        className="h-3.5 w-3.5 rounded-full ring-1 ring-black/25 dark:ring-white/40"
      />
      {label}
    </button>
  )
}

/** 색 동그라미 하나. 고른 것에는 테두리를 두껍게 준다(색맹이어도 어느 게 켜졌는지 보이게). */
function Swatch({
  hex,
  name,
  active,
  onClick,
}: {
  hex: string
  name: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      title={name}
      aria-label={name}
      aria-pressed={active}
      onClick={onClick}
      style={{ background: hex }}
      className={`h-7 w-7 rounded-full transition ${
        active
          ? 'ring-2 ring-accent ring-offset-2 ring-offset-white dark:ring-offset-[#1c1c1e]'
          : 'ring-1 ring-black/25 hover:scale-110 dark:ring-white/40'
      }`}
    />
  )
}

/* ------------------------------------------------------------------ 본체 */

function SkinPicker({ value: o, onChange }: Props) {
  // 한 칸만 바꾼 새 옵션을 넘긴다. 부모가 이걸 CSS로 다시 굽는다.
  const set = <K extends keyof SkinOptions>(k: K, v: SkinOptions[K]) =>
    onChange({ ...o, [k]: v })

  return (
    <div className="divide-y divide-black/[0.06] dark:divide-white/10">
      <Row label="강조색" hint="링크·버튼">
        <button
          type="button"
          aria-pressed={o.accent === ''}
          onClick={() => set('accent', '')}
          className={o.accent === '' ? ui.btnPrimary : ui.btnGhost}
        >
          기본
        </button>
        {ACCENTS.map((c) => (
          <Swatch
            key={c.hex}
            hex={c.hex}
            name={c.name}
            active={o.accent === c.hex}
            onClick={() => set('accent', c.hex)}
          />
        ))}
        {/* 직접 고르기. 여섯 개로 안 끝나는 사람을 여기서 잡는다 —
            없으면 그 사람은 다시 CSS를 써야 하고, 그게 이 화면이 없애려던 벽이다. */}
        <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
          <input
            type="color"
            value={o.accent || '#215ba6'}
            onChange={(e) => set('accent', e.target.value.toLowerCase())}
            className="h-7 w-9 cursor-pointer rounded-field border border-black/10 bg-transparent p-0.5 dark:border-white/15"
          />
          직접
        </label>
      </Row>

      <Row label="바탕색" hint="밝은 모드만">
        <button
          type="button"
          aria-pressed={o.canvas === ''}
          onClick={() => set('canvas', '')}
          className={o.canvas === '' ? ui.btnPrimary : ui.btnGhost}
        >
          기본
        </button>
        {CANVASES.map((c) => (
          <ChipColor
            key={c.hex}
            hex={c.hex}
            label={c.name}
            active={o.canvas === c.hex}
            onClick={() => set('canvas', c.hex)}
          />
        ))}
      </Row>

      <Row label="모서리">
        <Seg<Corner>
          value={o.corner}
          onChange={(v) => set('corner', v)}
          options={[
            { v: 'round', label: '둥글게' },
            { v: 'soft', label: '기본' },
            { v: 'square', label: '각지게' },
          ]}
        />
      </Row>

      <Row label="글 목록">
        <Seg<ListShape>
          value={o.list}
          onChange={(v) => set('list', v)}
          options={[
            { v: 'list', label: '한 줄씩', title: '제목이 먼저 읽힌다. 커버 없는 글이 많으면 이쪽' },
            { v: 'grid', label: '카드 2열', title: '커버 이미지가 있는 글이 많을 때 어울린다' },
          ]}
        />
      </Row>

      <Row label="목록에 보일 것">
        <Check checked={o.thumb} onChange={(v) => set('thumb', v)} label="썸네일" />
        <Check checked={o.excerpt} onChange={(v) => set('excerpt', v)} label="요약" />
        <Check checked={o.tags} onChange={(v) => set('tags', v)} label="태그" />
        <Check checked={o.meta} onChange={(v) => set('meta', v)} label="날짜·읽는 시간" />
      </Row>

      <Row label="사이드바" hint="프로필·태그">
        <Check checked={o.sidebar} onChange={(v) => set('sidebar', v)} label="보이기" />
      </Row>

      <Row label="머리말" hint="목록 위 제목 구역">
        <Seg<HeroMode>
          value={o.hero}
          onChange={(v) => set('hero', v)}
          options={[
            { v: 'show', label: '그대로' },
            { v: 'mine', label: '내 문장만', title: "사이트가 넣은 '글'과 안내 두 줄을 숨긴다" },
            { v: 'hide', label: '숨기기', title: '내가 쓴 머리말까지 같이 사라진다' },
          ]}
        />
      </Row>
    </div>
  )
}

export default SkinPicker
