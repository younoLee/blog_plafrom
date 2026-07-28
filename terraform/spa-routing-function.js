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
function handler(event) {
    var request = event.request;
    var uri = request.uri;
    var last = uri.substring(uri.lastIndexOf('/') + 1);

    if (last.indexOf('.') === -1) {
        request.uri = '/index.html';
    }

    return request;
}
