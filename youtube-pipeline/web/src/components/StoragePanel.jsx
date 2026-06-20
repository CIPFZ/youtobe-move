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
          <div className="section-headline">
            <h2>清理候选</h2>
            <span className="muted">共 {preview.count || 0} 项，预计释放 {fmtBytes(preview.size_bytes)}</span>
          </div>
          <CleanupCandidates items={preview.items || []} />
        </section>
      </div>
    </div>
  );
}

function CleanupCandidates({ items }) {
  if (!items.length) return <div className="muted">暂无可清理内容。</div>;
  return (
    <div className="cleanup-list">
      {items.slice(0, 20).map((item) => (
        <details className="cleanup-item" key={item.video_id}>
          <summary>
            <span>
              <b>{item.title || item.video_id}</b>
              <small>{item.video_id} · {item.status} · {item.updated_at || "-"}</small>
            </span>
            <strong>{fmtBytes(item.size_bytes)}</strong>
          </summary>
          <div className="cleanup-paths">
            {(item.paths || []).map((path) => (
              <div className="cleanup-path" key={`${item.video_id}-${path.field}`}>
                <span>{path.field}</span>
                <code>{path.path}</code>
                <b>{fmtBytes(path.size_bytes)}</b>
              </div>
            ))}
          </div>
        </details>
      ))}
      {items.length > 20 ? <div className="muted">仅展示前 20 项。</div> : null}
    </div>
  );
}
