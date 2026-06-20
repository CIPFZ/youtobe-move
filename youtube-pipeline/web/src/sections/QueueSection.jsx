import { Check, RotateCcw, Send, SkipForward } from "lucide-react";
import { draftOptions, errorOptions, statusOptions } from "../constants";
import { IconButton } from "../components/IconButton";
import { VideoList } from "../components/VideoList";

export function QueueSection({ state, actions }) {
  const {
    videos,
    selectedId,
    filters,
    selectedVideoIds,
    addUrls,
    addPriority,
    addSourceLabel,
  } = state;
  const {
    setAddUrls,
    setAddPriority,
    setAddSourceLabel,
    setSelectedVideoIds,
    updateFilters,
    addQueueUrls,
    runBatchAction,
    toggleSelectedVideo,
    selectVideo,
  } = actions;

  return (
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
  );
}
