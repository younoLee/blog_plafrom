"""AI 초안 생성: 티어 게이팅 + 비용 캡(일일/월간). 외부 LLM 호출은 목킹한다.
비용을 태우는 로직이라 '누가 어떤 모델을 얼마나' 부분의 거부 경로에 집중."""
import pytest

from app.core.config import settings
from app.services import ai_usage
from app.services.ai import DEFAULT_MODEL, AIKeyMissingError


@pytest.fixture
def fake_generate(monkeypatch):
    """generate_draft를 목킹. 기본은 마크다운 반환, .fail(exc)로 예외 주입."""
    state = {"exc": None, "out": "# 제목\n\n본문입니다."}

    def _gen(memo, model, provider, user_key, base_url):
        if state["exc"] is not None:
            raise state["exc"]
        return state["out"]

    monkeypatch.setattr("app.routers.ai.generate_draft", _gen)

    class Handle:
        def fail(self, exc):
            state["exc"] = exc

    return Handle()


def _draft(client, headers, **body):
    payload = {"memo": "여행 갔던 메모"}
    payload.update(body)
    return client.post("/api/ai/draft", headers=headers, json=payload)


# ── 접근 권한 ────────────────────────────────────────────────────────────────
def test_draft_requires_auth(client):
    assert client.post("/api/ai/draft", json={"memo": "x"}).status_code == 401


def test_draft_pending_forbidden(client, make_user, auth_headers, fake_generate):
    pending = make_user(role="pending")
    assert _draft(client, auth_headers(pending)).status_code == 403  # require_writer


# ── 성공 + 사용량 증가 ───────────────────────────────────────────────────────
def test_draft_success_returns_markdown_and_counts(
    client, make_user, auth_headers, fake_generate, db
):
    user = make_user(role="writer")  # 비유료라도 기본(하이쿠)은 무료 티어
    r = _draft(client, auth_headers(user))
    assert r.status_code == 200
    body = r.json()
    assert body["markdown"].startswith("# 제목")
    assert body["model"] == DEFAULT_MODEL
    # 서버키(claude) 성공 호출은 일일 카운트에 반영
    assert ai_usage.count_today(db, user.id) == 1


# ── 티어 게이팅 ──────────────────────────────────────────────────────────────
def test_basic_writer_cannot_use_opus(client, make_user, auth_headers, fake_generate):
    user = make_user(role="writer", is_pro=False)
    r = _draft(client, auth_headers(user), model="claude-opus-4-8")
    assert r.status_code == 403  # 유료 전용 모델


def test_pro_writer_can_use_opus(client, make_user, auth_headers, fake_generate):
    user = make_user(role="writer", is_pro=True)
    r = _draft(client, auth_headers(user), model="claude-opus-4-8")
    assert r.status_code == 200


# ── 비용 캡 ──────────────────────────────────────────────────────────────────
def test_daily_cap_exceeded_429(
    client, make_user, auth_headers, fake_generate, monkeypatch
):
    monkeypatch.setattr(settings, "ai_daily_cap", 0)  # 0회 = 즉시 초과
    user = make_user(role="writer")
    r = _draft(client, auth_headers(user))
    assert r.status_code == 429


def test_monthly_cap_exceeded_429(
    client, make_user, auth_headers, fake_generate, monkeypatch
):
    monkeypatch.setattr(settings, "ai_daily_cap", 100)  # 일일은 통과
    monkeypatch.setattr(settings, "ai_monthly_cap", 0)  # 월간에서 막힘
    user = make_user(role="writer")
    r = _draft(client, auth_headers(user))
    assert r.status_code == 429


# ── 생성 실패 경로 ───────────────────────────────────────────────────────────
def test_draft_key_missing_503(client, make_user, auth_headers, fake_generate):
    fake_generate.fail(AIKeyMissingError())
    user = make_user(role="writer")
    assert _draft(client, auth_headers(user)).status_code == 503


def test_draft_generation_error_502(client, make_user, auth_headers, fake_generate):
    fake_generate.fail(ValueError("upstream 500"))
    user = make_user(role="writer")
    assert _draft(client, auth_headers(user)).status_code == 502


# ── 조회 엔드포인트 ──────────────────────────────────────────────────────────
def test_usage_endpoint(client, make_user, auth_headers):
    user = make_user(role="writer")
    r = client.get("/api/ai/usage", headers=auth_headers(user))
    assert r.status_code == 200
    body = r.json()
    assert body["daily_cap"] == settings.ai_daily_cap
    assert body["daily_used"] == 0


def test_models_gated_by_tier(client, make_user, auth_headers):
    basic = make_user(role="writer", is_pro=False)
    ids = [m["id"] for m in client.get("/api/ai/models", headers=auth_headers(basic)).json()["models"]]
    assert "claude-haiku-4-5" in ids
    assert "claude-opus-4-8" not in ids  # 유료 전용은 목록에서 잠김

    pro = make_user(role="writer", is_pro=True)
    pro_ids = [m["id"] for m in client.get("/api/ai/models", headers=auth_headers(pro)).json()["models"]]
    assert "claude-opus-4-8" in pro_ids
