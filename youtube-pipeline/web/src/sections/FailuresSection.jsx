import { RefreshCw, RotateCcw } from "lucide-react";
import { errorOptions } from "../constants";
import { IconButton } from "../components/IconButton";

const jobTypes = ["", "download", "describe", "publish"];

export function FailuresSection({ state, actions }) {
  const { failures, failureFilters, selectedId } = state;
  const { loadFailures, updateFailureFilters, selectVideo, runVideoAction } = actions;
  const rows = failures?.failures || [];
  const limit = Number(failureFilters.limit || 30);
  const offset = Number(failureFilters.offset || 0);

  return (
    <section className="panel wide" id="failures">
      <div className="panel-head">
        <h2>失败</h2>
        <div className="toolbar">
          <select value={failureFilters.jobType} onChange={(event) => updateFailureFilters((prev) => ({ ...prev, jobType: event.target.value, offset: 0 }))}>
            {jobTypes.map((item) => <option value={item} key={item || "all"}>{item || "全部任务"}</option>)}
          </select>
          <select value={failureFilters.errorType} onChange={(event) => updateFailureFilters((prev) => ({ ...prev, errorType: event.target.value, offset: 0 }))}>
            <option value="">全部错误</option>
            {errorOptions.map((item) => <option value={item} key={item}>{item}</option>)}
          </select>
          <select value={failureFilters.limit} onChange={(event) => updateFailureFilters((prev) => ({ ...prev, limit: Number(event.target.value), offset: 0 }))}>
            {[20, 30, 50, 100].map((item) => <option value={item} key={item}>{item} 条</option>)}
          </select>
          <IconButton icon={RefreshCw} onClick={() => loadFailures(failureFilters)}>刷新</IconButton>
        </div>
      </div>
      <div className="events-toolbar">
        <button disabled={offset <= 0} onClick={() => updateFailureFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}>上一页</button>
        <span className="muted">offset {offset} · 当前 {rows.length} 条</span>
        <button disabled={!failures?.has_more} onClick={() => updateFailureFilters((prev) => ({ ...prev, offset: offset + limit }))}>下一页</button>
      </div>
      {rows.length ? (
        <div className="failure-table">
          {rows.map((row) => (
            <div className={`failure-row${selectedId === row.video_id ? " active" : ""}`} key={row.video_id}>
              <button onClick={() => selectVideo(row.video_id)}>
                <b>{row.title || row.video_id}</b>
                <span>{row.video_id} · {row.channel || "-"}</span>
              </button>
              <div>
                <span className="badge failed">{row.job_error_type || "unknown"}</span>
                <span className="badge">{row.job_type || "-"}</span>
                <small>尝试 {row.job_attempts || 0}/{row.job_max_attempts || 0}</small>
              </div>
              <p>{row.job_error || row.last_error || "-"}</p>
              <div>
                {row.job_next_run_at ? <small>下次重试 {row.job_next_run_at}</small> : <small>无自动重试计划</small>}
                <IconButton icon={RotateCcw} onClick={() => runVideoAction(row.video_id, "retry")}>重试</IconButton>
              </div>
            </div>
          ))}
        </div>
      ) : <div className="panel-body muted">暂无失败记录。</div>}
    </section>
  );
}
