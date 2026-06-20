import { Play, RefreshCw } from "lucide-react";
import { IconButton } from "../components/IconButton";

export function WorkerSection({ state, actions }) {
  const { status } = state;
  const { runWorker, refreshAll } = actions;
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
        <div className="toolbar">
          <IconButton icon={Play} className="primary" onClick={runWorker}>运行一轮</IconButton>
          <IconButton icon={RefreshCw} onClick={refreshAll}>刷新状态</IconButton>
        </div>
      </div>
      <div className="worker-grid">
        <div className="worker-card">
          <h3>运行开关</h3>
          <div className="switch-list">
            {switches.map(([label, value]) => (
              <div className="switch-row" key={label}>
                <span>{label}</span>
                <span className={`badge ${value ? "published" : "failed"}`}>{value ? "on" : "off"}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="worker-card">
          <h3>调度参数</h3>
          <div className="kv compact">
            <div>interval</div><div>{settings.worker_interval_seconds ?? "-"} 秒</div>
            <div>cron</div><div>{settings.worker_cron || "未启用"}</div>
            <div>lease</div><div>{settings.job_lease_seconds ?? "-"} 秒</div>
            <div>队列阈值</div><div>{settings.worker_discovery_min_queue_size ?? "-"}</div>
            <div>发现源</div><div>{settings.worker_discovery_source || "全部"}</div>
          </div>
        </div>
        <div className="worker-card">
          <h3>任务锁</h3>
          <div className="worker-locks">
            <div><b>{locks.running || 0}</b><span>running</span></div>
            <div><b>{locks.locked || 0}</b><span>locked</span></div>
          </div>
        </div>
        <div className="worker-card">
          <h3>Job 分布</h3>
          {jobRows.length ? (
            <div className="job-status-table">
              {jobRows.map((row) => (
                <div key={`${row.job_type}-${row.status}`}>
                  <span>{row.job_type}</span>
                  <span className={`badge ${row.status}`}>{row.status}</span>
                  <b>{row.count}</b>
                </div>
              ))}
            </div>
          ) : <div className="muted">暂无 job。</div>}
        </div>
        <div className="worker-card wide">
          <h3>最近 Worker 事件</h3>
          {workerEvents.length ? (
            <div className="worker-events">
              {workerEvents.slice(0, 6).map((event) => (
                <div className="worker-event" key={event.id}>
                  <div>
                    <b>{event.event_type}</b>
                    <span>{event.created_at}</span>
                  </div>
                  <p>{event.message}</p>
                </div>
              ))}
            </div>
          ) : <div className="muted">暂无 worker 事件。</div>}
        </div>
      </div>
    </section>
  );
}
