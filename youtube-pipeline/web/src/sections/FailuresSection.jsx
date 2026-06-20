import { Button, Select, Space } from "antd";
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
        <Space wrap>
          <Select value={failureFilters.jobType} style={{ width: 132 }} onChange={(value) => updateFailureFilters((prev) => ({ ...prev, jobType: value, offset: 0 }))} options={jobTypes.map((item) => ({ value: item, label: item || "全部任务" }))} />
          <Select value={failureFilters.errorType} style={{ width: 132 }} onChange={(value) => updateFailureFilters((prev) => ({ ...prev, errorType: value, offset: 0 }))} options={[{ value: "", label: "全部错误" }, ...errorOptions.map((item) => ({ value: item, label: item }))]} />
          <Select value={failureFilters.limit} style={{ width: 100 }} onChange={(value) => updateFailureFilters((prev) => ({ ...prev, limit: Number(value), offset: 0 }))} options={[20, 30, 50, 100].map((item) => ({ value: item, label: `${item} 条` }))} />
          <IconButton icon={RefreshCw} onClick={() => loadFailures(failureFilters)}>刷新</IconButton>
        </Space>
      </div>
      <div className="events-toolbar">
        <Button disabled={offset <= 0} onClick={() => updateFailureFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}>上一页</Button>
        <span className="muted">offset {offset} · 当前 {rows.length} 条</span>
        <Button disabled={!failures?.has_more} onClick={() => updateFailureFilters((prev) => ({ ...prev, offset: offset + limit }))}>下一页</Button>
      </div>
      {rows.length ? (
        <div className="failure-table">
          {rows.map((row) => (
            <div className={`failure-row${selectedId === row.video_id ? " active" : ""}`} key={row.video_id}>
              <Button type="text" onClick={() => selectVideo(row.video_id)}>
                <b>{row.title || row.video_id}</b>
                <span>{row.video_id} · {row.channel || "-"}</span>
              </Button>
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
