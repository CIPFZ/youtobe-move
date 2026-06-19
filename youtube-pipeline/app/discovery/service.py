from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.discovery.filters import filter_candidate
from app.discovery.models import VideoCandidate
from app.discovery.scoring import sort_candidates
from app.discovery.sources import fetch_candidates, fetch_candidates_for_source, load_discovery_sources


logger = logging.getLogger("youtube-pipeline")


def candidate_summary(candidate: VideoCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data.pop("raw", None)
    return data


def discover_videos(config: Config, source_type: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    candidates = sort_candidates(fetch_candidates(config, source_type=source_type))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    inserted: list[dict[str, Any]] = []

    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        repo.create_event(
            None,
            None,
            "discovery",
            "discovery_started",
            "Discovery started",
            {"source_type": source_type or "", "dry_run": dry_run},
        )
        conn.commit()

        seen: set[str] = set()
        for candidate in candidates:
            summary = candidate_summary(candidate)
            if candidate.video_id in seen:
                rejected.append({"candidate": summary, "reason": "duplicate_in_run"})
                continue
            seen.add(candidate.video_id)

            result = filter_candidate(candidate, repo, config)
            if not result.accepted:
                rejected.append({"candidate": summary, "reason": result.reason})
                repo.create_event(
                    None,
                    None,
                    "discovery",
                    "candidate_rejected",
                    result.reason,
                    {"video_id": candidate.video_id, "candidate": summary},
                )
                continue

            accepted.append(summary)
            if dry_run:
                continue

            video = repo.upsert_video(
                video_id=candidate.video_id,
                source_url=candidate.source_url,
                status="selected",
                title=candidate.title,
                channel=candidate.channel,
                duration=candidate.duration,
                view_count=candidate.view_count,
                category=candidate.category,
            )
            job_id = repo.create_job(
                "download",
                video_id=candidate.video_id,
                payload={
                    "source": "discovery",
                    "source_type": candidate.source_type,
                    "source_name": candidate.source_name,
                    "source_query": candidate.source_query,
                },
            )
            repo.create_event(
                candidate.video_id,
                job_id,
                "discovery",
                "candidate_selected",
                "Candidate selected for download",
                summary,
            )
            inserted.append({"video": video, "job_id": job_id, "candidate": summary})

        repo.create_event(
            None,
            None,
            "discovery",
            "discovery_finished",
            "Discovery finished",
            {
                "candidate_count": len(candidates),
                "accepted_count": len(accepted),
                "rejected_count": len(rejected),
                "inserted_count": len(inserted),
                "dry_run": dry_run,
            },
        )
        conn.commit()

    return {
        "status": "ok",
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "inserted_count": len(inserted),
        "accepted": accepted,
        "rejected": rejected,
        "inserted": inserted,
    }


def preview_discovery_source(config: Config, index: int) -> dict[str, Any]:
    sources = load_discovery_sources(config)
    if not (0 <= index < len(sources)):
        raise IndexError(f"Discovery source index out of range: {index}")

    source = sources[index]
    candidates = sort_candidates(fetch_candidates_for_source(source, config))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        for candidate in candidates:
            summary = candidate_summary(candidate)
            if candidate.video_id in seen:
                rejected.append({"candidate": summary, "reason": "duplicate_in_run"})
                continue
            seen.add(candidate.video_id)
            result = filter_candidate(candidate, repo, config)
            if result.accepted:
                accepted.append(summary)
            else:
                rejected.append({"candidate": summary, "reason": result.reason})

    return {
        "status": "ok",
        "source": {"index": index, "type": source.type, "name": source.name, "params": source.params},
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
    }
