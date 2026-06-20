import React, { useEffect, useMemo, useState } from "react";
import {
  Check,
  HardDrive,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Settings,
  SkipForward,
  X,
} from "lucide-react";
import { api } from "./api";
import { configFields, errorOptions, statusOptions } from "./constants";
import { flattenConfig, statusMap } from "./format";
import { ConfigPanel } from "./components/ConfigPanel";
import { DiscoverySourcesPanel } from "./components/DiscoverySourcesPanel";
import { IconButton } from "./components/IconButton";
import { StoragePanel } from "./components/StoragePanel";
import { VideoDetail } from "./components/VideoDetail";
import { VideoList } from "./components/VideoList";

function App() {
  const [status, setStatus] = useState(null);
  const [videos, setVideos] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [config, setConfig] = useState(null);
  const [storage, setStorage] = useState(null);
  const [discoverySources, setDiscoverySources] = useState([]);
  const [sourcePreview, setSourcePreview] = useState(null);
  const [filters, setFilters] = useState({ status: "", draftStatus: "", errorType: "" });
  const [selectedVideoIds, setSelectedVideoIds] = useState([]);
  const [addUrls, setAddUrls] = useState("");
  const [addPriority, setAddPriority] = useState("100");
  const [addSourceLabel, setAddSourceLabel] = useState("web");
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

  async function loadDiscoverySources() {
    const payload = await api("/api/discovery/sources");
    setDiscoverySources(payload.sources || []);
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
    setSelectedVideoIds((prev) => {
      const visibleIds = new Set((listPayload.videos || []).map((item) => item.video.video_id));
      return prev.filter((videoId) => visibleIds.has(videoId));
    });
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
    if (action === "cleanup-media") {
      if (!window.confirm("确认清理该视频的媒体文件？数据库记录会保留。")) return;
      body.confirm = true;
      body.dry_run = false;
    }
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
        body: JSON.stringify({
          urls: value,
          priority: Number.parseInt(addPriority || "100", 10),
          source_label: addSourceLabel.trim() || "web",
        }),
      });
      setAddUrls("");
      showToast(`添加完成：created=${result.created_count}, exists=${result.exists_count}, errors=${result.error_count}`);
      const firstCreated = (result.results || []).find((item) => item.status === "created");
      await loadAll(firstCreated?.video?.video_id || "");
    } catch (error) {
      showToast(error.message);
    }
  }

  async function runBatchAction(action) {
    if (!selectedVideoIds.length) {
      showToast("请先选择视频。");
      return;
    }
    if (action === "skip" && !window.confirm(`确认跳过 ${selectedVideoIds.length} 个视频？`)) return;
    try {
      const result = await api("/api/videos/batch", {
        method: "POST",
        body: JSON.stringify({ action, video_ids: selectedVideoIds }),
      });
      showToast(result);
      setSelectedVideoIds([]);
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function refreshAll() {
    setLoading(true);
    try {
      await Promise.all([loadAll(), loadConfig(), loadStorage(), loadDiscoverySources()]);
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

  async function saveDiscoverySource(source, index = null) {
    try {
      const path = index === null ? "/api/discovery/sources" : `/api/discovery/sources/${index}`;
      const result = await api(path, {
        method: index === null ? "POST" : "PATCH",
        body: JSON.stringify(index === null ? { source } : source),
      });
      setDiscoverySources(result.sources || []);
      await loadConfig();
      showToast(result);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function deleteDiscoverySource(index) {
    if (!window.confirm("确认删除该发现源？")) return;
    try {
      const result = await api(`/api/discovery/sources/${index}`, { method: "DELETE", body: "{}" });
      setDiscoverySources(result.sources || []);
      await loadConfig();
      showToast(result);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function previewDiscoverySource(index) {
    if (index === null || index === undefined) {
      showToast("请先选择发现源。");
      return;
    }
    try {
      const result = await api(`/api/discovery/sources/${index}`, {
        method: "POST",
        body: JSON.stringify({ action: "preview" }),
      });
      setSourcePreview(result);
      showToast(`预览完成：accepted=${result.accepted_count}, rejected=${result.rejected_count}`);
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
            <div className="queue-meta-row">
              <label>
                <span>优先级</span>
                <input value={addPriority} onChange={(event) => setAddPriority(event.target.value)} />
              </label>
              <label>
                <span>来源标签</span>
                <input value={addSourceLabel} onChange={(event) => setAddSourceLabel(event.target.value)} />
              </label>
            </div>
            <div className="toolbar">
              <IconButton icon={Send} className="primary" onClick={addQueueUrls}>添加到队列</IconButton>
              <span className="muted">重复 video_id 不会重复入库。</span>
            </div>
          </div>
          <div className="bulk-toolbar">
            <div className="toolbar">
              <button onClick={() => setSelectedVideoIds(videos.map((item) => item.video.video_id))}>全选</button>
              <button onClick={() => setSelectedVideoIds([])}>清空</button>
              <IconButton icon={Check} disabled={!selectedVideoIds.length} onClick={() => runBatchAction("approve")}>批量通过</IconButton>
              <IconButton icon={RotateCcw} disabled={!selectedVideoIds.length} onClick={() => runBatchAction("retry")}>批量重试</IconButton>
              <IconButton icon={SkipForward} className="danger" disabled={!selectedVideoIds.length} onClick={() => runBatchAction("skip")}>批量跳过</IconButton>
            </div>
            <span className="muted">已选择 {selectedVideoIds.length} 项</span>
          </div>
          <VideoList
            videos={videos}
            selectedId={selectedId}
            selectedVideoIds={selectedVideoIds}
            onToggleSelected={(videoId, checked) => {
              setSelectedVideoIds((prev) => checked ? [...new Set([...prev, videoId])] : prev.filter((item) => item !== videoId));
            }}
            onSelect={selectVideo}
          />
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

        <section className="panel wide">
          <div className="panel-head">
            <h2>发现源</h2>
            <div className="toolbar">
              <IconButton icon={RefreshCw} onClick={loadDiscoverySources}>刷新</IconButton>
            </div>
          </div>
          <DiscoverySourcesPanel
            sources={discoverySources}
            preview={sourcePreview}
            onSave={saveDiscoverySource}
            onDelete={deleteDiscoverySource}
            onPreview={previewDiscoverySource}
          />
        </section>
      </main>

      {toast ? <div className="toast show">{toast}</div> : null}
    </>
  );
}

export default App;
