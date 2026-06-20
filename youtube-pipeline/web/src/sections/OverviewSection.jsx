import { AlertTriangle, CheckCircle2, Clock, Database, HardDrive, PauseCircle, PlayCircle } from "lucide-react";
import { fmtBytes, statusMap } from "../format";

export function OverviewSection({ state }) {
  const { status, storage } = state;
  const counts = statusMap(status?.videos_by_status);
  const locks = status?.job_lock_status || {};
  const settings = status?.settings || {};
  const failedVideos = status?.failed_videos || [];
  const publishEnabled = Boolean(settings.worker_enable_publish);
  const dryRun = Boolean(settings.worker_publish_dry_run);
  const storageAlerts = [
    storage?.over_max ? "超过最大占用" : "",
    storage?.over_warn ? "超过警戒线" : "",
    storage?.below_min_free ? "磁盘剩余空间不足" : "",
  ].filter(Boolean);

  const cards = [
    {
      label: "自动发布",
      value: publishEnabled ? (dryRun ? "dry-run" : "enabled") : "disabled",
      icon: publishEnabled ? PlayCircle : PauseCircle,
      tone: publishEnabled && !dryRun ? "ok" : "warn",
      sub: `mode ${settings.publish_mode || "-"}`,
    },
    {
      label: "活跃队列",
      value: status?.active_queue_count || 0,
      icon: Clock,
      tone: (status?.active_queue_count || 0) > 0 ? "ok" : "",
      sub: `selected ${counts.selected || 0} / downloaded ${counts.downloaded || 0}`,
    },
    {
      label: "待发布",
      value: counts.ready_to_publish || 0,
      icon: CheckCircle2,
      tone: (counts.ready_to_publish || 0) > 0 ? "ok" : "",
      sub: `published ${counts.published || 0}`,
    },
    {
      label: "任务运行",
      value: locks.running || 0,
      icon: Database,
      tone: (locks.running || 0) > 0 ? "ok" : "",
      sub: `locked ${locks.locked || 0}`,
    },
    {
      label: "下载目录",
      value: storage ? fmtBytes(storage.total_size_bytes) : "-",
      icon: HardDrive,
      tone: storageAlerts.length ? "warn" : "",
      sub: storage ? `free ${fmtBytes(storage.disk_free_bytes)}` : "loading",
    },
    {
      label: "失败视频",
      value: counts.failed || 0,
      icon: AlertTriangle,
      tone: (counts.failed || 0) > 0 ? "danger" : "",
      sub: failedVideos[0]?.title || failedVideos[0]?.video_id || "no recent failures",
    },
  ];

  return (
    <section className="panel wide overview-panel" id="overview">
      <div className="panel-head">
        <h2>总览</h2>
        <div className="muted">
          发布窗口 {settings.publish_window_start || "-"} - {settings.publish_window_end || "-"} · 每日上限 {settings.publish_daily_limit ?? "-"}
        </div>
      </div>
      <div className="overview-grid">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <div className={`overview-card ${card.tone}`} key={card.label}>
              <div className="overview-icon"><Icon size={18} /></div>
              <div>
                <span>{card.label}</span>
                <b>{card.value}</b>
                <small>{card.sub}</small>
              </div>
            </div>
          );
        })}
      </div>
      {storageAlerts.length ? (
        <div className="overview-alerts">
          {storageAlerts.map((item) => <span className="badge failed" key={item}>{item}</span>)}
        </div>
      ) : null}
    </section>
  );
}
