from __future__ import annotations


VIDEO_STATUSES = {
    "discovered",
    "selected",
    "downloading",
    "downloaded",
    "describing",
    "ready_to_publish",
    "publishing",
    "published",
    "failed",
    "skipped",
}


ALLOWED_VIDEO_TRANSITIONS = {
    "discovered": {"selected", "skipped", "failed"},
    "selected": {"downloading", "skipped", "failed"},
    "downloading": {"downloaded", "failed"},
    "downloaded": {"describing", "ready_to_publish", "skipped", "failed"},
    "describing": {"ready_to_publish", "failed"},
    "ready_to_publish": {"publishing", "skipped", "failed"},
    "publishing": {"published", "failed"},
    "published": set(),
    "failed": {"selected", "downloading", "describing", "ready_to_publish", "publishing", "skipped"},
    "skipped": {"selected"},
}


JOB_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
}


def ensure_video_status(status: str) -> None:
    if status not in VIDEO_STATUSES:
        raise ValueError(f"Unknown video status: {status}")


def ensure_video_transition(old_status: str, new_status: str) -> None:
    ensure_video_status(old_status)
    ensure_video_status(new_status)
    if old_status == new_status:
        return
    if new_status not in ALLOWED_VIDEO_TRANSITIONS[old_status]:
        raise ValueError(f"Invalid video status transition: {old_status} -> {new_status}")
