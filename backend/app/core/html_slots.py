"""블로그 '내 문장' — 사용자가 넣은 HTML을 방문자에게 안전하게 내보낸다.

무엇인가: 제목 아래 머리말·사이드바 소개·푸터, 세 자리에 자기 문장을 넣는다.
스킨(CSS)이 '어떻게 보이나'를 정한다면 이건 '무엇이 적히나'를 정한다. 둘은 `class`로
이어진다 — 여기서 `<p class="hi">`를 쓰고 스킨에서 `.hi { ... }`를 쓰면 된다.

⚠️ 이 값은 **무인증으로 공개되고(GET /api/skin) 방문자 브라우저에서 HTML로 파싱된다.**
스킨 CSS와 성질이 다르다 — CSS는 `<`를 통째로 막아 끝났지만(schemas/user.py) 여기는
`<`가 목적이다. 그래서 막는 목록이 아니라 **허용 목록**으로 간다.

왜 허용 목록인가: 막는 목록은 새는 게 기본값이다. `<script>`를 지우면 `<img onerror>`가
남고, 그걸 지우면 `<svg onload>`가, `on*`를 지우면 `<a href="javascript:">`가 남는다.
허용 목록은 **모르는 것이 전부 사라지는** 쪽으로 틀린다. 새 공격 형태가 나와도
이미 허용 목록 밖이다.

왜 정규식이 아니라 파서인가: `<scr<script>ipt>`·`<img/**/onerror=x>`·`<a href="jav&#9;ascript:">`
같은 변형은 문자열 치환으로는 못 쫓는다. HTMLParser로 **읽고 다시 쓴다** — 출력은
파서가 이해한 것만 담기므로, 입력의 기묘한 형태가 출력에 그대로 남는 경로가 없다.

겹으로 있는 방어(이것 하나에 걸지 않는다):
  ① 여기 — 허용 목록 재작성. 저장 시점에 한 번, DB에는 이미 씻긴 값만 들어간다.
  ② CSP `script-src 'self'` (unsafe-inline 없음) — 인라인 `on*` 핸들러가 실행 안 된다.
  ③ 프론트가 innerHTML로 넣는다 — 명세상 `<script>`는 그 경로로 실행되지 않는다.
  ④ 프론트에도 가벼운 2차 세척이 있다(frontend/src/api/slots.ts).
①이 무너져도 ②가 남는다. ②만 믿지 않는 이유는 CSP가 엣지 함수에 있어서
로컬·직접 오리진 접근에는 안 걸리기 때문이다.
"""

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

# 세 자리. 키를 늘리면 프론트(SlotEditor·useSlots)와 함께 늘려야 한다.
SLOT_KEYS = ("intro", "aside", "footer")

# 한 칸 4000자. 문단 몇 개와 이미지 몇 장이 넉넉히 들어가고, 여기에 글 한 편을
# 통째로 붙여 넣는 건 이 기능의 용도가 아니다(그건 글로 쓰면 된다).
SLOT_MAX = 4_000

# 태그 → 그 태그에만 허용하는 속성. `class`는 아래 _GLOBAL로 전부에 허용한다.
_ALLOWED: dict[str, tuple[str, ...]] = {
    "p": (), "br": (), "hr": (),
    "strong": (), "b": (), "em": (), "i": (), "u": (), "s": (), "small": (),
    "span": (), "div": (),
    "h2": (), "h3": (), "h4": (),
    "ul": (), "ol": (), "li": (),
    "blockquote": (), "code": (), "pre": (),
    "figure": (), "figcaption": (),
    "a": ("href", "title", "target"),
    "img": ("src", "alt", "title", "width", "height"),
}

# 어디에나 붙일 수 있는 속성. `class`만 둔다 — 사용자 CSS와 이어주는 유일한 끈이고,
# 그 자체로는 아무 동작도 안 한다.
#
# `style`은 **일부러 뺐다.** 넣으면 CSS 값도 씻어야 하는데(`url(javascript:)`,
# 옛 IE의 `expression()`), 스킨 편집기가 이미 CSS를 담당하므로 얻는 게 없다.
# `id`도 뺐다 — 페이지의 진짜 id(#main 등)와 부딪히면 본문 바로가기 같은 게 망가진다.
_GLOBAL: tuple[str, ...] = ("class",)

# 닫는 태그가 없는 것들. 스택에 쌓지 않는다.
_VOID = {"br", "hr", "img"}

# 내용까지 통째로 버리는 것. 여는 태그를 만나면 그 안의 글자도 안 내보낸다 —
# `<script>alert(1)</script>`에서 태그만 지우면 `alert(1)`이 본문에 남는다.
_DROP_TREE = {
    "script", "style", "iframe", "object", "embed", "applet",
    "noscript", "template", "svg", "math", "frame", "frameset",
    "form", "select", "textarea", "option", "button",
}

# 내용이 없는(닫는 태그가 안 오는) 위험 태그. 위 집합에 넣으면 깊이 세기가
# 영영 안 풀려서 뒤 내용이 통째로 사라진다. 그래서 따로 두고 그냥 무시한다.
_DROP_VOID = {"link", "meta", "input", "base", "source", "track", "param"}

_OK_SCHEMES = {"http", "https", "mailto"}


def _clean_url(value: str) -> str | None:
    """링크·이미지 주소. 통과하지 못하면 None(그 속성을 안 쓴다)."""
    # 공백·제어문자를 **먼저** 없앤다. `jav&#9;ascript:`는 파서가 엔티티를 풀어
    # `jav\tascript:`로 넘겨주고, 탭이 든 채로는 스킴이 안 잡히는데 브라우저는
    # 그걸 무시하고 실행한다 — 브라우저와 같은 눈으로 봐야 한다.
    v = "".join(ch for ch in value if ord(ch) > 0x20).strip()
    if not v:
        return None
    # **백슬래시를 슬래시로 접는다.** 브라우저의 URL 파서는 `/\evil.example/x`를
    # `//evil.example/x`와 **같게** 읽는다(WHATWG URL, 크롬·파이어폭스 공통. 실측:
    # `new URL('/\\evil.example/x','https://site/a')` → `https://evil.example/x`).
    # 아래 `//` 검사만 있으면 백슬래시 한 글자로 우회된다(2026-08-19 보안검사).
    # 정상 주소는 안 깨진다 — 경로에 백슬래시를 쓰려면 `%5C`로 인코딩되기 때문이다.
    # 위에서 제어문자를 먼저 터는 것과 같은 논리다: **브라우저와 같은 눈으로 본다.**
    v = v.replace("\\", "/")
    # `//evil.example/x` — 스킴 없는 절대 주소다. 상대 경로처럼 생겼지만 남의
    # 출처로 나간다. 이 기능에 필요 없으니 막는다.
    if v.startswith("//"):
        return None
    if v[0] in "/#":
        return v  # 사이트 안 경로·앵커
    scheme = urlparse(v).scheme.lower()
    if not scheme:
        return v  # `image.png` 같은 상대 경로
    return v if scheme in _OK_SCHEMES else None


class _Rewriter(HTMLParser):
    """읽은 것 중 허용된 것만 다시 쓴다."""

    def __init__(self) -> None:
        # convert_charrefs=True: `&amp;`를 글자로 풀어서 준다. 우리가 다시 escape하므로
        # 결과는 같고, 엔티티에 숨긴 스킴(`&#106;avascript:`)이 여기서 드러난다.
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.drop = 0  # _DROP_TREE 안에 있는 깊이

    # --- 태그 -------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_TREE:
            self.drop += 1
            return
        if self.drop or tag in _DROP_VOID:
            return
        if tag not in _ALLOWED:
            # 모르는 태그는 **껍데기만** 버리고 안의 글자는 남긴다. 사람이 쓴 문장이
            # 낯선 태그에 싸였다고 사라지면, 왜 글이 없어졌는지 알 길이 없다.
            return
        rendered = self._attrs(tag, attrs)
        if rendered is None:
            return  # 필수 속성이 없어 태그 자체가 무의미(src 없는 img)
        self.out.append(f"<{tag}{rendered}>")
        if tag not in _VOID:
            self.stack.append(tag)

    # `<br/>`처럼 스스로 닫는 형태. 기본 구현은 start+end를 부르는데, end에서
    # 스택을 건드리면 엉킨다. 여는 쪽만 태운다(_VOID는 어차피 안 쌓인다).
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # ⚠️ _DROP_TREE 태그의 **자기닫는 형태**는 여기서 끝내야 한다.
        # `handle_starttag`에 넘기면 `self.drop += 1`이 되는데, `<svg/>`에는 닫는 태그가
        # 안 오므로 `handle_endtag`가 영영 안 불려 drop이 0으로 안 돌아온다. 그러면
        # **그 뒤의 모든 글자가 버려진다** — `<p>안녕</p><svg/><p>연락처</p>`가
        # `<p>안녕</p>` 하나로 줄었다(2026-08-19 검사, 실행해서 확인).
        # 이 파일 위쪽 주석이 그 실패 모드를 알고 있었는데, 처방인 `_DROP_VOID`가
        # link·meta처럼 **항상** void인 태그만 덮었다. svg·iframe·form처럼 보통은
        # 짝이 있는 태그가 자기닫는 형태로 오는 경우가 빠져 있었다.
        if tag in _DROP_TREE:
            return  # 이 태그 하나만 버린다. 안에 든 게 없으니 그걸로 끝이다.
        self.handle_starttag(tag, attrs)
        if tag in _ALLOWED and tag not in _VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()
            self.out.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TREE:
            self.drop = max(0, self.drop - 1)
            return
        if self.drop or tag in _VOID or tag not in self.stack:
            return
        # 안 닫힌 태그를 함께 닫는다. `<div><p>x</div>`처럼 어긋나 있어도 출력은
        # 항상 짝이 맞는다 — 안 맞으면 사용자 문장 하나가 그 아래 화면 전체를 삼킨다.
        while self.stack:
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    # --- 내용 -------------------------------------------------------------
    def handle_data(self, data: str) -> None:
        if self.drop:
            return
        self.out.append(escape(data, quote=False))

    # 주석·`<!DOCTYPE>`·`<?pi?>`는 기본 구현이 아무것도 안 해서 그대로 사라진다.
    # 주석은 특히 지워야 한다 — 옛 IE의 조건부 주석이 그 안에서 실행됐다.

    # --- 속성 -------------------------------------------------------------
    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        allowed = _ALLOWED[tag] + _GLOBAL
        kept: list[str] = []
        seen: set[str] = set()
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            # `on*`은 허용 목록에 없어서 이미 안 들어오지만, 한 줄로 못 박아 둔다.
            # 나중에 누가 허용 목록을 넓힐 때 이 줄이 마지막 방어선이 된다.
            if name.startswith("on") or name not in allowed or name in seen:
                continue
            seen.add(name)
            value = raw_value or ""
            if name in ("href", "src"):
                cleaned = _clean_url(value)
                if cleaned is None:
                    continue
                value = cleaned
            elif name in ("width", "height"):
                if not value.isdigit():
                    continue
            elif name == "target":
                if value != "_blank":
                    continue
            kept.append(f'{name}="{escape(value, quote=True)}"')

        got = {a.split("=", 1)[0] for a in kept}
        if tag == "img" and "src" not in got:
            return None  # 주소 없는 이미지는 깨진 아이콘만 남긴다
        if tag == "a":
            if "href" not in got:
                return None  # 목적지 없는 링크는 링크가 아니다
            # 새 창으로 여는 링크에 opener를 남기면 그쪽 페이지가 이 창을 조종할 수
            # 있다(tabnabbing). ugc/nofollow는 남의 글에 링크를 허용할 때의 관례다.
            kept.append('rel="nofollow ugc noopener noreferrer"')
        if tag == "img":
            kept.append('loading="lazy"')
            if "alt" not in got:
                # alt가 없으면 화면낭독기가 파일 이름을 읽는다. 장식으로 선언하는 게 낫다.
                kept.append('alt=""')
        return (" " + " ".join(kept)) if kept else ""

    def result(self) -> str:
        self.close()
        while self.stack:  # 안 닫힌 것 정리
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out).strip()


def sanitize_html(value: str) -> str:
    """사용자 HTML → 내보내도 되는 HTML. 실패하지 않는다(위험한 부분만 사라진다)."""
    if not value or not value.strip():
        return ""
    r = _Rewriter()
    r.feed(value)
    out = r.result()
    # 태그만 남고 글자가 없으면 빈 것으로 본다 — `<p></p>`가 저장돼 있으면
    # '내 문장이 있다'로 세어져서 빈 칸이 화면에 자리를 차지한다.
    return "" if not out or not _Rewriter_text(out) else out


def _Rewriter_text(html: str) -> str:
    """태그를 뺀 알맹이가 있는지 보는 용도. 이미지는 알맹이로 친다."""
    if "<img" in html:
        return "img"
    stripped = _Stripper()
    stripped.feed(html)
    return "".join(stripped.text).strip()


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def sanitize_slots(raw: dict[str, str] | None) -> dict[str, str]:
    """세 칸을 통째로 씻는다. 모르는 키는 버리고, 빈 칸은 빈 문자열로 맞춘다."""
    raw = raw or {}
    return {k: sanitize_html(str(raw.get(k) or "")) for k in SLOT_KEYS}

