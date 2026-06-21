import { useState } from "react";
import { Button, Drawer, Dropdown, Form, Input, InputNumber, Segmented, Space, Tag } from "antd";
import { Check, Plus, RefreshCw, RotateCcw, Send, SkipForward, X } from "lucide-react";
import { IconButton } from "../components/IconButton";
import { VideoList } from "../components/VideoList";

export function QueueSection({ state, actions }) {
  const [addDrawerOpen, setAddDrawerOpen] = useState(false);
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
    loadVideosPage,
    updateFilters,
    applyQueuePreset,
    addQueueUrls,
    runBatchAction,
    runVideoAction,
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
  const presetValue = getPresetValue(filters);
  const batchMenuItems = [
    { key: "approve", label: "批量通过", icon: <Check size={14} /> },
    { key: "reject", label: "批量拒绝", icon: <X size={14} /> },
    { key: "retry", label: "批量重试", icon: <RotateCcw size={14} /> },
    { key: "skip", label: "批量跳过", danger: true, icon: <SkipForward size={14} /> },
  ];

  async function submitAddQueueUrls() {
    await addQueueUrls();
    setAddDrawerOpen(false);
  }

  return (
    <section className="panel" id="queue">
      <div className="panel-head">
        <h2>队列</h2>
        <Space wrap>
          <IconButton icon={Plus} className="primary" onClick={() => setAddDrawerOpen(true)}>添加任务</IconButton>
          <IconButton icon={RefreshCw} onClick={() => loadVideosPage(selectedId)}>刷新</IconButton>
        </Space>
      </div>
      <div className="queue-table-toolbar">
        <Space wrap>
          <Segmented value={presetValue} options={presetButtons} onChange={(value) => applyQueuePreset(value)} />
          <div className="filter-summary">
            {activeFilters.length ? activeFilters.map((item) => <Tag key={item}>{item}</Tag>) : <span className="muted">当前显示全部队列。</span>}
            {activeFilters.length ? <Button size="small" onClick={() => applyQueuePreset("all")}>清除筛选</Button> : null}
          </div>
        </Space>
        <Space wrap>
          <span className="muted">已选择 {selectedVideoIds.length} 项</span>
          <Button onClick={() => setSelectedVideoIds(videos.map((item) => item.video.video_id))}>全选</Button>
          <Button disabled={!selectedVideoIds.length} onClick={() => setSelectedVideoIds([])}>清空</Button>
          <Dropdown
            menu={{
              items: batchMenuItems,
              onClick: ({ key }) => runBatchAction(key),
            }}
            disabled={!selectedVideoIds.length}
          >
            <Button type="primary" disabled={!selectedVideoIds.length}>批量操作</Button>
          </Dropdown>
        </Space>
      </div>
      <Drawer
        title="添加任务"
        width={440}
        open={addDrawerOpen}
        onClose={() => setAddDrawerOpen(false)}
        destroyOnClose={false}
        extra={<Button type="primary" icon={<Send size={16} />} onClick={submitAddQueueUrls}>添加到队列</Button>}
      >
        <Form layout="vertical" className="queue-add-form">
          <Form.Item label="YouTube 链接" extra="支持一行一个。重复 video_id 不会重复入库。">
            <Input.TextArea value={addUrls} onChange={(event) => setAddUrls(event.target.value)} placeholder="输入 YouTube 链接" autoSize={{ minRows: 7, maxRows: 12 }} />
          </Form.Item>
          <Form.Item label="优先级">
            <InputNumber value={Number(addPriority || 100)} min={0} max={10000} onChange={(value) => setAddPriority(String(value ?? 100))} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="来源标签">
            <Input value={addSourceLabel} onChange={(event) => setAddSourceLabel(event.target.value)} />
          </Form.Item>
        </Form>
      </Drawer>
      <VideoList
        videos={videos}
        selectedId={selectedId}
        selectedVideoIds={selectedVideoIds}
        filters={filters}
        onFilterChange={(nextFilters) => updateFilters((prev) => ({ ...prev, ...nextFilters }))}
        onToggleSelected={toggleSelectedVideo}
        onSelect={selectVideo}
        onAction={runVideoAction}
      />
    </section>
  );
}

function getPresetValue(filters) {
  if (!filters.status && !filters.draftStatus && !filters.errorType) return "all";
  if (filters.status === "failed" && !filters.draftStatus && !filters.errorType) return "failed";
  if (filters.status === "ready_to_publish" && !filters.draftStatus && !filters.errorType) return "ready";
  if (filters.status === "ready_to_publish" && filters.draftStatus === "pending" && !filters.errorType) return "pendingDraft";
  if (filters.status === "ready_to_publish" && filters.draftStatus === "approved" && !filters.errorType) return "approvedDraft";
  if (filters.status === "published" && !filters.draftStatus && !filters.errorType) return "published";
  return "";
}
