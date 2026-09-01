"""Single-Leg Drop Jump protocol identifiers and metadata."""

TRIAL_SDJ_L = "SDJ_L"
TRIAL_SDJ_R = "SDJ_R"
TRIAL_SDJ30_L = "SDJ30_L"
TRIAL_SDJ30_R = "SDJ30_R"

TRIAL_SIDE = {
    TRIAL_SDJ_L: "L",
    TRIAL_SDJ_R: "R",
    TRIAL_SDJ30_L: "L",
    TRIAL_SDJ30_R: "R",
}

TRIAL_PLATFORM_CM = {
    TRIAL_SDJ_L: 15,
    TRIAL_SDJ_R: 15,
    TRIAL_SDJ30_L: 30,
    TRIAL_SDJ30_R: 30,
}


def is_sdj(trial_type: str) -> bool:
    return trial_type in TRIAL_SIDE


def active_side(trial_type: str) -> str:
    return TRIAL_SIDE[trial_type]
