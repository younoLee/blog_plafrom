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
