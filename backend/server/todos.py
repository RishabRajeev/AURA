"""
AURA Energy-Based To-Do List

Stores tasks locally and re-orders based on current cognitive capacity.
Low fatigue = show harder tasks first; high fatigue = show easy wins.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("AURA_DATA_DIR", Path.home() / ".aura"))
TODOS_PATH = DATA_DIR / "todos.json"


def _load_todos() -> list[dict]:
    if not TODOS_PATH.exists():
        return []
    try:
        with open(TODOS_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_todos(todos: list[dict]):
    TODOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TODOS_PATH, "w") as f:
        json.dump(todos, f, indent=2)


def get_todos(fatigue_score: float = 0, fuel_gauge: float = 100) -> list[dict]:
    """
    Returns todos re-ordered by energy.
    High fatigue/fuel low -> easy tasks first; low fatigue -> hard first.
    """
    todos = _load_todos()
    # Sort: low energy = prefer low effort (effort 1 first); high energy = prefer high impact
    energy_ok = fatigue_score < 50 and fuel_gauge > 50
    sorted_todos = sorted(
        todos,
        key=lambda t: (
            t.get("effort", 2),  # 1=easy, 2=med, 3=hard
            -t.get("impact", 1),  # 1=low, 2=med, 3=high
        ) if energy_ok else (
            -t.get("effort", 2),  # easy first when tired
            t.get("impact", 1),
        ),
    )
    return sorted_todos


def add_todo(title: str, effort: int = 2, impact: int = 2) -> dict:
    todos = _load_todos()
    tid = str(max([int(t.get("id", 0)) for t in todos], default=0) + 1)
    t = {"id": tid, "title": title, "effort": effort, "impact": impact, "done": False}
    todos.append(t)
    _save_todos(todos)
    return t


def toggle_todo(todo_id: str) -> bool:
    todos = _load_todos()
    for t in todos:
        if str(t.get("id")) == str(todo_id):
            t["done"] = not t.get("done", False)
            _save_todos(todos)
            return True
    return False


def delete_todo(todo_id: str) -> bool:
    todos = [t for t in _load_todos() if str(t.get("id")) != str(todo_id)]
    if len(todos) < len(_load_todos()):
        _save_todos(todos)
        return True
    return False
