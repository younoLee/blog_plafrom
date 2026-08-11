"""관리자 인프라 대시보드용 서버 실측 지표 (psutil).

Docker 컨테이너 안에서 읽지만 CPU·메모리·부하는 호스트(EC2 t2.micro) 기준이라
'서버 혼잡도'로 유효하다. DB 커넥션 수는 라우터에서 pg_stat_activity로 따로 합친다.
"""

import os
import time

import psutil


def gather_infra() -> dict:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:  # 일부 환경엔 loadavg 없음
        load1 = load5 = load15 = 0.0
    return {
        # `interval=0.2`였다. 그건 **요청 스레드를 0.2초 재우는** 블로킹 표본이다.
        # 관리자 화면이 10초마다 이걸 부르므로(AdminPage 폴링) 탭 하나를 켜두면
        # 하루 8,640회 × 0.2초 = 1,728 vCPU-초 = **CPU 크레딧 29/일**(적립 144의 20%)을
        # 태운다. 방문자가 사실상 없는 블로그에서 최대 API 부하원이 '열어둔 관리자 탭'이
        # 되는 셈이다. uvicorn 워커가 1개라 그 0.2초가 다른 요청도 밀어낸다.
        #
        # `interval=None`은 **직전 호출 이후의 평균**을 논블로킹으로 준다 — 10초 폴링에선
        # 0.2초 표본보다 오히려 대표성이 좋다(순간값이 아니라 10초 평균).
        # 첫 호출은 0.0을 주는데, 폴링 화면이라 다음 주기에 바로 채워진다.
        # (2026-08-11 병목검사 — AWS 지표로 크레딧 소모를 실측해 나온 자리)
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": os.cpu_count() or 1,
        "load_avg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "memory": {
            "percent": vm.percent,
            "used_mb": vm.used // (1024 * 1024),
            "total_mb": vm.total // (1024 * 1024),
        },
        "disk": {
            "percent": du.percent,
            "used_gb": round(du.used / (1024 ** 3), 1),
            "total_gb": round(du.total / (1024 ** 3), 1),
        },
        "uptime_seconds": int(time.time() - psutil.boot_time()),
    }
