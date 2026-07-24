from __future__ import annotations

SKILL_META = {
    "name": "example_greeting",
    "description": "Print a friendly greeting for the provided name.",
    "version": "1.0.0",
}


def execute(name: str = "world") -> str:
    message = f"Hello, {name}!"
    print(message)
    return message
