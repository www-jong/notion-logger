"""로컬 상태 저장소 — v0.6

세션별 기록 위치를 파일로 보관해서 같은 세션이면 같은 페이지에 이어 쓰고,
중복 기록을 방지한다.

저장 위치 (플랫폼별):
    Windows : %LOCALAPPDATA%/notion-logger/state.json
    POSIX   : $XDG_STATE_HOME/notion-logger/state.json

구조:
{
  "Antigravity/SKALA/7d473d80": {
      "page_id": "abc123...",   ← 이 세션의 노션 페이지
      "offset": 17,             ← 트랜스크립트에서 마지막으로 읽은 위치(엔트리 수)
      "turns": 2                ← 지금까지 기록한 턴 수
  }
}

파일이 없거나 깨져도 동작에 지장 없게 방어적으로 처리한다.
(state를 잃으면 노션의 Session ID 컬럼으로 페이지를 재탐색한다)
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _state_dir() -> Path:
    xdg = os.getenv("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "notion-logger"
    local = os.getenv("LOCALAPPDATA")
    if local:
        return Path(local) / "notion-logger"
    return Path.home() / ".local" / "state" / "notion-logger"


def _state_file() -> Path:
    return _state_dir() / "state.json"


def session_key(agent: str, project: str, session_id: str) -> str:
    """세션 식별 키. 프로젝트명까지 포함해서 다른 프로젝트와 섞이지 않게 한다."""
    return f"{agent}/{project}/{session_id}"


def _load_all() -> Dict[str, Any]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get(key: str) -> Optional[Dict[str, Any]]:
    """세션 키에 해당하는 상태 레코드 조회."""
    return _load_all().get(key)


def update(key: str, **fields: Any) -> None:
    """세션 키의 상태를 갱신/생성하고 즉시 디스크에 저장."""
    data = _load_all()
    record = data.get(key) or {}
    record.update(fields)
    data[key] = record

    try:
        directory = _state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _state_file().write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # 저장 실패해도 에이전트 작업은 막지 않는다


def remove(key: str) -> None:
    """세키 키 레코드 삭제 (테스트용)."""
    data = _load_all()
    data.pop(key, None)
    try:
        _state_file().write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
