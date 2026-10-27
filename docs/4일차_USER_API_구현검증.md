# 4일차 USER API 구현 검증

검증일: 2026-10-27. 기준: `4일차_USER_API_설계.md`. 작업 브랜치: `fix/user-api-spec-compliance`.

## 담당 기능 확인

| 순번 / 담당 | 기능 | 결과 |
|---|---|---|
| 1 / 강선영 | 회원가입, 공통 비밀번호 해싱 | 구현 확인. 입력 검증·정규화·중복·pending 가입·Argon2 저장 검증 |
| 2 / 최현영 | 로그인, JWT 발급·검증·재발급·로그아웃 | 구현 확인. 잘못된 비밀번호·위조/만료/종류 오류·필수 claim 누락 거부, 쿠키 삭제 검증 |
| 3 / 소혜진 | 관리자 회원 목록, 권한 변경 | 구현 확인. 검색·부서 필터·빈 결과·관리자 제한·본인 변경 금지·없는 대상·권한 즉시 반영 검증 |
| 4 / 김지영 | 내 정보 조회·수정, 비밀번호 변경, 탈퇴 | 구현 확인. pending 접근·부분 수정·null/불가 필드/중복 번호 거부·비밀번호 변경 후 재로그인·탈퇴 검증 |

API 10개가 main.py에 등록되어 있다. 사용자 응답에 비밀번호 해시를 포함하지 않는다. 비활성 계정과 탈퇴한 계정은 인증·재발급에서 차단된다.

## 이번 보완

- JWT의 exp·iat·user_id·token_type을 필수로 검증하고 bool/0/음수 사용자 ID를 거부한다.
- 변경 요청의 Origin을 검사한다. Origin이 없는 CLI 요청은 허용한다. 설정이 없으면 동일 출처를 허용하며 `Origin: null`은 거부한다.
- 재발급 실패 401에 WWW-Authenticate 헤더를 추가했다.
- 가입·로그인·비밀번호 변경 입력에 보기/숨기기 버튼을 추가했다.
- 탈퇴 안내를 X-ray·진료 데이터 보존 정책과 일치시켰다. X-ray 화면은 uploader_id가 null이면 ‘탈퇴한 사용자’를 표시한다. 진료/X-ray API 자체는 이번 USER API 범위 밖이므로 해당 화면의 실제 데이터 연동 검증은 별도다.
- ORM에 passive_deletes를 설정해 미로딩 X-ray 전체를 가져오지 않고 DB의 ON DELETE SET NULL 정책을 사용한다.
- 프런트엔드 토큰 재발급은 원래 요청당 한 번만 재시도한다. 동시 요청이 재발급 실패 시 계속 대기하던 문제를 해결했다.
- 실제 DB 스키마를 변경 없이 확인하는 `scripts/check_user_schema.py`를 추가했다.

## 실행 결과

- Python unittest 13개 통과: 기존 관리자 테스트, 삭제 실패 롤백 테스트, 실제 ORM·서비스·인증을 사용하는 임시 SQLite 통합 테스트.
- Node 테스트 3개 통과: 재발급 재시도 상한, 동시 요청 재발급 실패 종료, 비밀번호 표시 전환.
- JavaScript 구문 검사와 git diff --check 통과.
- Alembic의 MySQL 대상 `upgrade head --sql` 생성 통과. 실제 MySQL에서 실행한 결과는 아니다.
- 탈퇴 검증: 사용자 물리 삭제, X-ray uploader_id=NULL, 환자·진료·AI 결과·이미지 경로 보존, 삭제 사용자 토큰 거부 확인. 실제 파일 삭제 함수는 호출하지 않는다. 브라우저 실기동 UI 검증은 수행하지 않았다.

테스트 환경: macOS ARM64, Python 3.14.8 임시 가상환경, FastAPI 0.162.0, SQLAlchemy 2.1.6, PyJWT 2.15.1. 프로젝트 의존성 범위 내 설치이며 uv.lock으로 고정한 환경에서 실행한 결과는 아니다. SQLite 테스트 스키마에서는 MySQL 전용 current_timestamp(0) 기본값만 CURRENT_TIMESTAMP로 변환한다.

성능: 임시 SQLite, 회원 최대 2명, 동시 요청 1개, 탈퇴 회원 X-ray 1개. 정상·검색·오류·탈퇴 포함 42개 요청의 TestClient 호출 시간이 모두 3초 미만이며 최대 0.118초였다. 서버 처리 외 TestClient 비용도 포함한다. 운영 MySQL·다량 데이터·동시 부하에서 3초를 보장하는 결과는 아니다.

## 재현

프로젝트 하위 폴더 `AH_web_development_assignment`에서 프로젝트 의존성을 설치한 환경을 사용한다. 추가 테스트 의존성 설치와 실행:

```sh
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
node --test tests/test_frontend.cjs
```

DB가 준비되면 `.env`를 구성하고 다음 읽기 전용 검사를 실행한다.

```sh
python scripts/check_user_schema.py
```

## 남은 배포 검증

현재 로컬 MySQL localhost:3306은 연결 거부 상태다. 따라서 실제 DB 마이그레이션 적용 확인과 운영 DB 통합/부하 검증은 미완료다. 기존 migration은 수정하지 않았다. 기존 부서·권한 코드와 NULL 데이터를 먼저 점검하고 매핑을 결정한 다음 마이그레이션을 적용해야 한다. 임의의 기존 값 변환은 수행하지 않았다.

운영에서는 JWT_SECRET_KEY를 환경 변수로 지정하고 COOKIE_SECURE=true로 설정한다. 프록시 사용 시 외부 주소를 명시한다. 예: `ALLOWED_ORIGINS=["https://health.example.com"]`. MySQL 스키마 검사 및 실제 데이터 보존 검증, 브라우저 UI 검증, 기록된 운영 규모의 부하 검증까지 통과해야 배포 검증 완료로 판단한다.
