// 서비스워커의 알림 표시 규칙 — **서버가 보낸 값과 짝이 맞는지**를 잠근다.
//
// 이 저장소는 여기서 두 번 다쳤다:
//   1. 2026-08-14 — `tag`만 있고 `renotify`가 없어 두 번째 알림부터 소리도 배너도 없이
//      앞 알림을 갈아치웠다. 발송은 성공하는데 사람은 못 본다.
//   2. 2026-08-15 — 그 `tag`가 'new-post'로 **고정**이라, 댓글 알림이 생기는 순간
//      새 글 알림과 서로를 지웠다. 같은 실패의 다른 얼굴이다.
// 둘 다 화면에 아무 흔적을 안 남긴다. 그래서 소스를 글자로 읽어 감시한다.
import { describe, it, expect } from 'vitest'
import swSource from '../public/sw.js?raw'

describe('sw.js 알림 표시', () => {
  it('tag를 서버가 준 값에서 읽는다 (한 값으로 고정하지 않는다)', () => {
    expect(swSource).toMatch(/tag:\s*data\.tag/)
  })

  it('renotify가 켜져 있다 (tag와 짝이다 — 없으면 조용히 교체된다)', () => {
    expect(swSource).toMatch(/renotify:\s*true/)
  })

  it('알림 클릭이 서버가 준 url로 간다', () => {
    expect(swSource).toMatch(/data\.url/)
  })
})
