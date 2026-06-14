from app.discovery.models import VideoCandidate
from app.discovery.scoring import compute_hot_score, compute_score_details, dedupe_and_sort, should_keep_candidate


def test_should_keep_candidate_uses_real_filters_only():
    assert should_keep_candidate(
        view_count=1000,
        duration_sec=120,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
    )
    assert not should_keep_candidate(
        view_count=999,
        duration_sec=120,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
    )
    assert not should_keep_candidate(
        view_count=1000,
        duration_sec=59,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
    )
    assert not should_keep_candidate(
        view_count=1000,
        duration_sec=601,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
    )
    assert not should_keep_candidate(
        view_count=1000,
        duration_sec=120,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
        title="Official trailer compilation",
        title_blocklist="trailer",
    )
    assert not should_keep_candidate(
        view_count=1000,
        duration_sec=120,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
        channel_title="Blocked Channel",
        channel_blocklist="blocked",
    )
    assert not should_keep_candidate(
        view_count=1000,
        duration_sec=120,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
        channel_title="Other Channel",
        channel_allowlist="trusted",
    )
    assert should_keep_candidate(
        view_count=1000,
        duration_sec=120,
        min_views=1000,
        min_duration_sec=60,
        max_duration_sec=600,
        channel_title="Trusted Channel",
        channel_allowlist="trusted",
    )


def test_compute_hot_score_handles_missing_or_invalid_publish_time():
    assert compute_hot_score(1000, "") > 0
    assert compute_hot_score(1000, "not-a-date") > 0
    assert compute_hot_score(10000, "") > compute_hot_score(1000, "")


def test_compute_score_details_explains_total():
    details = compute_score_details(
        view_count=10000,
        published_at="",
        duration_sec=180,
        title="funny cats compilation",
        keyword="funny cats",
        channel_title="Cat Channel",
    )

    assert details["score_total"] == round(
        details["score_views"]
        + details["score_freshness"]
        + details["score_duration"]
        + details["score_channel"]
        + details["score_keyword"],
        6,
    )
    assert details["score_duration"] > 0
    assert details["score_keyword"] > 0
    assert details["penalty_duplicate"] == 0


def test_dedupe_and_sort_keeps_highest_score_per_video():
    rows = [
        VideoCandidate("v1", "u", "t", "c", "", 100, 1000, "low", "pets", 1.0, "{}"),
        VideoCandidate("v1", "u", "t", "c", "", 100, 1000, "high", "pets", 9.0, "{}"),
        VideoCandidate("v2", "u", "t", "c", "", 100, 1000, "top", "pets", 10.0, "{}"),
    ]

    selected = dedupe_and_sort(rows, top_n=2)

    assert [item.video_id for item in selected] == ["v2", "v1"]
    assert selected[1].keyword == "high"
