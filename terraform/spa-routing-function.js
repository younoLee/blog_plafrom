// CloudFront Function (viewer-request): SPA 딥링크 라우팅.
//
// 왜 이게 생겼나 — 원래 이 일은 `custom_error_response`(403 → 200 /index.html)가 했다.
// S3는 OAC 뒤에서 없는 키에 403을 주므로, /posts/32 같은 딥링크를 index.html로 되돌리는
// 데 그걸 썼다. 그런데 **custom_error_response는 distribution 전체에 걸린다** — 동작별로
// 못 건다. 그래서 백엔드가 주는 인가 거부 403까지 200 + HTML로 바뀌고 있었다.
//
// 그게 왜 위험했나 — 프론트는 `if (!res.ok) throw`로 실패를 판정한다(api/*.ts). 403이
// 200이 되면 res.ok가 true라 **아무 일도 안 일어났는데 UI는 성공으로 표시한다**.
// 예: admin.ts의 승인·차단·삭제. 서버는 제대로 막았으니 권한 우회는 아니지만,
// "됐다고 보이는데 안 된 상태"는 그 자체로 사고를 부른다.
//
// 그래서 라우팅만 이 함수로 떼어내고 custom_error_response는 없앴다. 이 함수는 기본
// 동작(S3)에만 붙으므로 /api/* 는 아예 지나가지 않는다 — 백엔드 응답 코드는 이제
// 손대는 것이 없다.
//
// 규칙: 마지막 경로 조각에 점이 없으면 딥링크로 보고 index.html을 서빙한다.
//   /posts/32      → /index.html      (딥링크)
//   /login         → /index.html
//   /              → /index.html      (default_root_object와 같은 결과)
//   /index-abc.js  → 그대로            (정적 자산)
//   /uploads/x.jpg → 그대로            (업로드 이미지도 기본 동작이 서빙한다)
// 전제: 확장자 없는 오브젝트가 버킷에 없다. 2026-07-28에 전수 확인했다(0개).
// 없는 자산(예: 옛 해시 .js)은 이제 HTML 대신 403이 그대로 나간다 — 그게 맞다.
// JS를 기대한 자리에 HTML이 오는 것보다 낫고, 배포 사고가 조용히 묻히지 않는다.
//
// ── 2026-08-15 추가: 이 사이트가 서빙할 리 없는 확장자는 엣지에서 끊는다 ──────
//
// 실측(2026-08-15, 라이브): `/nope.bar`·`/wp-login.php` → **403 + S3의 원시 XML**
//   <?xml …><Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>
// 점이 있으니 위 규칙이 그대로 S3로 흘려보내고, OAC 뒤의 S3는 없는 키에 403을 준다.
// 사람에겐 뜻 없는 XML이고, 봇에겐 "여기는 S3다"라는 대답이다.
//
// **distribution 전체 에러페이지(custom_error_response)로 고치지 않는다** — 위에 적힌
// 이유 그대로다. 대신 viewer-request 함수가 **응답을 직접 만들어 돌려준다.** 이 함수는
// 기본 동작에만 붙으므로 /api/*는 여전히 지나가지 않는다.
//
// 허용 목록으로 짠 이유: 엣지에서는 오브젝트의 존재를 알 수 없다. 그래서 '없는 것'이
// 아니라 **'이 사이트가 낼 수 있는 종류인가'**로 가른다. 목록은 실제 산출물 기준이다
// (dist: html·js·css·json·md·txt·xml·svg·png / 업로드: png·jpg뿐 — routers/uploads.py가
// 매직바이트로 그 둘만 통과시킨다). 앞으로 쓸 수 있는 것 몇 개를 미리 넣어뒀다.
//
// ⚠️ **이걸로 다 막히지는 않는다.** 허용 목록에 있는 확장자인데 파일이 없으면
// (예: `/devlog/2026-99-99.html`) 여전히 S3의 원시 XML이 나간다. 그건 존재를 알아야
// 판단할 수 있는 자리라 엣지 함수로는 못 고친다 — 고치려면 오리진을 바꾸거나
// Lambda@Edge가 필요하고, 지금 그 값은 비용을 못 한다. 여기서 닫는 것은
// **봇 스캔과 오타 대부분**이다.
var SERVABLE = /\.(html|js|css|json|md|txt|xml|svg|png|jpe?g|gif|webp|avif|ico|woff2?|map)$/i;

// 엣지에서 만드는 404 페이지. 자기 완결이어야 한다(외부 파일을 못 부른다).
// 인라인 <script>는 없다 — CSP가 script-src 'self'라 어차피 막힌다.
var NOT_FOUND_HTML =
    '<!doctype html><html lang="ko"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>없는 주소 — DEV 블로그</title>' +
    // 아이콘 선언. 이 페이지도 탭에 뜨는 화면이고, 파일은 이미 S3에 있다
    // (favicon.svg·icon-192 둘 다 200). 정적 페이지들과 같은 이유로 붙인다.
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' +
    '<link rel="apple-touch-icon" href="/icon-192.png">' +
    '<meta name="theme-color" content="#863bff">' +
    '<style>' +
    ':root{color-scheme:light dark}' +
    'body{margin:0;padding:4rem 1.25rem;font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;' +
    'color:#1d1d1f;background:#fff}' +
    'main{max-width:34rem;margin:0 auto}h1{font-size:1.5rem;margin:0 0 .75rem;letter-spacing:-.02em}' +
    'p{color:#515154;margin:0 0 1.5rem}a{color:#0071e3}' +
    '@media(prefers-color-scheme:dark){body{color:#f5f5f7;background:#000}p{color:#a1a1a6}a{color:#0a84ff}}' +
    '</style></head><body><main>' +
    '<h1>그런 주소는 없어</h1>' +
    '<p>주소를 잘못 눌렀거나, 옮겨진 페이지야.</p>' +
    '<p><a href="/">첫 화면</a> · <a href="/devlog.html">개발일지 전체</a> · <a href="/rss.xml">RSS</a></p>' +
    '</main></body></html>';

function handler(event) {
    var request = event.request;
    var uri = request.uri;
    var last = uri.substring(uri.lastIndexOf('/') + 1);

    if (last.indexOf('.') === -1) {
        request.uri = '/index.html';
        return request;
    }

    if (!SERVABLE.test(last)) {
        return {
            statusCode: 404,
            statusDescription: 'Not Found',
            headers: {
                'content-type': { value: 'text/html; charset=utf-8' },
                // 이 판정은 경로만 보고 내리므로 캐시해도 안전하고, 봇 스캔이
                // 오리진까지 안 가게 된다.
                'cache-control': { value: 'public, max-age=300' },
                'x-content-type-options': { value: 'nosniff' }
            },
            body: NOT_FOUND_HTML
        };
    }

    return request;
}
