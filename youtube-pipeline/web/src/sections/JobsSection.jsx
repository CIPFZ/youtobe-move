import { Button, Select, Space } from "antd";
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
        <Space wrap>
          <Select value={jobFilters.jobType} style={{ width: 132 }} onChange={(value) => updateJobFilters((prev) => ({ ...prev, jobType: value, offset: 0 }))} options={jobTypes.map((item) => ({ value: item, label: item || "全部任务" }))} />
          <Select value={jobFilters.status} style={{ width: 132 }} onChange={(value) => updateJobFilters((prev) => ({ ...prev, status: value, offset: 0 }))} options={jobStatuses.map((item) => ({ value: item, label: item || "全部状态" }))} />
          <Select value={jobFilters.errorType} style={{ width: 132 }} onChange={(value) => updateJobFilters((prev) => ({ ...prev, errorType: value, offset: 0 }))} options={[{ value: "", label: "全部错误" }, ...errorOptions.map((item) => ({ value: item, label: item }))]} />
          <Select value={jobFilters.limit} style={{ width: 100 }} onChange={(value) => updateJobFilters((prev) => ({ ...prev, limit: Number(value), offset: 0 }))} options={[20, 30, 50, 100].map((item) => ({ value: item, label: `${item} 条` }))} />
          <IconButton icon={RefreshCw} onClick={() => loadJobs(jobFilters)}>刷新</IconButton>
        </Space>
      </div>
      <div className="events-toolbar">
        <Button disabled={offset <= 0} onClick={() => updateJobFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}>上一页</Button>
        <span className="muted">offset {offset} · 当前 {rows.length} 条</span>
        <Button disabled={!jobs?.has_more} onClick={() => updateJobFilters((prev) => ({ ...prev, offset: offset + limit }))}>下一页</Button>
      </div>
      {rows.length ? (
        <div className="job-table">
          {rows.map((job) => (
            <div className="job-row" key={job.id}>
              <Button type="text" disabled={!job.video_id} onClick={() => selectVideo(job.video_id)}>
                <b>#{job.id} {job.job_type}</b>
                <span>{job.video_title || job.video_id || "-"}</span>
              </Button>
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
