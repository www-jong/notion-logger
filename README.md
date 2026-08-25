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
- **중복 방지는 노션이 진실원천**: 매 실행마다 해당 세션으로 이미 기록된
  `Turns` 번호를 노션에서 조회하고, 없는 번호만 생성한다. 로컬 state 파일
  없음 — 트랜스크립트가 재작성(프롬프트 컴팩션 등)돼도 영향 없다.
- **저비용 게이트**: 새 턴 여부를 JSON 파싱 없이 문자열/SQL 스캔으로 먼저
  판별하므로, 트랜스크립트가 아무리 길어져도 새 턴이 없으면 수 ms 만에 종료.
- `Created At` = 실제 대화 시각(트랜스크립트 기준), `Last At` = 노션 기록 시각.
- 마크다운(헤딩/목록/표/코드블록/굵게/링크 등)은 노션 블록으로 변환된다.
  리스트 중첩은 노션 API 제한에 맞춰 2단계까지만 지원(그 이상은 `↳`로 평탄화).
- 동시 실행 방지 락: 훅이 겹쳐 발동돼도 프로세스 하나만 처리한다.

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

1. 해당 DB를 **full page로 열기** (DB 뷰 우측 상단 ⋯ → "Open as full page(전체 페이지로 열기)")
2. 브라우저 주소창 URL에서 마지막 32자리 영숫자가 DB ID:
   ```
   https://www.notion.so/내DB이름-abcdefegaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 32글자 이 부분

   https://app.notion.com/p/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?v=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&source=copy_link
                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 32글자 이 부분
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

| OS          | 경로                                            |
| ----------- | ----------------------------------------------- |
| Windows     | `C:\Users\<사용자>\.gemini\config\hooks.json` |
| macOS/Linux | `~/.gemini/config/hooks.json`                 |

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

- `command` 끝에 **에이전트 이름을 argv로 지정**한다 (`run.py antigravity`).
  이름을 생략하면 payload 지문으로 자동 감지한다(폴백).
- `command`에는 **이 저장소의 run.py 절대 경로**를 적는다.
  (macOS/Linux라면 `"python3 /Users/xxx/notion-logger/run.py antigravity"`)
- `timeout`은 밀린 턴을 몰아 기록할 수 있게 넉넉히 (권장 120). 짧으면
  처리 도중 강제 종료되지만, 턴 단위로 이어 기록되므로 다음 훅에서 계속된다.
- 설정 후 에이전트를 **재시작**해야 반영된다.

### opencode

트랜스크립트 파일이 없고 SQLite DB(`~/.local/share/opencode/opencode.db`)와
플러그인 방식을 쓴다는 점만 다르고 흐름은 같다.

1. 플러그인 등록 — `~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "file:///절대경로/notion-logger/plugin/session-logger.js"
  ]
}
```

   또는 저장소의 `plugin/session-logger.js`를 `~/.config/opencode/plugins/`
   아래에 복사해도 된다. **둘 중 한 곳에만** 등록할 것 (중복 등록 시
   같은 턴이 두 번 기록될 수 있음).

2. opencode 재시작 → 대화 1턴 진행 → 노션 확인.

플러그인은 세션 유휴(`session.idle`) 시점에 `run.py opencode`를 호출하고,
어댑터가 SQLite DB를 readonly로 읽어 파싱한다.

### 다른 에이전트 추가하기

`notion_logger/adapters/base.py::Adapter`를 상속해 다음을 구현하고
`adapters/__init__.py` `_ADAPTERS` 딕셔너리에 이름과 함께 등록한다:

- `matches(payload)` — stdin payload가 이 에이전트 것인지 판별 (폴백용)
- `context(payload)` — 프로젝트명 / 세션 ID 추출
- `count_turns(payload)` — 총 턴 수 저비용 카운트 (JSON 파싱 금지)
- `parse_turns(payload, numbers)` — 요청된 순번의 턴만 파싱

## 4. 노션에서 보기

DB에 다음 정렬을 추가하면 편하다:

- **최근 활동 순**: `Last At` 내림차순
- **세션별 대화 흐름**: `Session ID` 오름차순 → `Turns` 오름차순

각 행(페이지) 본문 구성: 📝 사용자 요청 → ⚙️ 작업 내역(툴 호출) → 최종 응답

## 5. 문제 해결

| 증상                              | 확인할 곳                                                                      |
| --------------------------------- | ------------------------------------------------------------------------------ |
| 노션에 안 들어감                  | 저장소`tmp/logger.log` — hook이 실행됐는지, 오류 메시지는 뭔지              |
| hook 호출 여부부터 확인           | `debug_hook.py`를 hook command로 잠시 연결하면 stdin 수신 내용을 파일로 덤프 |
| 404 object_not_found              | DB가 인테그레이션에 연결되지 않음 (위 1-2 참고)                                |
| 페이지는 생기는데 컬럼이 비어있음 | DB에 해당 이름의 컬럼이 없는 것 —`setup_notion_db.py` 재실행                |

## 6. OS 호환성

- 경로 처리는 전부 `pathlib` 기반, stdin은 바이트로 읽어 UTF-8 디코딩하므로
  Windows(cp949) / macOS / Linux 모두 동작한다.
- opencode 어댑터는 `~/.local/share/opencode/opencode.db`를 readonly
  (SQLite URI `mode=ro`)로 열므로 본체와 충돌하지 않는다.
- hook 등록 명령에서 실행 파일 이름만 주의: Windows `python`, macOS/Linux `python3`
- 로그 파일은 항상 UTF-8로 기록된다.

## 7. 개발

```
python test_connection.py   # 노션 연결 + 테스트 페이지 생성
python test_md2notion.py    # 마크다운 변환 렌더링 확인
python test_adapter.py      # 실제 세션 기록 파싱 → 페이지 생성 전체 흐름
```

### 브랜치 구조

| 브랜치               | 구조                                                          |
| -------------------- | ------------------------------------------------------------- |
| `master`           | **한 행당 한 대화(턴)** — 권장                         |
| `session-per-page` | 세션당 페이지 1개, 턴 타임라인 append + 목차 (대안 구현 보관) |

## 라이선스

개인용. 미정.
