#!/usr/bin/env python3
"""주입용 가짜 업스트림 — 바깥 의존이 '어떻게' 죽는지를 골라서 재현한다.

07-28 훈련이 Anthropic에서 배운 것: **'거부'와 '무응답'은 다른 사고다.**
연결 거부는 0.5초에 502가 됐고, 연결은 받고 무응답인 경우는 115초를 붙들었다.
후자가 훨씬 나쁜데 `docker stop`으로는 재현되지 않는다 — 그건 항상 '거부'다.

그래서 죽이는 대신 **가로챈다.** extra_hosts로 DNS를 이 서버로 돌리고, 여기서
모드를 골라 응답한다. 모드는 파일 하나로 바꾼다(/state/mode) — 재기동 없이 바뀐다.

모드:
  refuse  즉시 연결을 끊는다 (docker stop과 같은 모양)
  hang    연결·요청은 받고 **응답하지 않는다**. 클라이언트 타임아웃을 재는 용도
  error   503을 낸다. 업스트림이 살아 있지만 아픈 경우
  gone    410을 낸다. 푸시에서 특히 중요하다 — 구독 만료의 표준 신호이고,
          services/push.py가 이걸 받으면 행을 지운다. 그 정리가 실제로 도는지 본다
  pass    정상 200. 기준선 확인용

TLS를 종단한다. 대상이 전부 https라 평문으로는 가로챌 수 없다.
인증서는 make_ca.sh가 만든 사설 CA로 서명하고, 컨테이너 신뢰 저장소에 넣는다.
"""
import http.server
import os
import pathlib
import ssl
import sys
import threading
import time

STATE = pathlib.Path(os.environ.get("CHAOS_STATE", "/state/mode"))
LOG = pathlib.Path(os.environ.get("CHAOS_LOG", "/state/hits.log"))


def mode() -> str:
    try:
        return STATE.read_text().strip() or "pass"
    except OSError:
        return "pass"


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 기본 로거는 stderr로 시끄럽다
        pass

    def _record(self, m):
        # 무엇이 몇 번 걸렸는지 남긴다. '주입이 실제로 닿았는가'를 나중에 증명해야 한다 —
        # 안 닿았는데 앱이 멀쩡한 것을 '견뎠다'로 읽으면 훈련이 거짓말을 한다.
        try:
            with LOG.open("a") as f:
                f.write(f"{time.time():.3f} {m} {self.command} {self.headers.get('Host','?')}{self.path}\n")
        except OSError:
            pass

    def _handle(self):
        m = mode()
        self._record(m)
        if m == "refuse":
            self.close_connection = True
            try:
                self.connection.close()
            except OSError:
                pass
            return
        if m == "hang":
            # 응답을 안 준다. 클라이언트가 스스로 끊을 때까지 잡고 있는다.
            # 이게 이 서버의 존재 이유다 — docker stop으로는 이 상태를 못 만든다.
            time.sleep(600)
            return
        if m == "error":
            body = b'{"error":"chaos: upstream unavailable"}'
            self.send_response(503)
        elif m == "gone":
            body = b'{"error":"chaos: subscription gone"}'
            self.send_response(410)
        else:
            body = b'{"ok":true,"chaos":"pass"}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _handle


def serve(port: int, certfile: str, keyfile: str) -> None:
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()


def main() -> int:
    cert = os.environ.get("CHAOS_CERT", "/certs/server.crt")
    key = os.environ.get("CHAOS_KEY", "/certs/server.key")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE.exists():
        STATE.write_text("pass\n")
    # 443만 열면 되지만, 평문으로 오는 것도 잡으려면 80도 필요하다.
    # 평문 쪽은 TLS 없이 같은 핸들러를 쓴다.
    threading.Thread(
        target=lambda: http.server.ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever(),
        daemon=True,
    ).start()
    print(f"blackhole: :443(TLS) :80  state={STATE}", flush=True)
    serve(443, cert, key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
