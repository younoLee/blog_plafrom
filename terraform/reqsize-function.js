// CloudFront Function (viewer-request): 큰 요청 본문을 '엣지에서' 413으로 차단.
// Content-Length가 6MB를 넘으면 EC2(t2.micro)에 닿기 전에 끊어, 대용량 본문으로 인한
// 메모리/대역폭 고갈(DoS)을 원본 도달 전에 막는다. (앱에도 같은 상한 미들웨어가 있음 — 이중 방어)
// /api/* 동작(오리진=EC2)에만 연결한다. 이미지 업로드(5MB)는 통과.
function handler(event) {
    var request = event.request;
    var cl = request.headers['content-length'];
    if (cl && parseInt(cl.value, 10) > 6291456) {
        // 6 * 1024 * 1024
        return {
            statusCode: 413,
            statusDescription: 'Payload Too Large',
        };
    }
    return request;
}
