from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 — Base.metadata에 모든 모델을 등록시키기 위한 import
from app.core.config import settings
from app.db.base import Base
from app.db.engine import create_configured_engine

# 정리 대상 테이블 — FK 자식 → 부모 순서(citation/mention이 execution_run을 참조하는 식)로
# 나열한다. TRUNCATE ... CASCADE를 쓰므로 순서 자체는 필수가 아니지만 가독성을 위해 유지한다.
_BATCH_TABLES_CHILD_TO_PARENT = (
    "mention",
    "citation",
    "weekly_snapshot",
    "execution_run",
    "prompt",
    "llm_provider",
    "brand_alias",
    "brand_domain",
    "brand",
    "batch_config",
)


def _test_database_url() -> str:
    if not settings.test_database_url:
        pytest.fail(
            "TEST_DATABASE_URL이 설정되지 않았습니다. .env에 TEST_DATABASE_URL을 채우세요 "
            "(.env.example 참조). 개발 DB를 오염시키지 않기 위해 테스트는 별도 DB를 사용한다."
        )
    return settings.test_database_url


@pytest.fixture(scope="session")
def _schema() -> Iterator[None]:
    """스키마를 세션당 한 번만 생성/정리한다."""
    setup_engine = create_configured_engine(_test_database_url())
    Base.metadata.create_all(setup_engine)
    setup_engine.dispose()

    yield

    teardown_engine = create_configured_engine(_test_database_url())
    Base.metadata.drop_all(teardown_engine)
    teardown_engine.dispose()


@pytest.fixture
def db_session(_schema: None) -> Iterator[Session]:
    """테스트마다 새 엔진/트랜잭션을 열고 끝에 롤백한다 — 테스트 간 상태가 섞이지 않는다."""
    test_engine = create_configured_engine(_test_database_url())
    try:
        with test_engine.connect() as conn:
            trans = conn.begin()
            session_factory = sessionmaker(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            session = session_factory()
            try:
                yield session
            finally:
                session.close()
                trans.rollback()
    finally:
        test_engine.dispose()


@pytest.fixture
def session_factory(_schema: None) -> Iterator[sessionmaker[Session]]:
    """실제 커밋이 필요한 통합 테스트(배치 파이프라인 등)용.

    db_session과 달리 롤백하지 않는다 — worker 데몬은 여러 스레드가 각자 독립된 세션에서 커밋해야
    하므로 하나의 트랜잭션으로 감싸 롤백하는 격리 방식을 쓸 수 없다. 이 팩토리를 쓰는 테스트는
    clean_batch_tables로 직접 정리한다.
    """
    test_engine = create_configured_engine(_test_database_url())
    try:
        yield sessionmaker(bind=test_engine, expire_on_commit=False)
    finally:
        test_engine.dispose()


@pytest.fixture
def clean_batch_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    """배치 관련 테이블을 테스트 전후로 비운다 (session_factory는 롤백하지 않으므로 필요)."""

    def _truncate() -> None:
        with session_factory() as session:
            session.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(_BATCH_TABLES_CHILD_TO_PARENT)
                    + " RESTART IDENTITY CASCADE"
                )
            )
            session.commit()

    _truncate()
    yield
    _truncate()


@pytest.fixture
def client(db_session: Session):
    """관리자 CRUD/조회 API 테스트용 Flask 테스트 클라이언트.

    db_session(롤백 격리, 하나의 세션 인스턴스 재사용)을 모든 라우트가 get_session()으로 얻도록
    오버라이드한다 — FastAPI의 app.dependency_overrides에 대응하는 Flask용 패턴
    (app/db/session.py의 set_session_override 참조).
    """
    from app.db.session import set_session_override
    from app.main import app as flask_app

    set_session_override(db_session)
    try:
        with flask_app.test_client() as test_client:
            yield test_client
    finally:
        set_session_override(None)


@pytest.fixture
def client_committing(session_factory: sessionmaker[Session]):
    """실제 커밋이 필요한 통합 테스트(배치 트리거→상태 조회 등)용 Flask 테스트 클라이언트.

    매 get_session() 호출마다 session_factory()로 새 세션을 만든다 — 여러 "요청"에 걸쳐 커밋된
    최신 상태를 정확히 봐야 하고, 단일 세션을 재사용하면 SQLAlchemy identity map이 다른 세션
    (worker 데몬 등)의 커밋을 반영하지 못해 stale해질 수 있기 때문이다.
    """
    from app.db.session import set_session_factory_override
    from app.main import app as flask_app

    set_session_factory_override(session_factory)
    try:
        with flask_app.test_client() as test_client:
            yield test_client
    finally:
        set_session_factory_override(None)
