"""쿼리 문자열의 NUL 바이트 — **무인증 500**이 나던 자리를 잠근다.

psycopg2는 `\\x00`이 든 문자열을 DB에 보내기 전에 `ValueError`를 던진다. 이 앱의
예외 핸들러 넷(OperationalError·PoolTimeout·RequestValidation·DataError) 어디에도 안
걸려서 **text/plain 500**이 나갔다. JSON을 기대하는 프론트는 파싱조차 못 한다.

이 파일이 진짜로 지키는 건 한 건의 버그가 아니라 **모양**이다. 같은 실수가 세 번 났다:

    2026-08-12  `q`엔 상한이 있는데 바로 옆 `tag`엔 없었다
    2026-08-12  `limit`엔 상한이 있는데 바로 옆 `offset`엔 없었다
    2026-08-19  `q`·`tag`엔 NUL 가드가 있는데 같은 함수의 `author`엔 없었다

세 번 다 "짝지어진 파라미터 중 한쪽만 안 쓸린" 모양이고, 세 번째는 처방이 **두 줄 위에**
있는 채로 났다. 그래서 가드를 `app/core/textguard.py` 함수 하나로 옮겼고, 여기서는
문자열을 받는 무인증 입구를 **전부** 훑는다. 새 파라미터가 생기면 이 목록에 한 줄을
더하는 것으로 끝나야 한다.
"""

import pytest

# (경로, 기대 상태코드). 값은 전부 `a\x00b` — 길이 검사를 통과하는 세 글자다
# (`%00` 단독은 min_length에 걸려 다른 이유로 막히므로 재현이 안 된다).
NUL = "a%00b"

CASES = [
    # 목록 조회 — 셋 다 같은 함수의 형제 파라미터다
    (f"/api/posts?q={NUL}", 422),
    (f"/api/posts?tag={NUL}", 422),
    (f"/api/posts?author={NUL}", 422),
    # 스킨 — **방문자 전원이 첫 화면에서 부르고 레이트리밋도 일부러 없는** 경로다.
    # 여기선 422가 아니라 200 + 빈 스킨이다. 없는 핸들과 같은 취급이고, 그건
    # 이 조회가 화면 실패 경로를 안 만들기로 한 결정을 따른 것이다.
    (f"/api/skin?handle={NUL}", 200),
    # 사람 정보 — 여긴 '그 화면이 존재하는가'에 대한 답이라 404가 맞다.
    (f"/api/authors/{NUL}", 404),
]


@pytest.mark.parametrize("path,expected", CASES)
def test_NUL이_들어와도_500이_아니다(client, path, expected):
    r = client.get(path)
    assert r.status_code == expected, f"{path} → {r.status_code}"
    # 상태코드만큼 중요한 것: **JSON이어야 한다.** 500은 text/plain으로 나가서
    # 프론트가 에러 문구조차 못 읽었다.
    assert r.headers["content-type"].startswith("application/json")


def test_빈_스킨을_준다_남의_것이_아니라(client, make_user, auth_headers):
    """NUL 핸들에 200을 준다고 해서 **사이트 스킨**을 주면 안 된다.

    빈 값이어야 하는 이유: 그 응답은 곧 '이 주소의 주인이 정한 외형'이라는 뜻이다.
    주인 것을 돌려주면 아무 주소에나 주인의 색과 **주인이 쓴 문장**이 붙는다.
    """
    owner = make_user(role="admin")
    client.put(
        "/api/skin",
        json={"custom_css": ":root { --color-accent: #20c997 }"},
        headers=auth_headers(owner),
    )
    assert client.get("/api/skin").json()["css"] != ""  # 사이트 스킨은 있다
    assert client.get(f"/api/skin?handle={NUL}").json()["css"] == ""


def test_핸들_길이_상한이_있다(client):
    """상한이 없으면 아무 길이나 조회로 간다. handle 컬럼과 같은 20자."""
    r = client.get("/api/skin?handle=" + "a" * 21)
    assert r.status_code == 422
