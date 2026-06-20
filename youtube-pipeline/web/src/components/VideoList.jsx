import { Button, Empty, Image, Space, Table, Tag, Typography } from "antd";
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

export function VideoList({ videos, selectedId, selectedVideoIds, onToggleSelected, onSelect }) {
  const rows = videos.map((item) => ({
    key: item.video.video_id,
    ...item,
  }));

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
      width: 128,
      render: (_, row) => <Tag color={statusTone[row.video.status] || "default"}>{row.video.status}</Tag>,
    },
    {
      title: "草稿",
      width: 120,
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
      scroll={{ x: 860 }}
      size="middle"
    />
  );
}
