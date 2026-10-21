# Alembic Database Migrations

이 디렉터리는 Alembic을 사용한 데이터베이스 마이그레이션 스크립트를 관리합니다.

## 1. SQLAlchemy 모델 작성 가이드

이 프로젝트에서는 `app/core/db/databases.py`에 정의된 `Base` 클래스를 상속받아 모델을 작성합니다.

- **모델 위치**: `app/models/` 하위에 작성합니다.
- **모델 예시**:
  ```python
  from sqlalchemy import String
  from sqlalchemy.orm import Mapped, mapped_column
  from app.core.db.databases import Base
  from app.core.db.models import UUIDMixin, TimestampMixin

  class User(Base, UUIDMixin, TimestampMixin):
      __tablename__ = "users"
      username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
      email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
  ```
- **중요**: 새로운 모델 파일을 생성한 경우, `app/models/__init__.py`에 임포트해야 Alembic이 모델을 인식할 수 있습니다.

## 2. Alembic 기본 명령어

모든 명령어는 프로젝트 루트에서 `uv run`을 통해 실행하는 것을 권장합니다.

### 마이그레이션 파일 생성 (Autogenerate)
모델 변경 사항을 감지하여 자동으로 마이그레이션 스크립트를 생성합니다.
```bash
uv run alembic revision --autogenerate -m "description of changes"
```

### 마이그레이션 적용 (Upgrade)
최신 버전으로 데이터베이스 스키마를 업데이트합니다.
```bash
uv run alembic upgrade head
```

### 마이그레이션 취소 (Downgrade)
마지막 마이그레이션을 한 단계 취소합니다.
```bash
uv run alembic downgrade -1
```

## 3. 마이그레이션 충돌 해결 방법

여러 명의 개발자가 동시에 마이그레이션 파일을 생성하면 `head`가 여러 개가 되어 충돌이 발생할 수 있습니다.

### 충돌 확인
`alembic upgrade head` 실행 시 `Multiple heads are present` 오류가 발생하면 충돌이 발생한 것입니다. 현재 `head` 목록을 확인하려면 다음 명령어를 실행합니다.
```bash
uv run alembic heads
```

### 해결 방법 1: 마이그레이션 병합 (Merge)
두 개의 `head`를 하나로 합치는 새로운 마이그레이션 파일을 생성합니다.
```bash
uv run alembic merge -m "merge two heads" <revision_id_1> <revision_id_2>
```
이후 생성된 병합 마이그레이션을 적용합니다.
```bash
uv run alembic upgrade head
```

### 해결 방법 2: 순서 조정 (Rebase)
충돌이 발생한 파일 중 하나를 삭제하고, 다른 개발자의 마이그레이션을 먼저 적용(`upgrade head`)한 뒤 다시 `revision --autogenerate`를 실행하여 자신의 변경 사항을 새로 생성합니다. (가장 깔끔한 방법)

1. 내가 만든 마이그레이션 파일 삭제
2. `uv run alembic upgrade head` (다른 개발자의 변경사항 반영)
3. `uv run alembic revision --autogenerate -m "my changes"` (다시 생성)
4. `uv run alembic upgrade head` (내 변경사항 반영)
