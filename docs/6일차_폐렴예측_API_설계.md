# 6일차 폐렴 예측 API 설계

| 항목 | 내용 |
|---|---|
| 목적 | 저장된 진료기록의 X-Ray로 예측을 요청하고, 같은 모델의 기존 결과를 재사용하며 결과 목록을 조회한다 |
| 대상 | REQ-PRED-001, REQ-PRED-002, NFR-PRED-001, NFR-PRED-002 |
| 작성 기준 | 현재 main에서 분기한 프로젝트 코드와 5일차 API 설계 |
| 상태 | 구현 전 설계안. 모델 학습·선정 및 팀 검토 전이며 실제 모델 성능은 미검증 |
| 작업 브랜치 | `docs/day6-pneumonia-api-design` |
| 범위 | API 명세·DB·worker 연동 설계. 이 문서 작성으로 API 구현 또는 main 병합이 완료되는 것은 아니다 |

본문의 프로젝트 경로는 `AH_web_development_assignment/` 기준이다. 과제의 Hitmap은 코드에서 사용하는 `heatmap_url`(히트맵)로 표기한다.

## 1. 현재 프로젝트와 연결

| 근거 파일 | 확인한 현재 동작 | 이번 설계 |
|---|---|---|
| `static/apis.js` | `POST /medical-records/{id}/predict`, `GET /medical-records/{id}/analyses` 호출 | 기존 경로 유지 |
| `static/pages.js` | 목록을 배열로 처리하고 `confidence` 뒤에 `%` 표시. POST 성공 직후 완료 안내 | 목록 배열·백분율 유지. 202는 접수 안내와 작업 조회로 변경 |
| `app/models/ai_analysis_result.py` | `record_id`, `is_pneumonia`, `confidence Numeric(5,2)`, 필수 `heatmap_url`, `ai_model`, 생성·수정일시 | 기존 결과 모델 확장, 선택적인 히트맵은 NULL 허용 |
| `app/core/dependencies.py` | `StaffUser`는 staff·admin 허용, pending 차단. 비활성 계정 차단 | 예측 요청·목록·작업 조회·히트맵 조회 모두 재사용 |
| `app/models/xray_image.py` | 이미지 상대 경로와 진료기록 FK 저장 | 업로드된 기존 이미지만 사용 |
| `app/repositories/medical_record_repository.py` | 이미지 교체 시 기존 이미지와 AI 결과 삭제. 히트맵 경로도 파일 정리 대상으로 수집 | 기존 무효화·정리 정책 유지, 실행 중 작업과의 경쟁 처리 추가 |
| `app/services/medical_record_service.py` | 환자 → 진료기록 순서의 행 잠금 사용 | 예측 접수·결과 저장도 같은 잠금 순서 적용 |
| `app/core/file_storage.py` | X-Ray·히트맵 비공개 저장소, 종류별 경로 검증·삭제 지원 | 재사용. API URL과 DB의 상대 경로를 구분 |
| `app/main.py`, `docker-compose.yml` | 예측 라우터·worker 서비스 없음. Compose는 FastAPI·MySQL 구성 | 라우터·별도 worker·공유 저장소 추가 필요 |

현재 운영 규칙은 **진료기록 1건당 X-Ray 1장**이다. DB 관계는 1:N이지만 이번에 다중 이미지 선택 API를 추가하지 않는다. 결과 목록은 현재 진료기록의 결과이며, 다른 진료기록까지 합친 환자 전체 이력은 별도 범위다.

## 2. 요구사항과 API 목록

모든 경로의 기본 접두사는 `/api/v1`이다.

| 요구사항 | 설계 |
|---|---|
| REQ-PRED-001 | 기존 이미지로 예측 요청. 동일 이미지·동일 모델 버전의 완료 결과가 있으면 추론 없이 반환 |
| REQ-PRED-002 | 진료기록 상세에서 X-Ray와 완료 결과 목록 표시. ID·폐렴 여부·confidence·히트맵 URL·수행 일시·모델 제공 |
| NFR-PRED-001 | 실제 모델로 Recall ≥ 0.90, Accuracy 목표 0.80~0.90 검증. 최소 Accuracy 기준은 팀 확정 필요 |
| NFR-PRED-002 | HTTP 요청은 3초 이내 응답하도록 추론을 별도 worker에서 수행. 실제 부하 측정으로 검증 |

| Method | Endpoint | 성공 | 목적 |
|---|---|---|---|
| POST | `/medical-records/{record_id}/predict` | 200 / 202 | 기존 결과 반환 또는 작업 접수·재사용 |
| GET | `/medical-records/{record_id}/analyses` | 200 | 완료 결과 목록 |
| GET | `/medical-records/{record_id}/prediction-jobs/{job_id}` | 200 | 비동기 작업 상태 조회 (신규 보조 API) |
| GET | `/medical-records/{record_id}/analyses/{analysis_id}/heatmap` | 200 | 인증된 히트맵 파일 조회 (선택 기능) |

## 3. 공통 계약

- 인증: `Authorization: Bearer <access_token>`. 활성 계정의 `StaffUser`만 허용한다. 연구·의료·개발 부서 staff 및 admin이 대상이며, 의료 부서 전용 의존성을 사용하지 않는다.
- ID: `record_id`, `job_id`, `analysis_id`는 양의 정수. 잘못된 형식·범위는 422.
- 입력 이미지나 파일 경로를 클라이언트로부터 받지 않는다. 서버가 진료기록의 이미지와 활성 모델을 선택한다.
- 오류: 업무 오류는 `{"detail": "메시지"}`, 검증 오류는 FastAPI 기본 형식. 내부 파일 경로·예외·SQL은 숨긴다.
- 신규 시각은 UTC 저장, ISO 8601 `Z` 응답. 기존 타임존 없는 값은 실제 시간대를 확인해 이관한다.
- JSON·이미지 응답에 `Cache-Control: private, no-store`. 이미지에는 `X-Content-Type-Options: nosniff`도 적용한다.

### 3-1. 예측 결과 `AnalysisResponse`

| 필드 | 타입 | 의미 |
|---|---|---|
| id | integer | 결과 고유 ID |
| record_id | integer | 진료기록 ID |
| xray_image_id | integer | 추론에 사용한 이미지 ID |
| is_pneumonia | boolean | 모델의 폐렴 확률이 해당 버전의 임계값 이상이면 true |
| confidence | number | **판정된 클래스의 점수**, 0~100%, 소수 둘째 자리 반올림 |
| heatmap_url | string 또는 null | 인증된 히트맵 조회 API 경로. 생성하지 않으면 null |
| ai_model | string | 화면 표시용 모델명 |
| model_version | string | 가중치·전처리·클래스 매핑·임계값을 식별하는 불변 버전 |
| created_at | datetime | 추론 완료 결과를 저장한 일시. 작업 접수 일시와 구분 |

worker가 폐렴 클래스의 점수 `p ∈ [0,1]`를 반환한다면, `is_pneumonia = p >= threshold`, `confidence = (p if is_pneumonia else 1-p) * 100`이다. 판정은 반올림 전 점수로 수행한다. confidence는 모델 점수이며 임상적 확실성을 의미하지 않는다. 임계값을 낮추면 true 판정의 confidence도 50% 미만일 수 있다. 팀에서 confidence를 폐렴 확률로 바꾸려면 이 계약과 화면 설명을 함께 수정한다.

## 4. API 상세

### 4-1. 예측 요청

`POST /api/v1/medical-records/{record_id}/predict`

요청 본문·이미지 재업로드·모델 선택 파라미터 없음. 현재 활성 모델 버전을 사용한다.

**기존 완료 결과: 200 OK**

```json
{
  "status": "completed",
  "cached": true,
  "result": {
    "id": 41,
    "record_id": 12,
    "xray_image_id": 25,
    "is_pneumonia": true,
    "confidence": 94.12,
    "heatmap_url": null,
    "ai_model": "team-pneumonia",
    "model_version": "v1",
    "created_at": "2026-10-28T02:00:00Z"
  }
}
```

`team-pneumonia`, `v1`, 점수는 응답 형식 설명용 예시이며 선정·평가된 모델을 의미하지 않는다. 캐시 적중 시 추론 함수 호출 수는 0이어야 한다. 이미 저장된 결과는 worker가 일시 중단되어도 반환할 수 있다.

**신규 접수 또는 동일 작업 진행 중: 202 Accepted**

헤더: `Location: /api/v1/medical-records/12/prediction-jobs/73`, `Retry-After: 1`

```json
{
  "job_id": 73,
  "record_id": 12,
  "status": "queued",
  "ai_model": "team-pneumonia",
  "model_version": "v1",
  "status_url": "/api/v1/medical-records/12/prediction-jobs/73"
}
```

이미 처리 중이면 같은 job_id와 실제 상태(`queued` 또는 `running`)를 반환한다. 202는 추론 완료가 아닌 **DB에 작업이 영속적으로 접수됨**을 의미한다. 실제 모델 준비 전 운영 요청은 503이며 mock 결과를 대신 저장하지 않는다.

### 4-2. 결과 목록

`GET /api/v1/medical-records/{record_id}/analyses?limit=20&offset=0`

- 현재 진료기록의 완료 결과를 `created_at DESC, id DESC`로 반환한다. 모든 모델 버전을 포함한다.
- 응답은 `AnalysisResponse[]`. 결과가 없으면 `200 []`, 진료기록이 없으면 404.
- `limit`: 기본 20, 1~100. `offset`: 기본 0, 0 이상 정수.
- 응답 헤더 `X-Total-Count`에 전체 완료 결과 개수를 담는다. 화면에 페이지 이동을 추가하여 첫 페이지 밖 결과도 조회할 수 있게 한다.
- 목록 조회는 모델·worker 준비 여부와 무관하며 추론을 시작하지 않는다. queued·running·failed 작업은 결과 목록에 넣지 않는다.
- X-Ray는 기존 `GET /api/v1/medical-records/{record_id}/xray-image`를 사용한다. 이미지 바이너리를 JSON에 포함하지 않는다.

### 4-3. 작업 상태

`GET /api/v1/medical-records/{record_id}/prediction-jobs/{job_id}`

```json
{
  "job_id": 73,
  "record_id": 12,
  "status": "completed",
  "ai_model": "team-pneumonia",
  "model_version": "v1",
  "created_at": "2026-10-28T01:59:58Z",
  "completed_at": "2026-10-28T02:00:00Z",
  "result_id": 41,
  "error_code": null
}
```

상태는 `queued → running → completed | failed | cancelled`. 미완료 시 `completed_at`, `result_id`는 null. 종료된 실패·취소 작업도 HTTP 200으로 상태를 반환하고, `error_code`에 `INFERENCE_FAILED`, `INVALID_IMAGE`, `MODEL_UNAVAILABLE`, `TIMEOUT`, `IMAGE_CHANGED` 등의 공개 코드를 담는다. 종료 시각은 실패·취소에도 기록한다. 다른 진료기록에 속한 job_id는 404.

재시도는 POST를 다시 호출한다. 실패·취소 작업은 별도 이력으로 남기고 새 작업을 만든다. 진행 작업이 있으면 중복 생성하지 않는다.

### 4-4. 히트맵 조회 (선택 기능)

`GET /api/v1/medical-records/{record_id}/analyses/{analysis_id}/heatmap`

결과가 해당 진료기록에 속하는지 검사하고, DB 상대 경로를 `resolve_stored_path(FILE_KIND_HEATMAP, ...)`로 검증하여 파일을 반환한다. 성공 시 200 및 실제 `image/png` 또는 `image/jpeg`. 결과·히트맵·파일이 없으면 404. DB에는 API URL 대신 비공개 저장소의 상대 경로만 저장하고 응답 시 URL을 구성한다. `/media`에 환자 영상이나 히트맵을 저장하지 않는다.

### 4-5. 오류 코드

| HTTP | 상황 | detail 예시 |
|---|---|---|
| 401 | 토큰 누락·만료·위조·탈퇴 계정 | 인증 정보가 유효하지 않습니다. |
| 403 | pending·비활성 계정·허용되지 않은 요청 출처 | 기존 인증·Origin 검사 메시지 유지 |
| 404 | 진료기록 없음 | 진료기록을 찾을 수 없습니다. |
| 404 | 저장된 X-Ray 행 또는 파일 없음 (새 예측 시) | X-Ray 이미지를 찾을 수 없습니다. |
| 404 | 작업·결과·히트맵 없음 또는 소속 불일치 | 예측 작업을 찾을 수 없습니다. / 히트맵을 찾을 수 없습니다. |
| 422 | 잘못된 ID·목록 파라미터 | FastAPI 기본 검증 오류 |
| 503 | 신규 추론에 필요한 모델·worker 준비 안 됨 또는 접수 용량 초과 | 예측 서비스를 준비 중입니다. 잠시 후 다시 시도해주세요. |
| 500 | DB·저장소의 예상하지 못한 오류 | 잠시 후 다시 시도해주세요. |

진행 중 이미지 교체는 작업을 cancelled로 종료하며, 이미 202로 접수된 추론 오류는 상태 조회로 전달한다. HTTP 접수 성공과 작업 성공을 구분한다.

## 5. DB 변경 설계

기존 마이그레이션을 수정하지 않고 새 Alembic 리비전을 추가한다.

### 5-1. `ai_analysis_results` 확장

| 항목 | 변경 |
|---|---|
| record_id | 기존 진료기록 FK와 ON DELETE CASCADE 유지 |
| xray_image_id | 이미지 FK 추가, NOT NULL, ON DELETE CASCADE |
| model_version | String(128), NOT NULL 추가. 표시명 ai_model과 구분 |
| heatmap_url | 기존 String(255)을 nullable로 변경. 비공개 상대 경로 저장 |
| confidence | 기존 Numeric(5,2) 유지, 0~100 범위 검증·CHECK 추가 |
| 중복 방지 | UNIQUE(record_id, xray_image_id, model_version) |
| 목록 인덱스 | (record_id, created_at, id) |

이미지가 같아도 모델 버전이 다르면 새로운 결과다. 버전은 가중치뿐 아니라 전처리·출력 해석·임계값 변경 시에도 새로 부여한다. 활성 모델 변경 후에도 이전 버전 결과는 목록에 보존한다.

기존 결과의 이미지·버전을 입증할 수 없으면 임의 연결하거나 신규 결과 캐시로 쓰지 않는다. 마이그레이션 전 기존 행·중복·confidence 범위·히트맵 경로를 점검하고, 미확인 결과는 별도 보관 후 팀이 이관 정책을 확정한다. 필수 컬럼은 검증된 데이터 이관 후 NOT NULL로 전환한다.

### 5-2. `prediction_jobs` 신설

| 필드 | 의미 |
|---|---|
| id, record_id, xray_image_id | 작업 식별자, 진료기록·입력 이미지 FK |
| ai_model, model_version | 접수 시 고정한 모델 정보 |
| status | queued / running / completed / failed / cancelled |
| active_key | 진행 중에만 `record_id:xray_image_id:model_version`, 종료 시 NULL |
| result_id | 완료 결과 FK, nullable, 결과 삭제 시 SET NULL |
| created_at, started_at, completed_at | UTC 접수·시작·종료 일시 |
| lease_expires_at, attempt_count, claim_token | 실행 임대 만료·시도 횟수·실행권 식별자 |
| error_code | 외부 공개용 실패·취소 코드, nullable |

- `active_key`에 UNIQUE: MySQL의 여러 NULL 허용을 이용해 진행 중 작업만 하나로 제한한다. 종료 상태와 active_key 해제는 같은 트랜잭션에서 처리한다.
- `(status, created_at, id)` 인덱스로 대기 작업을 조회한다. 결과 UNIQUE 제약도 최종 중복 방어로 유지한다.
- 환자·진료기록 삭제 시 작업도 CASCADE 삭제한다. 이미지 교체 시 해당 이미지의 미완료 작업을 cancelled로 바꾸고 `xray_image_id`를 NULL로 전환한 후 기존 이미지 행을 삭제한다. 이 FK는 nullable·ON DELETE SET NULL로 설계한다. 접수 시에는 반드시 이미지가 있어야 한다.
- 작업은 처리 입력의 스냅샷(이미지 상대 경로 포함)을 보관하지만, 완료 직전에는 현재 이미지 ID를 다시 확인한다. 작업 경로는 클라이언트 응답에 노출하지 않는다.

## 6. 처리 흐름과 동시성

### 6-1. 예측 요청

1. 인증·StaffUser 검사 후 활성 모델 버전 설정을 확인한다.
2. 환자 → 진료기록 순서로 짧게 잠그고 현재 이미지 ID를 얻는다.
3. 동일 기록·이미지·버전의 완료 결과가 있으면 200 반환한다. 파일 재추론·모델 로딩 없음.
4. 동일한 진행 작업이 있으면 같은 작업의 202 반환한다.
5. 신규 작업이면 이미지 파일과 해당 버전 worker의 최근 준비 상태·접수 용량을 확인한다. 준비 안 됨은 503.
6. 작업을 queued로 저장·커밋한 뒤 202 반환한다. UNIQUE 충돌은 롤백 후 이미 생성된 결과·작업을 재조회한다.

모델 설정 자체가 없으면 신규 모델을 식별할 수 없으므로 POST는 503이다. 결과 목록은 계속 제공한다. 잠금 대기는 응답 예산 내로 제한하고 초과 시 재시도 가능한 503으로 처리한다.

### 6-2. worker 실행

이번 제안은 별도 Redis/Celery 없이 **MySQL 영속 작업 테이블을 별도 worker가 조회하는 방식**이다. 현재 Compose에 MySQL만 있으므로 추가 인프라를 줄이고, 접수 저장과 작업 발행 사이의 유실을 피한다. FastAPI BackgroundTasks만으로 추론을 수행하지 않는다.

1. worker 프로세스 시작 시 `worker/models/`의 선정 모델과 메타데이터를 로드하고 준비 상태를 갱신한다.
2. 짧은 트랜잭션에서 queued 작업을 원자적으로 선점한다. MySQL 8의 `FOR UPDATE SKIP LOCKED` 등을 사용하고 running·임대·claim_token을 기록한 뒤 커밋한다.
3. 접수 시 지정된 모델 버전과 이미지로 추론한다. DB 행 잠금을 잡은 채 추론하지 않는다.
4. 결과 저장 시 환자 → 진료기록 → 작업 순서로 잠그고, 실행권·미취소 여부·현재 이미지 ID가 모두 일치하는지 재검증한다.
5. 정상 결과 INSERT와 작업 completed 전환을 같은 트랜잭션으로 커밋한다. DB UNIQUE 충돌 시 기존 결과에 연결한다.
6. 이미지 교체·삭제 또는 실행권 상실이면 결과를 저장하지 않고 생성한 임시 히트맵을 정리한다.

임대 만료 작업은 제한적으로 재접수한다(제안: 최대 3회). 오래된 실행자는 claim_token이 달라 결과를 커밋할 수 없다. 추론 제한 시간은 초기 60초로 두고 실제 모델 측정 후 조정한다. HTTP 3초와 별개다. 실행 프로세스를 종료·복구할 수 있어야 하며, 단순 async 취소만으로 CPU/GPU 연산 중단을 가정하지 않는다.

### 6-3. 교체·삭제 및 파일 일관성

- 이미지 교체는 기존 정책대로 기존 AI 결과를 삭제하고 파일 정리 작업을 기록한다. 미완료 예측 작업 취소도 같은 트랜잭션에 추가한다.
- 증상·차트 번호만 수정할 때는 이미지가 그대로이므로 기존 결과를 재사용한다.
- 진료기록·환자 삭제 후 worker가 끝나도 결과를 다시 생성하지 않는다.
- 히트맵은 비공개 임시 경로에 생성하고 검증 후 최종 경로로 이동한다. DB 저장 실패·중복 결과·취소 시 새 파일을 삭제하며, 삭제 실패는 기존 `FileCleanupService`로 추적한다.
- 파일 생성 직후 프로세스가 중단되는 경우에 대비해 오래된 임시 파일 및 DB 미참조 파일을 정기 점검한다.

## 7. 모델 학습 전 확정할 연결 규약

`worker/model.py`의 제안 인터페이스:

```python
# 프레임워크·이미지 크기·정규화는 선정 모델의 학습 코드 확인 후 구현한다.
load_model(model_path, metadata) -> LoadedPredictor
predictor.predict(image_path) -> PredictionOutput
# PredictionOutput: pneumonia_probability (0~1), heatmap_relative_path (선택)
```

- 모델은 작업마다 로드하지 않고 **worker 프로세스 시작 시 한 번 메모리에 로드**한다. 프로세스 수만큼 메모리 복제 가능성을 고려한다.
- 입력 해상도·RGB/흑백·정규화·클래스 순서·sigmoid/softmax·임계값을 학습 코드와 동일하게 고정한다. NaN·무한대·범위 밖 점수는 실패 처리한다.
- 새 worker는 담당 모델 버전을 명시하고 해당 버전 작업만 선점한다. 구버전 대기 작업은 해당 worker를 유지해 처리하거나 명시적으로 취소하며, 새 모델로 몰래 대체하지 않는다.
- 손상 이미지 실제 디코딩 실패·픽셀 수 상한 초과를 검사한다. 확장자·서명 검증만으로 정상 이미지를 보장하지 않는다.
- 개발·테스트에서는 같은 인터페이스의 fake predictor를 주입한다. 운영 환경에서는 fake 사용을 차단하고 테스트 결과를 운영 DB에 넣지 않는다.
- 모델 파일은 `worker/models/`에 배치하되 대용량 파일의 Git 추적/LFS 정책은 팀이 정한다. 실제 프레임워크·모델 이름·버전은 학습 완료 후 확정한다.

## 8. 화면 변경

기존 `apis.js` 경로는 유지하고 작업 상태·히트맵 조회 함수를 추가한다.

1. 상세 진입 시 기존 인증된 X-Ray와 결과 목록을 표시한다. 목록 조회 실패가 상세 화면 전체 표시를 막지 않도록 오류를 분리한다.
2. 예측 버튼 클릭 시 중복 클릭을 막는다. 200이면 반환 결과와 목록을 즉시 표시한다.
3. 202이면 “예측 처리 중” 표시 후 상태 URL을 약 1초 간격으로 조회한다. 완료 후 목록을 다시 조회하고, failed·cancelled는 재시도 안내를 표시한다.
4. 화면 이탈 시 조회를 중지한다. 장시간 대기는 간격을 늘리고 수동 새로고침을 제공하며, HTTP 오류와 작업 실패를 구분한다.
5. 결과 표에 기존 수행 일시·폐렴 여부·confidence·모델 외에 **고유 ID·모델 버전·히트맵 링크**를 추가한다. 히트맵이 null이면 “미제공” 표시.
6. X-Ray와 히트맵은 Bearer 토큰을 포함한 fetch → Blob URL로 표시하고, 화면 이탈 시 URL을 해제한다. 페이지 이동으로 이전 결과도 볼 수 있게 한다.

현재 `handlePredict`는 202도 완료로 표시할 수 있으므로 반드시 수정한다.

## 9. 성능·모델 평가

### 9-1. API 3초

3초는 **HTTP 요청부터 응답 완료까지**로 설계한다. 비동기 접수는 추론 완료까지 3초를 보장하지 않는다. 과제의 의미가 버튼 클릭부터 최종 결과 표시까지 3초라면 이 설계만으로 충족되지 않으며 실제 추론 측정·최적화와 팀 합의가 필요하다.

- API 프로세스에서 모델 로딩·추론을 실행하지 않는다. 목록은 인덱스·페이지 크기 상한을 적용한다.
- 준비 상태는 worker의 버전별 heartbeat로 확인하고 오래된 상태는 준비 안 됨으로 취급한다. 허용 heartbeat 간격·대기열 상한은 부하 측정 후 설정한다.
- 제안 검증 조건: 진료기록 1만 건·결과 10만 건, 동시 사용자 20명, 최대 허용 이미지 10MB, 모델 프로세스 메모리 상주 환경. 실제 사용한 CPU/GPU·RAM·DB·네트워크 조건을 보고서에 기록한다.
- 캐시 적중·신규 접수·목록·상태·이미지 API를 각각 측정한다. p95와 최대 응답 시간을 기록하고 **관측된 요청 중 3초 초과가 있으면 미충족**으로 기록한다. p95만으로 충족 판정하지 않는다.
- 추론 시간·대기 시간·실패율도 별도 측정한다. 아직 성능 통과를 주장하지 않는다.

### 9-2. 모델 평가

| 항목 | 정의·기준 |
|---|---|
| TP | 폐렴 환자를 폐렴으로 예측 |
| FP | 정상인을 폐렴으로 예측 |
| FN | 폐렴 환자를 정상으로 예측. 특히 줄여야 하는 오류 |
| TN | 정상인을 정상으로 예측 |
| Recall | TP / (TP + FN), 최소 0.90, 목표 0.90~0.95 이상 |
| Accuracy | (TP + TN) / 전체 표본 수, 목표 0.80~0.90. 최소 통과 기준 팀 확정 |

환자 단위로 학습·검증·테스트를 분리해 누수를 막는다. 임계값은 검증 세트에서 정하고, 고정된 모델·전처리·임계값으로 별도 테스트 세트를 한 번 평가한다. 혼동행렬·클래스별 표본 수·데이터 출처·모델 버전·임계값·지표를 기록한다. 분모가 0인 지표는 0이나 통과로 임의 처리하지 않고 평가 불가로 기록한다. mock으로는 이 기준을 검증할 수 없다.

## 10. 구현 파일과 진행 순서

| 대상 | 예정 작업 |
|---|---|
| `app/apis/prediction_apis.py` | 예측 요청·목록·작업·히트맵 라우터 |
| `app/schemas/prediction.py` | 결과·작업·200/202 응답 스키마 |
| `app/services/prediction_service.py` | 권한 이후 업무 검증, 캐시·접수·중복 처리 |
| `app/repositories/prediction_repository.py` | 결과·작업 조회와 원자적 선점·저장 |
| `app/models/ai_analysis_result.py`, 신규 작업 모델 | 결과 확장·작업 모델 및 관계 |
| `app/models/__init__.py`, Alembic 신규 리비전 | 모델 등록·스키마 이관 |
| `app/services/medical_record_service.py` 등 기존 교체·삭제 경로 | 작업 취소·잠금·파일 정리 연동 |
| `app/main.py`, `app/core/config.py` | 라우터 등록, 활성 모델·worker 설정 |
| `worker/model.py`, `worker/models/`, `worker/main.py` | 모델 상주 로딩·추론·작업 실행 루프 |
| `docker-compose.yml`, 의존성 파일 | worker 서비스 및 모델 프레임워크 추가. API·worker가 동일 X-Ray·히트맵 저장소를 공유하도록 명시적 볼륨 설정 |
| `static/apis.js`, `static/pages.js` | 202 처리·상태 조회·결과 필드·페이지 이동·인증 히트맵 |
| `tests/` | fake 기반 API·동시성 검증, 실제 모델 평가·성능 검증 분리 |

**모델 준비 전:** 팀 명세 검토 → DB·API·worker 골격 → fake를 이용한 계약·저장·재사용·실패 처리 검증.

**모델 준비 후:** 선정 파일 배치 → 전처리·출력 매핑 확정 → 실제 추론 연결 → 모델 평가·HTTP 및 추론 시간 측정 → 팀 코드 리뷰.

## 11. 검증 시나리오

| 구분 | 시나리오 | 기대 결과 |
|---|---|---|
| 권한 | 의료·개발·연구 staff, admin | 모든 예측 관련 API 접근 가능 |
| 권한 | 무토큰 / pending·비활성 | 401 / 403 |
| 입력 | 없는 기록·잘못된 ID·잘못된 페이지 | 404 / 422 / 422 |
| 접수 | 모델 준비 전, 완료 결과 없음 | 503, 가짜 결과 저장 없음 |
| 재사용 | 동일 이미지·버전 결과 존재, worker 중단 | 200, 추론 호출 0회 |
| 접수 | 최초 예측 | 202, 작업 커밋 후 상태 URL 제공 |
| 동시성 | 같은 기록에 동시 POST | 진행 작업 1개, 완료 결과 1개 |
| 버전 | 동일 이미지에 새 모델 버전 활성화 | 새 작업 생성, 이전 결과는 목록 보존 |
| 목록 | 결과 없음·다수·동일 시각 결과 | [] / 페이지 이동·전체 개수 / ID로 안정적 정렬 |
| 격리 | 다른 기록의 작업·결과 ID 지정 | 404 |
| 결과 | true/false, 경계 점수·임계값·반올림 | 계약에 맞는 bool·백분율 |
| 오류 | NaN·손상 이미지·추론 예외·시간 초과 | failed, 실패 코드 제공, 완료 결과 없음 |
| 교체 | 추론 중 이미지 교체 | 이전 작업 취소, 이전 결과·히트맵 무효화, 새 이미지로 재접수 |
| 삭제 | 추론 중 기록·환자 삭제 | 작업·결과 재생성 없음, 생성 파일 정리 |
| 수정 | 증상만 수정 | 기존 이미지 결과 유지 |
| 복구 | worker 중단·임대 만료·중복 실행 | 제한 재처리, 이전 실행권의 저장 차단 |
| 파일 | 히트맵 없음·인증 누락·경로 이탈 | null / 401 / 안전한 실패, 내부 경로 비노출 |
| 트랜잭션 | 결과 커밋 실패·파일 삭제 실패 | 완료 표시 없음, 파일 정리 또는 재처리 작업 추적 |
| 화면 | POST 202 후 완료·실패·화면 이탈 | 접수 안내·목록 갱신·실패 안내·조회 중지 |
| 비기능 | 실제 모델 및 부하 테스트 | 9절 기준으로 측정하고 근거 기록 |

## 12. 팀 검토 및 완료 조건

아래는 합의 완료 사항이 아닌 검토 항목이다.

- [ ] 모델 파일·프레임워크·입력 크기·클래스 매핑·버전·임계값 확정
- [ ] confidence 의미와 백분율 표기 공유
- [ ] 3초의 의미(HTTP 응답 또는 최종 예측 완료)와 비동기 처리 합의
- [ ] MySQL 작업 테이블 방식·worker 임대·재시도·준비 상태·공유 저장소 검토
- [ ] 기존 결과 이관과 이미지 교체 시 결과 삭제 정책 확인
- [ ] Accuracy 최소 기준, 평가 데이터 및 부하 조건 확정
- [ ] 팀원 전체가 캐시 적중·신규 추론·실패·이미지 교체 흐름을 설명하고 명세 리뷰
- [ ] 설계 문서 PR 작성·리뷰 후 과제 요구대로 main에 병합
- [ ] 실제 구현·모델 연결 후 기능·성능·평가 검증 결과를 별도 기록

문서 브랜치를 만들었다고 main에 병합된 것은 아니다. 1번 모델 학습 없이도 이 문서와 fake 기반 구현은 진행 가능하지만, 실제 모델의 추론·평가 완료는 모델 준비 이후에 확인한다.
