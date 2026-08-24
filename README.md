# notion-logger

어떤 코딩 에이전트(Antigravity, opencode, ...)든 **hook 한 줄 연결**만으로
작업 기록(사용자 요청 → 툴 사용 내역 → 최종 응답)을 노션 데이터베이스에
자동으로 쌓아주는 도구.

## 동작 방식

```
에이전트 hook 발동 (턴 종료 시)
   └─ stdin으로 JSON payload 전달
        └─ run.py: 어댑터 감지 → 대화 기록(transcript) 파싱
             └─ 턴 1개당 노션 DB 행 1개 생성
```

- **한 행 = 한 번의 대화(턴)**. 같은 세션의 대화들은 `Session ID` 컬럼이 같고,
  `Turns` 컬럼에 세션 내 순번이 기록된다.
- **세션 흐름 보기**: DB에서 `Session ID` 오름차순 + `Turns` 오름차순 정렬을
  추가하면 하나의 세션이 시간순 대화 목록처럼 보인다.
- 이미 기록한 턴은 로컬 state 파일로 중복 기록을 막는다.
- 마크다운(헤딩/목록/표/코드블록/굵게/링크 등)은 노션 블록으로 변환된다.

## 요구 사항

- Python **3.10 이상**
- 의존성: `requests` 하나 (`pip install -r requirements.txt`)
- Windows에서는 `python`, macOS/Linux에서는 보통 `python3` 명령을 사용한다.
  아래의 hook 설정에서 본인 환경에 맞는 명령을 쓸 것.

## 1. 노션 준비

### 1-1. API 키(인테그레이션) 만들기

1. https://www.notion.so/profile/integrations 접속
2. **새 인테그레이션 만들기** → 이름 입력 (예: `agent_auto_database`)
3. 만들면 **내부 통합 시크릿**(`ntn_...` 으로 시작)이 발급됨 → 복사

### 1-2. 데이터베이스 만들기

1. 노션에서 아무 페이지나 열고 빈 **데이터베이스**(전체 페이지 또는 인라인) 생성
2. 데이터베이스가 있는 **페이지**에서 우측 상단 `⋯` → **연결(Connections)** →
   위에서 만든 인테그레이션 선택 ← **이 단계를 빼먹으면 API 접근이 안 됨(404)**

### 1-3. 데이터베이스 ID 확인

1. 해당 DB를 **full page로 열기** (DB 뷰 우측 상단 ⋯ → "Open as full page")
2. 브라우저 주소창 URL에서 마지막 32자리 영숫자가 DB ID:
   ```
   https://www.notion.so/내DB이름-3c6031069f3380c99d59e1fc2c9b5f46
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 이 부분
   ```

### 1-4. 컬럼 자동 생성

저장소 루트의 `.env` 파일을 만들고(아래 2장 참고):

```bash
python setup_notion_db.py    # macOS/Linux: python3 setup_notion_db.py
```

필요한 컬럼(Agent, Host/Device, Project, Session ID, Status, Work Type,
Created At, Last At, Turns, 통계 number 컬럼들)이 자동으로 추가된다.
이미 있으면 건너뛰므로 몇 번을 실행해도 안전하다.

## 2. 설정 (.env)

저장소 루트에 `.env` 파일 생성 (**절대 커밋 금지 — .gitignore에 등록되어 있음**):

```
NOTION_API_KEY=ntn_여기에_발급받은_키
NOTION_DATABASE_ID=32자리_DB_ID
```

환경변수로 직접 설정해도 된다(.env보다 환경변수가 우선).

## 3. 에이전트 연결 (hook)

### Antigravity

파일: `~/.gemini/config/hooks.json` (없으면 새로 만들기)

| OS | 경로 |
|---|---|
| Windows | `C:\Users\<사용자>\.gemini\config\hooks.json` |
| macOS/Linux | `~/.gemini/config/hooks.json` |

```json
{
  "notion-auto-logger": {
    "Stop": [
      {
        "type": "command",
        "command": "python C:/dev/notion-logger/run.py",
        "timeout": 30
      }
    ]
  }
}
```

- `command`에는 **이 저장소의 run.py 절대 경로**를 적는다.
  (macOS/Linux라면 `"python3 /Users/xxx/notion-logger/run.py"`)
- 설정 후 에이전트를 **재시작**해야 반영된다.

### opencode

미구현 (roadmap). 어댑터 인터페이스(`notion_logger/adapters/base.py`)에
맞춰 구현하면 된다.

### 다른 에이전트 추가하기

`notion_logger/adapters/base.py::Adapter`를 상속해 세 가지만 구현하고
`adapters/__init__.py`에 등록한다:

- `matches(payload)` — stdin payload가 이 에이전트 것인지 판별
- `context(payload)` — 프로젝트명 / 세션 ID 추출
- `parse_turns(payload)` — transcript를 턴 배열로 파싱

## 4. 노션에서 보기

DB에 다음 정렬을 추가하면 편하다:

- **최근 활동 순**: `Last At` 내림차순
- **세션별 대화 흐름**: `Session ID` 오름차순 → `Turns` 오름차순

각 행(페이지) 본문 구성: 📝 사용자 요청 → ⚙️ 작업 내역(툴 호출) → 최종 응답

## 5. 문제 해결

| 증상 | 확인할 곳 |
|---|---|
| 노션에 안 들어감 | 저장소 `tmp/logger.log` — hook이 실행됐는지, 오류 메시지는 뭔지 |
| hook 호출 여부부터 확인 | `debug_hook.py`를 hook command로 잠시 연결하면 stdin 수신 내용을 파일로 덤프 |
| 404 object_not_found | DB가 인테그레이션에 연결되지 않음 (위 1-2 참고) |
| 페이지는 생기는데 컬럼이 비어있음 | DB에 해당 이름의 컬럼이 없는 것 — `setup_notion_db.py` 재실행 |

## 6. OS 호환성

- 경로 처리는 전부 `pathlib` 기반, stdin은 바이트로 읽어 UTF-8 디코딩하므로
  Windows(cp949) / macOS / Linux 모두 동작한다.
- state 파일 위치: Windows `%LOCALAPPDATA%\notion-logger\state.json`,
  그 외 `$XDG_STATE_HOME/notion-logger/state.json` (기본 `~/.local/state/...`)
- hook 등록 명령에서 실행 파일 이름만 주의: Windows `python`, macOS/Linux `python3`
- 로그 파일은 항상 UTF-8로 기록된다.

## 7. 개발

```
python test_connection.py   # 노션 연결 + 테스트 페이지 생성
python test_md2notion.py    # 마크다운 변환 렌더링 확인
python test_adapter.py      # 실제 세션 기록 파싱 → 페이지 생성 전체 흐름
```

### 브랜치 구조

| 브랜치 | 구조 |
|---|---|
| `master` | **한 행당 한 대화(턴)** — 권장 |
| `session-per-page` | 세션당 페이지 1개, 턴 타임라인 append + 목차 (대안 구현 보관) |

## 라이선스

개인용. 미정.
