"""Bilateral Drop Jump protocol identifiers."""

TRIAL_DJ = "DJ"


def is_dj(trial_type: str) -> bool:
    return trial_type == TRIAL_DJ


def active_sides() -> list[str]:
    return ["L", "R"]
