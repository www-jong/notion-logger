"""어댑터 레지스트리.

정식 경로: hook 설정(run.py argv)에서 에이전트 이름을 직접 지정.
지문 폴백: 이름이 없으면 payload 필드로 각 어댑터의 matches()를 순회 판별.
"""

from typing import Any, Dict, Optional

from .antigravity import AntigravityAdapter
from .base import Adapter
from .opencode import OpenCodeAdapter

_ADAPTERS: Dict[str, Adapter] = {
    "antigravity": AntigravityAdapter(),
    "opencode": OpenCodeAdapter(),
}


def get_adapter(name: str) -> Optional[Adapter]:
    """이름으로 어댑터 조회. 없으면 None."""
    return _ADAPTERS.get((name or "").strip().lower())


def detect_adapter(payload: Any) -> Optional[Adapter]:
    """payload 형태를 보고 맞는 어댑터 반환. 못 찾으면 None."""
    for adapter in _ADAPTERS.values():
        if adapter.matches(payload):
            return adapter
    return None
