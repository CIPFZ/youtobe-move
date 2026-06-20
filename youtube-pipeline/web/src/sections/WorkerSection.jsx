import { Card, Col, Descriptions, List, Row, Space, Statistic, Tag } from "antd";
import { Play, RefreshCw } from "lucide-react";
import { IconButton } from "../components/IconButton";

export function WorkerSection({ state, actions }) {
  const { status } = state;
  const { runWorker, loadOperationsPage } = actions;
  const settings = status?.settings || {};
  const jobRows = status?.jobs_by_type_status || [];
  const locks = status?.job_lock_status || {};
  const workerEvents = (status?.recent_events || []).filter((event) => event.module === "worker");
  const switches = [
    ["总开关", settings.pipeline_enabled],
    ["发现", settings.worker_enable_discovery],
    ["下载", settings.worker_enable_download],
    ["文案", settings.worker_enable_describe],
    ["发布", settings.worker_enable_publish],
    ["发布 dry-run", settings.worker_publish_dry_run],
  ];

  return (
    <section className="panel" id="worker">
      <div className="panel-head">
        <h2>Worker</h2>
        <Space wrap>
          <IconButton icon={Play} className="primary" onClick={runWorker}>运行一轮</IconButton>
          <IconButton icon={RefreshCw} onClick={loadOperationsPage}>刷新状态</IconButton>
        </Space>
      </div>
      <div className="panel-body">
        <Row gutter={[12, 12]}>
          <Col xs={24} lg={8}>
            <Card size="small" title="运行开关">
              <Space wrap>
                {switches.map(([label, value]) => (
                  <Tag color={value ? "success" : "error"} key={label}>{label}: {value ? "on" : "off"}</Tag>
                ))}
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card size="small" title="调度参数">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="interval">{settings.worker_interval_seconds ?? "-"} 秒</Descriptions.Item>
                <Descriptions.Item label="cron">{settings.worker_cron || "未启用"}</Descriptions.Item>
                <Descriptions.Item label="lease">{settings.job_lease_seconds ?? "-"} 秒</Descriptions.Item>
                <Descriptions.Item label="队列阈值">{settings.worker_discovery_min_queue_size ?? "-"}</Descriptions.Item>
                <Descriptions.Item label="发现源">{settings.worker_discovery_source || "全部"}</Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card size="small" title="任务锁">
              <Row gutter={12}>
                <Col span={12}><Statistic title="running" value={locks.running || 0} /></Col>
                <Col span={12}><Statistic title="locked" value={locks.locked || 0} /></Col>
              </Row>
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card size="small" title="Job 分布">
              {jobRows.length ? (
                <Space wrap>
                  {jobRows.map((row) => (
                    <Tag key={`${row.job_type}-${row.status}`}>{row.job_type} / {row.status}: {row.count}</Tag>
                  ))}
                </Space>
              ) : <span className="muted">暂无 job。</span>}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card size="small" title="最近 Worker 事件">
              <List
                size="small"
                dataSource={workerEvents.slice(0, 6)}
                locale={{ emptyText: "暂无 worker 事件。" }}
                renderItem={(event) => (
                  <List.Item>
                    <List.Item.Meta
                      title={<Space><span>{event.event_type}</span><Tag>{event.created_at}</Tag></Space>}
                      description={event.message}
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </section>
  );
}
