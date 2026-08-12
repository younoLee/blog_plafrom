import { useEffect, useRef, useState } from 'react'

/** 클립보드 복사 버튼. 코드블록 복사와 글 링크 공유가 같은 동작이라 한 군데 둔다.
 *
 *  value가 함수인 이유: 코드블록은 렌더된 DOM에서 글자를 읽어야 해서(마크다운 문자열이
 *  아니라 **실제 보이는 텍스트**를 복사해야 한다) 누르는 시점에 값을 만들어야 한다. */
type Props = {
  value: string | (() => string)
  label: string
  copiedLabel?: string
  className?: string
  title?: string
}

export function CopyButton({ value, label, copiedLabel = '복사됨', className = '', title }: Props) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 언마운트 뒤에 타이머가 setState를 부르면 경고가 난다(글을 옮기면 바로 벌어진다).
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  async function copy() {
    const text = typeof value === 'function' ? value() : value
    if (!text) return
    try {
      // navigator.clipboard는 **보안 컨텍스트에서만** 있다(https·localhost). 그 밖에서는
      // undefined라 그냥 부르면 TypeError로 죽는다 — 조용히 아무 일도 안 일어나는 버튼이 된다.
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.setAttribute('readonly', '')
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        ta.remove()
      }
      setCopied(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1600)
    } catch {
      // 브라우저가 권한을 막은 경우. 버튼이 거짓말을 하지 않도록 '복사됨'을 띄우지 않는다.
      setCopied(false)
    }
  }

  return (
    <button type="button" onClick={copy} title={title} aria-live="polite" className={className}>
      {copied ? copiedLabel : label}
    </button>
  )
}

export default CopyButton
