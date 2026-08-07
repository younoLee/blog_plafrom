import { useEffect, useState } from 'react'
import {
  fetchPushStatus,
  isSubscribedHere,
  pushSupported,
  subscribePush,
  unsubscribePush,
} from '../api/push'
import { ui } from '../ui'

// 이 기기로 브라우저 알림을 받을지.
//
// **글쓴이별 🔔 토글과 역할이 다르다.** 그쪽은 "누구의 새 글 알림을 받을래?"라는
// 의사고, 이건 "그 알림을 이 기기로 보내라"는 경로다. 그래서 둘 다 켜야 알림이 온다 —
// 헷갈리기 쉬운 지점이라 화면에도 그렇게 적는다.
//
// 왜 이 채널을 붙였나 — 이메일 알림이 스팸함에 꽂힌다(발신 도메인이 없어 SPF·DKIM
// 정렬이 깨진다). 푸시는 SES를 안 거치므로 그 문제 밖에 있다.

type State = 'loading' | 'off' | 'on' | 'denied' | 'unsupported' | 'disabled'

function PushToggle() {
  const [state, setState] = useState<State>('loading')
  const [devices, setDevices] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      if (!pushSupported()) {
        if (alive) setState('unsupported')
        return
      }
      try {
        const [status, here] = await Promise.all([fetchPushStatus(), isSubscribedHere()])
        if (!alive) return
        setDevices(status.devices)
        // 서버에 키가 없으면 켤 방법 자체가 없다 → 켜기 버튼을 보여주지 않는다.
        if (!status.enabled) setState('disabled')
        else if (Notification.permission === 'denied') setState('denied')
        else setState(here ? 'on' : 'off')
      } catch {
        if (alive) setState('disabled')
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  async function turnOn() {
    setError('')
    setBusy(true)
    try {
      const r = await subscribePush()
      if (r === 'ok') {
        setState('on')
        setDevices((await fetchPushStatus()).devices)
      } else if (r === 'denied') setState('denied')
      else if (r === 'unsupported') setState('unsupported')
      else setState('disabled')
    } catch (e) {
      setError(e instanceof Error ? e.message : '알림을 켜지 못했어')
    } finally {
      setBusy(false)
    }
  }

  async function turnOff() {
    setError('')
    setBusy(true)
    try {
      await unsubscribePush()
      setState('off')
      setDevices((await fetchPushStatus()).devices)
    } catch (e) {
      setError(e instanceof Error ? e.message : '알림을 끄지 못했어')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'loading' || state === 'disabled') return null

  return (
    <section className={`${ui.card} mt-6`}>
      <h2 className="text-lg font-semibold tracking-tight">이 기기로 알림 받기</h2>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        위에서 🔔을 켠 글쓴이가 새 글을 올리면 이 브라우저로 알림이 와.
        <br />
        <span className="text-xs">
          메일 대신 쓰는 경로야 — 메일은 스팸함으로 가는 경우가 많아.
        </span>
      </p>

      {state === 'unsupported' && (
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          이 브라우저는 알림을 지원하지 않아.
          <br />
          <span className="text-xs">
            아이폰이라면 사파리에서 <span className="font-medium">공유 → 홈 화면에 추가</span>로
            설치한 뒤 그 아이콘으로 열면 켤 수 있어.
          </span>
        </p>
      )}

      {/* 거부는 다시 물어봐도 브라우저가 프롬프트를 안 띄운다 → 버튼을 주면 안 된다 */}
      {state === 'denied' && (
        <p className="mt-3 text-sm text-amber-600 dark:text-amber-400">
          알림이 차단돼 있어. 주소창 옆 자물쇠(또는 설정 → 사이트 권한)에서 직접 허용해줘.
        </p>
      )}

      {(state === 'on' || state === 'off') && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={state === 'on' ? turnOff : turnOn}
            disabled={busy}
            aria-pressed={state === 'on'}
            className={state === 'on' ? ui.btnGhost : ui.btnPrimary}
          >
            {busy ? '처리 중…' : state === 'on' ? '이 기기 알림 끄기' : '이 기기 알림 켜기'}
          </button>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {state === 'on' ? '이 기기에서 받는 중' : '이 기기에서는 꺼져 있어'}
            {devices > 0 && ` · 전체 ${devices}대`}
          </span>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
    </section>
  )
}

export default PushToggle
