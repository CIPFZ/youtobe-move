import { escapeText, fmtCount, fmtDuration } from "../format";

export function VideoList({ videos, selectedId, selectedVideoIds, onToggleSelected, onSelect }) {
  if (!videos.length) return <div className="panel-body muted">暂无数据。</div>;
  const selectedSet = new Set(selectedVideoIds || []);
  return (
    <div className="video-list">
      {videos.map((item) => {
        const video = item.video;
        const draft = item.publish_draft || {};
        const title = draft.title || video.title || video.video_id;
        const poster = item.media_files?.poster_path ? `/api/videos/${encodeURIComponent(video.video_id)}/file?type=poster` : "";
        return (
          <div className={`video-row${video.video_id === selectedId ? " active" : ""}`} key={video.video_id}>
            <input
              type="checkbox"
              checked={selectedSet.has(video.video_id)}
              aria-label={`选择 ${title}`}
              onChange={(event) => onToggleSelected(video.video_id, event.target.checked)}
            />
            <button className="video-main" onClick={() => onSelect(video.video_id)}>
              {poster ? <img className="thumb" src={poster} alt="" /> : <div className="thumb" />}
              <div>
                <div className="title">{title}</div>
                <div className="meta-line">{escapeText(video.channel || "-")} · {fmtDuration(video.duration)} · {fmtCount(video.view_count)} views</div>
                <div className="badges">
                  <span className={`badge ${video.status}`}>{video.status}</span>
                  <span className="badge">P{video.priority ?? 100}</span>
                  {video.source_label ? <span className="badge">{video.source_label}</span> : null}
                  {draft.status ? <span className="badge">{draft.status}</span> : null}
                  {draft.tid ? <span className="badge">tid {draft.tid}</span> : null}
                  {draft.tid_source ? <span className="badge">{draft.tid_source}</span> : null}
                </div>
              </div>
            </button>
          </div>
        );
      })}
    </div>
  );
}
