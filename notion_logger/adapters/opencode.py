"""opencode 어댑터.

opencode는 트랜스크립트 파일 대신 SQLite DB에 모든 것을 저장한다:
    ~/.local/share/opencode/opencode.db
        session  : 세션 메타 (id, directory, title, ...)
        message  : 턴 구성 단위 (data JSON에 role 포함)
        part     : 메시지 본문 조각 (text / reasoning / tool / step-* )

hook 트리거는 opencode 플러그인(JS)의 session.idle 이벤트이며,
run.py에 stdin JSON으로 전달되는 payload 예시:
    {
      "source": "opencode",
      "sessionID": "ses_xxx",
      "directory": "/Users/wonjong/workspace"
    }

part.type 매핑:
    role=user  의 text        → Turn.user_request
    role=assistant 의 tool    → Event(tool_call) + 결과(tool_result/error)
    role=assistant 의 text    → 마지막 것이 Turn.final_response
    reasoning / step-start 등 → 무시 (표시용 아님)

offset은 라인 인덱스가 아니라 커서 문자열 "time_created:message_id"를 쓴다.
DB는 append-only이므로 (시각, id) 순서쌍이 곧 위치가 된다.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import Adapter, Context, Event, Turn, classify_tool, git_project_name

# 툴 결과 본문 최대 길이 (노션 페이지 폭증 방지)
MAX_RESULT_LENGTH = 8000


def db_path() -> Path:
    """opencode 데이터베이스 위치."""
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def connect_ro() -> Optional[sqlite3.Connection]:
    """readonly 연결. WAL 중인 본 프로세스와 충돌하지 않게 쓰기 잠금을 걸지 않는다."""
    path = db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _cursor(time_created: Any, message_id: Any) -> str:
    return f"{time_created}:{message_id}"


def _split_cursor(value: Any) -> Tuple[int, str]:
    time_s, _, msg_id = str(value).partition(":")
    try:
        return int(time_s), msg_id
    except ValueError:
        return 0, msg_id


class OpenCodeAdapter(Adapter):
    agent_name = "OpenCode"

    @staticmethod
    def matches(payload: Dict[str, Any]) -> bool:
        # 정식 경로는 hook 설정에서 이름을 직접 지정하는 것이고,
        # matches는 설정에 이름이 없을 때의 지문 폴백이다.
        return isinstance(payload, dict) and (
            str(payload.get("source") or "").lower() == "opencode"
            and "sessionID" in payload
        )

    def context(self, payload: Dict[str, Any]) -> Context:
        session_id = str(payload.get("sessionID") or "unknown-session")

        directory = ""
        conn = connect_ro()
        if conn is not None and session_id != "unknown-session":
            try:
                row = conn.execute(
                    "SELECT directory FROM session WHERE id = ?", (session_id,)
                ).fetchone()
                directory = str(row["directory"] or "") if row else ""
            except sqlite3.Error:
                directory = ""
            finally:
                conn.close()

        if not directory:
            directory = str(payload.get("directory") or "")

        project = os.path.basename(directory.rstrip("/\\")) if directory else git_project_name([])

        return Context(
            agent=self.agent_name,
            project=project,
            session_id=session_id,
        )

    def is_new(self, offset: Any, last_offset: Any) -> bool:
        """커서 문자열 비교. (time_created, id) 순서쌍으로 판정한다."""
        return _split_cursor(offset) > _split_cursor(last_offset)

    def parse_turns(self, payload: Dict[str, Any]) -> List[Tuple[Any, Turn]]:
        """DB에서 세션 메시지를 읽어 턴 단위로 파싱.

        반환: [(커서 "time_created:id", Turn), ...]
        """
        session_id = str(payload.get("sessionID") or "")
        if not session_id:
            return []

        conn = connect_ro()
        if conn is None:
            return []

        turns: List[Tuple[str, Turn]] = []
        try:
            messages = conn.execute(
                "SELECT id, time_created, data FROM message "
                "WHERE session_id = ? ORDER BY time_created, id",
                (session_id,),
            ).fetchall()

            current: Optional[Turn] = None
            current_events: List[Event] = []
            final_candidates: List[str] = []
            current_cursor = ""

            for row in messages:
                cursor = _cursor(row["time_created"], row["id"])
                try:
                    meta = json.loads(row["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(meta, dict):
                    continue

                role = str(meta.get("role") or "")

                if role == "user":
                    # 이전 턴 확정
                    if current is not None:
                        current.final_response = final_candidates[-1] if final_candidates else ""
                        turns.append((current_cursor, current))
                    request = self._user_request(conn, row["id"])
                    current = Turn(user_request=request, final_response="", events=[])
                    current_events = current.events
                    final_candidates = []
                    current_cursor = cursor
                elif role == "assistant":
                    self._parse_assistant(conn, row["id"], current_events, final_candidates)
                    current_cursor = cursor

            # 마지막 턴 확정
            if current is not None:
                current.final_response = final_candidates[-1] if final_candidates else ""
                turns.append((current_cursor, current))

        except sqlite3.Error:
            return []

        finally:
            conn.close()

        return turns

    def _user_request(self, conn: sqlite3.Connection, message_id: str) -> str:
        """사용자 메시지의 첫 번째 text part를 요청 본문으로 쓴다."""
        try:
            rows = conn.execute(
                "SELECT data FROM part WHERE message_id = ? ORDER BY time_created, id",
                (message_id,),
            ).fetchall()
        except sqlite3.Error:
            return ""

        for row in rows:
            try:
                part = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(part, dict) and part.get("type") == "text":
                return str(part.get("text") or "").strip()
        return ""

    def _parse_assistant(self, conn: sqlite3.Connection, message_id: str,
                         events: List[Event], final_candidates: List[str]) -> None:
        """assistant 메시지의 part들을 해석해 events / 최종응답 후보에 추가."""
        try:
            rows = conn.execute(
                "SELECT data FROM part WHERE message_id = ? ORDER BY time_created, id",
                (message_id,),
            ).fetchall()
        except sqlite3.Error:
            return

        for row in rows:
            try:
                part = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(part, dict):
                continue

            ptype = str(part.get("type") or "")

            if ptype == "tool":
                events.extend(self._tool_events(part))
            elif ptype == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    final_candidates.append(text)
            # reasoning / step-start / step-finish 등은 표시 대상이 아니므로 무시

    @staticmethod
    def _tool_events(part: Dict[str, Any]) -> List[Event]:
        """tool part 하나를 tool_call(+결과) 이벤트들로 변환."""
        tool = str(part.get("tool") or "unknown")
        st = part.get("state") or {}
        if not isinstance(st, dict):
            st = {}
        args = st.get("input") or {}
        if not isinstance(args, dict):
            args = {}
        status = str(st.get("status") or "")

        ev_list = [Event(
            kind="tool_call",
            tool=tool,
            category=classify_tool(tool, args),
            args=args,
        )]

        output = st.get("output")
        if isinstance(output, list):
            output = "\n".join(str(x) for x in output)
        if output is not None and str(output).strip():
            result_text = str(output).strip()[:MAX_RESULT_LENGTH]
            if status == "error":
                ev_list.append(Event(kind="error", result=result_text))
            elif status == "completed":
                ev_list.append(Event(kind="tool_result", result=result_text))
            # pending/running은 아직 결과 없음 — 기록 안 함

        return ev_list
