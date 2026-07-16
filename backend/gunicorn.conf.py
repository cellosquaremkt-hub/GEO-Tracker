"""Gunicorn 설정 — docs/migration_flask_postgres.md §2.4 참조.

이 웹 앱은 CLI 서브프로세스를 직접 실행하지 않는다(배치 실행은 app/worker/daemon.py라는
별도 프로세스가 전담 — §2.3). 그래서 모든 요청이 DB 읽기/쓰기 정도로 빠르게 끝나고,
worker 종류는 기본 sync로 충분하며 timeout도 기본값을 늘릴 이유가 없다.
"""

bind = "0.0.0.0:8000"
worker_class = "sync"
# 통상 (2 x CPU 코어 수) + 1 (Gunicorn 공식 권장값) — 트래픽 규모가 작으므로 낮게 시작.
workers = 3
# 기본값(30초) 유지 — 배치가 아무리 오래 걸려도 이 프로세스는 그 시간을 기다리지 않는다.
timeout = 30
accesslog = "-"
errorlog = "-"
