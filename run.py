#!/usr/bin/env python3
"""
hook 진입점 — v0.5b

에이전트 hook이 이 스크립트를 stdin과 함께 실행한다:
    python C:/dev/notion-logger/run.py

동작:
    1. stdin JSON(payload) 읽기 (UTF-8, 바이트로 직접 읽음 — cp949 문제 회피)
    2. 어댑터 감지 후 마지막 턴 파싱
    3. 노션 DB에 페이지 생성

모든 실패는 조용히 로그만 남기고 종료한다 (에이전트 작업 방해 금지).
로그 위치: tmp/logger.log
"""

import json
import logging
import sys
from pathlib import Path

# tmp/ 로거 설정
_LOG_DIR = Path(__file__).parent / "tmp"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(_LOG_DIR / "logger.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",  # Windows(cp949) 등 모든 OS에서 한글/이모지 로깅 보장
)


def main() -> None:
    from notion_logger import config
    from notion_logger.pipeline import process_payload

    try:
        raw = sys.stdin.buffer.read()
        if not raw.strip():
            logging.info("stdin 비어있음 — 종료")
            return

        payload = json.loads(raw.decode("utf-8", errors="replace"))

        # hook 설정에서 에이전트 이름을 argv[1]로 지정 (예: run.py opencode)
        agent_name = sys.argv[1] if len(sys.argv) > 1 else ""

        config.load_env()
        if not config.is_configured():
            logging.error(".env 설정 없음 — 종료")
            return

        page_id = process_payload(payload, agent_name=agent_name)
        if page_id is None:
            logging.warning("페이지 생성 실패")
        else:
            logging.info("성공: %s", page_id)

    except Exception:
        logging.exception("run.py 치명적 예외")


if __name__ == "__main__":
    main()
