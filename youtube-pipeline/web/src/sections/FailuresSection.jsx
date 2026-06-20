import { Button, Select, Space, Table, Tag, Typography } from "antd";
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

  const columns = [
    {
      title: "视频",
      render: (_, row) => (
        <Button type="link" className="table-title-link" onClick={() => selectVideo(row.video_id)}>
          {row.title || row.video_id}
        </Button>
      ),
    },
    {
      title: "任务",
      width: 180,
      render: (_, row) => (
        <Space wrap size={4}>
          <Tag color="error">{row.job_error_type || "unknown"}</Tag>
          <Tag>{row.job_type || "-"}</Tag>
        </Space>
      ),
    },
    {
      title: "尝试",
      width: 92,
      render: (_, row) => `${row.job_attempts || 0}/${row.job_max_attempts || 0}`,
    },
    {
      title: "错误",
      render: (_, row) => <Typography.Text ellipsis={{ tooltip: row.job_error || row.last_error || "-" }}>{row.job_error || row.last_error || "-"}</Typography.Text>,
    },
    {
      title: "下次重试",
      width: 180,
      render: (_, row) => row.job_next_run_at || <span className="muted">无自动重试</span>,
    },
    {
      title: "操作",
      width: 100,
      render: (_, row) => <IconButton icon={RotateCcw} onClick={() => runVideoAction(row.video_id, "retry")}>重试</IconButton>,
    },
  ];

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
      <Table
        className="ops-table"
        columns={columns}
        dataSource={rows}
        rowKey="video_id"
        rowClassName={(row) => row.video_id === selectedId ? "active-row" : ""}
        pagination={false}
        size="middle"
        scroll={{ x: 980 }}
        footer={() => (
          <TablePager
            offset={offset}
            limit={limit}
            count={rows.length}
            hasMore={failures?.has_more}
            onPrev={() => updateFailureFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}
            onNext={() => updateFailureFilters((prev) => ({ ...prev, offset: offset + limit }))}
          />
        )}
      />
    </section>
  );
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
