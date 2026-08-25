<div align="center">

# notion-logger

**어떤 코딩 에이전트든, 대화가 끝나면 노션에 자동 기록**

Antigravity · opencode 지원 — hook 한 줄 연결로
사용자 요청 → 툴 사용 내역 → 최종 응답을 노션 데이터베이스에 턴 단위로 쌓아준다.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#os-호환성)
[![Notion](https://img.shields.io/badge/API-Notion%20Data%20Cloud-black?logo=notion)](https://developers.notion.com/)
[![License](https://img.shields.io/badge/license-unspecified-orange)](#라이선스)

</div>

---

## ✨ 동작 방식

```
에이전트 hook 발동 (턴 종료 시)
   └─ stdin으로 JSON payload 전달
        └─ run.py: 어댑터 감지 → transcript 파싱
             └─ 미기록 턴마다 노션 DB 행 1개 생성
```

- **한 행 = 한 번의 대화(턴)** — `Session ID` + `Turns`(세션 내 순번) 컬럼으로
  하나의 세션이 시간순 대화 목록처럼 재생된다.
- **노션이 진실의 원천** — 매 실행마다 기록된 `Turns` 번호를 노션에서 조회해
  없는 번호만 생성. 로컬 state 파일 없음 → 프롬프트 컴팩션 등으로
  트랜스크립트가 재작성돼도 중복·누락 없음.
- **저비용 게이트** — 새 턴 여부를 JSON 파싱 없이 문자열/SQL 스캔으로 먼저
  판별. 트랜스크립트가 아무리 길어져도 새 턴이 없으면 수 ms 만에 종료.
- **시간 이중 기록** — `Created At` = 실제 대화 시각, `Last At` = 기록 시각.
- **마크다운 렌더링** — 헤딩/목록/표/코드블록/굵게/링크를 노션 블록으로 변환.
- **안전장치** — 동시 실행 락, 실패 시 조용히 로그만 남김(에이전트 작업 비방해).

## 📦 요구 사항

| 항목 | 내용 |
|---|---|
| Python | **3.10+** |
| 의존성 | `requests` 하나 (`pip install -r requirements.txt`) |
| 노션 | 인테그레이션(API 키) + 데이터베이스 |

## 🚀 시작하기

### 1. 노션 준비

1. [인테그레이션 만들기](https://www.notion.so/profile/integrations)
   → **내부 통합 시크릿**(`ntn_...`) 복사
2. 노션에서 데이터베이스 생성 → DB가 있는 페이지 `⋯` → **연결(Connections)** →
   인테그레이션 추가 *(빼먹으면 404)*
3. DB를 full page로 열고 URL 마지막 **32자리 영숫자** = 데이터베이스 ID

### 2. 설정

저장소 루트에 `.env` 생성 (**절대 커밋 금지**):

```dotenv
NOTION_API_KEY=ntn_여기에_발급받은_키
NOTION_DATABASE_ID=32자리_DB_ID
```

컬럼 자동 생성 (멱등 — 몇 번을 실행해도 안전):

```bash
python setup_notion_db.py    # macOS/Linux: python3
```

### 3. 에이전트 연결

#### Antigravity

`~/.gemini/config/hooks.json`:

```json
{
  "notion-auto-logger": {
    "Stop": [
      {
        "type": "command",
        "command": "python C:/dev/notion-logger/run.py antigravity",
        "timeout": 120
      }
    ]
  }
}
```

- `run.py`는 **절대경로**, 끝에 에이전트 이름 지정 (`run.py antigravity`).
  이름 생략 시 payload 지문으로 자동 감지(폴백).
- macOS/Linux는 `python3` 사용.
- `timeout`은 넉넉히 (권장 120). 짧으면 처리 중 강제 종료되지만 턴 단위로
  이어 기록되므로 다음 훅에서 계속된다.
- 설정 후 에이전트 **재시작** 필요.

#### opencode

opencode는 트랜스크립트 파일 대신 SQLite DB + 플러그인 방식을 쓴다.

1. **경로 설정** — `plugin/session-logger.js` 상단의 `RUN_PATH`를 본인 환경에 맞게 수정
   *(미수정 시 플러그인 무기능)*:

   ```js
   const RUN_PATH = "/Users/me/dev/notion-logger/run.py"; // ← 본인 경로
   ```

2. **등록** — `~/.config/opencode/opencode.jsonc`:

   ```jsonc
   {
     "$schema": "https://opencode.ai/config.json",
     "plugin": [
       "file:///절대경로/notion-logger/plugin/session-logger.js"
     ]
   }
   ```

   또는 `plugin/session-logger.js`를 `~/.config/opencode/plugins/` 아래에 복사.
   **둘 중 한 곳에만** 등록할 것 (중복 등록 시 같은 턴이 두 번 기록됨).

3. opencode 재시작 → 대화 1턴 → 노션 확인.

> 플러그인은 세션 유휴(`session.idle`) 시점에 `run.py opencode`를 호출하고,
> 어댑터가 DB를 readonly로 읽어 파싱한다.

#### 다른 에이전트 추가하기

`notion_logger/adapters/base.py::Adapter` 상속 후 구현,
`adapters/__init__.py` `_ADAPTERS`에 이름과 함께 등록:

| 메서드 | 역할 |
|---|---|
| `matches(payload)` | payload 지문 판별 (폴백) |
| `context(payload)` | 프로젝트명 / 세션 ID 추출 |
| `count_turns(payload)` | 총 턴 수 저비용 카운트 (JSON 파싱 금지) |
| `parse_turns(payload, numbers)` | 요청 순번의 턴만 파싱 |

## 🗂 노션 스키마

| 컬럼 | 의미 |
|---|---|
| `Session ID` / `Turns` | 세션 식별 / 세션 내 턴 순번 |
| `Created At` / `Last At` | 실제 대화 시각 / 기록 시각 |
| `Agent` / `Project` / `Host/Device` | 어느 에이전트·프로젝트·머신 |
| `Status` / `Work Type` | 성공·실패 / 작업 유형 자동 분류 |
| `Tool Calls` · `Commands` · `Files Read` · `Files Changed` · `Errors` | 턴 통계 |

추천 정렬 — **최근 활동**: `Last At` 내림차순 ·
**세션 흐름**: `Session ID` 오름차순 → `Turns` 오름차순

페이지 본문: 📝 사용자 요청 → ⚙️ 작업 내역(툴 호출 상세) → 📤 실행 결과 → ❌ 에러 → 📝 최종 응답

## 🔧 문제 해결

| 증상 | 확인할 곳 |
|---|---|
| 노션에 안 들어감 | 저장소 `tmp/logger.log` — 훅 실행 여부, 오류 메시지 |
| 훅 호출 여부 확인 | `debug_hook.py`를 잠시 command로 연결 → stdin 덤프 |
| 404 object_not_found | DB가 인테그레이션에 연결 안 됨 |
| 컬럼이 비어있음 | DB에 같은 이름 컬럼 없음 → `setup_notion_db.py` 재실행 |
| opencode 트리거 안 됨 | `tmp/opencode_plugin.log` — 플러그인 로드/이벤트 추적 |

## 🖥 OS 호환성

- 경로 처리 전부 `pathlib`, stdin 바이트 읽기 + UTF-8 디코딩 → Windows(cp949) / macOS / Linux 동작
- 로그는 항상 UTF-8
- opencode DB는 readonly(SQLite URI `mode=ro`)로 열어 본체와 충돌 없음
- 실행 파일 이름 주의: Windows `python`, macOS/Linux `python3`

## 🧪 개발

```bash
python test_connection.py   # 노션 연결 + 테스트 페이지 생성
python test_md2notion.py    # 마크다운 변환 렌더링 확인
python test_adapter.py      # 실제 세션 파싱 → 페이지 생성 전체 흐름
```

### 구조

```
notion_logger/
├── adapters/          # 에이전트별 payload/transcript 파서
│   ├── base.py        #   공통 인터페이스 (Turn/Event/Adapter)
│   ├── antigravity.py #   Google Antigravity (JSONL transcript)
│   └── opencode.py    #   opencode (SQLite DB)
├── pipeline.py        # 게이트 → 조회 → 미기록 턴 생성
├── render.py          # 통계/속성/본문 블록 생성
├── md2notion.py       # 마크다운 → 노션 블록 변환
├── notion_api.py      # 노션 REST 최소 클라이언트
└── config.py          # .env 로딩
plugin/
└── session-logger.js  # opencode session.idle 트리거
run.py                 # 훅 진입점 (stdin → pipeline)
```

### 브랜치

| 브랜치 | 구조 |
|---|---|
| `master` | **한 행당 한 대화(턴)** — 권장 |
| `session-per-page` | 세션당 페이지 1개, 타임라인 append (대안 보관) |

## 🤝 기여

버그 리포트와 PR 환영. 새 에이전트 어댑터 추가가 가장 좋은 기여입니다 —
위 "다른 에이전트 추가하기" 참고.

## 라이선스

개인용. 미정.
