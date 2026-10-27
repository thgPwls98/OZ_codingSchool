# 4일차 USER API 설계 및 명세

> 회원 요구사항 REQ-USER-001~009, NFR-USER-001~003을 바탕으로 작성한 구현 전 설계 명세이다. 현재 구현된 `/practice_api` 연습 API와 구분한다. 경로와 주요 필드명은 기존 `static/apis.js`를 참고했으며, 요구사항과 다른 기존 코드의 변경 사항은 문서 마지막에 정리한다.

## 1. 공통 규칙

### 1-1. 기본 규칙

| 항목 | 규칙 |
|---|---|
| 기본 경로 | `/api/v1` |
| 통신 | 운영 환경에서 HTTPS 사용 |
| 요청·응답 형식 | 기본 JSON. 로그인 요청은 `multipart/form-data`, 본문 없는 요청은 Content-Type 불필요 |
| 인증 | `Authorization: Bearer <access_token>` |
| 인증 사용자 판별 | 검증된 토큰의 `user_id`로 DB 사용자를 조회한다. 요청 본문의 사용자 ID로 본인을 판별하지 않는다. |
| 성공 응답 | 단일 자원은 객체, 목록은 배열. `204`는 본문 없음 |
| 오류 응답 | 업무 오류는 `{"detail": "오류 메시지"}`, 입력 검증 오류는 FastAPI 형식의 오류 배열 |
| 민감 정보 | 비밀번호 원문·해시·리프레시 토큰을 사용자 응답에 포함하지 않는다. |
| 설계상 추가 규칙 | 길이 제한, 검색 방식, 자기 권한 변경 금지 등 요구사항에 없는 세부 동작은 이 문서에서 정한 구현 기준이다. |

### 1-2. 공통 코드 값

| 항목 | API 값 | 화면 표시 |
|---|---|---|
| 부서 | `research` / `medical` / `development` | 연구 / 의료 / 개발 |
| 성별 | `male` / `female` | M / F |
| 권한 | `pending` / `staff` / `admin` | 대기자 / 스태프 / 어드민 |

성별 요구사항의 M/F는 화면 표시로 해석하고, API는 기존 화면과 DB의 `male/female`을 유지한다. 회원가입 시 권한은 서버에서 `pending`, 계정 활성화 여부는 `true`로 지정한다. 대기 상태와 계정 비활성화는 서로 다른 개념이다.

| 권한 | 허용 범위 |
|---|---|
| pending | 마이페이지 조회·수정, 비밀번호 변경, 탈퇴, 토큰 재발급, 로그아웃 |
| staff | pending의 기능 + 흉부 X-ray 관련 서비스 읽기·쓰기·수정 |
| admin | staff의 기능 + 회원 목록 조회 및 회원 권한 변경 |

비활성 계정은 로그인과 서비스 이용을 차단한다. 권한과 활성 상태는 매 인증 요청에서 DB로 확인하여 변경 사항을 즉시 반영한다. 관리자 전용 화면을 숨기는 것과 별개로 서버에서도 권한을 검증한다.

### 1-3. 공통 사용자 응답 `UserResponse`

| 필드명 | 타입 | 설명 |
|---|---|---|
| id | integer | 사용자 고유 ID |
| email | string | 이메일 |
| name | string | 이름 |
| department | string | `research`, `medical`, `development` |
| gender | string | `male`, `female` |
| phone_number | string | 하이픈 없는 휴대폰 번호. 예: `01012345678` |
| role | string | `pending`, `staff`, `admin` |
| is_active | boolean | 계정 활성화 여부 |

```json
{
  "id": 1,
  "email": "hong@example.com",
  "name": "홍길동",
  "department": "medical",
  "gender": "male",
  "phone_number": "01012345678",
  "role": "pending",
  "is_active": true
}
```

### 1-4. 공통 오류

| 상태 코드 | 발생 상황 | detail 예시 |
|---|---|---|
| 400 Bad Request | 수정 항목 없음 등 업무 규칙 위반 | `수정할 항목을 하나 이상 입력하세요.` |
| 401 Unauthorized | 인증 누락, 토큰 위조·만료, 삭제된 사용자 | `인증 정보가 유효하지 않습니다.` |
| 403 Forbidden | 권한 부족 또는 계정 비활성화 | `접근 권한이 없습니다.` / `비활성화된 사용자입니다.` |
| 404 Not Found | 권한 변경 대상 회원 없음 | `회원을 찾을 수 없습니다.` |
| 409 Conflict | 이메일·휴대폰 번호 중복 | `이미 사용 중인 이메일입니다.` |
| 422 Unprocessable Entity | 필수 값 누락, 잘못된 타입·형식·코드 값, 허용되지 않은 필드 | 아래 검증 오류 예시 참고 |
| 500 Internal Server Error | 예상하지 못한 서버 처리 실패 | `잠시 후 다시 시도해주세요.` |

업무 오류 예시:

```json
{"detail": "접근 권한이 없습니다."}
```

입력 검증 오류 예시(회원가입의 이메일 누락):

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

| 필드명 | 타입 | 설명 |
|---|---|---|
| detail | string 또는 array | 업무 오류 메시지 또는 입력 검증 오류 목록 |
| detail[].loc | array | 오류 위치. 본문은 `body`, 쿼리는 `query`로 시작 |
| detail[].msg | string | 검증 오류 설명 |
| detail[].type | string | 검증 오류 종류 |

각 API의 실패 표는 공통 오류 본문 형식을 사용한다. Bearer 인증 실패의 `401` 응답에는 `WWW-Authenticate: Bearer`를 포함한다.

## 2. API 목록

| 요구사항 ID | API | Method | Endpoint | 인증·권한 | 성공 |
|---|---|---|---|---|---|
| REQ-USER-001 | 회원가입 | POST | `/api/v1/users/signup` | 불필요 | 201 |
| REQ-USER-002 | 로그인 | POST | `/api/v1/users/login` | 불필요 | 200 |
| NFR-USER-001 | 토큰 재발급 | POST | `/api/v1/users/refresh` | 리프레시 쿠키 | 200 |
| REQ-USER-003 | 로그아웃 | POST | `/api/v1/users/logout` | 리프레시 쿠키 삭제 | 204 |
| REQ-USER-004 | 회원 목록 조회 | GET | `/api/v1/admin/users` | admin | 200 |
| REQ-USER-005 | 회원 권한 변경 | PATCH | `/api/v1/admin/users/role` | admin | 200 |
| REQ-USER-006 | 내 정보 조회 | GET | `/api/v1/users/me` | 모든 로그인 사용자 | 200 |
| REQ-USER-007 | 내 정보 수정 | PATCH | `/api/v1/users/me` | 모든 로그인 사용자 | 200 |
| REQ-USER-008 | 비밀번호 변경 | PATCH | `/api/v1/users/me/password` | 모든 로그인 사용자 | 204 |
| REQ-USER-009 | 회원탈퇴 | DELETE | `/api/v1/users/me` | 모든 로그인 사용자 | 204 |

총 10개 API이며, 비밀번호 입력 보안과 응답 성능 요구사항은 별도 엔드포인트가 아닌 공통 구현 기준으로 적용한다.

## 3. 회원가입 API

### 3-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-001 |
| 설명 | 사내 구성원이 계정을 생성한다. 관리자의 권한 변경 전까지 대기자로 등록한다. |
| Endpoint / Method | `/api/v1/users/signup` / `POST` |
| 인증 필요 여부 | N |

### 3-2. 요청

Headers: `Content-Type: application/json`. 쿼리 파라미터 없음.

| 본문 필드 | 타입 | 필수 | 검증·설명 |
|---|---|---|---|
| email | string | Y | 이메일 형식, 최대 255자, 앞뒤 공백 제거 및 소문자로 정규화 후 중복 검사 |
| password | string | Y | 8~64자, 영문 대문자·소문자·숫자·특수문자 각 1개 이상. 공백 불허 |
| name | string | Y | 앞뒤 공백 제거 후 2~20자 |
| department | string | Y | 공통 부서 코드 |
| gender | string | Y | `male` 또는 `female` |
| phone_number | string | Y | `010`으로 시작하는 숫자 11자리, 중복 불허 |

```json
{
  "email": "hong@example.com",
  "password": "Example123!",
  "name": "홍길동",
  "department": "medical",
  "gender": "male",
  "phone_number": "01012345678"
}
```

### 3-3. 응답

성공: `201 Created`. 본문은 1-3절의 `UserResponse` 예시와 동일하다(`role: pending`, `is_active: true`). 토큰과 쿠키는 발급하지 않는다.

| 실패 코드 | 상황 / detail |
|---|---|
| 409 | `이미 사용 중인 이메일입니다.` 또는 `이미 사용 중인 휴대폰 번호입니다.` |
| 422 | 필수 항목 누락, 형식·길이 오류, `role`·`is_active` 등 허용되지 않은 입력 |

### 3-4. 비고

비밀번호는 비밀번호 전용 해시 알고리즘으로 해싱하여 `hashed_password`에 저장한다. 중복은 사전 조회뿐 아니라 DB UNIQUE 제약 위반도 처리한다. 가입 후 로그인 화면으로 이동한다.

## 4. 로그인 API

### 4-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-002, NFR-USER-001 |
| 설명 | 이메일과 비밀번호를 검증하고 액세스·리프레시 토큰을 발급한다. |
| Endpoint / Method | `/api/v1/users/login` / `POST` |
| 인증 필요 여부 | N |

### 4-2. 요청

Headers: `Content-Type: multipart/form-data; boundary=<브라우저가 생성한 값>`. 쿼리 없음. 기존 화면의 `FormData` 요청을 따른다. JavaScript에서 Content-Type을 직접 지정하지 않는다.

| 폼 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| username | string | Y | 이메일. 회원가입과 동일하게 정규화 |
| password | string | Y | 비밀번호 원문 |

폼 데이터 예시:

```text
username=hong@example.com
password=Example123!
```

### 4-3. 응답

성공: `200 OK`.

```json
{
  "access_token": "<access-jwt>",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 1,
    "email": "hong@example.com",
    "name": "홍길동",
    "department": "medical",
    "gender": "male",
    "phone_number": "01012345678",
    "role": "pending",
    "is_active": true
  }
}
```

| 응답 필드 | 타입 | 설명 |
|---|---|---|
| access_token | string | 유효기간 30분의 JWT |
| token_type | string | `bearer` |
| expires_in | integer | 만료까지 남은 시간(초), 발급 시 `1800` |
| user | object | 공통 `UserResponse` |

| 응답 Header | 값 | 설명 |
|---|---|---|
| Set-Cookie | `refresh_token=<refresh-jwt>; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/users; Max-Age=604800` | 리프레시 토큰 7일, 운영 환경 기준 |
| Cache-Control | `no-store` | 토큰 응답 캐시 방지 |

| 실패 코드 | 상황 / detail |
|---|---|
| 401 | `이메일 또는 비밀번호가 일치하지 않습니다.` |
| 403 | 비밀번호 검증 성공 후 계정 비활성 확인: `비활성화된 사용자입니다.` |
| 422 | `username` 또는 `password` 누락·잘못된 입력 형식 |

### 4-4. 비고

대기자도 로그인과 마이페이지 이용이 가능하다. 액세스 토큰은 JSON, 리프레시 토큰은 HttpOnly 쿠키로만 전달한다. 토큰 설계는 13절을 따른다.

## 5. 액세스 토큰 재발급 API

### 5-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | NFR-USER-001 |
| 설명 | 유효한 리프레시 토큰으로 새 액세스 토큰을 발급한다. |
| Endpoint / Method | `/api/v1/users/refresh` / `POST` |
| 인증 필요 여부 | 리프레시 쿠키 필요. 액세스 토큰 불필요 |

### 5-2. 요청

| Header | 값 | 설명 |
|---|---|---|
| Cookie | `refresh_token=<refresh-jwt>` | 브라우저가 자동 전송 |

요청 본문·쿼리 없음. 리프레시 토큰을 JSON으로 보내지 않는다.

### 5-3. 응답

성공: `200 OK`.

```json
{
  "access_token": "<new-access-jwt>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

응답 필드 의미는 로그인 응답과 동일하다. `Cache-Control: no-store`를 반환한다. 이 설계는 리프레시 토큰의 최초 발급 시점부터 7일을 유지하며, 재발급 시 쿠키를 갱신하거나 만료를 연장하지 않는다.

| 실패 코드 | 상황 / detail |
|---|---|
| 401 | 쿠키 누락, 서명·종류·만료 검증 실패, 삭제된 사용자: `다시 로그인해주세요.` |
| 403 | `비활성화된 사용자입니다.` |

실패 시 리프레시 쿠키를 삭제한다. 클라이언트는 액세스 토큰을 지우고 로그인 화면으로 이동한다.

## 6. 로그아웃 API

### 6-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-003 |
| 설명 | 리프레시 쿠키를 삭제하여 현재 브라우저에서 로그아웃한다. |
| Endpoint / Method | `/api/v1/users/logout` / `POST` |
| 인증 필요 여부 | 불필요. 리프레시 쿠키가 있으면 삭제하며 액세스 토큰 만료 상태에서도 호출 가능 |

### 6-2. 요청

Headers: `Cookie: refresh_token=<refresh-jwt>`. 요청 본문·쿼리 없음. 클라이언트가 기존 액세스 토큰을 함께 보내도 된다.

### 6-3. 응답

성공: `204 No Content`. 본문 없음.

```http
Set-Cookie: refresh_token=; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/users; Max-Age=0
```

쿠키가 없거나 이미 만료된 경우도 동일하게 `204`로 응답한다. 서버에 토큰이나 세션을 저장하지 않으며, 응답으로 브라우저의 쿠키 삭제를 지시한다.

### 6-4. 비고

클라이언트는 액세스 토큰과 사용자 상태를 제거한 후 로그인 화면으로 이동한다. 다른 기기의 로그인 상태는 유지한다. 서버에서 토큰을 즉시 무효화하지 않으므로 복사된 액세스·리프레시 토큰은 만료 전까지 사용할 수 있다(13절).

## 7. 회원 목록 조회 API

### 7-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-004 |
| 설명 | 관리자가 전체 회원을 조회하고 이메일·이름 검색과 부서 필터를 적용한다. |
| Endpoint / Method | `/api/v1/admin/users` / `GET` |
| 인증 필요 여부 | Y, admin |

### 7-2. 요청

Headers: `Authorization: Bearer <access_token>`. 본문 없음.

| 쿼리 | 타입 | 필수 | 설명 |
|---|---|---|---|
| query | string | N | 앞뒤 공백 제거 후 최대 255자. 이메일 또는 이름의 대소문자 구분 없는 부분 일치 검색 |
| department | string | N | 공통 부서 코드 중 하나 |

```http
GET /api/v1/admin/users?query=hong&department=medical
Authorization: Bearer <access_token>
```

검색어와 부서 필터를 함께 보내면 AND 조건으로 적용한다. 검색어 내부는 이메일 OR 이름이다. 빈 검색어는 검색 조건 없음으로 처리한다. 부서 전체 조회 시 파라미터를 생략한다.

### 7-3. 응답

성공: `200 OK`. `UserResponse` 배열이며, `id` 오름차순으로 반환한다.

```json
[
  {
    "id": 1,
    "email": "hong@example.com",
    "name": "홍길동",
    "department": "medical",
    "gender": "male",
    "phone_number": "01012345678",
    "role": "pending",
    "is_active": true
  }
]
```

검색 결과가 없으면 `200 OK`와 `[]`를 반환한다. 비활성 계정도 목록에 포함한다.

| 실패 코드 | 상황 |
|---|---|
| 401 | 인증 누락 또는 토큰 무효 |
| 403 | admin이 아니거나 요청자 계정 비활성 |
| 422 | 잘못된 부서 값 또는 검색어 길이 초과 |

### 7-4. 비고

현재 화면이 배열을 기대하므로 이번 과제 범위는 페이지네이션 없는 목록으로 설계한다. 데이터 증가로 3초 요구사항을 충족하지 못하면 페이지네이션을 도입하고 화면·응답 명세를 함께 변경한다.

## 8. 회원 권한 변경 API

### 8-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-005 |
| 설명 | 관리자가 선택한 회원 1명의 권한을 변경한다. |
| Endpoint / Method | `/api/v1/admin/users/role` / `PATCH` |
| 인증 필요 여부 | Y, admin |

### 8-2. 요청

Headers: `Authorization: Bearer <access_token>`, `Content-Type: application/json`. 쿼리 없음.

| 본문 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| user_id | integer | Y | 변경 대상 회원 ID, 1 이상 |
| new_role | string | Y | `pending`, `staff`, `admin` |

```json
{"user_id": 1, "new_role": "staff"}
```

### 8-3. 응답

성공: `200 OK`. 변경된 회원의 `UserResponse`를 반환한다. 1-3절 예시에서 `role`이 `staff`인 형태이다.

| 실패 코드 | 상황 / detail |
|---|---|
| 400 | 자기 자신의 권한 변경: `본인의 권한은 변경할 수 없습니다.` |
| 401 | 인증 누락 또는 토큰 무효 |
| 403 | admin이 아니거나 요청자 계정 비활성 |
| 404 | `회원을 찾을 수 없습니다.` |
| 422 | 대상 ID 또는 권한 코드 오류, 필수 값 누락 |

### 8-4. 비고

동일 권한으로 변경하면 `200`과 현재 정보를 반환한다. 계정 활성 여부는 이 API로 바꾸지 않는다. 관리자 자신에 대한 변경 금지는 서버에서도 검증한다. 최초 admin은 별도 초기 데이터 작업으로 준비한다. UI는 요구사항에 따라 대상 선택 후 상단 변경 버튼으로 요청하도록 수정하며, 일괄 변경은 이번 설계 범위에 포함하지 않는다.

## 9. 마이페이지 조회 API

### 9-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-006 |
| 설명 | 로그인한 사용자가 본인 정보를 확인한다. |
| Endpoint / Method | `/api/v1/users/me` / `GET` |
| 인증 필요 여부 | Y, pending·staff·admin |

### 9-2. 요청

Headers: `Authorization: Bearer <access_token>`. 요청 본문·쿼리 없음.

### 9-3. 응답

성공: `200 OK`. 1-3절의 `UserResponse` 객체를 반환한다.

| 실패 코드 | 상황 |
|---|---|
| 401 | 인증 누락, 토큰 무효 또는 삭제된 사용자 |
| 403 | 요청자 계정 비활성 |

### 9-4. 비고

대기자도 접근 가능하다. 서버가 토큰의 사용자 ID로 조회하며 다른 회원 ID를 전달받지 않는다.

## 10. 회원 정보 수정 API

### 10-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-007 |
| 설명 | 본인의 부서·휴대폰 번호를 부분 수정한다. |
| Endpoint / Method | `/api/v1/users/me` / `PATCH` |
| 인증 필요 여부 | Y, pending·staff·admin |

### 10-2. 요청

Headers: `Authorization: Bearer <access_token>`, `Content-Type: application/json`. 쿼리 없음.

| 본문 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| department | string | N | 공통 부서 코드 |
| phone_number | string | N | `010`으로 시작하는 숫자 11자리 |

```json
{"department": "research"}
```

### 10-3. 응답

성공: `200 OK`. 변경 후의 `UserResponse` 전체를 반환한다. 예시 요청은 1-3절 응답에서 `department`가 `research`로 바뀐다.

| 실패 코드 | 상황 / detail |
|---|---|
| 400 | 빈 객체 입력: `수정할 항목을 하나 이상 입력하세요.` |
| 401 | 인증 누락 또는 토큰 무효 |
| 403 | 요청자 계정 비활성 |
| 409 | 다른 회원이 사용 중인 번호: `이미 사용 중인 휴대폰 번호입니다.` |
| 422 | null·잘못된 코드·번호 형식, 이메일·이름·권한 등 수정 불가 필드 입력 |

### 10-4. 비고

전달한 필드만 변경하고 생략한 필드는 유지한다. `null`과 빈 문자열은 허용하지 않는다. 본인이 사용하던 휴대폰 번호를 다시 보내는 것은 허용한다.

## 11. 비밀번호 변경 API

### 11-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-008 |
| 설명 | 기존 비밀번호를 검증한 뒤 새 비밀번호로 변경한다. |
| Endpoint / Method | `/api/v1/users/me/password` / `PATCH` |
| 인증 필요 여부 | Y, pending·staff·admin |

### 11-2. 요청

Headers: `Authorization: Bearer <access_token>`, `Content-Type: application/json`. 쿼리 없음.

| 본문 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| current_password | string | Y | 현재 비밀번호 |
| new_password | string | Y | 회원가입의 비밀번호 규칙과 동일 |

```json
{
  "current_password": "Example123!",
  "new_password": "Changed456!"
}
```

### 11-3. 응답

성공: `204 No Content`. 본문 없음. 로그아웃과 같은 속성으로 리프레시 쿠키를 삭제한다.

| 실패 코드 | 상황 / detail |
|---|---|
| 400 | `기존 비밀번호가 일치하지 않습니다.` 또는 `새 비밀번호는 기존 비밀번호와 달라야 합니다.` |
| 401 | 인증 누락 또는 토큰 무효 |
| 403 | 요청자 계정 비활성 |
| 422 | 필수 값 누락 또는 새 비밀번호 규칙 위반 |

### 11-4. 비고

새 비밀번호를 해싱하여 DB에 저장한다. 성공 응답에서 현재 브라우저의 리프레시 쿠키를 삭제하고, 클라이언트도 액세스 토큰을 제거한 뒤 재로그인하도록 한다. 서버의 토큰 저장소가 없으므로 기존에 발급된 토큰과 다른 기기의 로그인은 만료 전까지 유지된다.

## 12. 회원탈퇴 API

### 12-1. API 개요

| 항목 | 내용 |
|---|---|
| 요구사항 ID | REQ-USER-009 |
| 설명 | 본인 계정을 즉시 삭제하고, 기존 X-ray의 업로더 참조를 NULL로 변경하여 진료 데이터를 보존한다. |
| Endpoint / Method | `/api/v1/users/me` / `DELETE` |
| 인증 필요 여부 | Y, pending·staff·admin |

### 12-2. 요청

Headers: `Authorization: Bearer <access_token>`. 브라우저는 리프레시 쿠키도 자동 전송한다. 요청 본문·쿼리 없음. `Content-Type` 불필요.

### 12-3. 응답

성공: `204 No Content`. 본문 없음. 액세스 토큰이나 사용자 정보를 반환하지 않는다.

```http
Set-Cookie: refresh_token=; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/users; Max-Age=0
```

| 실패 코드 | 상황 |
|---|---|
| 401 | 인증 누락, 토큰 무효 또는 이미 삭제된 사용자 |
| 403 | 요청자 계정 비활성 |
| 500 | 회원 삭제 트랜잭션 실패. 성공 응답을 반환하지 않음 |

### 12-4. 삭제 범위와 처리 기준

이번 과제에서는 사용자 요청에 따라 회원 행만 삭제하고 진료 데이터는 보존한다. 원래 요구사항의 “회원과 관련된 정보는 모두 즉시 삭제”에서 X-ray·진료 데이터는 보존하는 것으로 삭제 범위를 구체화한 설계이다.

| 대상 | 처리 |
|---|---|
| 본인 `users` 행 | 즉시 물리 삭제. 소프트 삭제로 대체하지 않음 |
| 본인이 업로드한 `xray_images` 행 | 보존. `uploader_id`를 `NULL`로 변경 |
| X-ray 원본 파일 | 보존 |
| AI 판독 결과 및 히트맵 | 보존 |
| 환자 및 진료 기록 | 보존 |
| 현재 브라우저의 인증 정보 | 리프레시 쿠키 삭제, 클라이언트 액세스 토큰 제거 |

`xray_images.uploader_id`를 NULL 허용으로 변경하고, `users.id`를 참조하는 외래키에 `ON DELETE SET NULL`을 적용한다. 사용자 삭제와 업로더 참조 해제는 같은 DB 트랜잭션에서 처리하며 커밋 완료 후 `204`를 반환한다. 실패 시 롤백하고 `500`을 반환한다. X-ray 조회 화면은 업로더가 없을 때 “탈퇴한 사용자”로 표시한다.

파일을 삭제하지 않으므로 파일 삭제·재시도·복구 절차는 이번 범위에서 제외한다. 삭제된 사용자 ID를 담은 토큰은 서명·만료가 유효하더라도 사용자 DB 조회에서 거부한다.

탈퇴 완료 후 클라이언트는 인증 상태를 제거하고 로그인 화면으로 이동한다. 관리자 탈퇴도 허용한다. 마지막 관리자 보호 정책은 현재 요구사항에 없으므로 추가하지 않는다.

## 13. 인증·보안 및 성능 공통 설계

### 13-1. JWT와 HttpOnly 쿠키 (NFR-USER-001)

| 항목 | 기준 |
|---|---|
| 액세스 토큰 | 유효기간 30분(1,800초), Bearer 방식 |
| 리프레시 토큰 | 유효기간 7일(604,800초), HttpOnly 쿠키 |
| 개인정보 | payload에 이름·이메일·전화번호·부서·권한을 넣지 않음 |
| 사용자 식별 | `user_id`만 사용자 식별 정보로 사용 |
| 검증 메타데이터 | `exp`(만료), `iat`(발급), `token_type`(access/refresh) 포함 |
| 토큰 종류 검증 | 액세스용 API에 리프레시 토큰을 사용하거나 그 반대로 사용하는 것을 거부 |
| 서명 검증 | 서버에서 설정한 알고리즘·키로 검증. 키는 환경 변수 등으로 관리 |
| 서버 저장소 | 세션 저장소·토큰 저장 테이블·토큰 차단 목록은 이번 범위에서 제외 |
| 사용자 확인 | 인증 요청과 토큰 재발급마다 DB에서 사용자 존재 여부·활성 상태를 확인하고, 권한이 필요한 API는 현재 DB 권한을 확인 |

“payload에는 user_id만 저장”은 **사용자 개인정보는 user_id만 포함**한다는 의미로 해석했다. 토큰 만료와 종류 검증에 필요한 메타데이터는 별도로 포함한다. 이 해석을 엄격한 user_id 단일 필드 제한으로 바꾸면 토큰 만료·종류를 검증하는 설계도 변경해야 한다.

```json
{
  "user_id": 1,
  "exp": 1790001800,
  "iat": 1790000000,
  "token_type": "access"
}
```

시각은 형식을 설명하기 위한 Unix timestamp 예시다. 로그인 시 JWT를 발급하고, 서버에 토큰 원문·해시·세션을 저장하지 않는다. 재발급 시 쿠키의 리프레시 JWT 자체를 검증한다.

로그아웃과 비밀번호 변경은 현재 브라우저의 쿠키·액세스 토큰을 제거하는 방식이다. 이미 복사된 토큰이나 다른 기기의 토큰을 즉시 무효화하는 기능은 이번 범위에서 제외하며, 해당 토큰은 만료 전까지 유효하다. 탈퇴한 사용자는 매 요청과 재발급에서 DB 존재 여부를 확인하여 차단한다.

### 13-2. 쿠키 및 브라우저 처리

- 운영 환경은 `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/users`를 사용하고 Domain을 지정하지 않는다.
- 쿠키 삭제 시 발급 시점과 같은 Path·Domain 범위를 사용한다.
- 로컬 HTTP 개발에 한해 Secure를 비활성화하는 설정을 분리한다.
- 현재처럼 화면과 API가 동일 출처인 구성을 기준으로 한다. 쿠키를 쓰는 변경 요청은 허용된 Origin인지 검증한다.
- 리프레시 토큰은 JavaScript나 JSON 응답으로 노출하지 않는다. 재발급 실패 시 무한 재시도하지 않고 로그인 화면으로 이동한다.

### 13-3. 비밀번호 입력 보안 (NFR-USER-002)

회원가입·로그인·비밀번호 변경의 모든 비밀번호 입력은 기본적으로 `type="password"`로 마스킹한다. 보기 아이콘으로 해당 입력의 표시 여부를 전환한다. 이 요구사항은 화면에서 구현하며, 비밀번호를 응답하거나 로그에 남기지 않는다.

### 13-4. 응답 성능 (NFR-USER-003)

모든 USER API는 서버가 요청을 수신한 시점부터 응답을 준비할 때까지 최대 3초 이내 처리를 목표로 한다. DB 조회·변경과 토큰 검증 시간도 포함하며 클라이언트 네트워크 전송 시간은 제외한다. `3초가 지나면 성공을 반환`하는 의미는 아니다.

과제 검증 시 테스트 장비, 회원 수, 동시 요청 수, 회원별 X-ray 참조 수를 기록하고 정상·검색·오류·탈퇴 요청의 처리 시간을 측정한다. 입력 데이터량·부하 조건이 주어지지 않은 현재 상태에서는 무조건 3초를 보장했다고 판단하지 않는다. 특히 전체 목록과 X-ray 참조가 많은 회원의 탈퇴는 부하 검증 후 쿼리·인덱스를 조정한다. 파일 삭제·복구 작업은 이번 API 범위에서 제외한다.

## 14. 현재 코드에서 변경할 사항

| 대상 | 현재 상태 | 이 명세를 구현할 때 필요한 변경 |
|---|---|---|
| `users.department` | `radiology`, `administration` | `research`, `medical`, `development`로 변경. 기존 값은 의미가 일치하지 않아 임의 변환하지 않고 데이터 매핑 결정 후 새 마이그레이션 작성 |
| `users.role` | `admin`, `doctor`, `user` | `pending`, `staff`, `admin`으로 변경하고 기존 데이터의 권한 매핑 검토 |
| 필수 사용자 컬럼 | email·hashed_password·name·phone_number가 nullable | 기존 데이터 점검 후 NOT NULL 전환 |
| 가입 기본값 | role 기본값 없음 | 서버에서 pending 지정, is_active=true |
| 인증 저장소 | 없음 | 추가하지 않음. JWT 검증과 HttpOnly 쿠키 방식 사용 |
| 삭제 연관 관계 | uploader_id가 NOT NULL이며 삭제 정책 없음 | nullable로 변경하고 외래키에 ON DELETE SET NULL 적용. ORM 업로더 관계도 선택형으로 변경하여 DB 정책과 일치시킴 |
| 프런트엔드 부서 값 | `developer`, `medical team`, `researcher` | 공통 부서 코드로 변경 |
| 관리자 목록 화면 | 일부 요구 필드 누락 | ID·성별·계정 활성 여부를 포함해 요구사항의 전체 항목 표시 |
| 권한 변경 화면 | 행별 드롭다운 변경 시 즉시 호출 | 대상 선택 + 상단 권한 변경 버튼 방식 적용 |
| 비밀번호 변경 화면 | 성공 후 화면에서 재로그인 처리 필요 | 현재 브라우저의 쿠키 삭제 응답에 맞춰 액세스 토큰 삭제·로그인 이동 |
| 실제 USER API | `/practice_api` 연습용 CRUD만 등록 | schemas → repositories → services → apis 구현 후 main.py에 등록 |

기존에 공유한 초기 마이그레이션은 수정하지 않고 새 리비전을 추가한다. 이 문서는 설계 명세이며 위 코드·DB 변경을 완료했다는 의미는 아니다.

## 15. 구현 확인 항목

| 요구사항 | 확인할 동작 |
|---|---|
| REQ-USER-001 | 필수 필드·중복 검증, 해시 저장, pending 가입, 권한 주입 거부 |
| REQ-USER-002 | 정상 로그인, 잘못된 자격 증명, 비활성 계정 차단 |
| NFR-USER-001 | 만료·위조·종류가 다른 토큰 거부, 쿠키 전용 전달, 재발급, 삭제·비활성 사용자 차단 |
| REQ-USER-003 | 로그아웃 시 쿠키·클라이언트 상태 제거, 쿠키가 없어도 204 응답 |
| REQ-USER-004 | admin 전용, 이메일·이름 검색, 부서 필터 조합, 빈 목록 |
| REQ-USER-005 | 권한 변경 즉시 반영, 자기 권한 변경 금지, 잘못된 대상·권한 거부 |
| REQ-USER-006 | pending 포함 본인 정보 조회, 비밀번호 필드 미노출 |
| REQ-USER-007 | 부분 수정, 생략 필드 유지, 중복 번호·null·변경 불가 필드 거부 |
| REQ-USER-008 | 기존 비밀번호 검증, 새 비밀번호 해시 저장, 현재 브라우저 쿠키·토큰 제거 |
| REQ-USER-009 | 사용자 물리 삭제, uploader_id SET NULL, X-ray·AI 결과·파일 보존, 탈퇴 사용자 토큰 차단 |
| NFR-USER-002 | 모든 비밀번호 입력의 마스킹·보기 전환 |
| NFR-USER-003 | 기록된 데이터·부하 조건에서 최대 3초 처리 여부 측정 |

---

## 16. 팀 기여도

| 번호 | 담당 | 구현 내용 | PR |
|---|---|---|---|
| 1번 | 강선영 | 회원가입, 비밀번호 해싱 공통 기능 | |
| 2번 | 최현영 | 로그인, JWT 발급·검증·재발급·로그아웃 | #18 |
| 3번 | 소혜진 | 관리자 회원 목록 조회, 권한 변경 | |
| 4번 | 김지영 | 마이페이지 조회·정보 수정, 비밀번호 변경, 회원 탈퇴 | |
| - | 서민서 | 병가 | |
