import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class State:
    last_synced_time: int = 0  # unix seconds
    last_synced_message_id: Optional[str] = None


class StateStore:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Dict[str, Any]] = {}

    def load(self) -> None:
        if self.state_path.exists():
            self._data = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def get_chat_state(self, chat_id: str) -> State:
        raw = self._data.get(chat_id, {})
        return State(
            last_synced_time=int(raw.get("last_synced_time", 0) or 0),
            last_synced_message_id=raw.get("last_synced_message_id"),
        )

    def set_chat_state(self, chat_id: str, state: State) -> None:
        self._data[chat_id] = {
            "last_synced_time": int(state.last_synced_time),
            "last_synced_message_id": state.last_synced_message_id,
        }

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)


class JsonlWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, obj: Dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
