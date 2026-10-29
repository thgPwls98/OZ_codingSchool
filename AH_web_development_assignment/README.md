# AI Health Web Assignment

## 로컬 실행 (macOS)

저장소 루트에서 Python 3.14 가상환경을 활성화한 뒤 앱 폴더로 이동합니다.

```sh
source .venv-py314/bin/activate
cd AH_web_development_assignment
brew services start mysql@8.4
alembic upgrade head
fastapi run app/main.py
```

브라우저에서 http://0.0.0.0:8000/ 에 접속합니다. DB 연결 정보는 앱 폴더의
`.env`에서 읽으며 이 파일은 Git에 포함하지 않습니다. MySQL 서버와 `.env`에
지정한 DB·사용자가 먼저 준비되어 있어야 합니다. AI 예측에는 `worker/models/`의
Fold 가중치 5개가 필요합니다.

회원가입한 계정은 기본적으로 승인 대기 상태입니다. 환자 등록·진료기록 업로드는
관리자 또는 의료 부서의 승인된 스태프 계정으로 테스트합니다.

## Alembic Migration Guide

이 프로젝트는 데이터베이스 마이그레이션을 위해 Alembic을 사용합니다.

### 1. 마이그레이션 파일 생성 (자동 생성)
모델(`app/models/`)이 변경된 경우 다음 명령어를 실행하여 마이그레이션 파일을 생성합니다.
```bash
uv run alembic revision --autogenerate -m "변경 내용 설명"
```

### 2. 데이터베이스에 반영
생성된 마이그레이션을 데이터베이스에 적용하려면 다음 명령어를 실행합니다.
```bash
uv run alembic upgrade head
```

### 3. 이전 상태로 되돌리기 (Rollback)
마지막 마이그레이션을 취소하려면 다음 명령어를 실행합니다.
```bash
uv run alembic downgrade -1
```
