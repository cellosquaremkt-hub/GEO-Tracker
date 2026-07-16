from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BatchConfig(Base):
    """단일 행(id=1)만 쓰는 배치 실행 설정. 관리자가 Settings 화면에서 REPEAT_COUNT를
    서버 재시작 없이 바꿀 수 있도록 .env 대신 이 테이블을 진실 원천으로 쓴다.

    행이 아직 없으면(마이그레이션 직후 등) app/services/batch_config_service.py가
    settings.repeat_count(.env)를 기본값으로 폴백한다.
    """

    __tablename__ = "batch_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False)
