"""공용 설정 로딩 모듈 — v0.3

저장소 루트의 .env 파일을 읽어 노션 접속 정보를 제공한다.
.env 형식: KEY=VALUE 한 줄씩, # 으로 시작하는 줄은 주석.

절대 .env에 실제 키를 커밋하지 않는다. (.gitignore 등록 완료)
"""

import os
from pathlib import Path

# ------------------------------------------------------------
# 상수
# ------------------------------------------------------------

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

_PROJECT_ROOT = Path(__file__).parent.parent


def load_env(env_path: Path | None = None) -> None:
    """.env 파일을 읽어 환경변수로 등록한다.

    - 이미 os.environ에 있는 값은 덮어쓰지 않는다 (실제 환경변수 우선).
    - 파일이 없으면 조용히 무시한다 (hook 실행 중 에러로 인한 방해 방지).
    """
    path = env_path or (_PROJECT_ROOT / ".env")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def api_key() -> str:
    """노션 인테그레이션 API 키."""
    return os.getenv("NOTION_API_KEY", "")


def database_id() -> str:
    """기록 대상 데이터베이스 ID (하이픈 제거 형태로 정규화)."""
    return os.getenv("NOTION_DATABASE_ID", "").replace("-", "")


def is_configured() -> bool:
    """필수 설정이 모두 있는지 확인."""
    return bool(api_key() and database_id())
