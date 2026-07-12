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
        "cpu_percent": psutil.cpu_percent(interval=0.2),  # 0.2초 표본
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
