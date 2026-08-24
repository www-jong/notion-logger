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

    def parse_last_turn(self, payload: Dict[str, Any]) -> Tuple[str, List[Event], str]:
        entries = load_jsonl(str(payload.get("transcriptPath", "")))
        return self._parse_entries(entries)

    @staticmethod
    def _parse_entries(entries: List[Dict[str, Any]]) -> Tuple[str, List[Event], str]:
        """마지막 USER_INPUT 이후의 기록을 하나의 턴으로 파싱."""

        def event_type(e: Dict[str, Any]) -> str:
            return str(e.get("type") or "").upper()

        # 마지막 USER_INPUT 위치 찾기
        last_user = -1
        for i in range(len(entries) - 1, -1, -1):
            if event_type(entries[i]) == "USER_INPUT":
                last_user = i
                break

        if last_user == -1:
            return "", [], ""

        user_request = clean_user_request(
            str(entries[last_user].get("content") or "")
        )

        events: List[Event] = []
        final_candidates: List[str] = []

        for entry in entries[last_user + 1:]:
            etype = event_type(entry)
            content = entry.get("content")

            # ---- PLANNER_RESPONSE: tool_calls + 모델 텍스트 ----
            if etype == "PLANNER_RESPONSE":
                for call in entry.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    name = str(call.get("name") or call.get("tool_name") or "unknown")
                    args = call.get("args") or {}
                    events.append(Event(
                        kind="tool_call",
                        tool=name,
                        category=classify_tool(name, args),
                        summary=str(args.get("summary") or ""),
                        args=args if isinstance(args, dict) else {},
                        command=arg_command(args),
                        path="",
                    ))
                # 툴 경로는 args 안에 있으므로 여기서 보강
                for ev in events:
                    if ev.kind == "tool_call" and not ev.path:
                        ev.path = arg_path(ev.args)

                if isinstance(content, str) and content.strip():
                    final_candidates.append(content.strip())
                continue

            # ---- GENERIC: 툴 결과 / 에러 ----
            if etype == "GENERIC":
                if isinstance(content, list):
                    content = "\n".join(str(x) for x in content)
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                content = content.strip()
                if not content:
                    continue

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
                continue

            # 다른 타입(CHECKPOINT 등)은 무시

        final_response = final_candidates[-1] if final_candidates else ""
        return user_request, events, final_response
