import { fmtBytes } from "../format";

export function StoragePanel({ storage }) {
  if (!storage) return <div className="panel-body muted">正在加载存储信息。</div>;
  const preview = storage.cleanup_preview || {};
  const alerts = [
    storage.over_max ? "超过最大占用" : "",
    storage.over_warn ? "超过警戒线" : "",
    storage.below_min_free ? "磁盘剩余空间不足" : "",
  ].filter(Boolean);
  return (
    <div className="panel-body">
      <div className="stats storage-stats">
        <div className="stat"><span>下载目录</span><b>{fmtBytes(storage.total_size_bytes)}</b></div>
        <div className="stat"><span>磁盘剩余</span><b>{fmtBytes(storage.disk_free_bytes)}</b></div>
        <div className="stat"><span>清理候选</span><b>{preview.count || 0}</b></div>
        <div className="stat"><span>可释放</span><b>{fmtBytes(preview.size_bytes)}</b></div>
        <div className="stat"><span>保留天数</span><b>{storage.retention_days}</b></div>
        <div className="stat"><span>清理开关</span><b>{storage.cleanup_enabled ? "on" : "off"}</b></div>
      </div>
      <div className="storage-path">{storage.output_dir}</div>
      {alerts.length ? <div className="badges">{alerts.map((item) => <span className="badge failed" key={item}>{item}</span>)}</div> : null}
      <div className="storage-grid">
        <section className="section">
          <h2>状态占用</h2>
          {(storage.by_status || []).length ? storage.by_status.map((row) => (
            <div className="storage-row" key={row.status}>
              <span>{row.status}</span>
              <b>{fmtBytes(row.size_bytes)}</b>
            </div>
          )) : <div className="muted">暂无媒体文件。</div>}
        </section>
        <section className="section">
          <h2>清理候选</h2>
          {(preview.items || []).length ? preview.items.slice(0, 12).map((item) => (
            <div className="storage-row" key={item.video_id}>
              <span>{item.video_id} · {item.status}</span>
              <b>{fmtBytes(item.size_bytes)}</b>
            </div>
          )) : <div className="muted">暂无可清理内容。</div>}
        </section>
      </div>
    </div>
  );
}
