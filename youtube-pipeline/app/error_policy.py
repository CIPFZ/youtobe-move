from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDecision:
    error_type: str
    retryable: bool


def classify_error(error: str, module: str = "") -> ErrorDecision:
    text = error.lower()
    module = module.lower()

    if "http error 403" in text or "403: forbidden" in text or "forbidden" in text:
        return ErrorDecision("youtube_403", False)
    if "private video" in text or "video unavailable" in text or "this video is unavailable" in text:
        return ErrorDecision("youtube_unavailable", False)
    if "login" in text and ("required" in text or "cookie" in text):
        return ErrorDecision("login_required", False)
    if "fallback" in text and "tid" in text:
        return ErrorDecision("fallback_tid", False)
    if "ffmpeg" in text or "merge" in text:
        return ErrorDecision("merge_failed", False)
    if module == "publisher" or "bilibili" in text or "biliup" in text:
        return ErrorDecision("publish_failed", True)
    if module == "describer" or "llm" in text or "minimax" in text:
        return ErrorDecision("llm_failed", True)
    if (
        "timeout" in text
        or "network" in text
        or "timed out" in text
        or "connection reset" in text
        or "connection aborted" in text
        or "temporary failure" in text
        or "http error 5" in text
        or "502" in text
        or "503" in text
        or "504" in text
    ):
        return ErrorDecision("network_error", True)
    if "no output file" in text or "incomplete" in text or ".part" in text:
        return ErrorDecision("download_incomplete", True)

    return ErrorDecision("unknown", False)
