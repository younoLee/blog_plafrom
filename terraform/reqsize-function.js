// CloudFront Function (viewer-request): 큰 요청 본문을 '엣지에서' 413으로 차단.
// Content-Length가 상한을 넘으면 EC2(t2.micro)에 닿기 전에 끊어, 대용량 본문으로 인한
// 메모리/대역폭 고갈(DoS)을 원본 도달 전에 막는다. /api/* 동작(오리진=EC2)에만 연결한다.
//
// 2026-09-02: 상한을 **경로별**로 나눴다. 그전에는 전 경로가 6MB였는데, 6MB는 이미지
// 업로드(5MB 파일 + multipart 경계·헤더 여유) 하나 때문에 잡은 값이다. 그 값을
// /api/auth/login 같은 **무인증 JSON 경로**까지 나눠 갖고 있었고, 무인증 경로가 6MB를
// 받으면 t2.micro 메모리 고갈 계산이 그대로 되살아난다(backend/app/main.py의
// BodySizeLimitMiddleware docstring에 실측이 있다). 엣지와 앱이 서로 다른 상한을 들고
// 있으면 "엣지는 통과시켰는데 앱이 413"이 되므로, 앱과 **같은 정책**으로 맞춘다:
//   /api/upload 만 6291456, 나머지는 524288.
//
// 이 파일은 CloudFront Functions에서 도므로 ES5.1 수준만 쓴다 — const/let, 화살표 함수,
// 템플릿 리터럴, String.prototype.startsWith 전부 쓰지 않는다. var와 indexOf로만 짠다.
// 검사는 terraform/cf-functions.test.mjs 가 이 파일의 텍스트를 그대로 불러서 한다.

// 앱의 UPLOAD_PATH와 같은 값이어야 한다. 한쪽만 고치면 정책이 갈린다.
var UPLOAD_PATH = '/api/upload';
var MAX_UPLOAD_BODY = 6291456; // 6 * 1024 * 1024
var MAX_BODY = 524288; // 512 * 1024

// 이 요청에 걸 상한을 경로로 고른다.
function limitFor(uri) {
    var path = uri || '';

    // 쿼리스트링·프래그먼트는 경로가 아니다. CloudFront의 request.uri에는 원래 안 들어오지만
    // (쿼리는 request.querystring에 따로 있다) 들어와도 판정이 흔들리지 않게 잘라둔다.
    var q = path.indexOf('?');
    if (q !== -1) {
        path = path.substring(0, q);
    }
    var h = path.indexOf('#');
    if (h !== -1) {
        path = path.substring(0, h);
    }

    // 후행 슬래시만 접는다(여러 개도 접는다). 앱의 path.rstrip("/")와 같은 동작.
    while (path.length > 1 && path.charAt(path.length - 1) === '/') {
        path = path.substring(0, path.length - 1);
    }

    // 비교는 접두사(indexOf === 0)가 아니라 **정확히 같은가**다. 접두사로 하면
    // /api/uploadsomething 이 6MB를 얻는다 — 무인증 경로 하나만 잘못 넓혀도 위 계산이
    // 되살아난다. 업로드 라우트는 uploads.py에 router.post("") 하나뿐이라 하위 경로도 없다.
    if (path === UPLOAD_PATH) {
        return MAX_UPLOAD_BODY;
    }
    return MAX_BODY;
}

function handler(event) {
    var request = event.request;
    var cl = request.headers['content-length'];

    // 헤더가 아예 없으면 그대로 통과시킨다 — 본문 없는 GET/HEAD가 그 모양이다.
    if (cl) {
        var size = parseInt(cl.value, 10);
        // 숫자로 안 읽히면(NaN) 여기서는 막지 않는다. 엣지는 '헤더가 말하는 크기'만 보는
        // 보조 방어이고, 실제 바이트는 앱의 BodySizeLimitMiddleware가 수신 스트림을 세면서
        // 끊는다(Transfer-Encoding: chunked 우회도 거기서 막힌다). 여기서 임의로 413을 내면
        // 앱과 정책이 갈리고, 엣지가 앱보다 엄격해지는 쪽의 오탐은 조용히 사용자만 잃는다.
        if (!isNaN(size) && size > limitFor(request.uri)) {
            return {
                statusCode: 413,
                statusDescription: 'Payload Too Large',
            };
        }
    }
    return request;
}
