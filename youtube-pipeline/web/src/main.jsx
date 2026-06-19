import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  Download,
  Eye,
  FileText,
  HardDrive,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
  SkipForward,
  X,
} from "lucide-react";
import "./styles.css";

const statusOptions = ["selected", "downloaded", "ready_to_publish", "published", "failed", "skipped"];
const draftOptions = ["pending", "approved", "rejected"];
const errorOptions = ["youtube_403", "network_error", "llm_failed", "publish_failed", "unknown"];
const configFields = [
  "PIPELINE_ENABLED",
  "WORKER_INTERVAL_SECONDS",
  "WORKER_CRON",
  "WORKER_ENABLE_DISCOVERY",
  "WORKER_ENABLE_DOWNLOAD",
  "WORKER_ENABLE_DESCRIBE",
  "WORKER_ENABLE_PUBLISH",
  "WORKER_PUBLISH_DRY_RUN",
  "PROXY",
  "RETRIES",
  "FRAGMENT_RETRIES",
  "PUBLISH_MODE",
  "PUBLISH_DAILY_LIMIT",
  "PUBLISH_MIN_INTERVAL_SECONDS",
  "STORAGE_MAX_GB",
  "STORAGE_WARN_GB",
  "STORAGE_MIN_FREE_GB",
  "STORAGE_RETENTION_DAYS",
  "STORAGE_CLEANUP_ENABLED",
  "STORAGE_CLEANUP_STATUSES",
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function escapeText(value) {
  return String(value ?? "");
}

function fmtDuration(seconds) {
  if (!seconds) return "-";
  const min = Math.floor(seconds / 60);
  const sec = String(seconds % 60).padStart(2, "0");
  return `${min}:${sec}`;
}

function fmtCount(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString("zh-CN");
}

function fmtBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function statusMap(rows) {
  const map = {};
  for (const row of rows || []) map[row.status] = row.count;
  return map;
}

function flattenConfig(config) {
  const map = {};
  for (const fields of Object.values(config?.groups || {})) {
    for (const field of fields) map[field.key] = field;
  }
  return map;
}

function parseTags(raw) {
  try {
    const parsed = JSON.parse(raw || "[]");
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

function tagsToText(raw) {
  return parseTags(raw).join(", ");
}

function parseTidOptions(raw) {
  return String(raw || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const [tid, ...labelParts] = item.split(":");
      return { tid: tid.trim(), label: labelParts.join(":").trim() };
    })
    .filter((item) => /^\d+$/.test(item.tid));
}

function IconButton({ icon: Icon, children, ...props }) {
  return (
    <button {...props}>
      {Icon ? <Icon size={16} /> : null}
      <span>{children}</span>
    </button>
  );
}

function App() {
  const [status, setStatus] = useState(null);
  const [videos, setVideos] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [config, setConfig] = useState(null);
  const [storage, setStorage] = useState(null);
  const [filters, setFilters] = useState({ status: "", draftStatus: "", errorType: "" });
  const [addUrls, setAddUrls] = useState("");
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(false);

  const configByKey = useMemo(() => flattenConfig(config), [config]);

  function showToast(message) {
    setToast(typeof message === "string" ? message : JSON.stringify(message, null, 2));
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => setToast(""), 5200);
  }

  async function loadConfig() {
    setConfig(await api("/api/config"));
  }

  async function loadStorage() {
    setStorage(await api("/api/storage"));
  }

  async function loadAll(keepSelected = selectedId) {
    const params = new URLSearchParams({ limit: "80" });
    if (filters.status) params.set("status", filters.status);
    if (filters.draftStatus) params.set("draft_status", filters.draftStatus);
    if (filters.errorType) params.set("error_type", filters.errorType);
    const [statusPayload, listPayload] = await Promise.all([
      api("/api/status?events_limit=5"),
      api(`/api/videos?${params.toString()}`),
    ]);
    setStatus(statusPayload);
    setVideos(listPayload.videos || []);
    if (keepSelected && (listPayload.videos || []).some((item) => item.video.video_id === keepSelected)) {
      await selectVideo(keepSelected);
    } else {
      setSelectedId("");
      setDetail(null);
    }
  }

  async function selectVideo(videoId) {
    setSelectedId(videoId);
    setDetail(await api(`/api/videos/${encodeURIComponent(videoId)}`));
  }

  async function runVideoAction(videoId, action) {
    const body = {};
    if (action === "publish") {
      if (!window.confirm("确认真实发布到 B 站？")) return;
      body.confirm = true;
    }
    if (action === "skip" && !window.confirm("确认跳过该视频？")) return;
    try {
      const result = await api(`/api/videos/${encodeURIComponent(videoId)}/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      showToast(result);
      await loadAll(videoId);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function runWorker() {
    try {
      const result = await api("/api/worker-run", { method: "POST", body: "{}" });
      showToast(result);
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function discoverDryRun() {
    try {
      const result = await api("/api/discover", { method: "POST", body: JSON.stringify({ dry_run: true }) });
      showToast(result);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function saveConfig() {
    const values = {};
    for (const key of configFields) {
      const field = configByKey[key];
      if (!field) continue;
      const element = document.querySelector(`[data-config-key="${key}"]`);
      if (!element) continue;
      if (field.type === "bool") values[key] = element.value === "true";
      else if (field.type === "int") values[key] = Number.parseInt(element.value || "0", 10);
      else if (field.type === "float") values[key] = Number.parseFloat(element.value || "0");
      else values[key] = element.value;
    }
    try {
      const result = await api("/api/config", { method: "PATCH", body: JSON.stringify({ values }) });
      setConfig(result.config);
      showToast(`已保存配置：${result.updated.join(", ")}`);
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function addQueueUrls() {
    const value = addUrls.trim();
    if (!value) {
      showToast("请输入至少一个 YouTube 链接。");
      return;
    }
    try {
      const result = await api("/api/videos/add-urls", {
        method: "POST",
        body: JSON.stringify({ urls: value }),
      });
      setAddUrls("");
      showToast(`添加完成：created=${result.created_count}, exists=${result.exists_count}, errors=${result.error_count}`);
      const firstCreated = (result.results || []).find((item) => item.status === "created");
      await loadAll(firstCreated?.video?.video_id || "");
    } catch (error) {
      showToast(error.message);
    }
  }

  async function refreshAll() {
    setLoading(true);
    try {
      await Promise.all([loadAll(), loadConfig(), loadStorage()]);
    } catch (error) {
      showToast(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    loadAll("").catch((error) => showToast(error.message));
  }, [filters.status, filters.draftStatus, filters.errorType]);

  const counts = statusMap(status?.videos_by_status);
  const locks = status?.job_lock_status || {};
  const stats = [
    ["active", status?.active_queue_count || 0],
    ["ready", counts.ready_to_publish || 0],
    ["published", counts.published || 0],
    ["running", locks.running || 0],
    ["locked", locks.locked || 0],
    ["mode", status?.settings?.publish_mode || "-"],
  ];

  async function runStorageCleanup(dryRun) {
    if (!dryRun && !window.confirm("确认清理符合条件的媒体文件？数据库记录会保留。")) return;
    try {
      const result = await api("/api/storage/cleanup", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, confirm: !dryRun }),
      });
      showToast(result);
      await Promise.all([loadStorage(), loadAll(selectedId)]);
    } catch (error) {
      showToast(error.message);
    }
  }

  return (
    <>
      <header>
        <div>
          <h1>YouTube Pipeline</h1>
          <div className="muted">发现、下载、文案、发布队列</div>
        </div>
        <div className="toolbar">
          <IconButton icon={Play} onClick={runWorker}>运行一轮</IconButton>
          <IconButton icon={Search} onClick={discoverDryRun}>发现预览</IconButton>
          <IconButton icon={RefreshCw} className="primary" onClick={refreshAll} disabled={loading}>刷新</IconButton>
        </div>
      </header>

      <main>
        <section className="panel">
          <div className="panel-head">
            <h2>队列</h2>
            <div className="toolbar">
              <select value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
                <option value="">全部</option>
                {statusOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <select value={filters.draftStatus} onChange={(event) => setFilters((prev) => ({ ...prev, draftStatus: event.target.value }))}>
                <option value="">草稿全部</option>
                {draftOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <select value={filters.errorType} onChange={(event) => setFilters((prev) => ({ ...prev, errorType: event.target.value }))}>
                <option value="">错误全部</option>
                {errorOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </div>
          </div>
          <div className="stats">
            {stats.map(([label, value]) => (
              <div className="stat" key={label}>
                <span>{label}</span>
                <b>{value}</b>
              </div>
            ))}
          </div>
          <div className="add-url-box">
            <textarea value={addUrls} onChange={(event) => setAddUrls(event.target.value)} placeholder="输入 YouTube 链接，支持一行一个" />
            <div className="toolbar">
              <IconButton icon={Send} className="primary" onClick={addQueueUrls}>添加到队列</IconButton>
              <span className="muted">重复 video_id 不会重复入库。</span>
            </div>
          </div>
          <VideoList videos={videos} selectedId={selectedId} onSelect={selectVideo} />
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>详情</h2>
            <div className="muted">{selectedId || "未选择"}</div>
          </div>
          <div className="panel-body">
            {detail ? (
              <VideoDetail
                data={detail}
                configByKey={configByKey}
                onAction={runVideoAction}
                onSaved={async () => {
                  await loadAll(detail.video.video_id);
                }}
                showToast={showToast}
              />
            ) : <div className="muted">请选择一个视频。</div>}
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-head">
            <h2>配置</h2>
            <div className="toolbar">
              <IconButton icon={RefreshCw} onClick={loadConfig}>重新加载</IconButton>
              <IconButton icon={Settings} className="primary" onClick={saveConfig}>保存配置</IconButton>
            </div>
          </div>
          <ConfigPanel config={config} configByKey={configByKey} />
        </section>

        <section className="panel wide">
          <div className="panel-head">
            <h2>存储</h2>
            <div className="toolbar">
              <IconButton icon={RefreshCw} onClick={loadStorage}>刷新</IconButton>
              <IconButton icon={HardDrive} onClick={() => runStorageCleanup(true)}>清理预览</IconButton>
              <IconButton icon={X} className="danger" onClick={() => runStorageCleanup(false)}>执行清理</IconButton>
            </div>
          </div>
          <StoragePanel storage={storage} />
        </section>
      </main>

      {toast ? <div className="toast show">{toast}</div> : null}
    </>
  );
}

function StoragePanel({ storage }) {
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

function VideoList({ videos, selectedId, onSelect }) {
  if (!videos.length) return <div className="panel-body muted">暂无数据。</div>;
  return (
    <div className="video-list">
      {videos.map((item) => {
        const video = item.video;
        const draft = item.publish_draft || {};
        const title = draft.title || video.title || video.video_id;
        const poster = item.media_files?.poster_path ? `/api/videos/${encodeURIComponent(video.video_id)}/file?type=poster` : "";
        return (
          <button className={`video-row${video.video_id === selectedId ? " active" : ""}`} key={video.video_id} onClick={() => onSelect(video.video_id)}>
            {poster ? <img className="thumb" src={poster} alt="" /> : <div className="thumb" />}
            <div>
              <div className="title">{title}</div>
              <div className="meta-line">{escapeText(video.channel || "-")} · {fmtDuration(video.duration)} · {fmtCount(video.view_count)} views</div>
              <div className="badges">
                <span className={`badge ${video.status}`}>{video.status}</span>
                {draft.status ? <span className="badge">{draft.status}</span> : null}
                {draft.tid ? <span className="badge">tid {draft.tid}</span> : null}
                {draft.tid_source ? <span className="badge">{draft.tid_source}</span> : null}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function VideoDetail({ data, configByKey, onAction, onSaved, showToast }) {
  const video = data.video;
  const draft = data.publish_draft || {};
  const records = data.publish_records || [];
  const events = data.events || [];
  const jobs = [
    ["download", data.latest_download_job],
    ["describe", data.latest_describe_job],
    ["publish", data.latest_publish_job],
  ].filter((entry) => entry[1]);
  const canPublish = video.status === "ready_to_publish" && draft.tid_source !== "fallback" && draft.status !== "rejected";
  const canReview = video.status === "ready_to_publish" && Boolean(draft.title);
  const canDescribe = ["downloaded", "ready_to_publish", "failed"].includes(video.status);
  const canDownload = ["selected", "failed"].includes(video.status);
  const canRetry = video.status === "failed";
  const canSkip = !["published", "skipped"].includes(video.status);
  const tidOptions = parseTidOptions(configByKey?.BILIBILI_TID_OPTIONS?.value);
  const [draftForm, setDraftForm] = useState(() => makeDraftForm(draft));
  const [savingDraft, setSavingDraft] = useState(false);

  useEffect(() => {
    setDraftForm(makeDraftForm(draft));
  }, [video.video_id, draft.updated_at]);

  function updateDraftField(field, value) {
    setDraftForm((prev) => ({ ...prev, [field]: value }));
  }

  async function saveDraft() {
    if (!draft.title) return;
    setSavingDraft(true);
    try {
      const result = await api(`/api/videos/${encodeURIComponent(video.video_id)}/draft`, {
        method: "PATCH",
        body: JSON.stringify({
          title: draftForm.title,
          description: draftForm.description,
          tags: draftForm.tags,
          tid: Number.parseInt(draftForm.tid || "0", 10),
          status: draftForm.status || "pending",
        }),
      });
      showToast(result);
      await onSaved();
    } catch (error) {
      showToast(error.message);
    } finally {
      setSavingDraft(false);
    }
  }

  return (
    <div className="detail-grid">
      <div>
        <section className="section">
          <h2>{video.title || video.video_id}</h2>
          <div className="kv">
            <div>状态</div><div><span className={`badge ${video.status}`}>{video.status}</span></div>
            <div>频道</div><div>{video.channel || "-"}</div>
            <div>时长</div><div>{fmtDuration(video.duration)}</div>
            <div>播放</div><div>{fmtCount(video.view_count)}</div>
            <div>分类</div><div>{video.category || "-"}</div>
            <div>原链接</div><div><a href={video.source_url} target="_blank" rel="noreferrer">{video.source_url}</a></div>
          </div>
          {video.last_error ? <p className="badge failed">{video.last_error}</p> : null}
          <div className="actions">
            <IconButton icon={Download} disabled={!canDownload} onClick={() => onAction(video.video_id, "download")}>下载</IconButton>
            <IconButton icon={FileText} disabled={!canDescribe} onClick={() => onAction(video.video_id, "describe")}>生成文案</IconButton>
            <IconButton icon={Check} disabled={!canReview || draft.status === "approved"} onClick={() => onAction(video.video_id, "approve")}>通过</IconButton>
            <IconButton icon={X} disabled={!canReview || draft.status === "rejected"} onClick={() => onAction(video.video_id, "reject")}>拒绝</IconButton>
            <IconButton icon={Eye} disabled={!canPublish} onClick={() => onAction(video.video_id, "publish-dry-run")}>发布预览</IconButton>
            <IconButton icon={Send} className="primary" disabled={!canPublish} onClick={() => onAction(video.video_id, "publish")}>真实发布</IconButton>
            <IconButton icon={RotateCcw} disabled={!canRetry} onClick={() => onAction(video.video_id, "retry")}>重试</IconButton>
            <IconButton icon={SkipForward} className="danger" disabled={!canSkip} onClick={() => onAction(video.video_id, "skip")}>跳过</IconButton>
          </div>
        </section>

        <section className="section">
          <h2>发布草稿</h2>
          {draft.title ? (
            <>
              <div className="draft-form">
                <label>
                  <span>标题</span>
                  <input value={draftForm.title} onChange={(event) => updateDraftField("title", event.target.value)} maxLength={80} />
                </label>
                <label>
                  <span>描述</span>
                  <textarea value={draftForm.description} onChange={(event) => updateDraftField("description", event.target.value)} rows={7} />
                </label>
                <label>
                  <span>标签</span>
                  <input value={draftForm.tags} onChange={(event) => updateDraftField("tags", event.target.value)} placeholder="使用逗号分隔" />
                </label>
                <div className="draft-row">
                  <label>
                    <span>分区</span>
                    <select value={draftForm.tid} onChange={(event) => updateDraftField("tid", event.target.value)}>
                      <option value="">请选择</option>
                      {tidOptions.map((item) => <option value={item.tid} key={item.tid}>{item.tid} {item.label}</option>)}
                      {!tidOptions.some((item) => item.tid === String(draft.tid || "")) && draft.tid ? (
                        <option value={String(draft.tid)}>{draft.tid} {draft.tid_label || ""}</option>
                      ) : null}
                    </select>
                  </label>
                  <label>
                    <span>审核</span>
                    <select value={draftForm.status} onChange={(event) => updateDraftField("status", event.target.value)}>
                      {draftOptions.map((item) => <option value={item} key={item}>{item}</option>)}
                    </select>
                  </label>
                </div>
                <div className="toolbar">
                  <IconButton icon={Save} className="primary" onClick={saveDraft} disabled={savingDraft}>保存草稿</IconButton>
                  <span className="muted">保存后分区来源会标记为 manual。</span>
                </div>
              </div>
              <div className="kv draft-meta">
                <div>当前分区</div><div>{draft.tid || "-"} {draft.tid_label || ""}</div>
                <div>审核</div><div><span className="badge">{draft.status || "-"}</span> {draft.review_note || ""}</div>
                <div>来源</div><div>{draft.tid_source || "-"}</div>
                <div>原因</div><div>{draft.tid_reason || "-"}</div>
              </div>
              <div className="badges">
                {parseTags(draft.tags_json).map((tag) => <span className="badge" key={tag}>{tag}</span>)}
              </div>
            </>
          ) : <div className="muted">暂无草稿。</div>}
        </section>

        <section className="section">
          <h2>任务状态</h2>
          {jobs.length ? jobs.map(([name, job]) => {
            const attempts = `${job.attempts || 0}/${job.max_attempts || 0}`;
            const lock = job.locked_at ? `lock ${job.lock_owner || "-"} ${job.locked_at}` : "";
            const text = [job.error_type, job.next_run_at ? `next ${job.next_run_at}` : "", lock, job.error].filter(Boolean).join(" · ");
            return <div className="event" key={name}><b>{name}</b> · <span className={`badge ${job.status}`}>{job.status}</span> · {attempts}<div className="muted">{text || "-"}</div></div>;
          }) : <div className="muted">暂无任务记录。</div>}
        </section>

        <section className="section">
          <h2>发布记录</h2>
          {records.length ? records.map((record) => (
            <div className="event" key={record.id}>{record.platform} · {record.account} · {record.status} · {record.published_at || record.created_at}</div>
          )) : <div className="muted">暂无发布记录。</div>}
        </section>

        <section className="section">
          <h2>最近事件</h2>
          <div className="events">
            {events.map((event) => (
              <div className="event" key={event.id}>
                <b>{event.event_type}</b>
                <div className="muted">{event.created_at} · {event.module}</div>
                <div>{event.message}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
      <div>
        <img className="poster" src={`/api/videos/${encodeURIComponent(video.video_id)}/file?type=poster`} alt="" />
        <div className="actions">
          <a href={`/api/videos/${encodeURIComponent(video.video_id)}/file?type=merged`} target="_blank" rel="noreferrer"><button>查看视频</button></a>
          <a href={`/api/videos/${encodeURIComponent(video.video_id)}/file?type=meta`} target="_blank" rel="noreferrer"><button>meta</button></a>
        </div>
      </div>
    </div>
  );
}

function makeDraftForm(draft) {
  return {
    title: draft.title || "",
    description: draft.description || "",
    tags: tagsToText(draft.tags_json),
    tid: draft.tid ? String(draft.tid) : "",
    status: draft.status || "pending",
  };
}

function ConfigPanel({ config, configByKey }) {
  if (!config) return <div className="panel-body muted">正在加载配置。</div>;
  return (
    <div className="panel-body">
      <div className="config-grid">
        {configFields.map((key) => {
          const field = configByKey[key];
          if (!field) return null;
          const value = field.value ?? "";
          return (
            <div className="config-field" key={key}>
              <label htmlFor={`cfg_${key}`}>{key}</label>
              {field.type === "bool" ? (
                <select id={`cfg_${key}`} data-config-key={key} defaultValue={value ? "true" : "false"}>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : field.choices?.length ? (
                <select id={`cfg_${key}`} data-config-key={key} defaultValue={String(value)}>
                  {field.choices.map((choice) => <option value={choice} key={choice}>{choice || "(empty)"}</option>)}
                </select>
              ) : (
                <input id={`cfg_${key}`} data-config-key={key} defaultValue={String(value)} />
              )}
            </div>
          );
        })}
      </div>
      <div className="muted config-path">配置文件：{config.env_path || "-"}</div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
