"""이미지 업로드 — 파일 업로드는 고전적 공격면. 내용(매직바이트)으로만 판별하는지,
크기/권한 가드가 도는지 검증. 저장은 임시폴더로 돌려 실제 uploads/를 안 더럽힌다."""
import pytest

# 유효 PNG 매직바이트(앞 8바이트) + 패딩. 스니핑은 앞부분만 보므로 이걸로 충분.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.routers.uploads.UPLOAD_DIR", tmp_path)


def test_upload_requires_auth(client):
    r = client.post("/api/upload", files={"file": ("x.png", PNG, "image/png")})
    assert r.status_code == 401


def test_pending_cannot_upload(client, make_user, auth_headers):
    pending = make_user(role="pending")
    r = client.post(
        "/api/upload",
        headers=auth_headers(pending),
        files={"file": ("x.png", PNG, "image/png")},
    )
    assert r.status_code == 403  # require_writer


def test_valid_png_upload_returns_url(client, make_user, auth_headers):
    w = make_user(role="writer")
    r = client.post(
        "/api/upload", headers=auth_headers(w), files={"file": ("x.png", PNG, "image/png")}
    )
    assert r.status_code == 200
    assert r.json()["url"].endswith(".png")


def test_rejects_non_image_despite_image_content_type(client, make_user, auth_headers):
    w = make_user(role="writer")
    # content-type을 image/png로 위조해도 내용이 HTML → 매직바이트로 거부(핵심 방어)
    r = client.post(
        "/api/upload",
        headers=auth_headers(w),
        files={"file": ("evil.png", b"<html><script>x</script></html>", "image/png")},
    )
    assert r.status_code == 400


def test_rejects_oversized_file(client, make_user, auth_headers):
    w = make_user(role="writer")
    big = PNG + b"0" * (5 * 1024 * 1024)  # 5MB 초과
    r = client.post(
        "/api/upload", headers=auth_headers(w), files={"file": ("big.png", big, "image/png")}
    )
    assert r.status_code == 413


def test_upload_is_rate_limited(client, make_user, auth_headers):
    """업로드에도 상한이 있어야 한다.

    2026-07-30 심층검사에서 찾은 것: 글 30/h · 댓글 20/h · AI 10/h · 결제 20/h가 다 있는데
    **업로드만 상한이 없어** 12연발이 전부 200으로 통과했다. 이 경로는 한 번에 5MB를 S3에
    얹고 CloudFront로 나가는 '비용이 붙는 쓰기'이고, 공개된 데모 계정(writer)이 그대로 부를
    수 있었다. 상한이 사라지면 이 테스트가 잡는다.

    레이트리밋은 conftest가 전역으로 꺼두므로(다른 테스트의 반복 호출과 충돌) 이 테스트만
    켜고, 끝나면 카운터까지 되돌린다 — 안 그러면 뒤 테스트가 이 30건을 물려받는다.
    """
    from app.core.ratelimit import limiter

    w = make_user(role="writer")
    headers = auth_headers(w)
    limiter.reset()
    limiter.enabled = True
    try:
        codes = [
            client.post(
                "/api/upload", headers=headers, files={"file": ("x.png", PNG, "image/png")}
            ).status_code
            for _ in range(31)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()

    assert codes[:30] == [200] * 30  # 상한(30/시간)까지는 그대로 통과
    assert codes[30] == 429  # 31번째부터 차단


def test_extension_is_derived_not_from_filename(client, make_user, auth_headers):
    w = make_user(role="writer")
    # 파일명이 .exe여도 내용이 PNG면 저장 확장자는 .png (사용자 파일명 안 씀)
    r = client.post(
        "/api/upload",
        headers=auth_headers(w),
        files={"file": ("malware.exe", PNG, "application/octet-stream")},
    )
    assert r.status_code == 200
    assert r.json()["url"].endswith(".png")


# ── 되돌리면 안 되는 불변식 ────────────────────────────────────────────────
# uploads.py 상단이 대문자 경고로 "async def로 되돌리지 마라"고 적어둔 것을 잠근다.
# 근거는 실측이다: async면 boto3 동기 호출이 이벤트 루프를 물어 **요청 1개로 API
# 전체가 112.3초 정지**하고, 도커 헬스체크가 약 95초 뒤 unhealthy로 뒤집힌다.
# 지금까지 이걸 지키는 건 주석뿐이었다(2026-08-11 공백검사).
def test_upload_endpoint_is_not_async():
    import inspect

    from app.routers import uploads

    assert not inspect.iscoroutinefunction(uploads.upload_image), (
        "upload_image가 async def가 됐다. 그 안의 boto3 put_object는 동기라 "
        "이벤트 루프를 물고, 워커가 1개라 요청 1개로 API 전체가 멈춘다(112.3초 실측)."
    )
