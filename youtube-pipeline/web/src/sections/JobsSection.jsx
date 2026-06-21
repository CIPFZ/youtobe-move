import { Button, Progress, Select, Space, Table, Tag, Typography } from "antd";
import { RefreshCw } from "lucide-react";
import { errorOptions } from "../constants";
import { IconButton } from "../components/IconButton";

const jobTypes = ["", "download", "describe", "publish"];
const jobStatuses = ["", "pending", "running", "succeeded", "failed", "cancelled"];
const statusColor = {
  pending: "default",
  running: "processing",
  succeeded: "success",
  failed: "error",
  cancelled: "warning",
};

export function JobsSection({ state, actions }) {
  const { jobs, jobFilters } = state;
  const { loadJobs, updateJobFilters, selectVideo } = actions;
  const rows = jobs?.jobs || [];
  const limit = Number(jobFilters.limit || 30);
  const offset = Number(jobFilters.offset || 0);

  const columns = [
    {
      title: "Job",
      width: 150,
      render: (_, job) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>#{job.id} {job.job_type}</Typography.Text>
          <Typography.Text type="secondary">{job.updated_at || "-"}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "视频",
      render: (_, job) => (
        <Button type="link" className="table-title-link" disabled={!job.video_id} onClick={() => selectVideo(job.video_id)}>
          {job.video_title || job.video_id || "-"}
        </Button>
      ),
    },
    {
      title: "状态",
      width: 150,
      render: (_, job) => (
        <Space wrap size={4}>
          <Tag color={statusColor[job.status] || "default"}>{job.status}</Tag>
          {job.error_type ? <Tag color="error">{job.error_type}</Tag> : null}
        </Space>
      ),
    },
    {
      title: "尝试",
      width: 92,
      render: (_, job) => `${job.attempts || 0}/${job.max_attempts || 0}`,
    },
    {
      title: "进度",
      width: 180,
      render: (_, job) => <JobProgress job={job} />,
    },
    {
      title: "错误 / 计划",
      render: (_, job) => <Typography.Text ellipsis={{ tooltip: job.error || job.next_run_at || job.locked_at || "-" }}>{job.error || job.next_run_at || job.locked_at || "-"}</Typography.Text>,
    },
  ];

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
      <Table
        className="ops-table"
        columns={columns}
        dataSource={rows}
        rowKey="id"
        pagination={false}
        size="middle"
        scroll={{ x: 920 }}
        footer={() => (
          <TablePager
            offset={offset}
            limit={limit}
            count={rows.length}
            hasMore={jobs?.has_more}
            onPrev={() => updateJobFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}
            onNext={() => updateJobFilters((prev) => ({ ...prev, offset: offset + limit }))}
          />
        )}
      />
    </section>
  );
}

function JobProgress({ job }) {
  const percent = Number(job.progress_percent || 0);
  if (job.job_type !== "download" || (!percent && job.status !== "running")) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  const stage = job.progress_stage || "download";
  return (
    <Space direction="vertical" size={2} style={{ width: "100%" }}>
      <Progress percent={Math.round(percent)} size="small" status={job.status === "failed" ? "exception" : "active"} />
      <Typography.Text type="secondary">{stage} · {formatBytes(job.progress_downloaded_bytes)} / {formatBytes(job.progress_total_bytes)}</Typography.Text>
    </Space>
  );
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "-";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GiB`;
}

function TablePager({ offset, limit, count, hasMore, onPrev, onNext }) {
  return (
    <div className="table-pager">
      <Button disabled={offset <= 0} onClick={onPrev}>上一页</Button>
      <span className="muted">offset {offset} · 当前 {count} 条</span>
      <Button disabled={!hasMore} onClick={onNext}>下一页</Button>
    </div>
  );
}
