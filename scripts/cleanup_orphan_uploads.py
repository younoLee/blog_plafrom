#!/usr/bin/env python3
"""지운 글의 업로드 이미지가 S3에 영원히 남는 것 — 고아 객체를 찾아 보여준다.

## 왜 필요한가

2026-09-02 공백 검사에서 확인했다. 저장소 전체에 S3 `delete_object` 가 **0건**이다
(`backend/app/routers/uploads.py:181-191`, `posts.py:556-567`, `admin.py:274-288`).
글을 지워도, 계정을 지워도, 그 글에 실렸던 이미지는 `blogplafromops/uploads/` 에
그대로 남는다. 그리고 그 버킷의 `uploads/` 접두사는 lifecycle 대상도 아니다.
즉 지운 글의 이미지가 **무인증 공개 URL로 영원히** 접근 가능한 상태로 남는다.

백엔드에서 삭제 시점에 지우는 게 정공법이지만 그건 다른 사람 몫이다. 여기서는
'이미 쌓인 것'을 사람이 보고 치우는 도구만 만든다.

## 왜 자동으로 안 도는가

이 스크립트는 **어디에도 배선하지 않는다.** cron 도, CI 도, 정지 절차도 아니다.
사람이 보고 돌리는 도구다. 이유는 이 저장소가 이미 값을 치른 사고다 —
2026-07-30 05:03 UTC 에 `s3 sync --delete` 가 업로드 이미지 2개를 조용히 지웠고,
`watch.sh` 가 그걸 "확인할 것 없음"으로 찍어 **12일 · 약 280회 실행이 전부 초록**이었다
(08-11에 버저닝으로 복구). 지우는 쪽을 자동화하면 같은 사고를 자동으로 반복하게 된다.

## 안전장치 (전부 '조용히 지우지 않기' 위한 것)

1. **기본은 dry-run.** 실제 삭제는 `--delete` 를 명시할 때만.
2. **30일 유예.** 방금 올리고 아직 글을 저장하지 않은 이미지를 죽이면 안 된다.
   업로드는 되고 글 저장은 나중인 순서가 정상 경로다(WritePostPage 의 초안).
3. **조회 실패를 0건으로 읽지 않는다.** DB 쿼리가 하나라도 실패하면 참조 목록이
   비는데, 그 상태로 비교하면 **살아 있는 이미지가 전부 고아로 보인다.** 그래서
   실패는 즉시 중단이고, 참조가 0건인데 객체가 있으면 삭제를 거부한다.
4. **지우기 전에 무엇을 지우는지 전부 출력한다.** 키·크기·나이·미러 사본 유무.
5. **백업 미러에 사본이 없으면 안 지운다**(`--allow-unmirrored` 로만 강행).
   정지 절차 4/6 의 `aws s3 sync … s3://<백업>/uploads/` 가 만드는 그 사본이다.
   그쪽은 `--delete` 가 없어서 원본에서 지워도 남는다 — 되돌릴 마지막 자리다.

## 참조를 어디서 모으나

`/uploads/<이름>` 이 들어갈 수 있는 자리를 **전부** 훑는다. 모델을 읽고 확인한 목록:

  · `posts.content`      글 본문 마크다운 (편집기가 `![](…)` 로 넣는다)
  · `posts.cover_image`  커버 이미지 (`models/post.py:36` — "/api/upload 로 올린 URL")
  · `users.custom_css`   스킨 CSS. `url(/uploads/x.png)` 가 **허용된다**
                         (`schemas/user.py:124`, `tests/test_skin.py:107`)
  · `users.custom_html`  스킨 HTML 슬롯(Text 에 담긴 JSON 문자열). `img src` 허용
                         (`core/html_slots.py:50`, `tests/test_slots.py:79-91`)
  · `comments.content`   평문으로 렌더되지만 URL 문자열은 남을 수 있다

`scripts/restore_drill.sh:378` 이 비슷한 일을 하는데 **앞의 둘만** 본다. 그쪽은
'참조됐는데 S3에 없는 것'을 찾는 반대 방향이라 목록이 좁아도 목적을 이루지만,
여기서는 목록이 좁으면 **살아 있는 이미지를 지운다.** 방향이 다르면 필요한
꼼꼼함도 다르다.

⚠️ URL 모양은 세 가지가 다 DB 에 들어갈 수 있다(`schemas/post.py:37-65`):
   상대경로 `/uploads/x.png` · `https://<CDN>/uploads/x.png` · `http://localhost:8000/…`.
   그래서 출처(origin)로 매칭하지 않고 **`/uploads/<이름>` 조각으로** 매칭한다.

## 사용법

    # 보기만 한다(기본)
    backend/.venv/bin/python scripts/cleanup_orphan_uploads.py --database-url "$DATABASE_URL"

    # 실제로 지운다 — 30일 넘고, 미러 사본이 확인된 고아만
    backend/.venv/bin/python scripts/cleanup_orphan_uploads.py --database-url "$DATABASE_URL" --delete

DB 는 EC2 안 컨테이너라 워크스테이션에서 바로 안 닿는다. 서버에서 돌리거나
SSH 터널을 뚫어야 한다. 예:

    ssh -i ~/.ssh/blog-key.pem -L 55432:localhost:5432 ec2-user@<DNS>
    # 위 터널을 열어둔 채, 다른 창에서
    DATABASE_URL=postgresql://postgres:<암호>@localhost:55432/postgres \\
      backend/.venv/bin/python scripts/cleanup_orphan_uploads.py

종료코드: 0 = 고아 0건(또는 --delete 가 정상 완료), 1 = 조회·삭제 실패나 안전장치
발동, 2 = 고아를 찾았고 dry-run 이라 아무것도 안 지웠다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

# 기본값은 운영과 같다. 이름을 여기 한 곳에만 둔다.
DEFAULT_BUCKET = "blogplafromops"
DEFAULT_MIRROR = "blog-db-backups-181568979775"
DEFAULT_PREFIX = "uploads/"
DEFAULT_REGION = "ap-northeast-2"
DEFAULT_MIN_AGE_DAYS = 30

# `/uploads/<이름>` 조각. 출처(origin)를 안 보는 이유는 머리말의 ⚠️ 참고.
_REF = re.compile(r"/uploads/([A-Za-z0-9._\-]+)")

# 참조가 들어갈 수 있는 모든 자리. (설명, SQL) — 머리말에 근거가 있다.
#
# **여기에 자리를 빠뜨리면 살아 있는 이미지를 지운다.** 새 컬럼이 생기면 반드시
# 여기에 추가할 것. 그래서 컬럼을 굳이 하나씩 나눠 적는다 — 한 줄로 뭉쳐 놓으면
# 무엇을 보고 있는지 읽는 사람이 알 수 없고, 빠진 것도 안 보인다.
REF_SOURCES: list[tuple[str, str]] = [
    ("posts.content", "select content from posts where content is not null"),
    ("posts.cover_image", "select cover_image from posts where cover_image is not null"),
    ("users.custom_css", "select custom_css from users where custom_css is not null"),
    ("users.custom_html", "select custom_html from users where custom_html is not null"),
    ("comments.content", "select content from comments where content is not null"),
]


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0  # type: ignore[assignment]
    return f"{n}B"


def collect_referenced(database_url: str) -> set[str]:
    """DB 가 참조하는 업로드 이름을 모은다. 하나라도 못 읽으면 예외를 올린다.

    **빈 집합을 돌려주는 것과 예외를 올리는 것은 전혀 다른 결과다.** 앞은 '참조가
    없다'이고 뒤는 '못 봤다'인데, 여기서 그 둘을 뭉개면 '못 봤다'가 곧 '전부 고아'가
    되어 라이브 이미지를 지운다. 그래서 여기서는 절대 예외를 삼키지 않는다.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    names: set[str] = set()
    with engine.connect() as conn:
        for label, sql in REF_SOURCES:
            rows = conn.execute(text(sql)).all()
            found = 0
            for (value,) in rows:
                if not value:
                    continue
                for m in _REF.finditer(str(value)):
                    names.add(m.group(1))
                    found += 1
            # 자리마다 몇 건이 걸렸는지 **센다.** 규칙을 쓴 다음에는 개수를 찍어
            # 0건이 아닌지 본다는 이 저장소의 습관이 그대로 적용되는 자리다.
            print(f"  {label:22s} 행 {len(rows):5d} · 참조 {found}건")
    return names


def list_objects(bucket: str, prefix: str, region: str) -> list[dict]:
    """S3 목록. 실패는 예외로 올린다(0건으로 읽지 않는다)."""
    import boto3

    s3 = boto3.client("s3", region_name=region)
    out: list[dict] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            out.append(o)
    return out


def mirrored(bucket: str, key: str, region: str) -> bool | None:
    """백업 미러에 사본이 있는가. True/False/None(못 봤음) 셋을 가른다.

    None 을 False 로 뭉개면 '권한이 없어서 못 봤다'가 '사본이 없다'가 되고,
    반대로 True 로 뭉개면 사본이 없는 것을 있다고 믿고 지운다. 둘 다 나쁘다.
    """
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=region)
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="S3 uploads/ 의 고아 이미지를 찾는다(기본은 보기만 한다)"
    )
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="기본값은 환경변수 DATABASE_URL",
    )
    ap.add_argument("--bucket", default=DEFAULT_BUCKET, help=f"기본 {DEFAULT_BUCKET}")
    ap.add_argument("--mirror-bucket", default=DEFAULT_MIRROR, help=f"기본 {DEFAULT_MIRROR}")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"기본 {DEFAULT_PREFIX}")
    ap.add_argument("--region", default=DEFAULT_REGION, help=f"기본 {DEFAULT_REGION}")
    ap.add_argument(
        "--min-age-days",
        type=int,
        default=DEFAULT_MIN_AGE_DAYS,
        help=f"이만큼 지난 것만 지운다(기본 {DEFAULT_MIN_AGE_DAYS}일)",
    )
    ap.add_argument("--delete", action="store_true", help="실제로 지운다(기본은 dry-run)")
    ap.add_argument(
        "--allow-unmirrored",
        action="store_true",
        help="백업 미러에 사본이 확인 안 된 것도 지운다(권장하지 않음)",
    )
    args = ap.parse_args(argv[1:])

    if not args.database_url:
        print("DATABASE_URL 이 필요하다 (--database-url 또는 환경변수)", file=sys.stderr)
        return 1
    if args.min_age_days < 1:
        # 0일을 허용하면 '방금 올린 것'을 지울 수 있다. 이 스크립트가 존재하는
        # 이유의 절반이 그걸 막는 것이라 아예 못 넣게 한다.
        print("--min-age-days 는 1 이상이어야 한다 (방금 올린 이미지 보호)", file=sys.stderr)
        return 1

    print(f"참조 수집 — {len(REF_SOURCES)}개 자리")
    try:
        referenced = collect_referenced(args.database_url)
    except Exception as e:  # noqa: BLE001 — 원인을 그대로 보여주고 멈추는 게 목적이다
        print(f"\n❌ DB 조회 실패 — 아무것도 지우지 않는다: {e}", file=sys.stderr)
        print("   '참조 0건'과 '못 읽었다'는 다르다. 후자로 비교하면 전부 고아가 된다.", file=sys.stderr)
        return 1
    print(f"  참조되는 이미지 이름 {len(referenced)}종\n")

    print(f"S3 목록 — s3://{args.bucket}/{args.prefix}")
    try:
        objects = list_objects(args.bucket, args.prefix, args.region)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ S3 목록 조회 실패 — 아무것도 지우지 않는다: {e}", file=sys.stderr)
        return 1
    print(f"  객체 {len(objects)}개\n")

    now = dt.datetime.now(dt.timezone.utc)
    orphans = []
    for o in objects:
        name = o["Key"].split("/")[-1]
        if not name:  # `uploads/` 자체(0바이트 디렉터리 표식)는 대상이 아니다
            continue
        if name in referenced:
            continue
        age = (now - o["LastModified"]).days
        orphans.append({"key": o["Key"], "size": o["Size"], "age": age})

    if not orphans:
        print("== 고아 0건 — 지울 것이 없다 ==")
        return 0

    orphans.sort(key=lambda x: -x["age"])
    print(f"고아 {len(orphans)}건 (참조하는 글·스킨·댓글이 없는 객체)")
    print(f"  {'키':<48} {'크기':>8} {'나이':>7}  미러사본")
    for o in orphans:
        m = mirrored(args.mirror_bucket, o["key"], args.region)
        o["mirror"] = m
        mark = {True: "있음", False: "**없음**", None: "못 봤음"}[m]
        print(f"  {o['key']:<48} {_human(o['size']):>8} {o['age']:>5}일  {mark}")

    young = [o for o in orphans if o["age"] < args.min_age_days]
    if young:
        print(
            f"\n  이 중 {len(young)}건은 {args.min_age_days}일이 안 됐다 — 지우지 않는다."
            " 올려놓고 아직 글을 저장하지 않은 것일 수 있다."
        )

    if not args.delete:
        print("\n== dry-run — 아무것도 지우지 않았다. 지우려면 --delete ==")
        return 2

    # ── 여기부터 실제 삭제. 안전장치를 하나씩 통과해야 한다. ──────────────────
    if not referenced and objects:
        # 참조가 0건인데 객체는 있다. 정상적으로 글을 다 지운 결과일 수도 있지만,
        # 스키마가 바뀌어 위 SELECT 가 빈 결과를 낸 것일 수도 있다. 둘을 여기서
        # 구분할 방법이 없고 틀렸을 때의 대가가 '전부 삭제'라 멈춘다.
        # (watch.sh 3절이 '원본 0 / 사본 N'을 놓고 같은 고민을 한 자리다.)
        print(
            "\n❌ 참조가 0건인데 객체는 있다 — 삭제를 거부한다.\n"
            "   글을 전부 지운 것이 맞다면 콘솔에서 직접 지워라. 스키마가 바뀌어\n"
            "   위 SELECT 가 빈 결과를 낸 경우와 이 스크립트는 구분하지 못한다.",
            file=sys.stderr,
        )
        return 1

    targets = [o for o in orphans if o["age"] >= args.min_age_days]
    if not args.allow_unmirrored:
        blocked = [o for o in targets if o["mirror"] is not True]
        targets = [o for o in targets if o["mirror"] is True]
        if blocked:
            print(f"\n  미러 사본이 확인 안 된 {len(blocked)}건은 건너뛴다:")
            for o in blocked:
                print(f"    {o['key']}")
            print("    먼저 사본을 만들어라(정지 절차 4/6과 같은 명령):")
            print(
                f"      aws s3 sync s3://{args.bucket}/{args.prefix}"
                f" s3://{args.mirror_bucket}/{args.prefix}"
            )
            print("    그래도 강행하려면 --allow-unmirrored (권장하지 않음).")

    if not targets:
        print("\n== 조건을 통과한 삭제 대상이 없다 ==")
        return 1

    # **지우기 직전에 한 번 더 전부 찍는다.** 위 표와 중복이지만 일부러 그렇게 한다 —
    # 위 표에는 '안 지울 것'이 섞여 있고, 여기 목록이 실제로 사라지는 것이다.
    # 2026-07-30에 이미지 2개가 조용히 사라졌던 사고가 이 출력이 없어서 생긴 종류다.
    print(f"\n지운다 — {len(targets)}건 (s3://{args.bucket}/)")
    for o in targets:
        print(f"  {o['key']}  {_human(o['size'])}  {o['age']}일")

    import boto3

    s3 = boto3.client("s3", region_name=args.region)
    failed = 0
    for o in targets:
        try:
            s3.delete_object(Bucket=args.bucket, Key=o["key"])
            print(f"  지움 {o['key']}")
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ 실패 {o['key']}: {e}", file=sys.stderr)
            failed += 1

    print(f"\n== {len(targets) - failed}건 삭제 · 실패 {failed}건 ==")
    # 이 버킷은 버저닝이 켜져 있다. 잘못 지웠으면 삭제 표식을 지워 되살릴 수 있다
    # (2026-08-11에 실제로 그 방법으로 복구했다). 그 사실을 여기서 알려준다.
    print("  잘못 지웠으면 버저닝으로 되살린다 — 삭제 표식을 지운다:")
    print(
        f"    aws s3api list-object-versions --bucket {args.bucket} --prefix {args.prefix} \\"
    )
    print('      --query "DeleteMarkers[?IsLatest==\\`true\\`].[Key,VersionId]" --output text')
    print(f"    aws s3api delete-object --bucket {args.bucket} --key <KEY> --version-id <ID>")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
