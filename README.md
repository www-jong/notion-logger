# notion-logger

어떤 코딩 에이전트(Antigravity, opencode, ...)든 **hook 한 줄 연결**로
작업 기록(유저 요청 → 툴 사용 내역 → 최종 응답)을 노션 데이터베이스에
자동으로 쌓아주는 도구.

## 목표

- 에이전트별 hook에서 stdin JSON을 받아 처리하는 공통 실행부(`run.py`)
- 에이전트마다 어댑터 1개만 추가하면 지원 가능 (어댑터 패턴)
- 노션에서 **PC / 에이전트 / 프로젝트 / 세션 / 시간** 기준 조회
- 마크다운 입출력을 노션 블록으로 변환

## 로드맵

| 버전 | 내용 |
|---|---|
| v0.1 | 저장소 골격 (현재) |
| v0.2 | `setup_notion_db.py` — DB 컬럼 자동 생성 |
| v0.3 | 노션 API 최소 연결 테스트 + `.env` 설정 분리 |
| v0.4 | 마크다운 → 노션 블록 변환기 (`md2notion.py`) |
| v0.5 | Antigravity 어댑터 이식 |
| v0.6 | 세션별 페이지 + 턴 타임라인 append (`state.py`) |
| v0.7 | opencode 어댑터 + hook 연결 |

## 설치

Python 3.10+ 필요.

```
pip install -r requirements.txt
```

API 키 등 비밀값은 절대 커밋하지 않고 `.env` 파일로 관리한다.
(자세한 설정은 v0.3 README 업데이트 예정)

## 라이선스

개인용. 미정.
