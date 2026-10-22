# 2일차 Git Branch 전략

## 목차

1. 브랜치 전략이란?
2. Git Flow
3. GitHub Flow
4. Git Flow vs GitHub Flow
5. PR과 코드 리뷰
6. 충돌(Conflict) 해결
7. 우리 팀의 선택과 규칙
8. 참고자료

---

## 1. 브랜치 전략이란?

여러 명이 하나의 저장소에서 같이 작업할 때 **브랜치를 어떻게 만들고, 어떻게 합칠지 정한 규칙(workflow)** 이다.
프로젝트 규모와 팀 상황에 맞는 전략을 고르는 게 중요하다.

> 🍳 **비유: 브랜치 = 내 조리대**
> 한 주방(저장소)에서 요리사 여러 명이 한 냄비에 동시에 재료를 넣으면 요리가 엉망이 된다.
> 그래서 각자 **자기 조리대(브랜치)** 에서 요리하고, 다 되면 검사받고 **완성 접시(main)** 에 올린다.

### 브랜치 전략이 필요한 이유

- **독립적인 작업**: 각자 다른 브랜치에서 작업하니 서로의 코드에 영향을 주지 않는다
- **작업 추적**: 브랜치가 기능·이슈 단위로 나뉘어 누가 무엇을 했는지 쉽게 알 수 있다
- **되돌리기(Rollback)**: 문제가 생기면 해당 작업 단위만 되돌릴 수 있다
- **배포 안정성**: 태그(v1.0 등)로 배포 버전을 관리할 수 있다

### 자주 나오는 용어

| 용어 | 뜻 | 비유 |
|---|---|---|
| Repository | 프로젝트 저장소 | 팀 공유 폴더 |
| Branch | 독립된 작업 공간 | 원본 문서를 복사한 내 사본 |
| Commit | 변경 내용 저장 | 게임 세이브 포인트 |
| Push | 원격 저장소에 올리기 | 내 사본을 공유 폴더에 업로드 |
| Pull | 원격의 최신 내용 받기 | 공유 폴더의 최신본 다운로드 |
| PR (Pull Request) | 내 브랜치를 합쳐달라는 요청 | 보고서 결재 올리기 |
| Review | 코드 검토 | 선배가 결재 전 검토하기 |
| Merge | 브랜치 합치기 | 결재 완료 후 원본에 반영 |
| Rebase | 내 커밋을 최신 브랜치 위로 옮겨 쌓기 | 최신 원본 위에 내 수정사항 다시 얹기 |
| Conflict | 같은 부분을 서로 다르게 고쳐서 생긴 충돌 | 같은 문장을 두 사람이 다르게 고친 상황 |

---

## 2. Git Flow

**Vincent Driessen이 2010년에 제안**한 브랜치 모델이다.
브랜치를 역할별로 나눠서 **체계적이고 엄격하게 버전을 관리**하는 것이 핵심이다.

### 브랜치 종류

| 브랜치 | 역할 | 어디서 만들고 → 어디로 합치나 |
|---|---|---|
| `main` (`master`) | 실제로 배포된 최종 코드 | - |
| `develop` | 다음 출시를 위해 개발 중인 기능들을 모으는 브랜치 | `main`에서 생성 |
| `feature/*` | 새로운 기능 개발 | `develop` → `develop` |
| `release/*` | 배포 전 테스트(QA), 버그 수정 | `develop` → `main`, `develop` |
| `hotfix/*` | 배포 후 발견된 긴급 버그 수정 | `main` → `main`, `develop` |

> 🍽️ **비유: 큰 레스토랑 주방**
> - `main` = 손님 테이블에 나간 요리
> - `develop` = 주방에서 준비 중인 요리들
> - `feature` = 요리사 각자의 조리대
> - `release` = 서빙 전 셰프가 맛보고 점검하는 단계
> - `hotfix` = 손님 테이블에서 문제가 생겨 급히 바꿔주는 것
>
> 단계가 많아서 느리지만, 손님에게 이상한 요리가 나갈 일이 적다.

### 작업 흐름

```
main     ──●──────────────────────●──────●──   (v1.0)  (v1.0.1)
            \                    /      /
hotfix       \                  /   ●──●
              \                /         \
release        \           ●──●           \
                \         /    \           \
develop          ●───●───●──────●───────────●──
                  \     /
feature/login      ●───●
```

1. **기능 개발**: `develop`에서 `feature` 브랜치를 만들어 기능을 개발한다
2. **develop에 합치기**: 개발이 끝나면 PR을 올리고, 리뷰를 받은 뒤 `develop`에 Merge
3. **배포 준비**: 출시할 때가 되면 `develop`에서 `release` 브랜치를 만들어 테스트한다
   - 테스트 중 발견된 버그는 `release` 브랜치에서 바로 고친다
4. **배포**: 테스트가 끝나면 `release`를 `main`에 Merge하고 버전 태그를 붙인다
   - **`develop`에도 꼭 Merge** 해야 다음 개발이 안정된 버전에서 이어진다
5. **긴급 수정**: 배포 후 버그가 생기면 `main`에서 `hotfix`를 만들어 고친다
   - 수정이 끝나면 `main`과 `develop` 둘 다에 Merge

### 실무 사례에서 배운 팁 (현업 Git Flow 글 참고)

- **환경별 테스트**: `develop`은 개발 서버(알파 QA), `release`는 배포 직전 서버(베타 QA)에 올려서 단계별로 테스트한다
- **이슈 번호로 브랜치 이름 짓기**: GitHub에 이슈를 먼저 등록하고, 이슈 번호로 브랜치를 만든다 (예: `feature/10`)
  - 커밋 메시지에도 `[#10] 로그인 API 추가`처럼 번호를 붙이면 나중에 이력 찾기가 쉽다
- **큰 기능은 부모-자식 브랜치로 나누기**: `feature/10`(부모)에서 `feature/10-1`(자식)을 만들어 작업하고, 자식 → 부모로 PR을 올릴 때 리뷰한다
- **브랜치 수시로 최신화하기**: 작업 중 기준 브랜치가 바뀌면 `git pull --rebase`로 내 브랜치를 최신 상태로 맞춰 충돌을 줄인다
- **배포 후엔 꼭 동기화**: `main`에 배포한 뒤 `develop`, `release`에도 반영하지 않으면 나중에 큰 충돌이 생긴다

### 장단점

- 👍 배포 버전과 개발 버전이 확실히 나뉘어 안정적이다
- 👍 버전 관리, 롤백 등 체계적인 운영이 가능하다
- 👎 브랜치가 많아 관리가 복잡하다
- 👎 급하게 기능을 배포해야 할 때 유연성이 떨어진다
- 👎 작은 팀이나 개인 프로젝트에는 과하다

---

## 3. GitHub Flow

**GitHub에서 제안**한 브랜치 모델이다.
`main` 브랜치 하나와, 거기서 분기한 작업 브랜치만으로 운영하는 **단순하고 빠른 방식**이다.

### 브랜치 종류

| 브랜치 | 역할 |
|---|---|
| `main` | 항상 배포 가능한 상태를 유지하는 단 하나의 핵심 브랜치 |
| `feature/*` | 모든 작업(기능 추가, 버그 수정 등)을 하는 브랜치 |

> 🚚 **비유: 푸드트럭**
> 요리사가 메뉴를 만들면(feature) 사장님이 바로 맛보고(Review) OK면 바로 판매(main)한다.
> 점검 단계가 적어서 빠르지만, 사장님이 대충 맛보면 맛없는 메뉴가 그대로 나갈 수 있다.

### 작업 흐름

```
main            ──●──────────●──────────●──
                   \        /  \       /
feature/count       ●──●───     \     /
feature/increase                 ●───●
```

1. `main`에서 작업 목적이 드러나는 이름으로 브랜치를 만든다 (`feature/count`)
2. 작업 후 commit, 원격에 push
3. GitHub에서 PR을 만들고 팀원을 리뷰어로 지정한다
4. 리뷰 피드백을 반영해 다시 commit, push (같은 PR에 자동으로 추가된다)
5. 승인(Approve)을 받으면 `main`에 Merge
6. Merge 후 로컬 `main`을 최신화하고 다음 작업을 시작한다

### 주요 특징

- 단일 핵심 브랜치(`main`)만 사용
- 모든 작업은 `main`에서 분기한 브랜치에서 하고 빠르게 병합
- PR과 코드 리뷰를 거쳐서 병합
- 이슈, 라벨, 마일스톤 등 GitHub 기능을 활용해 협업
- 지속적 배포(CI/CD)로 빠르게 피드백을 받는다

### 장단점

- 👍 구조가 단순해서 배우기 쉽고 빠르게 개발할 수 있다
- 👍 PR 중심이라 코드 리뷰 문화가 자연스럽게 생긴다
- 👎 별도의 테스트 브랜치 없이 `main`에 바로 합쳐지므로 리뷰가 부실하면 위험하다
- 👎 명시적인 릴리스 관리가 없어 대규모 프로젝트에는 맞지 않는다

---

## 4. Git Flow vs GitHub Flow

| 구분 | Git Flow | GitHub Flow |
|---|---|---|
| 제안 | Vincent Driessen (2010) | GitHub |
| 브랜치 | main, develop, feature, release, hotfix | main, feature |
| 복잡도 | 높음 | 낮음 |
| 배포 방식 | release·hotfix를 거치는 정해진 절차 | main에서 수시로 배포 |
| 안정성 | 단계별 테스트로 높음 | 리뷰·테스트에 의존 |
| 속도 | 느림 | 빠름 |
| 어울리는 곳 | 대규모 프로젝트, 정기 배포하는 제품(앱 등) | 소규모 팀, 웹 서비스, 짧은 프로젝트 |

> 💡 정답은 없다. **프로젝트 규모, 요구사항, 팀의 작업 방식**에 맞춰 고르면 된다.

---

## 5. PR과 코드 리뷰

### PR 만들기

1. 작업 브랜치를 push한다
2. GitHub 저장소 → **Pull requests** → **New pull request**
3. **base**(합쳐질 곳, 예: `main`) ← **compare**(내 브랜치) 지정
4. **Able to merge** 표시가 뜨면 충돌 없이 합칠 수 있다는 뜻
5. 제목·설명 작성, **Reviewers**(리뷰어), **Assignees**(담당자), **Labels**(라벨) 지정 후 생성

### 리뷰하기

- **Files changed** 탭에서 바뀐 코드를 보고, 줄마다 `+` 버튼으로 댓글을 단다
- 다 쓰면 **Finish your review**로 제출하고 리뷰 타입을 고른다

| 리뷰 타입 | 의미 |
|---|---|
| Comment | 의견만 남김 (승인 아님) |
| Approve | 병합해도 좋다고 승인 |
| Request changes | 병합 전에 꼭 고쳐야 할 점이 있음 |

> 💬 리뷰는 비난하지 말고, 이유와 대안을 함께 제시하기!

- 피드백을 반영했으면 작성자가 **Resolve conversation**을 누르고 다시 리뷰를 요청한다
- 새로 고친 부분은 **Commits** 탭에서 최신 커밋만 골라 보면 편하다

### 병합(Merge) 옵션 3가지

| 옵션 | 동작 | 특징 |
|---|---|---|
| Create a merge commit (기본) | 모든 커밋 + 병합 커밋 1개 추가 | 병합 이력이 명확하게 남는다 |
| Squash and merge | 모든 커밋을 1개로 압축해서 추가 | 깔끔하지만 세부 이력은 사라진다 |
| Rebase and merge | 커밋들을 그대로 한 줄로 이어 붙임 | 직관적이지만 충돌이 복잡해질 수 있다 |

### main 브랜치 보호하기 (선택)

저장소 **Settings → Rules → Rulesets**에서 `main`에 규칙을 걸 수 있다. (무료 계정은 Public 저장소만 가능)

- **Require a pull request before merging**: PR 없이 `main`에 직접 push 금지
- **Required approvals**: 최소 승인 인원 지정 (예: 1명)
- **Require conversation resolution**: 모든 리뷰 댓글이 해결돼야 병합 가능

### 이슈와 연결하기 (선택)

- **Issues** 탭에서 할 일을 이슈로 만들면 `#5`처럼 번호가 붙는다
- 커밋 메시지나 PR에 `close #5`를 쓰면 Merge될 때 이슈가 자동으로 닫힌다 (`fix`, `resolve`도 가능)

---

## 6. 충돌(Conflict) 해결

같은 파일의 **같은 줄**을 서로 다른 브랜치에서 고치면 충돌이 난다.
`pull`, `merge`, `rebase`, `cherry-pick` 할 때 생각보다 자주 생긴다.

> 📝 **비유: 같은 문장을 두 사람이 다르게 고친 공유 문서**
> A는 "안녕하세요"로, B는 "반갑습니다"로 고쳤다면 Git은 어느 쪽이 맞는지 모른다.
> 그래서 사람에게 "둘 중 뭘 쓸지 골라줘!" 하고 물어보는 게 충돌이다.

### 예시 상황

```
# 원격 develop (다른 팀원이 A 파일 수정 후 push)
A ─── B ─── C            ← C 커밋에서 A 파일 수정

# 내 feature/login
A ─── B ─── L1 ─── L2    ← 내 커밋도 A 파일의 같은 줄 수정
```

이 상태에서 `git pull --rebase origin develop`을 하면 충돌이 난다.
rebase는 develop의 최신 커밋(C) 위에 내 커밋(L1, L2)을 다시 쌓는 작업인데, 같은 줄을 둘 다 고쳤기 때문이다.

### 충돌 표시 읽는 법

```
<<<<<<< HEAD
print("hello")    ← 이미 반영된 코드 (develop의 C 커밋)
=======
print("hi")       ← 내가 쌓으려는 코드 (L1 커밋)
>>>>>>> L1
```

### 해결 순서

1. 남길 코드만 두고 `<<<<<<<`, `=======`, `>>>>>>>` 줄은 모두 지운다
2. `git add 수정한파일` 로 스테이징
3. 이어서 진행
   - rebase 중이면 `git rebase --continue`
   - merge 중이면 `git commit`
4. 너무 헷갈리면 `git rebase --abort` (또는 `git merge --abort`)로 이전 상태로 되돌린다

> 💡 GitHub PR 화면에서 **Resolve conflicts** 버튼으로 웹에서 바로 고칠 수도 있다.
> VS Code에서는 **현재 변경 사항 / 수신 변경 사항 / 둘 다 수락** 버튼으로 쉽게 고를 수 있다.

### 충돌 해결의 핵심

- 가장 좋은 방법은 **그 코드를 쓴 팀원과 이야기해서** 정하기
- 그럴 수 없으면 코드 흐름을 읽고 맞는 쪽을 판단하기
- 충돌이 자주 나는 브랜치는 **기준 브랜치를 자주 pull** 받아 최신화하기

---

## 7. 우리 팀의 선택: GitHub Flow

### 선택 이유

- 팀 규모가 작고 프로젝트 기간이 짧다
- 별도의 배포 단계(release, hotfix)가 필요 없다
- Git 협업이 처음이라 **PR → 리뷰 → Merge** 흐름부터 확실히 익히는 게 좋다

### 브랜치 이름 규칙

| 접두어 | 용도 | 예시 |
|---|---|---|
| `feature/` | 새 기능 | `feature/practice-api` |
| `fix/` | 버그 수정 | `fix/login-error` |
| `docs/` | 문서 작업 | `docs/branch-strategy` |

### 커밋 메시지 규칙

| 태그 | 의미 | 예시 |
|---|---|---|
| `feat:` | 기능 추가 | `feat: 사용자 조회 API 추가` |
| `fix:` | 버그 수정 | `fix: 응답 코드 오류 수정` |
| `docs:` | 문서 수정 | `docs: 브랜치 전략 문서 추가` |
| `refactor:` | 코드 구조 개선 | `refactor: 라우터 분리` |
| `chore:` | 설정, 패키지 등 기타 | `chore: requirements.txt 추가` |

### 협업 규칙

- `main`에 직접 push 하지 않고 반드시 PR로 합친다
- PR에는 무엇을, 왜 바꿨는지 간단히 적는다
- 팀원 1명 이상 Approve 후 Merge 한다
- 작업 시작 전과 PR 올리기 전에 `main`을 pull 받아 최신화한다
- Merge가 끝난 브랜치는 삭제해서 목록을 깔끔하게 유지한다

### 작업 순서

```bash
# 1. main 최신화
git switch main
git pull origin main

# 2. 작업 브랜치 만들고 이동
git switch -c feature/기능명

# 3. 작업 후 커밋
git status
git add .
git commit -m "feat: 기능 설명"

# 4. 작업 중 main이 바뀌었다면 최신 내용 반영
git pull --rebase origin main

# 5. 원격에 올리기
git push origin feature/기능명

# 6. GitHub에서 PR 생성 → 리뷰 → Approve → Merge

# 7. 정리
git switch main
git pull origin main
git branch -d feature/기능명
```

> 💡 기본 브랜치 이름이 `master`로 되어 있다면 `git branch -m main`으로 바꿀 수 있다.

---

## 8. 참고자료

- [주니어 개발자의 현업에서 배운 Git Flow](https://velog.io/@myoungji-kim/git-flow)
- [Git Branch 전략 비교 - Git Flow vs GitHub Flow](https://devocean.sk.com/blog/techBoardDetail.do?ID=165571&boardType=techBlog)
- [사례로 이해하는 GitHub Flow](https://www.heropy.dev/p/6hdJi6)
- [A successful Git branching model (Git Flow 원문)](https://nvie.com/posts/a-successful-git-branching-model/)
- 오즈코딩스쿨 Git Command 학습 자료 / Git 시스템을 활용한 프로젝트 버전 관리
