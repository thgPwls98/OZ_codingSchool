# 6일차 AI 폐렴 예측 API 설계

| 항목 | 내용 |
|---|---|
| 문서 목적 | AI 폐렴 예측 요구사항을 분석하고, 구현 전에 예측 코드 인터페이스·API 명세·설계 결정을 확정한다 |
| 근거 자료 | 6일차 AI 폐렴 예측 사용자 요구사항 정의서, 프론트엔드 코드(`static/apis.js`, `static/pages.js`, `static/templates/record-detail.html`), 1단계 코드(`feature/pneumonia-model` 브랜치 `worker/model.py`, README 실행 검증), 1단계 실제 X-Ray 추론 측정(최현영), 현재 모델(`app/models/ai_analysis_result.py`), 5일차 진료기록 수정·삭제 코드 |
| 대상 요구사항 | REQ-PRED-001, REQ-PRED-002, NFR-PRED-001, NFR-PRED-002 |
| 선행 작업 | 4일차 JWT 인증, 5일차 진료기록·X-Ray 비공개 저장(`resolve_xray_path`), 잠금 순서(환자 → 진료기록), 파일 정리 작업(`FileCleanupService`), 6일차 1단계 `worker/model.py` |
| 설계 원칙 | ① 기존 화면·DB·권한 체계와 호환 ② 같은 진료기록·같은 모델은 한 번만 추론 ③ 1단계 예측 코드와 API 코드를 인터페이스로 분리 ④ 폐렴을 놓치지 않는 모델(Recall 우선) ⑤ 모든 API 3초 이내 |
| 작성 방식 | 팀원 5명의 설계안을 비교해 통합 (16절) |
| 번호 표기 | `D1`~`D17`은 **이 문서**의 설계 결정(11절)이다. 5일차 설계 문서의 결정은 **`5일차 문서 D○`**로 구분해 적는다 |

## 목차
1. [요구사항 분석](#1-요구사항-분석)
2. [공통 규칙](#2-공통-규칙)
3. [API 목록과 요구사항 추적](#3-api-목록과-요구사항-추적)
4. [API 상세](#4-api-상세)
5. [1단계 예측 모듈 인터페이스](#5-1단계-예측-모듈-인터페이스)
6. [주요 처리 흐름](#6-주요-처리-흐름)
7. [DB 변경 사항](#7-db-변경-사항)
8. [보안 설계](#8-보안-설계)
9. [성능 설계](#9-성능-설계)
10. [모델 평가 기준](#10-모델-평가-기준)
11. [설계 결정 기록](#11-설계-결정-기록)
12. [현재 코드에서 변경할 사항과 구현 구조](#12-현재-코드에서-변경할-사항과-구현-구조)
13. [테스트 시나리오](#13-테스트-시나리오)
14. [팀 결정이 필요한 사항](#14-팀-결정이-필요한-사항)
15. [향후 개선 과제](#15-향후-개선-과제)
16. [설계안 통합 기록](#16-설계안-통합-기록)
17. [팀 이해 확인 체크리스트](#17-팀-이해-확인-체크리스트)
18. [팀 기여도](#18-팀-기여도)

---

## 1. 요구사항 분석

### 1-1. 요구사항 요약

| ID | 기능 | 행위자 | 입력 | 출력 | 특이사항 |
|---|---|---|---|---|---|
| REQ-PRED-001 | AI 폐렴 예측 | 의료인·개발팀·연구자 | 진료기록 ID (`AI 예측 결과보기` 버튼) | 폐렴 여부, Confidence, 히트맵 URL(선택) | **진료기록 등록 시 업로드한 X-Ray 사용**, 같은 기록·같은 모델 결과가 있으면 **재추론 없이** 저장된 결과 응답 |
| REQ-PRED-002 | 예측 결과 목록 | 의료인·개발팀·연구자 | 진료기록 ID | 고유 ID, 폐렴 여부, Confidence, 히트맵 URL, 예측 수행 일시, 사용한 모델 | 진료기록 상세 화면의 AI 예측 결과 섹션. 정의서는 "**해당 환자의** X-Ray와 예측 결과 목록"이지만 이번 구현은 **진료기록 단위** (1-5절, Q7) |
| NFR-PRED-001 | 모델 평가 기준 | - | - | - | **Recall ≥ 0.90** (최소, 목표 0.95), Accuracy ≥ 0.80 (보조) |
| NFR-PRED-002 | 성능 | - | - | - | 모든 API 3초 이내 |

### 1-2. 행위자와 권한

정의서는 두 기능 모두 행위자를 "사내 **의료인, 개발팀, 연구자** 권한을 가진 유저"로 적었다. 즉 **이 세 부서만** 허용해야 한다.

**확인 결과**: `app/models/enums.py`의 `Department` Enum 값은 `research`·`medical`·`development` **세 개뿐**이다. 세 부서 = 모든 staff이므로 부서 조건을 따로 걸 필요 없이 5일차 `StaffUser`(`role ∈ {staff, admin}`, 비활성 계정 차단)를 재사용한다.

> 나중에 다른 부서 값(원무·행정 등)이 추가되면 `StaffUser`만으로는 요구사항보다 권한이 넓어진다. 그때 세 부서와 관리자만 통과시키는 의존성을 `core/dependencies.py`에 추가한다 (15절 F9).

| 행위자 | role / department | 예측 ⑫ | 목록 ⑬ | 히트맵 ⑭ |
|---|---|---|---|---|
| 의료진 | staff / medical | ✅ | ✅ | ✅ |
| 개발팀 | staff / development | ✅ | ✅ | ✅ |
| 연구진 | staff / research | ✅ | ✅ | ✅ |
| 관리자 | admin | ✅ (Q8) | ✅ (Q8) | ✅ (Q8) |
| 대기자·비활성 계정 | pending / - | ❌ 403 | ❌ 403 | ❌ 403 |
| 비로그인 | - | ❌ 401 | ❌ 401 | ❌ 401 |

- **관리자 포함 근거**: 정의서에 관리자는 명시되지 않았다. 5일차 조회 API가 모두 관리자를 허용하고, 운영 중 장애 확인에 필요해 포함한다. 팀 확인 항목으로 둔다 (14절 Q8).
- 예측은 결과 행을 **생성**하지만, 진료 데이터를 바꾸지 않고 이미 등록된 이미지를 판독만 한다. 정의서가 세 부서 모두를 행위자로 적었으므로 진료기록 등록(`MedicalStaffUser`)처럼 의료진으로 제한하지 않는다 (D3).
- 이하 문서의 "스태프 이상"은 위 표에서 ✅인 행위자를 뜻한다.

### 1-3. 데이터 모델 분석

```text
patients (환자)
 └─(1:N)─ medical_records (진료기록)
           ├─(1:N)─ xray_images (X-Ray, API는 기록당 1장 운영 - 5일차 문서 D15)
           └─(1:N)─ ai_analysis_results (AI 판독 결과)  ← 이번 작업 대상
```

**`ai_analysis_results` 현재 구조 (3일차 생성)**

| 컬럼 | 타입 | 제약 | 요구사항 대응 |
|---|---|---|---|
| `id` | BIGINT | PK | 고유 ID |
| `record_id` | BIGINT | FK → `medical_records.id`, `ON DELETE CASCADE` | 어느 진료기록의 결과인지 |
| `is_pneumonia` | BOOLEAN | NOT NULL | 폐렴 여부 |
| `confidence` | NUMERIC(5,2) | NOT NULL | Confidence (%, 예: `91.50`) |
| `heatmap_url` | VARCHAR(255) | **NOT NULL** | 히트맵 URL (**요구사항은 선택사항**) |
| `ai_model` | VARCHAR(50) | NOT NULL | 사용한 모델 |
| `created_at` / `updated_at` | DATETIME (UTC) | `TimestampMixin` | 예측 수행 일시 |

| 요구사항 | 현재 모델 | 차이와 조치 |
|---|---|---|
| 히트맵 URL **선택사항** | `heatmap_url` NOT NULL | 히트맵을 만들지 않으면 저장 시 DB 오류 → **nullable로 변경** (D4) |
| 같은 기록·같은 모델은 한 번만 추론 | 중복 방지 제약 없음 | 동시에 두 번 누르면 결과가 2건 생길 수 있음 → **UNIQUE 제약 추가** (D6) |
| "같은 모델"의 판단 | 모델 이름만 있음 | 같은 이름으로 가중치·임계값만 바꾸면 이전 결과가 재사용됨 → **`model_version` 컬럼 추가** (D5) |
| 이미지 교체 시 이전 결과 무효 | 5일차 구현 완료 | 진료기록 수정에서 이미지 교체 시 AI 결과 행·히트맵 파일 삭제. 추가 작업 없음 |
| 환자·진료기록 삭제 시 결과 삭제 | 5일차 구현 완료 | DB `CASCADE` + 히트맵 파일 정리. 정리 코드가 빈 `heatmap_url`을 건너뛴다(`if path`) → NULL 허용에도 수정 불필요 |

### 1-4. 프론트엔드 계약 분석

저장소에 AI 예측 화면과 호출 코드가 **이미 있다**. API는 화면이 호출하는 형식을 따른다 (D1).

| 화면 동작 | 호출 (`static/apis.js`) | 화면이 사용하는 응답 |
|---|---|---|
| `AI 예측 결과보기` 버튼 (`handlePredict`) | `POST /medical-records/{recordId}/predict` (본문 없음) | 없음. 성공(`response.ok`)하면 알림 후 상세 화면을 다시 그림 |
| 상세 화면 진입 (`renderRecordDetail`) | `GET /medical-records/{recordId}/analyses` | **배열**의 `created_at`, `is_pneumonia`, `confidence`, `ai_model` |

- 상세 화면은 진입할 때마다 `/analyses`를 호출한다. **이 API가 없으면 지금 진료기록 상세 화면 자체가 열리지 않는다** → 결과가 없어도 `200 []`을 반환한다.
- 화면은 `analyses.length`, `analyses.map`을 쓴다 → 응답은 **배열**이다.
- 화면은 `` `${a.confidence}%` ``로 표시한다 → `confidence`는 **0~100 숫자**로 응답한다.
- 오류는 `error.detail`을 읽어 `AI 예측 실패: {detail}`로 표시한다 → 오류 형식은 `{"detail": "메시지"}`를 유지한다.
- `201`과 `200`은 모두 `response.ok`이므로 화면 수정 없이 성공 처리된다.

### 1-5. REQ-PRED-002 목록 범위

정의서 원문은 "진료기록 상세 페이지의 AI 예측 결과 섹션에서 **해당 환자의** 흉부 X-Ray 사진과 예측 결과를 목록으로"이다.

| 해석 | 목록에 나오는 것 | 결과 수 |
|---|---|---|
| (a) 진료기록 단위 | **지금 보고 있는 진료기록**의 예측 결과 | 사용한 모델 버전 수 (보통 1건) |
| (b) 환자 단위 | 이 환자의 **모든 진료기록** X-Ray와 각 예측 결과 | 환자의 진료기록 수 × 모델 버전 수 |

**이번 구현은 (a)로 한다.**

- 프론트엔드가 이미 진료기록 단위 경로(`/medical-records/{id}/analyses`)를 호출한다 (D1).
- 진료기록 상세 페이지 안의 섹션이므로 그 기록의 결과를 보여주는 것이 화면 흐름에 맞다.
- (a)는 결과가 대부분 1건이라 "목록"의 의미가 약하다는 한계가 있다. 정의서 의도가 (b)라면 환자 단위 API를 **추가**해서 해결한다 (15절 F8). 기존 경로는 그대로 둔다.
- 이 해석은 **팀 합의가 필요하다** (14절 Q7). 합의 결과를 Q7에 기록한다.

---

## 2. 공통 규칙

### 2-1. 기본 규칙

5일차 2-1절 규칙(기본 경로 `/api/v1`, Bearer 인증, `{"detail": "메시지"}` 오류, UTC 저장·ISO 8601 `Z` 응답, 개인정보 로그 금지)을 그대로 따른다. 이번에 추가하는 규칙은 다음과 같다.

| 항목 | 규칙 |
|---|---|
| 요청 본문 | 없음. 예측에 쓸 이미지는 서버가 진료기록의 최신 X-Ray를 찾아 사용한다 |
| 사용 모델 | 서버에 올라간 현재 모델 하나 (`MODEL_NAME`, `MODEL_VERSION`). 요청으로 모델을 고르지 않는다 |
| Confidence | **판정한 클래스의 확률**을 0~100(%)으로, 소수 둘째 자리. JSON **숫자** |
| 히트맵 URL | 파일 위치가 아니라 **조회 API 경로**(`/api/v1/medical-records/{record_id}/analyses/{analysis_id}/heatmap`), 없으면 `null` |
| 경로 변수 | `record_id`, `analysis_id`는 1 이상 정수 (`Path(ge=1)`), 위반 시 422 |
| 로그 | 환자 이름·증상·이미지 경로·예측 결과를 남기지 않는다. 진료기록·이미지·결과 ID와 예외 종류만 기록 |

### 2-2. 응답 스키마 `AnalysisResultResponse` (예측·목록 공통)

| 필드 | 타입 | 설명 | 정의서 항목 |
|---|---|---|---|
| id | integer | 예측 결과 고유 ID | 고유 ID |
| record_id | integer | 진료기록 ID | |
| is_pneumonia | boolean | 폐렴 여부 | 폐렴 여부 |
| confidence | number | 판정한 클래스의 확률(%), 예: `83.28` | Confidence |
| heatmap_url | string \| null | 히트맵 조회 API 경로. 히트맵이 없으면 `null` | Hitmap Image URL |
| ai_model | string | 모델 이름 (화면 표시용) | 사용한 모델 |
| model_version | string | 모델 버전 (가중치·전처리·임계값 식별) | 사용한 모델 |
| created_at | datetime | 예측 수행 일시 (UTC `Z`) | 예측 수행 일시 |

```json
{
  "id": 12,
  "record_id": 1,
  "is_pneumonia": false,
  "confidence": 83.28,
  "heatmap_url": null,
  "ai_model": "efficientnet_b0_5fold",
  "model_version": "v1",
  "created_at": "2026-10-28T06:20:00Z"
}
```

**`confidence` 직렬화**: DB의 `NUMERIC`은 파이썬 `Decimal`이 되고, Pydantic v2는 `Decimal`을 JSON **문자열**(`"83.28"`)로 내보낸다. 화면 계산·정렬과 테스트를 위해 숫자로 바꾼다 (D10).

```python
class AnalysisResultResponse(BaseModel):
    id: int
    record_id: int
    is_pneumonia: bool
    confidence: Decimal
    heatmap_url: str | None
    ai_model: str
    model_version: str
    created_at: UTCDateTime

    @field_serializer("confidence")
    def _confidence(self, value: Decimal) -> float:
        return float(round(value, 2))
```

> `heatmap_url`은 DB에 저장 폴더 기준 상대 경로로 저장하고, 응답할 때 조회 API 경로로 바꾼다. 따라서 서비스에서 변환 함수(`to_analysis_response`)를 거쳐 스키마를 만든다.

### 2-3. Confidence 계산 규칙

모델 출력에서 폐렴 확률 `p`(0~1)를 얻었을 때:

| 판정 | 조건 | confidence |
|---|---|---|
| 폐렴 | `p > threshold` | `p × 100` |
| 정상 | `p ≤ threshold` | `(1 − p) × 100` |

팀 모델의 threshold는 **0.4**다 (`worker/model.py`의 `THRESHOLD = 0.40000000000000013`, 학습 시 OOF에서 탐색한 값). 비교는 **초과(`>`)** 다.

| 폐렴 확률 p | is_pneumonia | confidence | 비고 |
|---|---|---|---|
| 0.87 | true | 87.00 | |
| 0.167 | false | 83.30 | 실제 X-Ray 테스트 결과 (9절) |
| 0.40 | false | 60.00 | 경계값은 정상 (`>` 비교) |
| 0.45 | true | **45.00** | 폐렴 판정인데 confidence 50% 미만 |

- 판정은 **반올림 전** 확률로 한다.
- threshold가 0.5보다 낮아서 p가 0.4~0.5인 경우 "폐렴 판정인데 confidence가 50% 미만"인 결과가 나온다. 화면에서 이런 결과에 "확신도 낮음, 의료진 확인 필요"를 표시하는 것을 권장한다 (14절 Q5).
- confidence는 **모델 점수**이며 임상적 확실성을 뜻하지 않는다.
- 이 계산은 1단계 예측 모듈이 하고, API는 받은 값을 저장만 한다 (5절).

### 2-4. 오류 코드

| 코드 | 상황 | detail | 다시 시도하면? |
|---|---|---|---|
| 401 | 토큰 없음·만료·위조 | `인증 정보가 유효하지 않습니다.` | 로그인 후 가능 |
| 403 | 대기자·비활성 계정 | `접근 권한이 없습니다.` | |
| 404 | 진료기록 없음 (추론 중 삭제 포함) | `진료기록을 찾을 수 없습니다.` | |
| 404 | X-Ray 행·파일 없음, 저장 폴더 밖 경로 | `이미지 파일을 찾을 수 없습니다.` | |
| 404 | 예측 결과·히트맵 없음, 다른 기록 소속 | `예측 결과를 찾을 수 없습니다.` / `히트맵 이미지가 없습니다.` | |
| 409 | 추론하는 사이 X-Ray가 교체됨 | `X-Ray 이미지가 변경되었습니다. 다시 시도해주세요.` | ✅ 새 이미지로 예측 |
| 422 | 경로 변수 형식 오류 (`record_id=abc`, `0`) | FastAPI 기본 검증 오류 | |
| 422 | 저장된 파일이 이미지로 읽히지 않음 | `예측할 수 없는 이미지입니다.` | ❌ 같은 결과 (이미지 교체 필요) |
| 500 | 추론 중 예외, 비정상 출력(NaN 등), DB·저장소 실패 | `잠시 후 다시 시도해주세요.` | ✅ |
| 503 | 모델이 메모리에 없음 (파일 없음·손상) | `AI 예측 기능을 사용할 수 없습니다.` | 운영자 조치 후 |

> 손상 이미지를 500이 아니라 422로 구분하는 이유: 일시 오류(500)와 달리 **다시 시도해도 같은 결과**라서, 화면과 운영자가 "이미지를 다시 올려야 한다"고 판단할 수 있다 (D9).

---

## 3. API 목록과 요구사항 추적

번호는 5일차 API ①~⑪에 이어서 매긴다.

| No | Method | 경로 | 기능 | 요구사항 | 권한 | 성공 |
|---|---|---|---|---|---|---|
| ⑫ | POST | `/api/v1/medical-records/{record_id}/predict` | 폐렴 예측 (저장된 결과가 있으면 재사용) | REQ-PRED-001 | 스태프 이상 (1-2절) | 201 신규 / 200 재사용 |
| ⑬ | GET | `/api/v1/medical-records/{record_id}/analyses` | 예측 결과 목록 (진료기록 단위, 1-5절) | REQ-PRED-002 | 스태프 이상 (1-2절) | 200 |
| ⑭ | GET | `/api/v1/medical-records/{record_id}/analyses/{analysis_id}/heatmap` | 히트맵 이미지 조회 (선택) | REQ-PRED-001·002 히트맵 URL | 스태프 이상 (1-2절) | 200 (이미지) |

- ⑫⑬의 경로는 프론트엔드 코드에 이미 정해져 있다 (1-4절).
- ⑭는 히트맵을 만들기로 결정한 경우에만 구현한다 (14절 Q1). 5일차 X-Ray 조회(⑨)와 같은 방식이다.
- NFR-PRED-001은 10절, NFR-PRED-002는 9절에서 다룬다.

---

## 4. API 상세

### 4-1. ⑫ 폐렴 예측 `POST /api/v1/medical-records/{record_id}/predict`

| 항목 | 내용 |
|---|---|
| 요구사항 | REQ-PRED-001 |
| 권한 | 스태프 이상 (`StaffUser`, 1-2절) |
| 요청 본문 | 없음 |

**처리 규칙**
1. 진료기록이 없으면 404.
2. 이 진료기록에 **현재 모델(`MODEL_NAME` + `MODEL_VERSION`)로 저장된 결과가 있으면** 추론하지 않고 `200`으로 응답한다. 모델이 없어도(503 상황) 저장된 결과는 응답한다.
3. 없으면 진료기록의 X-Ray로 추론하고, 결과를 저장한 뒤 `201`로 응답한다.
4. 모델 버전이 바뀌면 같은 진료기록이라도 다시 추론한다. 이전 버전 결과는 지우지 않고 목록에 이력으로 남는다.

**요청 예**
```http
POST /api/v1/medical-records/1/predict
Authorization: Bearer eyJhbGciOi...
```

**응답 `201 Created`** (새로 추론)
```http
HTTP/1.1 201 Created
Location: /api/v1/medical-records/1/analyses

{"id": 12, "record_id": 1, "is_pneumonia": false, "confidence": 83.28, "heatmap_url": null,
 "ai_model": "efficientnet_b0_5fold", "model_version": "v1", "created_at": "2026-10-28T06:20:00Z"}
```

**응답 `200 OK`** (저장된 결과 재사용, **추론 함수 호출 0회**): 같은 형식

| 실패 | 상황 |
|---|---|
| 403 | 대기자·비활성 계정 |
| 404 | 진료기록 없음, X-Ray 행·파일 없음 |
| 409 | 추론하는 동안 이미지 교체 (6-1절) |
| 422 | `record_id` 형식 오류, 이미지로 읽히지 않는 파일 |
| 500 | 추론 중 예외, 비정상 출력, 저장 실패 |
| 503 | 모델 미로드 (저장된 결과가 없을 때만) |

> 재사용되는 결과는 항상 **현재 이미지**의 결과다. 이미지를 교체하면 5일차 ⑩이 기존 AI 결과를 지우기 때문이다 (6-3절).

### 4-2. ⑬ 예측 결과 목록 `GET /api/v1/medical-records/{record_id}/analyses`

| 항목 | 내용 |
|---|---|
| 요구사항 | REQ-PRED-002 |
| 권한 | 스태프 이상 (1-2절) |
| 범위 | **현재 진료기록**의 결과 (환자 전체가 아님, 1-5절·Q7) |
| 정렬 | 최신순 (`created_at DESC, id DESC`) |
| 페이지네이션 | 없음. 기록·모델 버전당 결과가 1건이라 결과 수는 사용한 모델 버전 수만큼이다 |

**응답 `200 OK`**: `AnalysisResultResponse` **배열**
```json
[
  {"id": 15, "record_id": 1, "is_pneumonia": true, "confidence": 93.41, "heatmap_url": null,
   "ai_model": "efficientnet_b0_5fold", "model_version": "v2", "created_at": "2026-10-29T02:10:00Z"},
  {"id": 12, "record_id": 1, "is_pneumonia": false, "confidence": 83.28, "heatmap_url": null,
   "ai_model": "efficientnet_b0_5fold", "model_version": "v1", "created_at": "2026-10-28T06:20:00Z"}
]
```

| 상황 | 응답 |
|---|---|
| 결과 없음 | `200 []` → 화면 "저장된 예측 결과가 없습니다." |
| 진료기록 없음 | `404 진료기록을 찾을 수 없습니다.` |
| 대기자·비활성 계정 | 403 |

- 목록 조회는 **추론하지 않고** 모델 상태와 무관하게 동작한다.
- 정의서의 "흉부 X-Ray 사진"은 같은 화면이 이미 ⑨ 이미지 API(Blob)로 표시하므로 응답에 다시 담지 않는다.
- Q7에서 환자 단위(b)로 결정되면 이 API는 그대로 두고 환자 단위 목록 API를 추가한다 (F8).

### 4-3. ⑭ 히트맵 이미지 조회 `GET /api/v1/medical-records/{record_id}/analyses/{analysis_id}/heatmap` (선택)

| 항목 | 내용 |
|---|---|
| 권한 | 스태프 이상 (1-2절) |
| 응답 | `image/png` 바이너리 |
| 응답 헤더 | `Content-Disposition: inline`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff` (⑨와 동일) |

| 실패 | 상황 |
|---|---|
| 404 | 진료기록·결과 없음, **결과가 다른 진료기록 소속**, 히트맵 `null`, 파일 없음, 저장 폴더 밖 경로 |

- `analysis_id`만으로 찾지 않고 `record_id`와 **함께** 조건을 건다. 다른 기록의 결과 ID로 조회하는 것을 막는다.
- 경로는 `resolve_stored_path(FILE_KIND_HEATMAP, ...)`로 검증한다.
- 화면은 X-Ray와 같은 방식(`fetch` + Blob)으로 표시한다.

---

## 5. 1단계 예측 모듈 인터페이스

1단계(`worker/model.py`)와 3단계(API)는 **아래 약속만 지키면 서로의 내부 구현을 몰라도 된다.** 1단계 코드는 `feature/pneumonia-model` 브랜치에 올라와 있으며, 이 절은 그 코드를 기준으로 한다.

### 5-1. 1단계가 제공하는 것 (현재 코드)

```python
# worker/model.py
THRESHOLD = 0.40000000000000013      # 폐렴 판정 기준 (p > THRESHOLD 이면 폐렴)


@dataclass(frozen=True)
class PredictionOutput:
    pneumonia_probability: float           # 폐렴 확률 0~1 (5개 모델 평균, DB에는 저장하지 않음)
    is_pneumonia: bool                     # 폐렴 여부
    confidence: float                      # 판정한 클래스의 확률, 0~100, 소수 둘째 자리 (2-3절)
    heatmap_relative_path: str | None = None   # 히트맵 미구현 → 항상 None (Q1)


def load_model(model_path=DEFAULT_MODEL_DIR, *, device="cpu") -> LoadedPredictor:
    """5개 가중치를 읽어 예측기를 만든다. 파일이 하나라도 없으면 FileNotFoundError."""

class LoadedPredictor:
    def predict(self, image_path) -> PredictionOutput:
        """X-Ray 1장을 전처리·추론한다. 동기 함수이며 API는 스레드풀에서 호출한다."""

def get_predictor() -> LoadedPredictor:          # lru_cache로 1회만 로딩
def predict_pneumonia(image) -> PredictionOutput: # get_predictor().predict(image)
```

### 5-2. 3단계 시작 전에 1단계에 추가할 것

| 추가 | 내용 | 이유 |
|---|---|---|
| 모델 이름·버전 상수 | `MODEL_NAME = "efficientnet_b0_5fold"`, `MODEL_VERSION = "v1"` (값은 Q2에서 확정) | `ai_analysis_results.ai_model`, `model_version`에 저장하고 재사용 판단 기준으로 쓴다 (D5) |
| 예외 구분 | 이미지 디코딩 실패(`PIL.UnidentifiedImageError`, `OSError`)는 `ValueError`로 감싸서 올린다. 모델 출력 NaN·범위 밖은 `ValueError`가 아니라 **`RuntimeError`** 로 바꾼다 | 지금은 손상 이미지가 `OSError`라 500이 되고, NaN 출력이 `ValueError`라 422가 된다. 2-4절의 422(이미지 문제)와 500(일시 오류) 구분이 뒤바뀐다 (D9) |
| 의존성 | `uv add timm torchvision torch`로 `pyproject.toml`·`uv.lock`에 추가 | 지금은 `worker/requirements.txt`에만 있어 `uv sync`로 설치되지 않는다 |

추가 후 3단계가 기대하는 예외는 다음과 같다.

| 예외 | 상황 | API 응답 |
|---|---|---|
| `FileNotFoundError` | 이미지 파일 없음 | 404 |
| `ValueError` | 이미지가 아니거나 손상, 2,500만 픽셀 초과 | 422 |
| `RuntimeError`, 그 밖의 예외 | 모델 출력 이상, 추론 실패 | 500 |

### 5-3. 3단계가 1단계 코드를 쓰는 방법

| 3단계에서 필요한 것 | 1단계 코드로 하는 방법 |
|---|---|
| 서버 시작 시 1회 로딩 | `lifespan`에서 `load_model()`을 호출해 반환된 예측기를 `app.state.predictor`에 둔다 (6-2절) |
| 모델 로드 여부 확인 (`is_loaded`) | `app.state.predictor is not None` |
| 추론 | `run_in_threadpool(predictor.predict, path)` |
| 테스트용 가짜 모델 | `predict()`가 있는 가짜 객체를 `app.state.predictor`에 넣는다 |

- `predict`는 **DB 접근과 파일 저장을 하지 않는다.** 경로를 받아 결과만 돌려준다.
- 히트맵은 구현하지 않으므로(Q1) API는 `heatmap_url`을 항상 `null`로 저장한다. 나중에 히트맵을 추가하면 1단계가 `Image` 객체를 돌려주고, 저장 위치(`storage/heatmap/...`)와 파일 정리는 API 쪽이 맡는다 (5일차 문서 D18).

### 5-4. 1단계 구현 확인

| 항목 | 1단계 코드 | 이유 |
|---|---|---|
| 저장 방식 | **`state_dict`(가중치만)** + 모델 클래스(`PneumoniaClassifier`)를 `model.py`에 정의 | 모델을 통째로 저장하면 학습 노트북의 클래스를 참조해 서버에서 불러올 수 없다 |
| 안전한 로딩 | `torch.load(..., map_location="cpu", weights_only=True)` | 가중치 외 객체를 실행하지 않음. GPU에서 저장된 가중치도 CPU로 불러옴 |
| 엄격한 로딩 | `load_state_dict(strict=True)` | 구조가 다르면 즉시 에러 → 잘못된 구조로 조용히 예측하는 것 방지 |
| 중복 로딩 방지 | `get_predictor()`에 `lru_cache(maxsize=1)` | 여러 번 호출해도 메모리에 1개 |
| 추론 모드 | `model.eval()` + `torch.inference_mode()` | 학습용 동작을 끄고, 기울기 계산을 꺼서 빠르고 메모리를 덜 씀 |
| 출력 검증 | NaN·무한대·0~1 범위 밖이면 예외 (5-2절에서 `RuntimeError`로 변경) | 비정상 결과를 저장하지 않음 |
| 큰 이미지 차단 | 2,500만 픽셀 초과 시 `ValueError` | 메모리 고갈 방지 |

### 5-5. 팀 모델 설정값

| 설정 | 값 |
|---|---|
| 구조 | EfficientNet-B0 (`timm`, `num_classes=2`) **5-fold 앙상블**. 5개 모델의 폐렴 확률을 평균 |
| 가중치 | `worker/models/best_model_fold0.pt` ~ `best_model_fold4.pt` (Git 제외, ZIP으로 별도 공유 - Q3) |
| 입력 | RGB 3채널, 224×224 리사이즈 |
| 정규화 | ImageNet (mean `[0.485, 0.456, 0.406]`, std `[0.229, 0.224, 0.225]`) |
| 클래스 순서 | 0 = NORMAL, 1 = PNEUMONIA (softmax 클래스 1이 폐렴 확률) |
| threshold | 0.4, 초과(`>`)면 폐렴 |
| `MODEL_NAME` / `MODEL_VERSION` | `efficientnet_b0_5fold` / `v1` (제안, Q2에서 확정) |
| 1장 추론 시간 | 평균 1.31초, 최대 1.46초 (맥북 CPU, 9절) |
| 모델 로딩 시간 | 17.5초 (서버 시작 시 1회, 9절) |
| 학습 버전 | torch 2.11.0, torchvision 0.26.0, timm 1.0.30 |

> 전처리·정규화·클래스 순서가 학습 코드와 다르면 **오류 없이 틀린 결과**가 나온다. 1단계는 Colab 학습 코드와 같은 순서(RGB → 224 리사이즈 → ImageNet 정규화)로 맞췄다. 실제 성능은 T24(테스트셋 평가)로 검증한다.

---

## 6. 주요 처리 흐름

### 6-1. ⑫ 폐렴 예측

```text
[화면] AI 예측 결과보기 클릭
   │ POST /api/v1/medical-records/1/predict
   ▼
[API] 인증·권한 확인 (1-2절) ─────────────────── 실패 → 401 / 403
   ▼
[Service]
   │ ── 1단계: 읽기 (잠금 없음) ──
   ├─ ① 진료기록 조회 → patient_id 기억 ─────────── 없음 → 404
   ├─ ② (record_id, MODEL_NAME, MODEL_VERSION) 결과 조회 ─ 있음 → 200 (추론 생략)
   ├─ ③ 모델 로드 확인 (app.state.predictor) ────── 미로드 → 503
   ├─ ④ 최신 X-Ray 행 조회 → image_id 기억
   │     resolve_xray_path(image_url) ──────────── 행·파일 없음, 폴더 밖 경로 → 404
   ├─ ⑤ 필요한 값(patient_id, image_id, 경로)을 일반 변수로 꺼낸 뒤
   │     읽기 트랜잭션 종료 (db.rollback())        ← 추론 동안 DB 연결·스냅샷을 붙잡지 않음
   │
   │ ── 2단계: 추론 (DB와 무관) ──
   ├─ ⑥ 동시 추론 수 제한(세마포어) 안에서 run_in_threadpool(predict, path)
   │     FileNotFoundError → 404 / ValueError → 422 / RuntimeError·그 밖의 예외 → 500
   ├─ ⑦ (히트맵 구현 시) storage/heatmap/{patient_id}/{uuid}.png 저장. 이번에는 미구현(Q1) → heatmap_url = NULL
   │
   │ ── 3단계: 저장 (잠금) ──
   ├─ ⑧ 환자 잠금 → 진료기록 잠금 (5일차 잠금 순서) ── 진료기록 없음(추론 중 삭제) → 히트맵 삭제, 404
   ├─ ⑨ 현재 X-Ray image_id를 다시 조회 ──────── ④와 다름(추론 중 교체) → 히트맵 삭제, 409
   ├─ ⑩ ai_analysis_results INSERT → commit → refresh
   │     └─ UNIQUE 위반 (동시 요청이 먼저 저장)
   │           → rollback, 히트맵 삭제, 먼저 저장된 결과 → 200
   └─ ⑪ 201 + 새 결과
   ▼
[화면] "AI 예측이 완료되었습니다." → 상세 화면 다시 그림 → GET /analyses
```

| 결정 | 이유 |
|---|---|
| **②(캐시 확인)를 ③(모델 확인)보다 먼저** | 모델이 고장 나도 이미 저장된 결과는 응답할 수 있다. 모델 확인을 라우터 의존성으로 걸면 캐시 결과까지 503이 되므로 서비스 안에서 순서를 정한다 |
| **추론은 트랜잭션 밖 (⑤)** | SQLAlchemy는 첫 조회 때 트랜잭션을 **자동으로 시작**한다. 명시적으로 끝내지 않으면 추론 내내 DB 연결을 붙잡아 연결 풀이 바닥나고, MySQL 기본 격리 수준(REPEATABLE READ)의 오래된 스냅샷이 남는다 |
| **rollback 전에 값을 변수로 꺼낸다 (⑤)** | `rollback()`은 세션 안의 ORM 객체를 모두 **만료(expire)**시킨다 (`expire_on_commit=False`는 commit에만 적용). 그 뒤 `image.id`처럼 속성에 접근하면 다시 조회(lazy load)를 시도하는데, `AsyncSession`에서는 `MissingGreenlet` 에러가 난다. 그래서 `patient_id`, `image_id`, 파일 경로를 **일반 변수**로 먼저 꺼내 두고, 이후에는 ORM 객체를 쓰지 않는다 |
| **commit 후 `refresh(result)` (⑩)** | `created_at`·`updated_at`처럼 **DB가 채우는 값**(`server_default`, `onupdate`)은 INSERT 후 객체에 로드되지 않는다. `expire_on_commit=False`여도 마찬가지다. 응답을 만들며 `result.created_at`에 접근하면 lazy load가 일어나 `MissingGreenlet`이 난다. `TimestampMixin`이 파이썬 `default=`를 쓰면 필요 없지만, 어느 쪽이든 안전하도록 **항상 refresh한다** |
| **저장 시 잠금 + 이미지 ID 재확인 (⑧⑨)** | 추론하는 사이 ⑩ 이미지 교체가 끝나면 예전 이미지로 만든 결과가 새 이미지에 붙는다. ⑩은 기존 이미지 행을 지우고 새 행을 넣으므로 ID가 바뀐다. **진료기록을 잠근 상태에서** 확인해야 확인과 INSERT 사이에 교체가 끼어들 수 없다 |
| **잠금 순서는 환자 → 진료기록** | 5일차 ⑤⑥⑩⑪과 같은 순서라 교착 상태(deadlock)가 생기지 않는다 |
| **중복은 DB UNIQUE가 최종 방어선 (⑩)** | ②의 조회만으로는 두 요청이 동시에 "결과 없음"을 보고 둘 다 추론할 수 있다 |
| **실패하면 만든 히트맵 파일 삭제** | 404·409·UNIQUE 충돌·커밋 실패 시 주인 없는 파일이 남지 않게 한다. 삭제까지 실패하면 5일차 파일 정리 작업(`file_cleanup_jobs`)에 기록한다 |

**서비스 의사 코드**
```python
async def predict(self, record_id: int) -> tuple[AIAnalysisResult, bool]:  # (결과, 새로 만들었는지)
    record = await self.records.get(record_id)
    if record is None:
        raise HTTPException(404, RECORD_NOT_FOUND)
    if saved := await self.analyses.get_current(record_id, MODEL_NAME, MODEL_VERSION):
        return saved, False                                   # 추론 생략 → 200
    if self.predictor is None:                       # app.state.predictor를 주입받음
        raise HTTPException(503, MODEL_UNAVAILABLE)

    image = await self.records.get_image(record_id)
    path = self._resolve_image(image)                         # 없음·폴더 밖 → 404
    # rollback은 ORM 객체를 만료시킨다 → 이후 image.id 접근 시 MissingGreenlet.
    # 필요한 값을 일반 변수로 먼저 꺼내고, 아래부터는 ORM 객체(record, image)를 쓰지 않는다.
    patient_id, image_id = record.patient_id, image.id
    await self.db.rollback()                                  # 읽기 트랜잭션 종료

    prediction = await self._infer(path)                      # 세마포어 + 스레드풀, 404 / 422 / 500
    heatmap_path = None                                       # 히트맵 미구현(Q1). 구현 시 self._save_heatmap(patient_id, ...)

    try:
        await self._lock_patient_then_record(patient_id, record_id)    # 없으면 404
        latest_id = await self.records.get_image_id(record_id)
        if latest_id != image_id:                             # None(이미지 삭제) 포함
            raise HTTPException(409, IMAGE_CHANGED)
        result = await self.analyses.add(record_id, prediction, heatmap_path)
        await self.db.commit()
        # DB가 채운 created_at·updated_at을 객체에 읽어 온다.
        # 생략하면 응답을 만들 때 result.created_at 접근에서 MissingGreenlet이 날 수 있다.
        await self.db.refresh(result)
        return result, True                                   # → 201
    except IntegrityError:
        await self.db.rollback()
        self._discard_heatmap(heatmap_path)
        saved = await self.analyses.get_current(record_id, MODEL_NAME, MODEL_VERSION)
        if saved is None:
            raise HTTPException(500, TRY_AGAIN_LATER)
        return saved, False                                   # 동시 요청 → 200
    except Exception:
        await self.db.rollback()
        self._discard_heatmap(heatmap_path)
        raise
```

> `refresh`는 commit **뒤**에 있으므로, refresh가 실패해도 결과는 이미 저장된 상태다. 이때 `except Exception`이 히트맵을 지우면 저장된 결과가 없는 파일을 가리키게 되므로, 구현 시 commit 성공 이후의 예외는 히트맵을 삭제하지 않도록 `committed` 플래그로 구분한다.

### 6-2. 서버 시작과 모델 로드

```text
uvicorn 시작
   ▼
FastAPI lifespan 시작 단계
   ├─ AI_PRELOAD_MODEL=true (기본) → worker.model.load_model() → app.state.predictor
   │     ├─ 성공 → 모델 5개가 메모리에 상주 (약 17.5초), 모든 요청이 재사용
   │     └─ 실패 → 오류 로그 기록, app.state.predictor = None, 서버는 계속 시작
   │               (⑫ 신규 추론만 503, 저장된 결과·⑬·나머지 API는 정상)
   └─ AI_PRELOAD_MODEL=false (개발용) → 시작 시 로딩하지 않음, 첫 예측 요청에서 로딩
```

- 모델을 요청마다 읽지 않고 **서버 시작 시 한 번** 읽는다. 과제 요구("모델을 메모리에 올려두고")와 3초 기준을 위한 것이다.
- 모델 파일이 없어도 서버는 뜬다. 환자·진료기록 기능까지 멈추지 않게 하기 위해서다 (D8).
- 테스트에서는 실제 모델 대신 가짜 예측기를 `app.state.predictor`에 주입한다 (13절).

**개발용 설정 `AI_PRELOAD_MODEL`** (D17)

| 값 | 동작 | 용도 |
|---|---|---|
| `true` (기본) | 서버 시작 시 로딩. 예측 요청은 1.3초대 | 운영, 성능 측정, 발표 |
| `false` | 첫 예측 요청에서 로딩. **첫 요청만 약 19초**(로딩 17.5초 + 추론), 이후는 같음 | 개발 중 `--reload`로 저장할 때마다 17초씩 기다리지 않기 위해 |

- `docker-compose.yml`은 항상 `uvicorn --reload`로 실행되므로, 예측 기능을 건드리지 않는 개발 중에는 `false`를 권장한다.
- `false`에서 첫 요청이 3초를 넘는 것은 개발 편의를 위해 감수한다. 성능 측정(9절)은 반드시 `true`로 한다.

**healthcheck 주의**: 로딩하는 17.5초 동안 서버가 `/healthcheck`에 응답하지 못한다. 현재 compose의 healthcheck(5초 간격 × 3회)로는 unhealthy로 판정될 수 있으므로 `start_period: 30s`를 추가한다 (12-1절).

### 6-3. 이미지 교체·삭제와 예측 결과 (5일차 구현, 변경 없음)

| 동작 | 예측 결과 | 히트맵 파일 |
|---|---|---|
| 진료기록 이미지 교체 (⑩ `PATCH`) | 해당 기록의 결과 전체 삭제 | 커밋 후 삭제 |
| 진료기록 삭제 (⑪) | `CASCADE` 삭제 | 커밋 후 삭제 |
| 환자 삭제 (⑤) | `CASCADE` 삭제 | 커밋 후 삭제 |
| 증상·차트 번호만 수정 | 유지 (이미지가 같으므로 재사용 정당) | 유지 |

이미지를 교체한 뒤 다시 `AI 예측 결과보기`를 누르면 저장된 결과가 없으므로 새 이미지로 추론한다 (201).

---

## 7. DB 변경 사항

Alembic 마이그레이션 1개로 처리한다.

| 변경 | 내용 | 근거 |
|---|---|---|
| `heatmap_url` NULL 허용 | `VARCHAR(255) NULL` | D4 |
| `model_version` 추가 | `VARCHAR(20) NOT NULL` | D5 |
| UNIQUE 제약 | `uq_ai_analysis_results_record_model (record_id, ai_model, model_version)` | D6. 맨 앞 컬럼이 `record_id`라 ⑬ 목록 조회에도 이 인덱스가 쓰인다 |
| CHECK 제약 | `ck_ai_analysis_results_confidence_range (confidence BETWEEN 0 AND 100)` | 잘못된 값 저장 방지 |

**모델 변경**
```python
class AIAnalysisResult(TimestampMixin, Base):
    __tablename__ = "ai_analysis_results"
    __table_args__ = (
        UniqueConstraint("record_id", "ai_model", "model_version", name="uq_ai_analysis_results_record_model"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_ai_analysis_results_confidence_range"),
    )
    heatmap_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="히트맵 이미지 상대 경로")
    model_version: Mapped[str] = mapped_column(String(20), nullable=False, comment="모델 버전")
```

**마이그레이션 `upgrade`**
```python
op.alter_column("ai_analysis_results", "heatmap_url", existing_type=sa.String(255), nullable=True)
op.add_column("ai_analysis_results", sa.Column("model_version", sa.String(20), nullable=False, server_default="v1"))
op.alter_column("ai_analysis_results", "model_version", server_default=None)   # 기존 행만 채우고 기본값 제거
op.create_unique_constraint("uq_ai_analysis_results_record_model",
                            "ai_analysis_results", ["record_id", "ai_model", "model_version"])
op.create_check_constraint("ck_ai_analysis_results_confidence_range",
                           "ai_analysis_results", "confidence BETWEEN 0 AND 100")
```

| 확인 사항 | 내용 |
|---|---|
| 적용 전 중복 확인 | `SELECT record_id, ai_model, COUNT(*) FROM ai_analysis_results GROUP BY 1, 2 HAVING COUNT(*) > 1;` 결과가 있으면 UNIQUE 생성이 실패한다. 현재는 예측 API가 없어 결과 행이 없지만, 개발 DB에 테스트 행이 있으면 정리 후 적용한다 |
| `downgrade` | 제약·컬럼 삭제 후 `heatmap_url`을 NOT NULL로 되돌린다. NULL 행이 있으면 실패하므로 먼저 정리한다 |
| 리비전 체인 | 최신 head(`alembic heads`)를 `down_revision`으로 지정. 5일차처럼 head가 2개가 되지 않게 확인한다 |

---

## 8. 보안 설계

| 위협 | 대책 |
|---|---|
| 승인 전 사용자의 의료 정보 접근 | 세 API 모두 1-2절의 권한 의존성 사용. 대기자·비활성 사용자 차단 |
| 허용되지 않은 부서의 접근 | `Department` Enum이 의료·개발·연구 세 개뿐이라 `StaffUser`로 충분하다. 부서가 추가되면 부서 조건 의존성을 도입한다 (1-2절, F9) |
| 저장 폴더 밖 파일 읽기 | X-Ray는 `resolve_xray_path()`, 히트맵은 `resolve_stored_path(FILE_KIND_HEATMAP, ...)`로 검증. 폴더 밖 경로는 이유를 숨기고 404 (로그에는 ID만) |
| 히트맵 노출 | 공개 폴더(`media/`)가 아닌 **비공개 폴더** `storage/heatmap/{patient_id}/{uuid}.png`. 히트맵은 환자 X-Ray 위에 그린 이미지라 X-Ray와 같은 수준으로 보호 (5일차 문서 D10) |
| 다른 기록 결과 조회 | 히트맵 조회 시 `record_id`와 `analysis_id`를 함께 조건으로 사용 |
| 악성 모델 파일 실행 | 서버 로컬 파일만 `weights_only=True`로 로드. 업로드받은 파일이나 URL로 모델을 로드하지 않는다 |
| 내부 정보 노출 | 추론 예외 메시지·스택·파일 경로를 응답하지 않음. 서버 로그에는 `record_id`와 예외 종류만 |
| 과도한 요청으로 CPU 고갈 | 동시 추론 수 제한, 결과 재사용 |
| 교차 출처 요청 | 4일차 Origin 검사 미들웨어가 `POST /predict`에도 적용 |
| 의료 판단 오해 | 화면에 "AI 예측 결과는 참고용이며 최종 판단은 의료진이 합니다" 표시 (14절 Q5) |

---

## 9. 성능 설계 (NFR-PRED-002)

| 대상 | 대응 |
|---|---|
| 모델 로드 | 서버 시작 시 1회 (6-2절). 요청 시간에 포함되지 않음 |
| 같은 기록 재요청 | 저장된 결과 재사용 → DB 조회 1~2회로 응답 |
| 추론 | `run_in_threadpool`로 실행해 이벤트 루프를 막지 않음. 추론 중에도 다른 API 처리 |
| 동시 추론 | 세마포어로 동시 실행 수 제한 (기본 1, 설정 `AI_MAX_CONCURRENT_PREDICTIONS`). 메모리 부족과 CPU 경합으로 모든 요청이 느려지는 것을 막음 |
| DB 연결 | 추론 전에 읽기 트랜잭션을 끝내 느린 추론이 연결 풀을 막지 않음 |
| 히트맵 | 이번에는 구현하지 않는다 (Q1). Grad-CAM을 추가하면 모델 5개에 대해 역전파가 필요해 추론 시간이 늘어나므로 다시 측정한다 |
| 결과 목록 | UNIQUE 인덱스(`record_id` 선두) 사용. 기록당 결과 수가 모델 버전 수만큼으로 작음 |

**3초 예산 (⑫ 신규 추론)**

| 단계 | 목표 | 근거 |
|---|---|---|
| 인증·진료기록·결과 조회 | 0.1초 | |
| 이미지 읽기·전처리 + 추론 (모델 5개) | 1.5초 | 측정 평균 1.31초, 최대 1.46초 |
| 히트맵 | 0초 | 미구현 (Q1) |
| DB 저장 | 0.1초 | |
| **합계** | **약 1.7초** | 여유 약 1.3초 |

**측정 방법**: 각 API를 20회 호출해 최대·평균·p95를 기록한다. **관측된 요청 중 하나라도 3초를 넘으면 미충족**으로 기록한다 (p95만으로 충족 판정하지 않음).

| 측정 항목 | 조건 | 최대 | 평균 | 판정 |
|---|---|---|---|---|
| 1장 추론 (`predict` 함수 단독) | 팀 모델 5개, 실제 X-Ray, 맥북 CPU (1단계 검증, 최현영) | 1.46초 | 1.31초 | ✅ 충족 |
| 서버 시작 | 모델 5개 로딩 (참고, 요청 시간 아님) | 17.5초 | | - |
| ⑫ 신규 추론 (API 전체) | 3단계 구현 후 Docker 환경 | *(기입)* | | |
| ⑫ 재사용 | 저장된 결과 있음 | *(기입)* | | |
| ⑬ 목록 | 결과 N건 | *(기입)* | | |

- 1단계 측정은 맥북 CPU 값이다. 서버(Docker) CPU에서는 다를 수 있으므로 3단계 구현 후 API 전체 시간을 다시 측정한다.
- 실제 X-Ray 1장 예측 결과: 정상, confidence 83.28% (폐렴 확률 16.7%). 정상 동작 확인.

**동시 요청 한계**: 동시 추론을 1개로 제한하므로 여러 명이 **동시에 새 추론**을 요청하면 뒤 요청은 앞 요청을 기다린다.

| 동시 신규 요청 | 마지막 요청의 대기 포함 시간 (추론 1.31초 기준) | 판정 |
|---|---|---|
| 1명 | 약 1.3초 | ✅ |
| 2명 | 약 2.6초 | ✅ (여유 적음) |
| 3명 이상 | 약 3.9초 이상 | ❌ 미충족 |

같은 기록 재요청은 추론하지 않으므로 이 대기에 포함되지 않는다. 3명 이상 동시 신규 추론은 이번 범위에서 **미충족으로 기록**하고, 비동기 처리를 향후 과제로 둔다 (D12, 15절 F1).

---

## 10. 모델 평가 기준 (NFR-PRED-001)

NFR-PRED-001은 API가 아니라 **선택한 모델의 성능 기준**이다. 1단계 담당자가 테스트셋으로 측정한 값을 기록하고, 기준을 넘는 모델과 threshold를 배포한다.

### 10-1. 지표

| | 실제 폐렴 | 실제 정상 |
|---|---|---|
| **폐렴으로 예측** | TP | FP (정상인을 오진) |
| **정상으로 예측** | **FN (폐렴 환자를 놓침, 가장 위험)** | TN |

| 지표 | 계산식 | 기준 | 측정값 | 충족 |
|---|---|---|---|---|
| **Recall (민감도)** | TP / (TP + FN) | **≥ 0.90** (목표 0.95) | **미측정** *(테스트셋 평가 후 기입)* | |
| Accuracy | (TP + TN) / 전체 | ≥ 0.80 (목표 0.90) | **미측정** *(테스트셋 평가 후 기입)* | |

> **현재 상태**: 1단계에서 확인된 성능 수치는 학습 중 OOF(Out-Of-Fold) Macro F1 **0.9850**뿐이다. 이 값은 OOF에서 threshold를 탐색한 점수라 실제보다 높게 나올 수 있고, Recall·Accuracy도 아니다. 따라서 **NFR-PRED-001 충족 여부는 아직 판단할 수 없다.** 3단계 통합 전에 테스트셋으로 Recall·Accuracy를 측정해 이 표를 채운다 (T24).

폐렴 데이터는 보통 폐렴 사진이 정상보다 많아(불균형), "모두 폐렴"이라고만 해도 Accuracy가 높게 나올 수 있다. 그래서 **Recall을 최우선**으로 보고, Accuracy로 "다 폐렴이라고 하는 모델"을 걸러낸다.

### 10-2. 평가 방법

| 항목 | 규칙 |
|---|---|
| 데이터 분리 | **환자 단위**로 학습·검증·테스트를 나눠 같은 환자의 사진이 양쪽에 섞이지 않게 한다 (데이터 누수 방지) |
| threshold 결정 | **검증셋**에서 정한다 |
| 최종 평가 | 고정한 모델·전처리·threshold로 **테스트셋을 한 번** 평가한다 |
| 서버 전처리 확인 | `worker/model.py`의 전처리로 다시 측정해 노트북 결과와 같은지 확인 (전처리·클래스 순서 불일치 검출) |
| 기록 | 데이터셋 이름, 클래스별 장수, 혼동행렬, 모델 버전, threshold, 지표 |
| 예외 | 분모가 0인 지표는 0이나 통과로 처리하지 않고 "평가 불가"로 기록 |

| 평가 기록 | 내용 |
|---|---|
| 평가 데이터 | *(데이터셋 이름, 테스트셋 장수, 폐렴/정상 비율)* |
| 혼동행렬 | *(TP / FP / FN / TN)* |
| 모델 버전 | `efficientnet_b0_5fold` / `v1` (Q2 확정 후) |

### 10-3. threshold 선택

팀 모델은 학습 시 OOF 예측에서 threshold를 탐색해 **0.4**로 정했다 (5-5절). Recall이 0.90에 못 미치면 threshold를 더 낮춰 폐렴 판정을 늘린다. 대신 FP가 늘어 Accuracy가 떨어진다.

**선택 방법**: 검증셋에서 threshold를 0.05 간격으로 바꿔 가며 Recall·Accuracy를 계산하고, **Recall ≥ 0.90을 만족하는 값 중 Accuracy가 가장 높은 값**을 고른다.

| threshold | Recall | Accuracy | 비고 |
|---|---|---|---|
| 0.50 | *(기입)* | *(기입)* | 비교용 |
| 0.40 | *(기입)* | *(기입)* | ✅ 현재 값 (OOF 탐색) |

> threshold를 바꾸면 같은 확률이라도 판정이 달라지므로 `MODEL_VERSION`을 올린다 (D5).

---

## 11. 설계 결정 기록

| No | 결정 | 검토한 대안 | 선택 이유 |
|---|---|---|---|
| D1 | 주소를 **프론트엔드 코드 기준**(`/predict`, `/analyses`)으로 | `/pneumonia-predictions`, `/ai-analysis-results` 등 새로 정의 | 화면이 이미 호출 코드를 갖고 있다. 다르면 상세 화면이 열리지 않는다 |
| D2 | 예측 이미지를 **요청으로 받지 않고** 진료기록의 X-Ray 사용 | 예측 API에서 이미지 업로드 | 정의서가 "진료기록 저장 시 업로드한 이미지를 활용"이라고 정했다 |
| D3 | 예측 권한을 **의료·개발·연구 부서 + 관리자**로, 구현은 **`StaffUser` 재사용** | 의료진(`MedicalStaffUser`)만 / 부서 조건을 거는 새 의존성 | 정의서가 세 부서를 행위자로 적었다. `Department` Enum이 이 세 개뿐이라 `StaffUser`와 범위가 같다 (1-2절). 진료 데이터를 바꾸지 않는 판독이다 |
| D4 | `heatmap_url`을 **nullable로 변경** | NOT NULL 유지 + 빈 문자열 / 히트맵 필수 구현 | 정의서상 선택사항. 빈 문자열은 "없음"과 "경로"가 섞여 실수하기 쉽다 |
| D5 | **`ai_model`(이름) + `model_version`(버전) 분리**, 재사용 기준에 둘 다 포함 | 이름에 버전을 붙이기 / 이름만 사용 | 같은 이름으로 가중치·전처리·threshold만 바꾸면 **이전 모델 결과가 재사용**된다. 표시명과 버전을 나누면 목록에서 구분하기도 쉽다 |
| D6 | **UNIQUE (record_id, ai_model, model_version)**, 위반 시 먼저 저장된 결과 응답 | 조회 후 INSERT만 / 매번 새 결과 저장 | 정의서가 "같은 모델 결과가 있으면 재추론 없이 응답"을 요구한다. 동시 요청까지 막는 최종 판단은 DB 제약이 한다 |
| D7 | 신규 **201**, 재사용 **200** | 둘 다 200 / 별도 `is_cached` 필드 | 상태 코드만으로 실제 추론 여부를 구분. 화면은 둘 다 성공 처리하므로 영향이 없다 |
| D8 | 모델 로드 실패 시 **서버는 시작, ⑫ 신규 추론만 503** | 서버 시작 실패 | 모델 파일 문제로 환자·진료기록 기능까지 멈추면 안 된다 |
| D9 | 손상 이미지 **422**, 일시 오류 **500** | 모두 500 / 400 | 다시 시도해서 해결되는지 여부를 구분 |
| D10 | `confidence`를 **JSON 숫자**로 직렬화 | `Decimal` 기본 직렬화(문자열) | 화면 계산·정렬, 테스트 비교 |
| D11 | confidence는 **판정한 클래스의 확률(%)** | 항상 폐렴 확률 | "정상, 12%"는 정상 판정을 12% 확신한다는 뜻으로 오해된다 |
| D12 | **동기 추론** (스레드풀 + 동시 실행 제한) | 별도 worker 프로세스 + 작업 테이블 + 202 접수·폴링 | 화면·5일차 코드 수정 없이 오늘 범위에서 구현·전원 이해 가능. 실제 추론이 1.31초라 단건은 3초를 지킨다 (9절). 3명 이상 동시 신규 추론은 미충족으로 기록하고 F1로 확장 |
| D13 | 추론은 **트랜잭션 밖**, 저장 시 **잠금 + 이미지 ID 재확인**, commit 후 **refresh** | 추론 전체를 트랜잭션 + 행 잠금 | 수 초 동안 연결·잠금을 잡지 않으면서, 교체된 이미지 결과 저장은 409로 막는다. rollback·commit 전후의 ORM 만료로 인한 `MissingGreenlet`을 막는다 |
| D14 | 예측 모듈은 **경로를 받아 결과만 반환**, 저장은 API | `predict`가 DB·파일까지 저장 | 1단계와 3단계를 병렬 개발·단독 테스트 |
| D15 | 히트맵은 **비공개 저장소 + 인증 API** | `media/` 공개 서빙 | 환자 X-Ray 위에 그린 이미지다 |
| D16 | 목록은 **진료기록 단위 배열, 페이지네이션 없음** | 환자 단위 목록 / `{total, items}` + page/size | 화면이 진료기록 단위 경로와 배열을 기대한다. 기록당 결과 수가 모델 버전 수만큼으로 작다. 환자 단위는 Q7 합의에 따라 F8로 추가 |
| D17 | 모델 미리 로딩을 **설정(`AI_PRELOAD_MODEL`)으로 끌 수 있게**, 기본은 켬 | 항상 시작 시 로딩 / 항상 첫 요청 때 로딩 | 로딩이 17.5초라 `--reload` 개발 중 저장할 때마다 기다리게 된다. 첫 요청 때 로딩하면 그 요청이 3초를 넘으므로 기본은 시작 시 로딩으로 둔다 (6-2절) |

---

## 12. 현재 코드에서 변경할 사항과 구현 구조

### 12-1. 백엔드

| 대상 | 현재 | 변경 | 근거 |
|---|---|---|---|
| `worker/model.py` | 팀 모델(EfficientNet-B0 5-fold) 추론 구현 (`feature/pneumonia-model`) | `MODEL_NAME`·`MODEL_VERSION` 상수 추가, 예외 구분(`ValueError`/`RuntimeError`) | 5-2절 |
| `app/models/ai_analysis_result.py` | `heatmap_url` NOT NULL | nullable, `model_version`, UNIQUE·CHECK | 7절 |
| `alembic/versions/` | - | 마이그레이션 1개 | 7절 |
| `core/config.py` | `HEATMAP_STORAGE_DIR` 있음 | `AI_MAX_CONCURRENT_PREDICTIONS`(기본 1), `AI_PRELOAD_MODEL`(기본 `true`) 추가 | 6-2절, 9절 |
| `core/dependencies.py` | `StaffUser`, `MedicalStaffUser` | 변경 없음 (`StaffUser` 재사용) | 1-2절 |
| `main.py` | 시작 시 작업 없음 | `lifespan`에서 `load_model()` → `app.state.predictor`, 예측 라우터 등록 | 6-2절 |
| `core/file_storage.py` | 업로드 파일 저장 함수 | 변경 없음 (히트맵 구현 시 히트맵 저장 함수 추가) | Q1 |
| `pyproject.toml`, `uv.lock` | AI 의존성 없음 (`worker/requirements.txt`에만 있음) | `uv add torch torchvision timm` | 5-2절 |
| `docker-compose.yml` | `./app`만 마운트, healthcheck 5초 × 3회 | `./worker` 마운트 (또는 이미지에 포함), healthcheck에 `start_period: 30s` 추가 | 6-2절 |
| `.gitignore` | `worker/models/*.pt` 제외 (1단계에서 추가) | 변경 없음. 가중치 ZIP은 팀 채널로 공유 | Q3 |

### 12-2. 프론트엔드

| 화면 | 변경 | 필수 여부 |
|---|---|---|
| 예측 버튼·목록 호출 | 없음 | - |
| 예측 버튼 | 요청 중 비활성화 + "예측 중..." (중복 클릭 방지) | 권장 |
| 결과 섹션 | "AI 예측 결과는 참고용입니다" 문구, confidence 50% 미만 폐렴 판정에 "의료진 확인 필요" | 권장 (Q5) |
| 결과 표 | `heatmap_url`이 있으면 "히트맵 보기" 열 (Blob 방식), 모델 버전 표시 | 히트맵 구현 시 |

### 12-3. 구현 구조

```text
AH_web_development_assignment/
├── worker/                          # 1단계
│   ├── models/best_model_fold0~4.pt # Git 제외, ZIP으로 공유
│   └── model.py                     # MODEL_NAME, MODEL_VERSION, THRESHOLD, load_model, get_predictor, predict_pneumonia
└── app/
    ├── apis/
    │   ├── prediction_apis.py       # ⑫ 예측 (C)
    │   └── analysis_apis.py         # ⑬ 목록 (B)
    ├── services/
    │   ├── prediction_service.py    # 재사용 판단, 추론 호출, 잠금·이미지 재확인, 중복 처리 (C)
    │   └── analysis_service.py      # 목록 조회 (B)
    ├── schemas/analysis.py          # AnalysisResultResponse, to_analysis_response (A)
    ├── repositories/analysis_repository.py  # get_current, list_by_record, add, refresh (A)
    └── core/
        └── config.py                # AI_MAX_CONCURRENT_PREDICTIONS, AI_PRELOAD_MODEL
```

- `worker/`는 과제가 정한 위치다. `app/`과 같은 높이에 두고 `from worker import model`로 가져온다.
- 서비스는 `worker.model`을 직접 import하지 않고 `app.state.predictor`를 **의존성으로 주입**받는다. 테스트에서 가짜 예측기로 바꿔 끼우기 위해서다 (5-3절).

### 12-4. Merge 순서

```text
① 이 설계 문서
        ↓
② 마이그레이션 + 모델 + 스키마 + 저장소        ← API·테스트가 모두 사용
        ↓
③ 1단계 worker/model.py (팀 모델, 5-2절 추가 반영)   ∥   ④ ⑫ 예측 API + ⑬ 목록 API (가짜 모델 테스트)   ← 5절 인터페이스로 병렬
        ↓
⑤ main.py lifespan 연결 + 실제 모델 통합 확인 + 성능 측정 (9절 표 기입)
        ↓
⑥ (히트맵 구현 시) ⑭ 히트맵 API + 화면 열
```

> ⑬만 먼저 Merge해도 상세 화면이 열리고 "저장된 예측 결과가 없습니다."가 표시된다.

---

## 13. 테스트 시나리오

기존 `tests/` 방식(임시 SQLite)으로 작성하고, **실제 모델 대신 가짜 예측 모듈**을 주입한다. 가짜 모듈은 고정 결과를 반환하고 호출 횟수를 센다.

> **SQLite 테스트의 한계**: SQLite는 `SELECT ... FOR UPDATE`를 무시한다. 그래서 자동 테스트가 통과해도 "**잠금 덕분에** 막혔다"는 것까지는 보장하지 못한다.
> - **SQLite로 검증되는 것**: UNIQUE·CHECK 제약은 SQLite에서도 동작하므로 T13(중복 방지)과 T26은 그대로 검증된다. T14·T15는 가짜 예측 함수 안에서 교체·삭제를 **순서대로** 일으키므로 이미지 ID 재확인 로직 자체는 검증된다.
> - **MySQL에서 따로 확인할 것**: 잠금이 실제로 교체(⑩)와 저장(⑫)을 직렬화하는지는 MySQL 컨테이너에서 두 요청을 동시에 보내 확인하고 결과를 기록한다 (T28).

| No | 요구사항 | 시나리오 | 기대 결과 |
|---|---|---|---|
| T1 | REQ-PRED-001 | 스태프가 X-Ray가 있는 진료기록 예측 | 201, `Location`, 결과 1건, 예측 함수 **1회** 호출 |
| T2 | REQ-PRED-001 | T1 후 같은 기록으로 다시 예측 | **200**, 같은 `id`, 예측 함수 **추가 호출 없음** |
| T3 | REQ-PRED-001 | T1 후 `MODEL_VERSION`을 바꿔 예측 | 201, 결과 2건 |
| T4 | REQ-PRED-001 | 의료·개발·연구 부서 스태프, 관리자가 예측 | 모두 201 |
| T5 | REQ-PRED-001 | 대기자 / 토큰 없음 | 403 / 401 |
| T6 | REQ-PRED-001 | 없는 진료기록 / `record_id=0` | 404 / 422 |
| T7 | REQ-PRED-001 | X-Ray 파일 없음 / 저장 폴더 밖 경로 | 404, 응답에 경로 없음 |
| T8 | REQ-PRED-001 | 이미지가 아닌 파일 (`ValueError`) | 422, 결과 행 없음 |
| T9 | REQ-PRED-001 | 모델 미로드 + 저장된 결과 없음 / 있음 | 503 / **200** (캐시 우선) |
| T10 | REQ-PRED-001 | 예측 함수가 예외 / NaN 출력 (`RuntimeError`) | 500, 응답에 예외 메시지 없음, 결과 행 없음 |
| T11 | REQ-PRED-001 | 히트맵 없는 결과 | 201, `heatmap_url: null` |
| T12 | REQ-PRED-001 (히트맵 구현 시, Q1) | 히트맵 있는 결과 | `storage/heatmap/{patient_id}/`에 파일, `heatmap_url`은 API 경로 |
| T13 | REQ-PRED-001 | 같은 기록에 동시 예측 2건 | 결과 1건, 두 응답 `id` 같음 (201 + 200), 남는 히트맵 파일 1개 |
| T14 | REQ-PRED-001 | 추론 중 이미지 교체 (가짜 함수 안에서 교체) | 409, 결과 행 없음, 히트맵 파일 삭제 |
| T15 | REQ-PRED-001 | 추론 중 진료기록 삭제 | 404, 결과 행 없음, 히트맵 파일 삭제 |
| T16 | REQ-PRED-001 | `p = 0.13`을 반환하는 모델 | `is_pneumonia=false`, `confidence=87.0` |
| T17 | REQ-PRED-002 | 결과 없는 기록 목록 | **200 `[]`** |
| T18 | REQ-PRED-002 | 결과 2건(버전 2개) 목록 | 최신순 배열, 필드 8개, `created_at`에 `Z` |
| T19 | REQ-PRED-002 | 대기자 / 없는 기록 | 403 / 404 |
| T20 | 응답 형식 | `confidence` 타입 | JSON **숫자** (문자열 아님), 0~100 |
| T21 | 보안 (히트맵 구현 시, Q1) | 기록 A 경로에 기록 B의 `analysis_id`로 히트맵 조회 | 404 |
| T22 | 보안 (히트맵 구현 시, Q1) | 토큰 없이 히트맵 / `/media/heatmap/...` 직접 접근 | 401 / 404 |
| T23 | 연동 | 예측 → 이미지 교체(⑩) → 다시 예측 | 결과·히트맵 삭제 → 201로 새 결과 (`id` 다름) |
| T24 | NFR-PRED-001 | **실제 모델**, 테스트셋, 서버 전처리 | Recall ≥ 0.90, Accuracy ≥ 0.80, 노트북 결과와 일치 |
| T25 | NFR-PRED-002 | **실제 모델**로 신규 / 재사용 / 목록 | 각각 3초 이내 (9절 표) |
| T26 | DB | confidence 101 저장 시도 | CHECK 제약 위반 |
| T27 | 화면 | 상세 화면 → `AI 예측 결과보기` | 성공 알림, 표에 결과 1행 |
| T28 | 동시성 (MySQL) | MySQL 컨테이너에서 예측(⑫)과 이미지 교체(⑩)를 동시에 요청 | 교체가 먼저 잠금을 잡으면 예측은 409, 예측이 먼저면 결과 저장 후 교체가 그 결과를 삭제. 오래된 결과가 남지 않음 |
| T29 | 회귀 | rollback·commit 이후 ORM 속성 접근 | 409 판정·히트맵 저장(T14), 201 응답의 `created_at` 직렬화(T1)가 `MissingGreenlet` 없이 동작 |
| T30 | 설정 | `AI_PRELOAD_MODEL=false`로 서버 시작 후 첫 예측 / 두 번째 예측 | 시작 시 로딩 없음, 첫 요청에서 로딩 후 201 / 두 번째는 로딩 없이 처리 |
| T31 | 예외 구분 | 손상 이미지(PIL 디코딩 실패) / 모델 출력 NaN | 422 / 500 (5-2절 예외 구분 반영 확인) |

---

## 14. 팀 결정이 필요한 사항

| No | 질문 | 선택지 | 제안 | 결정 |
|---|---|---|---|---|
| Q1 | 히트맵을 만들 것인가 | (a) Grad-CAM + ⑭ + 화면 열 / (b) 이번엔 `null`, 개선 과제로 | 팀 모델 추론 시간 측정 후 결정. 히트맵 포함 3초를 넘으면 (b) | **(b) 미구현** - 1단계에서 구현하지 않음. ⑭·히트맵 저장은 향후 과제 |
| Q2 | 모델 이름·버전 | 팀 모델 (EfficientNet-B0 5-fold) | `MODEL_NAME`은 구조 이름, `MODEL_VERSION`은 `v1`부터. 가중치·전처리·threshold를 바꾸면 올림 | 제안: `efficientnet_b0_5fold` / `v1` (1단계 상수 추가 시 확정) |
| Q3 | 모델 파일 Git 업로드 | (a) 그대로 커밋 (100MB 미만) / (b) Git LFS / (c) `.gitignore` 후 별도 공유 | 파일 크기 확인 후 결정. 100MB 이상이면 GitHub가 거부한다 | **(c)** - `worker/models/*.pt`를 `.gitignore`, 가중치 5개는 ZIP으로 공유 |
| Q4 | 이전 버전 결과를 목록에 보여줄 것인가 | (a) 모두 표시 / (b) 현재 버전만 | (a). 정의서 목록 필드에 "사용한 모델"이 있어 여러 모델 결과를 전제로 한다 | |
| Q5 | 참고용 고지·낮은 확신도 표시 | 표시 / 미표시 | 표시. 의료 판단 오해 방지 | |
| Q6 | 동시 추론 수 | 1 / 2 이상 | 기본 1, 팀 모델 측정 후 조정 | **1** - 추론 1.31초 기준 2명까지 3초 이내. 3명 이상은 F1 (9절) |
| **Q7** | **REQ-PRED-002 목록 범위** | (a) 진료기록 단위 / (b) 환자 단위 (1-5절) | (a)로 구현. 정의서 의도가 (b)라면 F8로 환자 단위 API 추가 | |
| **Q8** | **관리자(admin)를 예측 기능에 포함할 것인가** | (a) 포함 / (b) 의료·개발·연구 부서만 | (a). 5일차 조회 API와 일관, 운영 확인 필요 | |

---

## 15. 향후 개선 과제

| No | 과제 | 현재 한계 | 개선 방향 |
|---|---|---|---|
| F1 | **비동기 예측** | 모델이 무겁거나 동시 요청이 많으면 3초를 넘을 수 있다 | 별도 worker 프로세스 + MySQL 작업 테이블(`prediction_jobs`) + `202 Accepted` 접수 + 상태 조회 API. 작업 선점(`FOR UPDATE SKIP LOCKED`), 임대 만료·재시도, worker 준비 상태 확인, 화면 폴링 |
| F2 | 예측 이미지 추적 | 결과가 어떤 X-Ray로 만들어졌는지 직접 기록하지 않음 (교체 시 결과 삭제로 대신 보장) | `ai_analysis_results.xray_image_id` FK 추가, UNIQUE에 포함 |
| F3 | 판정 근거 저장 | 폐렴 확률 원본·threshold를 저장하지 않음 | `pneumonia_probability`, `threshold` 컬럼 추가 → threshold 재조정 시 재분석 가능 |
| F4 | 진료기록 등록 시 자동 예측 | 버튼을 눌러야 추론 | 등록 후 백그라운드 예측으로 결과 미리 준비 |
| F5 | 운영 중 성능 추적 | 배포 후 실제 Recall을 알 수 없음 | 의료진 확정 진단 입력 → 예측과 비교 |
| F6 | 입력 이미지 품질 검사 | 흉부 X-Ray가 아닌 사진도 예측됨 | 크기·종류 검사, 이상 입력 경고 |
| F7 | GPU 서버 | CPU 추론 | 추론 시간 단축, 히트맵 포함 3초 확보 |
| F8 | **환자 단위 예측 결과 목록** | ⑬은 현재 진료기록의 결과만 보여준다 (1-5절) | `GET /api/v1/patients/{patient_id}/analyses` 추가. 진료기록 ID·X-Ray 조회 경로·예측 결과를 최신순으로 반환. 기존 ⑬은 유지 |
| F9 | 부서 조건 권한 | `Department`가 세 개뿐이라 `StaffUser`로 충분하다 (1-2절) | 원무·행정 등 부서가 추가되면 의료·개발·연구 부서와 관리자만 통과시키는 의존성을 추가하고, 그 부서 staff의 403 테스트를 추가한다 |

---

## 16. 설계안 통합 기록

팀원들이 작성한 설계안 5개를 아래 기준으로 비교하고, **팀원 전원이 공동으로 취합**했다.

**비교 기준**

| 기준 | 이유 |
|---|---|
| ① API 주소가 프론트 코드(`/predict`, `/analyses`)와 같은가 | 다르면 구현해도 화면이 동작하지 않는다 |
| ② 같은 기록·같은 모델 재사용 규칙이 있는가 | 정의서 REQ-PRED-001의 핵심 조건 |
| ③ 히트맵을 선택사항으로 처리했는가 | DB `heatmap_url`이 NOT NULL이라 그대로는 저장할 수 없다 |

**설계안별 반영 내용**

| 설계안 | 작성자 | 반영한 내용 |
|---|---|---|
| A | 팀원 전원 (공동) | 1단계·3단계 인터페이스 분리, 히트맵 저장·실패 시 파일 정리 흐름, 3초 예산표, Merge 순서, 모델 파일 Git 업로드 검토, 버튼 중복 클릭 방지, 예측 함수 의존성 주입 |
| B | 팀원 전원 (공동) | 저장 시 잠금 + 이미지 ID 재확인, 추론 전 읽기 트랜잭션 종료, confidence 숫자 직렬화, 손상 이미지 422 구분, 샘플 모델 분석과 `state_dict` 로딩 방식, threshold 선택 방법 |
| C | 팀원 전원 (공동) | `ai_model`·`model_version` 분리, 모델 출력 NaN 검증, 환자 단위 데이터 분리·검증셋 threshold·테스트셋 1회 평가, 최대값 기준 성능 판정, 비동기 worker 설계(F1), 이미지 ID 추적(F2) |
| D | 팀원 전원 (공동) | 캐시 확인 후 모델 존재 검사, 폐렴 확률·threshold 저장(F3), 낮은 확신도 표시, 참고용 고지 문구 |
| E | 팀원 전원 (공동) | `field_serializer`를 이용한 confidence 직렬화 코드, 팀 이해 확인 체크리스트, 응답에 환자 식별 정보 제외 원칙 |

**팀원별 2단계 참여**

| 팀원 | 참여 내용 |
|---|---|
| 소혜진 (팀장) | 설계 논의 참여·의견 제시, 1단계 모델 정보 제공(구조·전처리·threshold, 히트맵 미구현 결정) |
| 최현영 | 설계안 공동 작성, 1단계 모델 실제 X-Ray 추론·시간 측정(9절), 1단계 PR 리뷰(설계 문서 분리, `uv add` 의존성 요청), 3단계 함수 이름 사전 합의 |
| 강선영 | 설계안 공동 작성, 통합본 수정(commit 후 `refresh`, REQ-PRED-002 목록 범위 1-5절, 권한 근거, D 번호 표기 규칙) |
| 서민서 | 설계안 공동 작성 |
| 김지영 | 설계안 공동 작성, 통합본 수정(1단계 결과 반영 5절·9절·14절, `AI_PRELOAD_MODEL`·healthcheck, 권한 `StaffUser` 확정, 18절 기여도) |

**통합본 리뷰 반영**

| 지적 | 조치 |
|---|---|
| `rollback()` 뒤 ORM 객체 접근 시 `MissingGreenlet` | rollback 전에 `patient_id`, `image_id`, 경로를 일반 변수로 꺼냄 (6-1절 ⑤, 의사 코드) |
| 의사 코드에 `patient_id` 조회가 없음 | 진료기록 조회 시 `patient_id`를 꺼내 히트맵 경로와 환자 잠금에 사용 |
| SQLite는 `FOR UPDATE`를 무시해 잠금을 검증할 수 없음 | 13절에 한계 명시, MySQL 동시성 확인 T28 추가 |
| commit 후 DB가 채운 `created_at` 접근 시 `MissingGreenlet` | commit 후 `refresh(result)` 추가, commit 이후 예외에서 히트맵을 지우지 않도록 명시 (6-1절, D13, T29) |
| REQ-PRED-002는 "환자의" 목록인데 진료기록 단위로 구현 | 1-5절에 해석·근거 정리, Q7 팀 합의 항목, F8 환자 단위 API 추가 |
| "세 부서 전체이므로 부서 제한 없음"은 부서가 셋뿐일 때만 성립 | `app/models/enums.py` 확인 결과 세 개뿐 → `StaffUser` 재사용 확정. 부서 추가 시 대응은 F9 |
| 5일차 결정 번호(D10·D15·D18)가 이 문서의 D 번호와 겹침 | 5일차 결정은 `5일차 문서 D○`로 표기 (문서 상단 번호 표기 규칙) |
| 문서가 샘플 모델(SimpleCNN) 기준이고 1단계 결과가 반영되지 않음 | 5절을 실제 1단계 코드(EfficientNet-B0 5-fold, threshold 0.4) 기준으로 갱신, 3단계 전 1단계 추가 사항(모델 이름·버전 상수, 예외 구분, `uv add`) 정리 |
| 손상 이미지는 PIL `OSError`, NaN 출력은 `ValueError`라 422/500 구분이 뒤바뀜 | 5-2절에 예외 구분 요청, T31 추가 |
| 모델 로딩 17.5초로 `--reload` 개발이 느리고 healthcheck가 실패할 수 있음 | `AI_PRELOAD_MODEL` 설정(D17), healthcheck `start_period` (6-2절), T30 |
| 성능 측정값·히트맵·모델 파일 결정이 비어 있음 | 9절 측정표(추론 1.31초, 로딩 17.5초), Q1 (b), Q3 (c), Q6 1 기입. Recall·Accuracy는 미측정으로 명시 (10-1절) |
| `model_version` 필드에 `protected_namespaces=()`가 필요하다고 적음 | 팀이 쓰는 Pydantic 2.12는 2.10부터 이 필드에 경고를 내지 않아 설정 제거 (2-2절) |

---

## 17. 팀 이해 확인 체크리스트

PR 리뷰 때 팀원 각자 아래 질문에 답할 수 있는지 확인한다. (과제 조건: 팀원 전체가 명세를 이해할 것)

- [ ] 같은 진료기록으로 예측을 두 번 누르면 DB에 몇 건이 남고, 각각 어떤 상태 코드가 오는가?
- [ ] 두 사람이 **동시에** 같은 기록을 예측하면 어떻게 되는가? 무엇이 중복을 막는가?
- [ ] 추론하는 사이 다른 사람이 X-Ray를 교체하면 어떻게 되는가? 왜 저장할 때 잠금을 거는가?
- [ ] 왜 추론 전에 `db.rollback()`을 하는가? rollback 전에 `patient_id`, `image_id`를 변수로 꺼내 두는 이유는?
- [ ] 왜 commit 후에 `refresh(result)`를 하는가?
- [ ] 개발 중 `AI_PRELOAD_MODEL=false`를 쓰면 무엇이 빨라지고, 무엇이 느려지는가? 왜 기본값은 `true`인가?
- [ ] 지금 NFR-PRED-001(Recall ≥ 0.90)을 충족한다고 말할 수 있는가? 없다면 무엇이 더 필요한가?
- [ ] SQLite 자동 테스트로 검증되는 것과 MySQL에서 따로 확인해야 하는 것은 무엇인가?
- [ ] 예측 결과 목록은 진료기록 단위인가, 환자 단위인가? 정의서와 다른 점은 무엇이고 어떻게 해결하는가?
- [ ] 왜 `PredictionUser` 같은 새 권한 의존성 없이 `StaffUser`를 그대로 써도 되는가?
- [ ] 모델 파일이 없을 때 서버와 각 API는 어떻게 동작하는가? 저장된 결과는 받을 수 있는가?
- [ ] 정상 판정에 confidence 87%는 무슨 뜻인가? `confidence`에 별도 직렬화가 필요한 이유는?
- [ ] 모델을 다시 학습하거나 threshold만 바꿨을 때 무엇을 바꿔야 하는가? 바꾸지 않으면 어떤 문제가 생기는가?
- [ ] 왜 Accuracy보다 Recall이 중요한가? Recall이 0.90 미만이면 무엇을 조정하는가?
- [ ] 히트맵은 어디에 저장되고, 왜 `media/`에 두지 않는가?
- [ ] 진료기록 이미지를 교체하거나 환자를 삭제하면 예측 결과와 히트맵은 어떻게 되는가?

| 팀원 | 확인 | 비고 |
|---|---|---|
| | ☐ | |
| | ☐ | |
| | ☐ | |
| | ☐ | |
| | ☐ | |

---

## 18. 팀 기여도

| 단계 | 담당 | 작업 | 구현 내용 | PR |
|---|---|---|---|---|
| 1단계 | 소혜진 (팀장) | `worker/model.py` | EfficientNet-B0 5-fold 앙상블 추론, 학습과 같은 전처리, 가중치 안전 로딩, 출력 검증, 의존성(`pyproject.toml`) 정리 | #34 |
| 2단계 | 팀원 전원 (공동 취합) | 설계 문서 | 5개 설계안 작성·비교·통합, 통합본 리뷰 반영 | |
| 3단계 A | 김지영 | DB 기반 | 마이그레이션(`heatmap_url` nullable, `model_version`, UNIQUE·CHECK), 모델·스키마·저장소 | #36 |
| 3단계 B | 강선영 | ⑬ 결과 목록 | 진료기록 단위 결과 목록 API, 상세 화면 연결 확인 | |
| 3단계 C | 최현영 | ⑫ 예측 | 재사용(200)·신규(201), 저장 시 잠금·이미지 재확인(409), 동시 요청 충돌 처리, 동시 추론 제한 | |
| 3단계 D | 서민서 | 모델 연결 | `lifespan` 모델 로딩, `AI_PRELOAD_MODEL`, `MODEL_NAME`·`MODEL_VERSION`·`is_loaded()`, 성능 측정 | |
| (선택) | Q1 결정 후 | ⑭ 히트맵 | 인증 히트맵 조회, 화면 열 | |
