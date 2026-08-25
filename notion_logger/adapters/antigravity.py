"""Google Antigravity 어댑터.

hook payload 예시 (stdin JSON):
{
  "conversationId": "7d473d80-...",
  "transcriptPath": "C:/Users/MASTER/.gemini/antigravity/brain/<id>/
                     .system_generated/logs/transcript_full.jsonl",
  "workspacePaths": ["g:/.../SKALA"],
  "modelName": "gemini-3.7-flash-high",
  ...
}

트랜스크립트(JSONL) 이벤트 타입:
    USER_INPUT       사용자 입력 (<USER_REQUEST> ... 태그 포함)
    PLANNER_RESPONSE 모델 응답 (tool_calls 배열 + content)
    GENERIC          툴 실행 결과 / 에러 본문
"""

import json
import os
import re
from typing import Any, Dict, List, Tuple

from .base import (
    Adapter,
    Context,
    Event,
    Turn,
    arg_command,
    arg_path,
    classify_tool,
    git_project_name,
)

# 툴 결과 본문 최대 길이 (노션 페이지 폭증 방지)
MAX_RESULT_LENGTH = 8000


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    """JSONL 파일을 읽어 dict 리스트로 반환. 없거나 깨진 줄은 건너뜀."""
    entries: List[Dict[str, Any]] = []

    if not path or not os.path.exists(path):
        return entries

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        entries.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return entries


def clean_user_request(text: str) -> str:
    """사용자 입력에서 시스템 태그(<USER_REQUEST> 등)를 제거하고 본문만 남김."""
    if not text:
        return ""

    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, flags=re.DOTALL)
    if m:
        text = m.group(1)

    # 그 외 시스템 메타 블록 제거
    text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


class AntigravityAdapter(Adapter):
    agent_name = "Antigravity"

    @staticmethod
    def matches(payload: Dict[str, Any]) -> bool:
        return isinstance(payload, dict) and "transcriptPath" in payload

    def context(self, payload: Dict[str, Any]) -> Context:
        workspace_paths = payload.get("workspacePaths") or []
        session_id = (
            payload.get("conversationId")
            or os.path.basename(os.path.dirname(payload.get("transcriptPath", "")))
            or "unknown-session"
        )
        return Context(
            agent=self.agent_name,
            project=git_project_name([str(p) for p in workspace_paths]),
            session_id=str(session_id),
        )

    @staticmethod
    def _event_type(e: Dict[str, Any]) -> str:
        return str(e.get("type") or "").upper()

    def count_turns(self, payload: Dict[str, Any]) -> int:
        """JSON 파싱 없이 USER_INPUT 라인 수만 세어 게이트 판정용으로 쓴다.

        content 본문에 우연히 같은 문자열이 있으면 과대 계상될 수 있으나
        방향이 안전하다 (게이트 통과 → parse_turns가 정확히 판정).
        """
        path = str(payload.get("transcriptPath", ""))
        if not path or not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for line in f if '"USER_INPUT"' in line)
        except OSError:
            return 0

    def parse_turns(self, payload: Dict[str, Any],
                    numbers: set) -> List[Turn]:
        """요청된 순번의 턴만 파싱.

        턴 순번 = USER_INPUT 출현 순서 (1부터).
        트랜스크립트 재작성으로 엔트리가 삽입/삭제되어도
        USER_INPUT의 상대 순서는 유지되므로 번호 기준은 안전하다.
        """
        entries = load_jsonl(str(payload.get("transcriptPath", "")))
        turns: List[Turn] = []

        number = 0
        i = 0
        while i < len(entries):
            if self._event_type(entries[i]) != "USER_INPUT":
                i += 1
                continue

            number += 1

            # USER_INPUT 하나가 턴의 시작. 다음 USER_INPUT 직전까지가 같은 턴.
            user_request = clean_user_request(
                str(entries[i].get("content") or "")
            )
            occurred_at = str(entries[i].get("created_at") or "")

            events: List[Event] = []
            final_candidates: List[str] = []

            j = i + 1
            while j < len(entries) and self._event_type(entries[j]) != "USER_INPUT":
                if number in numbers:
                    self._parse_entry(events, final_candidates, entries[j])
                j += 1

            if number in numbers:
                turns.append(Turn(
                    number=number,
                    occurred_at=occurred_at,
                    user_request=user_request,
                    final_response=final_candidates[-1] if final_candidates else "",
                    events=events,
                ))
            i = j

        return turns

    def _parse_entry(self, events: List[Event], final_candidates: List[str],
                     entry: Dict[str, Any]) -> None:
        """엔트리 1개를 해석해 events / 최종응답 후보에 추가."""
        etype = self._event_type(entry)
        content = entry.get("content")

        if etype == "PLANNER_RESPONSE":
            for call in entry.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name") or call.get("tool_name") or "unknown")
                args = call.get("args") or {}
                ev = Event(
                    kind="tool_call",
                    tool=name,
                    category=classify_tool(name, args),
                    summary=str(args.get("summary") or ""),
                    args=args if isinstance(args, dict) else {},
                    command=arg_command(args),
                    path=arg_path(args) if isinstance(args, dict) else "",
                )
                events.append(ev)

            if isinstance(content, str) and content.strip():
                final_candidates.append(content.strip())
            return

        if etype == "GENERIC":
            if isinstance(content, list):
                content = "\n".join(str(x) for x in content)
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            content = content.strip()
            if not content:
                return

            lowered = content.lower()
            is_error = (
                str(entry.get("status") or "").upper() in {"ERROR", "FAILED"}
                or "traceback" in lowered
                or "error:" in lowered
            )

            events.append(Event(
                kind="error" if is_error else "tool_result",
                result=content[:MAX_RESULT_LENGTH],
            ))

    def parse_last_turn(self, payload: Dict[str, Any]) -> Tuple[str, List[Event], str]:
        """(하위 호환용) 마지막 턴만 파싱."""
        total = self.count_turns(payload)
        turns = self.parse_turns(payload, {total})
        if not turns:
            return "", [], ""
        turn = turns[-1]
        return turn.user_request, turn.events, turn.final_response
