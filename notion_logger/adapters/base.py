"""어댑터 인터페이스와 공통 데이터 모델.

각 에이전트(Antigravity, opencode, ...)의 hook payload와 트랜스크립트 형식을
공통 Turn 구조로 바꿔주는 것이 어댑터의 역할이다.

새 에이전트 지원 방법:
    1. Adapter를 상속한 클래스를 adapters/ 아래에 추가
    2. __init__.py 의 detect_adapter()에 등록
"""

import socket
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Event:
    """턴 안에서 발생한 개별 활동 (툴 호출/결과/에러)."""
    kind: str                      # tool_call | tool_result | error
    tool: str = ""                 # 툴 이름
    category: str = ""             # command | file_read | file_edit | search | mcp | tool
    summary: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    command: str = ""              # command 카테고리일 때 실행 명령
    path: str = ""                 # 파일 관련 툴일 때 대상 경로
    result: str = ""               # tool_result / error 의 본문


@dataclass
class Turn:
    """사용자 요청 1회 ↔ 에이전트 최종 응답 1회 사이의 기록."""
    number: int = 0                # 세션 내 턴 순번 (1부터, USER_INPUT/user 메시지 기준)
    occurred_at: str = ""          # 턴 시작 실제 시각 (ISO 8601 / UTC)
    user_request: str = ""
    final_response: str = ""
    events: List[Event] = field(default_factory=list)


@dataclass
class Context:
    """이 기록이 어디서 발생했는지에 대한 메타 정보."""
    agent: str                     # 에이전트 이름 (예: Antigravity)
    project: str                   # 프로젝트(워크스페이스) 이름
    session_id: str                # 세션 고유키


def hostname() -> str:
    """이 PC의 이름."""
    return socket.gethostname() or "Unknown"


def git_project_name(workspace_paths: List[str]) -> str:
    """프로젝트 이름 결정: 워크스페이스 경로 > git 저장소명 > 현재폴더명 순."""
    import os

    if workspace_paths:
        path = str(workspace_paths[0]).rstrip("/\\")
        if path:
            return os.path.basename(path)

    try:
        repo = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        )
        return os.path.basename(repo.decode().strip())
    except Exception:
        return os.path.basename(os.getcwd())


class Adapter(ABC):
    """에이전트별 파서. 에이전트 하나당 구현체 하나."""

    agent_name: str = "unknown"

    @staticmethod
    @abstractmethod
    def matches(payload: Dict[str, Any]) -> bool:
        """stdin으로 받은 payload가 이 에이전트의 것인지 판별."""

    @abstractmethod
    def context(self, payload: Dict[str, Any]) -> Context:
        """프로젝트명과 세션 ID 추출."""

    @abstractmethod
    def count_turns(self, payload: Dict[str, Any]) -> int:
        """세션의 총 턴 수를 저비용으로 세어 반환.

        게이트 용도이므로 JSON 파싱 없이 문자열/SQL 스캔 등 가벼운 방식 사용.
        실제보다 크게 세어도 무방 (이후 parse_turns가 정확히 판정).
        """

    @abstractmethod
    def parse_turns(self, payload: Dict[str, Any],
                    numbers: set) -> List[Turn]:
        """요청된 순번의 턴만 파싱해 반환.

        numbers: 필요한 턴 순번 집합 (1부터 시작).
        트랜스크립트 재작성에 영향 받지 않도록 순번은
        USER_INPUT(또는 user 메시지) 출현 순서 기준.
        """


# ------------------------------------------------------------
# 툴 인자에서 공통 키 추출 헬퍼 (에이전트마다 키 이름이 달라 후보 방식 사용)
# ------------------------------------------------------------

ARG_PATH_KEYS = [
    "AbsolutePath", "absolutePath", "Path", "path",
    "FilePath", "filePath", "Target", "target",
]
ARG_COMMAND_KEYS = [
    "CommandLine", "commandLine", "Command", "command", "cmd",
]


def arg_path(args: Dict[str, Any]) -> str:
    for key in ARG_PATH_KEYS:
        if args.get(key):
            return str(args[key])
    return ""


def arg_command(args: Dict[str, Any]) -> str:
    for key in ARG_COMMAND_KEYS:
        if args.get(key):
            return str(args[key])
    return ""


def classify_tool(name: str, args: Dict[str, Any]) -> str:
    """툴 이름/인자로 카테고리 추정 (아이콘·표시용)."""
    n = (name or "").lower()

    if "run_command" in n or "shell" in n or "bash" in n:
        return "command"
    if any(k in n for k in ("view_file", "read_file", "cat_file")):
        return "file_read"
    if any(k in n for k in ("search", "grep", "find")):
        return "search"
    if any(k in n for k in ("replace", "write_file", "edit_file", "apply_patch")):
        return "file_edit"
    if "mcp" in n:
        return "mcp"
    return "tool"


TOOL_CATEGORY_ICONS = {
    "command": "▶️",
    "file_read": "📖",
    "file_edit": "✏️",
    "search": "🔍",
    "mcp": "🔌",
}
