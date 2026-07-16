"""배치 실행 설정(현재는 REPEAT_COUNT 하나) — DB 기반, 관리자가 런타임에 바꿀 수 있다.

.env의 REPEAT_COUNT는 이 테이블에 아직 행이 없을 때(최초 실행, 마이그레이션 직후)의 기본값
역할만 한다 — 관리자가 한 번이라도 값을 저장하면 그 이후로는 이 테이블 값이 우선한다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.batch_config import BatchConfig

_SINGLETON_ID = 1


def get_repeat_count(session: Session) -> int:
    row = session.get(BatchConfig, _SINGLETON_ID)
    if row is None:
        return settings.repeat_count
    return row.repeat_count


def update_repeat_count(session: Session, repeat_count: int) -> int:
    row = session.get(BatchConfig, _SINGLETON_ID)
    if row is None:
        row = BatchConfig(id=_SINGLETON_ID, repeat_count=repeat_count)
        session.add(row)
    else:
        row.repeat_count = repeat_count
    session.commit()
    return row.repeat_count
