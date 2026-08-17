// @vitest-environment jsdom
//
// 비밀번호 재설정의 **실패 문구**를 잠근다. localStorage(setToken)가 있어서 jsdom이다.
//
// 왜 이 테스트가 있어야 하는가 (2026-08-17 실측): 이 함수는 `!res.ok`를 전부
// "유효하지 않거나 만료된 링크야"로 뭉개고 있었다. 그런데 서버는 짧은 비밀번호를
// **422**로 막고, 그 422는 pydantic이 라우트에 들어가기 전에 잡는 것이라
// **토큰이 아직 소각되지 않았다 = 링크는 살아 있다.**
//
// 그 결과가 닫힌 고리였다: 8자 미만을 치면 "링크가 만료됐다"고 하고, 사용자는
// /forgot으로 돌아가 새 링크를 받아 같은 비밀번호를 다시 쳐서 또 "만료"를 본다.
// 스스로 빠져나올 수 없고, 계정 복구의 마지막 칸이라 대안도 없다.
//
// 잠그는 것 넷:
//   ① 422 → 길이 안내 (만료라고 말하지 않는다)
//   ② 429 → 잠시 후 다시 (만료라고 말하지 않는다)
//   ③ 400 → **서버 detail 그대로** (서버는 '서명·만료'와 '이미 사용함'을 구분해 말한다.
//      하드코딩하면 그 구분이 사라져 원인을 알 유일한 단서가 없어진다)
//   ④ 성공은 조용히 끝난다
import { describe, expect, it, afterEach, vi } from 'vitest'

import { resetPassword } from './auth'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stub(status: number, body: unknown = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  )
}

describe('resetPassword — 실패를 정확히 옮긴다', () => {
  it('① 422(짧은 비밀번호)는 만료가 아니다', async () => {
    stub(422, { detail: [{ msg: 'String should have at least 8 characters' }] })
    await expect(resetPassword('살아있는토큰', '123')).rejects.toThrow('비밀번호는 8~72자로 정해줘')
    await expect(resetPassword('살아있는토큰', '123')).rejects.not.toThrow(/만료/)
  })

  it('② 429(너무 잦음)도 만료가 아니다', async () => {
    stub(429, { detail: 'Too Many Requests' })
    await expect(resetPassword('t', '12345678')).rejects.toThrow(/잠시 후/)
    await expect(resetPassword('t', '12345678')).rejects.not.toThrow(/만료/)
  })

  it('③ 400은 서버가 구분해 말한 문장을 그대로 옮긴다', async () => {
    stub(400, { detail: '이미 사용했거나 만료된 링크야' })
    await expect(resetPassword('t', '12345678')).rejects.toThrow('이미 사용했거나 만료된 링크야')
  })

  it('④ 성공하면 던지지 않는다', async () => {
    stub(200)
    await expect(resetPassword('t', '12345678')).resolves.toBeUndefined()
  })
})
