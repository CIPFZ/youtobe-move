import React, { useEffect, useState } from "react";
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
import { draftOptions, errorOptions, statusOptions } from "./constants";
import { ConfigPanel } from "./components/ConfigPanel";
import { DiscoverySourcesPanel } from "./components/DiscoverySourcesPanel";
import { IconButton } from "./components/IconButton";
import { StoragePanel } from "./components/StoragePanel";
import { VideoDetail } from "./components/VideoDetail";
import { VideoList } from "./components/VideoList";
import { usePipelineDashboard } from "./hooks/usePipelineDashboard";

function App() {
  const [toast, setToast] = useState("");

  function showToast(message) {
    setToast(typeof message === "string" ? message : JSON.stringify(message, null, 2));
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => setToast(""), 5200);
  }

  const { state, actions } = usePipelineDashboard(showToast);
  const {
    videos,
    selectedId,
    detail,
    config,
    configByKey,
    storage,
    discoverySources,
    sourcePreview,
    filters,
    selectedVideoIds,
    addUrls,
    addPriority,
    addSourceLabel,
    loading,
    stats,
  } = state;
  const {
    setAddUrls,
    setAddPriority,
    setAddSourceLabel,
    setSelectedVideoIds,
    updateFilters,
    loadAll,
    loadConfig,
    loadStorage,
    loadDiscoverySources,
    refreshAll,
    selectVideo,
    runVideoAction,
    runWorker,
    discoverDryRun,
    saveConfig,
    addQueueUrls,
    runBatchAction,
    toggleSelectedVideo,
    runStorageCleanup,
    saveDiscoverySource,
    deleteDiscoverySource,
    previewDiscoverySource,
  } = actions;

  useEffect(() => {
    refreshAll();
  }, []);

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
              <select value={filters.status} onChange={(event) => updateFilters((prev) => ({ ...prev, status: event.target.value }))}>
                <option value="">全部</option>
                {statusOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <select value={filters.draftStatus} onChange={(event) => updateFilters((prev) => ({ ...prev, draftStatus: event.target.value }))}>
                <option value="">草稿全部</option>
                {draftOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <select value={filters.errorType} onChange={(event) => updateFilters((prev) => ({ ...prev, errorType: event.target.value }))}>
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
            onToggleSelected={toggleSelectedVideo}
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
