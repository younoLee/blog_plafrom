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
  notfound 404를 낸다. **410과 갈라 봐야 한다.** push.py:169가 404를 410과 **같게**
          보고 그 자리에서 구독을 지우는데, 벤더가 URL 형태를 바꾸거나 허용목록을 한 줄
          잘못 만지면 구독이 되돌릴 수 없게 전멸한다. 08-26·08-27 두 회차 모두 이 가지를
          못 밟았고, 이유가 "위험이 없어서"가 아니라 **여기 404 모드가 없어서**였다.
  slow    N초 뒤에 응답한다(CHAOS_SLOW_SECONDS, 기본 55). hang과 다른 사고다 —
          hang은 영영 안 답하니 클라이언트 타임아웃이 그대로 벽시계가 되지만, slow는
          **타임아웃 직전에 답이 와서 재시도가 다시 도는** 모양을 만든다. 08-26이
          "cohere 재시도의 최악 벽시계(3 × 55초)"를 추정으로만 남긴 것이 이 모드가
          없어서였다.
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

# slow 모드가 기다리는 초. 기본 55는 services/ai.py 의 REQUEST_TIMEOUT=55 와 같은 값이라
# '상한 직전에 답이 온다'를 만든다. 경계를 넘기려면 up.sh 에서 올려 잡는다.
SLOW_SECONDS = float(os.environ.get("CHAOS_SLOW_SECONDS", "55"))

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

    def _drain(self):
        """요청 본문을 끝까지 읽어 버린다.

        안 읽으면 수신 버퍼가 차서 클라이언트의 write() 가 막힌다. 그러면 재는 것이
        '업스트림 무응답'이 아니라 '업로드 도중 정체'가 된다 — 5MB 업로드처럼 본문이
        큰 경로에서만 갈라지므로 눈치채기 어렵다."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        left = n
        while left > 0:
            chunk = self.rfile.read(min(left, 65536))
            if not chunk:
                break
            left -= len(chunk)

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
            #
            # **자기 전에 본문을 다 읽는다.** 08-27 훈련에서 4.32MB 업로드가 14.21초에
            # "Connection was closed before we received a valid response"로 끝났는데,
            # 원인이 앱이 아니라 여기였을 가능성이 남아 있었다 — 본문을 안 읽으면 TCP
            # 수신 버퍼가 차서 클라이언트 쓰기가 막히고, 그건 '무응답'이 아니라
            # '전송 중 정체'라는 **다른 사고**다. 레인4의 핵심 질문(5MB가 60초를 넘는가)이
            # 그 때문에 빈칸으로 남았다. 읽고 나서 자야 재는 것이 진짜 무응답이 된다.
            self._drain()
            time.sleep(600)
            return
        if m == "slow":
            # 타임아웃 '직전'에 답하는 모양. 상한을 조금 넘기면 클라이언트가 끊고,
            # 조금 밑이면 재시도가 한 바퀴 더 돈다 — 그 경계가 이 모드로만 밟힌다.
            self._drain()
            time.sleep(SLOW_SECONDS)
            body = b'{"ok":true,"chaos":"slow"}'
            self.send_response(200)
        elif m == "error":
            body = b'{"error":"chaos: upstream unavailable"}'
            self.send_response(503)
        elif m == "gone":
            body = b'{"error":"chaos: subscription gone"}'
            self.send_response(410)
        elif m == "notfound":
            body = b'{"error":"chaos: not found"}'
            self.send_response(404)
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
