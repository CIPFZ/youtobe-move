import { Button, Input, InputNumber, Segmented, Select, Space, Tag } from "antd";
import { Check, RotateCcw, Send, SkipForward, X } from "lucide-react";
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
    applyQueuePreset,
    addQueueUrls,
    runBatchAction,
    toggleSelectedVideo,
    selectVideo,
  } = actions;
  const activeFilters = [
    filters.status ? `状态 ${filters.status}` : "",
    filters.draftStatus ? `草稿 ${filters.draftStatus}` : "",
    filters.errorType ? `错误 ${filters.errorType}` : "",
  ].filter(Boolean);
  const presetButtons = [
    { value: "all", label: "全部" },
    { value: "failed", label: "失败" },
    { value: "ready", label: "待发布" },
    { value: "pendingDraft", label: "待审核" },
    { value: "approvedDraft", label: "已通过" },
    { value: "published", label: "已发布" },
  ];

  return (
    <section className="panel" id="queue">
      <div className="panel-head">
        <h2>队列</h2>
        <Space wrap>
          <Select
            value={filters.status}
            style={{ width: 132 }}
            onChange={(value) => updateFilters((prev) => ({ ...prev, status: value }))}
            options={[{ value: "", label: "全部状态" }, ...statusOptions.map((item) => ({ value: item, label: item }))]}
          />
          <Select
            value={filters.draftStatus}
            style={{ width: 132 }}
            onChange={(value) => updateFilters((prev) => ({ ...prev, draftStatus: value }))}
            options={[{ value: "", label: "草稿全部" }, ...draftOptions.map((item) => ({ value: item, label: item }))]}
          />
          <Select
            value={filters.errorType}
            style={{ width: 132 }}
            onChange={(value) => updateFilters((prev) => ({ ...prev, errorType: value }))}
            options={[{ value: "", label: "错误全部" }, ...errorOptions.map((item) => ({ value: item, label: item }))]}
          />
        </Space>
      </div>
      <div className="queue-filter-bar">
        <Segmented options={presetButtons} onChange={(value) => applyQueuePreset(value)} />
        <div className="filter-summary">
          {activeFilters.length ? activeFilters.map((item) => <Tag key={item}>{item}</Tag>) : <span className="muted">当前显示全部队列。</span>}
          {activeFilters.length ? <Button size="small" onClick={() => applyQueuePreset("all")}>清除筛选</Button> : null}
        </div>
      </div>
      <div className="add-url-box">
        <Input.TextArea value={addUrls} onChange={(event) => setAddUrls(event.target.value)} placeholder="输入 YouTube 链接，支持一行一个" autoSize={{ minRows: 3, maxRows: 6 }} />
        <div className="queue-meta-row">
          <label>
            <span>优先级</span>
            <InputNumber value={Number(addPriority || 100)} min={0} max={10000} onChange={(value) => setAddPriority(String(value ?? 100))} />
          </label>
          <label>
            <span>来源标签</span>
            <Input value={addSourceLabel} onChange={(event) => setAddSourceLabel(event.target.value)} />
          </label>
        </div>
        <Space wrap>
          <IconButton icon={Send} className="primary" onClick={addQueueUrls}>添加到队列</IconButton>
          <span className="muted">重复 video_id 不会重复入库。</span>
        </Space>
      </div>
      <div className="bulk-toolbar">
        <Space wrap>
          <Button onClick={() => setSelectedVideoIds(videos.map((item) => item.video.video_id))}>全选</Button>
          <Button onClick={() => setSelectedVideoIds([])}>清空</Button>
          <IconButton icon={Check} disabled={!selectedVideoIds.length} onClick={() => runBatchAction("approve")}>批量通过</IconButton>
          <IconButton icon={X} disabled={!selectedVideoIds.length} onClick={() => runBatchAction("reject")}>批量拒绝</IconButton>
          <IconButton icon={RotateCcw} disabled={!selectedVideoIds.length} onClick={() => runBatchAction("retry")}>批量重试</IconButton>
          <IconButton icon={SkipForward} className="danger" disabled={!selectedVideoIds.length} onClick={() => runBatchAction("skip")}>批量跳过</IconButton>
        </Space>
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
