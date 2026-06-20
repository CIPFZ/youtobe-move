import { Button, Select, Space, Table, Tag, Typography } from "antd";
import { RefreshCw } from "lucide-react";
import { IconButton } from "../components/IconButton";

const eventModules = ["", "worker", "core", "operations", "download", "describe", "publish", "storage", "discovery", "config"];

export function EventsSection({ state, actions }) {
  const { events, eventFilters } = state;
  const { loadEvents, updateEventFilters } = actions;
  const rows = events?.events || [];
  const limit = Number(eventFilters.limit || 30);
  const offset = Number(eventFilters.offset || 0);

  const columns = [
    {
      title: "事件",
      width: 240,
      render: (_, event) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{event.event_type}</Typography.Text>
          <Space size={4} wrap>
            <Tag>{event.module}</Tag>
            {event.video_id ? <Tag>{event.video_id}</Tag> : null}
            {event.job_id ? <Tag>job {event.job_id}</Tag> : null}
          </Space>
        </Space>
      ),
    },
    {
      title: "消息",
      render: (_, event) => <Typography.Text ellipsis={{ tooltip: event.message || "-" }}>{event.message || "-"}</Typography.Text>,
    },
    {
      title: "时间",
      width: 180,
      dataIndex: "created_at",
    },
  ];

  return (
    <section className="panel wide" id="events">
      <div className="panel-head">
        <h2>事件</h2>
        <Space wrap>
          <Select value={eventFilters.module} style={{ width: 132 }} onChange={(value) => updateEventFilters((prev) => ({ ...prev, module: value, offset: 0 }))} options={eventModules.map((item) => ({ value: item, label: item || "全部模块" }))} />
          <Select value={eventFilters.limit} style={{ width: 100 }} onChange={(value) => updateEventFilters((prev) => ({ ...prev, limit: Number(value), offset: 0 }))} options={[20, 30, 50, 100].map((item) => ({ value: item, label: `${item} 条` }))} />
          <IconButton icon={RefreshCw} onClick={() => loadEvents(eventFilters)}>刷新</IconButton>
        </Space>
      </div>
      <Table
        className="ops-table"
        columns={columns}
        dataSource={rows}
        rowKey="id"
        pagination={false}
        size="middle"
        scroll={{ x: 760 }}
        footer={() => (
          <TablePager
            offset={offset}
            limit={limit}
            count={rows.length}
            hasMore={events?.has_more}
            onPrev={() => updateEventFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}
            onNext={() => updateEventFilters((prev) => ({ ...prev, offset: offset + limit }))}
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
