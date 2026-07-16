"""요청 단위 DB 세션 관리 (Flask, 동기).

참고 프로젝트(FastAPI)는 라우트 의존성 주입(Depends(get_session))으로 요청마다 새 세션을
열고 닫았다. Flask에서는 scoped_session + 요청 종료 시 remove()하는 패턴이 관례다 — 각 라우트는
`from app.db.session import get_session`으로 세션을 얻고, `init_session_teardown(app)`이 앱
팩토리에서 한 번 호출되어 요청 종료마다 자동으로 정리한다.

테스트는 `set_session_override()`로 이 모듈 전역의 오버라이드를 설정해 모든 라우트가 테스트
DB에 바인딩된 롤백 세션을 쓰도록 만든다 — FastAPI의 `app.dependency_overrides`에 해당하는
Flask용 대응이다. `get_session()`이 호출 시점에 `_session_override`를 다시 읽으므로, 각
라우트 모듈이 `from app.db.session import get_session`으로 함수를 미리 가져와 놓아도(같은
함수 객체를 참조) 문제없이 오버라이드가 적용된다.
"""

from __future__ import annotations

from collections.abc import Callable

from flask import Flask, g, has_app_context
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from app.core.config import settings
from app.db.engine import create_configured_engine

engine = create_configured_engine(settings.database_url, echo=False)
_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
SessionLocal: scoped_session[Session] = scoped_session(_session_factory)

_session_override: Session | None = None
_session_factory_override: Callable[[], Session] | None = None


def set_session_override(session: Session | None) -> None:
    """테스트 전용 — 이후의 모든 get_session() 호출이 이 (고정된) 세션을 반환하게 한다.

    하나의 트랜잭션 안에서 롤백으로 격리하는 CRUD 테스트(conftest.py의 db_session 픽스처)용 —
    같은 세션 인스턴스를 계속 재사용한다. None으로 해제.
    """
    global _session_override
    _session_override = session


def set_session_factory_override(factory: Callable[[], Session] | None) -> None:
    """테스트 전용 — 요청마다 factory()로 새 세션을 만들어 그 요청 동안 재사용하고, 요청이
    끝나면 닫는다.

    실제 커밋이 필요한 통합 테스트(배치 트리거→worker 데몬→상태 조회처럼 여러 "요청"에 걸쳐
    커밋된 최신 상태를 봐야 하는 경우, conftest.py의 session_factory 픽스처)용 — 세션 하나를
    테스트 전체에서 재사용하면 SQLAlchemy identity map이 다른 세션(worker)의 커밋을 반영하지
    못해 stale해질 수 있어 요청 단위로 새로 만든다. **요청마다 flask.g에 캐싱하고
    teardown_appcontext에서 반드시 close() 해야 한다** — 그렇지 않으면 매 요청이 커넥션 풀에서
    커넥션을 하나씩 열어놓은 채 반환하지 않아(유휴 트랜잭션), 이후 다른 세션의 TRUNCATE 등이
    그 잠금 때문에 무한 대기하게 된다(2026-07-15 실측 — 최초 구현에서 이 close() 누락으로
    테스트가 멈추는 것을 확인). None으로 해제.
    """
    global _session_factory_override
    _session_factory_override = factory


def init_session_teardown(app: Flask) -> None:
    @app.teardown_appcontext
    def _remove_session(_exception: BaseException | None = None) -> None:
        if _session_factory_override is not None:
            if has_app_context():
                session = g.pop("_factory_override_session", None)
                if session is not None:
                    session.close()
            return
        if _session_override is None:
            SessionLocal.remove()


def get_session() -> Session:
    """라우트/서비스에서 현재 요청의 세션을 얻는다."""
    if _session_factory_override is not None:
        if has_app_context() and "_factory_override_session" in g:
            return g._factory_override_session
        session = _session_factory_override()
        if has_app_context():
            g._factory_override_session = session
        return session
    if _session_override is not None:
        return _session_override
    return SessionLocal()
