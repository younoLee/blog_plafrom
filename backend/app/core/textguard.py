"""쿼리 문자열에 섞여 들어오는 NUL 바이트를 한 곳에서 막는다.

**왜 한 곳인가** — 이 가드는 원래 `list_posts` 안에 손으로 적혀 있었다(`q`와 `tag`).
그 뒤 같은 함수에 `author`가 추가됐는데 가드에는 안 들어갔고, 그래서 두 줄 아래에
멀쩡한 처방이 있는 채로 `?author=a%00b`가 **무인증 500**을 냈다(2026-08-19 검사).
같은 모양이 `GET /api/skin?handle=`과 `/api/authors/{handle}`에도 있었다.

가드를 손으로 적는 한 파라미터가 늘 때마다 이 자리가 다시 샌다. 이 저장소는 그걸
이미 세 번 밟았다(`q`↔`tag`, `limit`↔`offset`, 그리고 `author`). 그래서 목록이 아니라
**함수 하나**로 만든다 — 새 파라미터는 인자로 넘기기만 하면 된다.

## 왜 500이 나는가

psycopg2는 `\\x00`이 든 문자열을 만나면 DB에 닿기도 전에
`ValueError: A string literal cannot contain NUL characters`를 던진다. 이건
`OperationalError`도 `DataError`도 아니라서 이 앱의 예외 핸들러 넷 중 어디에도 안 걸리고,
Starlette의 기본 처리로 **text/plain 500**이 나간다. 프론트는 JSON을 기대하므로
파싱조차 못 한다.

길이 제한으로는 못 막는다 — `a%00b`는 세 글자짜리 정상 길이다.
"""


def has_nul(*values: str | None) -> bool:
    """넘긴 값 중 하나라도 NUL 바이트를 품고 있으면 True.

    None과 빈 문자열은 그냥 넘어간다 — '안 준 것'은 막을 게 없다.
    """
    return any(v is not None and "\x00" in v for v in values)
