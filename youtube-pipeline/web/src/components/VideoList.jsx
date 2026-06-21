import { Button, Dropdown, Empty, Image, Space, Table, Tag, Typography } from "antd";
import { MoreOutlined } from "@ant-design/icons";
import { draftOptions, errorOptions, statusOptions } from "../constants";
import { escapeText, fmtCount, fmtDuration } from "../format";

const statusTone = {
  published: "success",
  ready_to_publish: "processing",
  failed: "error",
  skipped: "default",
  downloading: "warning",
  describing: "warning",
  publishing: "warning",
};

const draftTone = {
  approved: "success",
  rejected: "error",
  pending: "processing",
  manual: "warning",
};

export function VideoList({ videos, selectedId, selectedVideoIds, filters, onFilterChange, onToggleSelected, onSelect, onAction }) {
  const rows = videos.map((item) => ({
    key: item.video.video_id,
    ...item,
  }));
  const selectedFilters = {
    status: filters?.status ? [filters.status] : null,
    draftStatus: filters?.draftStatus ? [filters.draftStatus] : null,
    errorType: filters?.errorType ? [filters.errorType] : null,
  };

  const columns = [
    {
      title: "视频",
      dataIndex: ["video", "title"],
      render: (_, row) => {
        const video = row.video;
        const draft = row.publish_draft || {};
        const title = draft.title || video.title || video.video_id;
        const poster = row.media_files?.poster_path ? `/api/videos/${encodeURIComponent(video.video_id)}/file?type=poster` : "";
        return (
          <Space align="start" size={10} className="video-table-title">
            {poster ? <Image className="table-thumb" src={poster} alt="" width={76} height={46} preview={false} /> : <div className="table-thumb placeholder" />}
            <div>
              <Button type="link" className="table-title-link" onClick={() => onSelect(video.video_id)}>{title}</Button>
              <div className="meta-line">{escapeText(video.channel || "-")} · {fmtDuration(video.duration)} · {fmtCount(video.view_count)} views</div>
              <Typography.Text className="video-id" copyable>{video.video_id}</Typography.Text>
            </div>
          </Space>
        );
      },
    },
    {
      title: "状态",
      key: "status",
      width: 128,
      filteredValue: selectedFilters.status,
      filters: statusOptions.map((item) => ({ text: item, value: item })),
      render: (_, row) => <Tag color={statusTone[row.video.status] || "default"}>{row.video.status}</Tag>,
    },
    {
      title: "草稿",
      key: "draftStatus",
      width: 120,
      filteredValue: selectedFilters.draftStatus,
      filters: draftOptions.map((item) => ({ text: item, value: item })),
      render: (_, row) => {
        const draft = row.publish_draft || {};
        return draft.status ? <Tag color={draftTone[draft.status] || "default"}>{draft.status}</Tag> : <span className="muted">-</span>;
      },
    },
    {
      title: "分区",
      width: 126,
      render: (_, row) => {
        const draft = row.publish_draft || {};
        if (!draft.tid) return <span className="muted">-</span>;
        return (
          <Space size={4} direction="vertical">
            <Tag>tid {draft.tid}</Tag>
            {draft.tid_source ? <span className="muted">{draft.tid_source}</span> : null}
          </Space>
        );
      },
    },
    {
      title: "优先级",
      width: 92,
      render: (_, row) => <Tag>P{row.video.priority ?? 100}</Tag>,
    },
    {
      title: "来源",
      width: 110,
      render: (_, row) => row.video.source_label ? <Tag>{row.video.source_label}</Tag> : <span className="muted">-</span>,
    },
    {
      title: "错误",
      key: "errorType",
      width: 120,
      filteredValue: selectedFilters.errorType,
      filters: errorOptions.map((item) => ({ text: item, value: item })),
      render: (_, row) => {
        const errorType = firstJobErrorType(row);
        return errorType ? <Tag color="red">{errorType}</Tag> : <span className="muted">-</span>;
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 150,
      fixed: "right",
      render: (_, row) => {
        const video = row.video;
        return (
          <Space size={4}>
            <Button type="link" onClick={() => onSelect(video.video_id)}>详情</Button>
            <Dropdown
              trigger={["click"]}
              menu={{
                items: actionItemsForRow(row),
                onClick: ({ key }) => onAction?.(video.video_id, key),
              }}
            >
              <Button type="text" icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        );
      },
    },
  ];

  if (!rows.length) return <div className="panel-body"><Empty description="暂无数据" /></div>;

  return (
    <Table
      className="video-table"
      columns={columns}
      dataSource={rows}
      pagination={false}
      rowKey={(row) => row.video.video_id}
      rowClassName={(row) => row.video.video_id === selectedId ? "active-row" : ""}
      rowSelection={{
        selectedRowKeys: selectedVideoIds || [],
        onSelect: (record, selected) => onToggleSelected(record.video.video_id, selected),
        onSelectAll: (selected, selectedRows, changedRows) => {
          for (const row of changedRows) onToggleSelected(row.video.video_id, selected);
        },
      }}
      onChange={(_, tableFilters) => {
        onFilterChange?.({
          status: firstFilterValue(tableFilters.status),
          draftStatus: firstFilterValue(tableFilters.draftStatus),
          errorType: firstFilterValue(tableFilters.errorType),
        });
      }}
      scroll={{ x: 980 }}
      size="middle"
    />
  );
}

function firstFilterValue(value) {
  if (!Array.isArray(value) || !value.length) return "";
  return value[0] || "";
}

function firstJobErrorType(row) {
  return [
    row.latest_download_job,
    row.latest_describe_job,
    row.latest_publish_job,
  ].find((job) => job?.error_type)?.error_type || "";
}

function actionItemsForRow(row) {
  const video = row.video || {};
  const draft = row.publish_draft || {};
  const canDownload = ["selected", "failed"].includes(video.status);
  const canDescribe = ["downloaded", "ready_to_publish", "failed"].includes(video.status);
  const canReview = video.status === "ready_to_publish" && Boolean(draft.title);
  const canRetry = video.status === "failed";
  const canSkip = !["published", "skipped"].includes(video.status);
  return [
    { key: "download", label: "下载", disabled: !canDownload },
    { key: "describe", label: "生成文案", disabled: !canDescribe },
    { type: "divider" },
    { key: "approve", label: "通过", disabled: !canReview || draft.status === "approved" },
    { key: "reject", label: "拒绝", disabled: !canReview || draft.status === "rejected", danger: true },
    { type: "divider" },
    { key: "retry", label: "重试", disabled: !canRetry },
    { key: "skip", label: "跳过", disabled: !canSkip, danger: true },
  ];
}
