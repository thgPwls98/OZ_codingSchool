from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def serialize_utc(value: datetime) -> str:
    """UTC 시각을 ISO 8601 `Z` 표기로 바꾼다 (설계 문서 2-1)

    DB에는 시간대 없는 UTC 값이 저장되므로(TimestampMixin, DB 세션 시간대 +00:00)
    시간대 정보가 없으면 UTC로 보고, 있으면 UTC로 변환한다.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z"


# 응답 스키마의 생성·수정일시에 사용한다. (환자·진료기록 공통)
UTCDateTime = Annotated[datetime, PlainSerializer(serialize_utc, return_type=str)]
