// CloudFront Function (viewer-response): Content-Security-Policy 헤더를 붙인다.
// CloudFront Free 요금제가 커스텀 Response Headers Policy(CSP)를 거부해서, 그 우회로 Function을 쓴다.
//
// 롤아웃 순서(중요):
//   1) 지금은 'content-security-policy-report-only' 로 배포 → 사이트는 절대 안 깨지고,
//      위반이 있으면 브라우저 콘솔(F12)에만 보고된다.
//   2) 라이브를 홈/글상세(이미지 포함)/로그인/글쓰기/관리자까지 돌면서 콘솔에 CSP 위반이
//      0건인지 확인한다.
//   3) 확인되면 아래 헤더명을 'content-security-policy'(Report-Only 없는 버전)로 바꿔 실제 적용.
function handler(event) {
    var response = event.response;
    var headers = response.headers;

    // 이 앱 실측 기준으로 짠 정책:
    //  - script-src 'self': 빌드된 index.html에 인라인 스크립트가 없어 엄격하게 잠가도 됨(핵심 방어)
    //  - style-src / font-src 에 cdn.jsdelivr.net: Pretendard 폰트 CSS를 외부 로드하기 때문
    //  - style 'unsafe-inline': React/Tailwind가 인라인 style 속성을 넣을 수 있어 허용(스타일 XSS는 저위험)
    //  - img-src https: : 마크다운 본문의 외부 이미지 링크 허용(업로드 이미지는 same-origin='self')
    //  - connect-src 'self': API가 same-origin(/api)이라 외부 연결 불필요
    //  - *.tosspayments.com / *.toss.im: 토스페이먼츠 결제창(SDK 스크립트·iframe·네트워크).
    //    결제 승인 자체는 백엔드(서버→토스)가 하지만, 결제창 SDK는 브라우저에서 토스 도메인을
    //    로드/연결/프레임하므로 script/connect/frame/form-action에 토스 도메인을 허용해야 창이 뜬다.
    //    (승인 검증은 여전히 서버가 시크릿키로 수행 — 프론트에 시크릿키 노출 없음)
    var csp = [
        "default-src 'self'",
        "script-src 'self' https://*.tosspayments.com",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net data:",
        "img-src 'self' data: https:",
        "connect-src 'self' https://*.tosspayments.com https://*.toss.im",
        "frame-src https://*.tosspayments.com https://*.toss.im",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'self'",
        "form-action 'self' https://*.tosspayments.com https://*.toss.im"
    ].join("; ");

    // 검증 완료(위반 0건) → 실제 적용(enforce).
    // 혹시 문제가 생기면 이 헤더명을 다시 'content-security-policy-report-only'로
    // 되돌리고 apply 하면 즉시 무해화(보고만)된다.
    headers['content-security-policy'] = { value: csp };

    return response;
}
