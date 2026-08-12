"""요청 본문 스키마의 공통 기반 — DB가 담을 수 없는 문자를 **입력 층에서** 거른다.

왜 여기인가 (2026-08-12 검사):
  NUL 바이트(`\\u0000`)가 든 문자열은 **psycopg2가 DB에 보내기도 전에** `ValueError`를
  던진다("A string literal cannot contain NUL (0x00) characters"). 그건 SQLAlchemy의
  `DataError`가 아니라 **평범한 ValueError**라 DB 예외 핸들러로는 못 잡는다.
  실측으로 확인했다 — `DataError` 핸들러를 붙였는데도 쓰기 경로가 그대로 터졌다.

  그렇다고 `ValueError`를 전역으로 잡으면 **진짜 코드 버그가 400 '입력이 나쁘다'로 둔갑한다**
  (이 저장소가 예외 핸들러를 좁게 유지해온 이유와 같다 — main.py의 db_unavailable 주석 참고).
  남는 답은 하나, 입력 층이다.

왜 필드마다가 아니라 기반 클래스인가:
  같은 날 오전에 `list_posts`의 `q`·`tag`에만 NUL 가드를 넣었는데, 오후 검사가
  **같은 병이 다섯 라우터에 그대로 남아 있는 것**을 찾았다(익명 댓글 content, 글 title·tags,
  푸시 endpoint, 결제 order_id). 필드를 세는 접근은 필드가 늘 때마다 다시 샌다.
  이 저장소가 '고친 자리 옆의 안 쓸린 입구'라고 부르는 바로 그 모양이다.

무엇을 거르나:
  - **NUL(U+0000)**: Postgres text가 담을 수 없다. 이건 '나쁜 값'이 아니라 '담을 수 없는 값'이다.
  - **고아 서로게이트(U+D800–U+DFFF)**: UTF-8로 인코딩되지 않는다. 검증을 통과하면 DB에서
    터지고, 검증에 걸려도 **422 응답을 인코딩하다가** 터진다(양쪽 다 실측).
  그 외 제어문자는 **거르지 않는다.** 개발일지 본문에 탭·개행이 정상적으로 들어오고,
  이 검사의 목적은 '예쁜 텍스트'가 아니라 '저장 가능한 텍스트'다. 범위를 넓히면
  멀쩡한 글이 거부되는 쪽으로 틀린다.
"""

from typing import Any

from pydantic import BaseModel, model_validator

_BAD = "\x00"


def _has_unstorable(value: Any) -> bool:
    """문자열이면 NUL·고아 서로게이트를 검사. 리스트/딕트는 재귀."""
    if isinstance(value, str):
        if _BAD in value:
            return True
        # 고아 서로게이트는 인코딩 시점에만 드러난다 — 직접 시도해 보는 게 가장 정확하다
        # (정규식으로 코드포인트를 세는 것보다 '실제로 못 담는가'에 가깝다).
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_has_unstorable(v) for v in value)
    if isinstance(value, dict):
        return any(_has_unstorable(v) for v in value.values())
    return False


class SafeModel(BaseModel):
    """요청 본문 스키마의 기반. 저장할 수 없는 문자가 있으면 422로 거절한다."""

    @model_validator(mode="after")
    def _reject_unstorable(self) -> "SafeModel":
        for name in type(self).model_fields:
            if _has_unstorable(getattr(self, name, None)):
                raise ValueError(f"{name}: 저장할 수 없는 문자가 들어 있어(NUL 또는 잘못된 유니코드).")
        return self
