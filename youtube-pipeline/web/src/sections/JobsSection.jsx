import { RefreshCw } from "lucide-react";
import { errorOptions } from "../constants";
import { IconButton } from "../components/IconButton";

const jobTypes = ["", "download", "describe", "publish"];
const jobStatuses = ["", "pending", "running", "succeeded", "failed", "cancelled"];

export function JobsSection({ state, actions }) {
  const { jobs, jobFilters } = state;
  const { loadJobs, updateJobFilters, selectVideo } = actions;
  const rows = jobs?.jobs || [];
  const limit = Number(jobFilters.limit || 30);
  const offset = Number(jobFilters.offset || 0);

  return (
    <section className="panel wide" id="jobs">
      <div className="panel-head">
        <h2>Jobs</h2>
        <div className="toolbar">
          <select value={jobFilters.jobType} onChange={(event) => updateJobFilters((prev) => ({ ...prev, jobType: event.target.value, offset: 0 }))}>
            {jobTypes.map((item) => <option value={item} key={item || "all"}>{item || "全部任务"}</option>)}
          </select>
          <select value={jobFilters.status} onChange={(event) => updateJobFilters((prev) => ({ ...prev, status: event.target.value, offset: 0 }))}>
            {jobStatuses.map((item) => <option value={item} key={item || "all"}>{item || "全部状态"}</option>)}
          </select>
          <select value={jobFilters.errorType} onChange={(event) => updateJobFilters((prev) => ({ ...prev, errorType: event.target.value, offset: 0 }))}>
            <option value="">全部错误</option>
            {errorOptions.map((item) => <option value={item} key={item}>{item}</option>)}
          </select>
          <select value={jobFilters.limit} onChange={(event) => updateJobFilters((prev) => ({ ...prev, limit: Number(event.target.value), offset: 0 }))}>
            {[20, 30, 50, 100].map((item) => <option value={item} key={item}>{item} 条</option>)}
          </select>
          <IconButton icon={RefreshCw} onClick={() => loadJobs(jobFilters)}>刷新</IconButton>
        </div>
      </div>
      <div className="events-toolbar">
        <button disabled={offset <= 0} onClick={() => updateJobFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}>上一页</button>
        <span className="muted">offset {offset} · 当前 {rows.length} 条</span>
        <button disabled={!jobs?.has_more} onClick={() => updateJobFilters((prev) => ({ ...prev, offset: offset + limit }))}>下一页</button>
      </div>
      {rows.length ? (
        <div className="job-table">
          {rows.map((job) => (
            <div className="job-row" key={job.id}>
              <button disabled={!job.video_id} onClick={() => selectVideo(job.video_id)}>
                <b>#{job.id} {job.job_type}</b>
                <span>{job.video_title || job.video_id || "-"}</span>
              </button>
              <div>
                <span className={`badge ${job.status}`}>{job.status}</span>
                {job.error_type ? <span className="badge failed">{job.error_type}</span> : null}
                <small>{job.attempts || 0}/{job.max_attempts || 0}</small>
              </div>
              <p>{job.error || job.next_run_at || job.locked_at || "-"}</p>
              <small>{job.updated_at}</small>
            </div>
          ))}
        </div>
      ) : <div className="panel-body muted">暂无 job。</div>}
    </section>
  );
}
