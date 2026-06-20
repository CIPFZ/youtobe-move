import { useState } from "react";
import { Save, Search } from "lucide-react";
import { fmtCount, fmtDuration } from "../format";
import { IconButton } from "./IconButton";

function emptyDiscoveryForm() {
  return {
    type: "search",
    name: "",
    keyword: "",
    region_code: "US",
    video_category_id: "",
    channel_id: "",
    handle: "",
    order: "relevance",
    max_results: "2",
    enabled: "true",
    priority: "100",
    min_duration_seconds: "",
    max_duration_seconds: "",
    min_view_count: "",
    title_blocklist: "",
    category_allowlist: "",
    category_blocklist: "",
  };
}

function sourceToForm(source) {
  return {
    ...emptyDiscoveryForm(),
    ...Object.fromEntries(Object.entries(source || {}).map(([key, value]) => [key, String(value ?? "")])),
    type: source?.type || "search",
    max_results: String(source?.max_results || 2),
  };
}

function formToSource(form) {
  const source = {
    type: form.type,
    name: form.name.trim(),
    max_results: Number.parseInt(form.max_results || "2", 10),
    enabled: form.enabled === "true",
    priority: Number.parseInt(form.priority || "100", 10),
  };
  for (const key of ["min_duration_seconds", "max_duration_seconds", "min_view_count"]) {
    if (String(form[key] || "").trim()) source[key] = Number.parseInt(form[key], 10);
  }
  for (const key of ["title_blocklist", "category_allowlist", "category_blocklist"]) {
    if (String(form[key] || "").trim()) source[key] = String(form[key]).trim();
  }
  if (form.type === "search") {
    source.keyword = form.keyword.trim();
    if (form.order.trim()) source.order = form.order.trim();
    if (form.channel_id.trim()) source.channel_id = form.channel_id.trim();
    if (form.region_code.trim()) source.region_code = form.region_code.trim();
    if (form.video_category_id.trim()) source.video_category_id = form.video_category_id.trim();
  } else if (form.type === "trending") {
    source.region_code = form.region_code.trim() || "US";
    if (form.video_category_id.trim()) source.video_category_id = form.video_category_id.trim();
  } else if (form.type === "channel_uploads") {
    if (form.channel_id.trim()) source.channel_id = form.channel_id.trim();
    if (form.handle.trim()) source.handle = form.handle.trim();
  }
  return source;
}

export function DiscoverySourcesPanel({ sources, preview, onSave, onDelete, onPreview }) {
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [form, setForm] = useState(emptyDiscoveryForm);

  function editSource(source) {
    setSelectedIndex(source.index);
    setForm(sourceToForm(source));
  }

  function resetForm() {
    setSelectedIndex(null);
    setForm(emptyDiscoveryForm());
  }

  function updateField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function submit() {
    await onSave(formToSource(form), selectedIndex);
    resetForm();
  }

  return (
    <div className="panel-body discovery-layout">
      <div>
        {(sources || []).length ? sources.map((source) => (
          <button className={`source-row${selectedIndex === source.index ? " active" : ""}`} key={source.index} onClick={() => editSource(source)}>
            <div>
              <b>{source.name || `${source.type}:${source.index}`}</b>
              <div className="muted">
                {source.type} · {source.enabled === false ? "disabled" : "enabled"} · priority {source.priority ?? 100} · max {source.max_results} · {source.keyword || source.region_code || source.handle || source.channel_id || "-"}
              </div>
            </div>
            <span className={`badge${source.enabled === false ? " failed" : ""}`}>{source.index}</span>
          </button>
        )) : <div className="muted">暂无发现源。</div>}
      </div>
      <div className="source-form">
        <div className="draft-row">
          <label>
            <span>类型</span>
            <select value={form.type} onChange={(event) => updateField("type", event.target.value)}>
              <option value="search">search</option>
              <option value="trending">trending</option>
              <option value="channel_uploads">channel_uploads</option>
            </select>
          </label>
          <label>
            <span>数量</span>
            <input value={form.max_results} onChange={(event) => updateField("max_results", event.target.value)} />
          </label>
        </div>
        <div className="draft-row">
          <label>
            <span>启用</span>
            <select value={form.enabled} onChange={(event) => updateField("enabled", event.target.value)}>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </label>
          <label>
            <span>优先级</span>
            <input value={form.priority} onChange={(event) => updateField("priority", event.target.value)} />
          </label>
        </div>
        <label>
          <span>名称</span>
          <input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
        </label>
        <div className="filter-box">
          <h2>过滤覆盖</h2>
          <div className="draft-row">
            <label><span>最小时长秒</span><input value={form.min_duration_seconds} onChange={(event) => updateField("min_duration_seconds", event.target.value)} /></label>
            <label><span>最大时长秒</span><input value={form.max_duration_seconds} onChange={(event) => updateField("max_duration_seconds", event.target.value)} /></label>
          </div>
          <label><span>最低播放量</span><input value={form.min_view_count} onChange={(event) => updateField("min_view_count", event.target.value)} /></label>
          <label><span>标题黑名单</span><input value={form.title_blocklist} onChange={(event) => updateField("title_blocklist", event.target.value)} /></label>
          <div className="draft-row">
            <label><span>分类白名单</span><input value={form.category_allowlist} onChange={(event) => updateField("category_allowlist", event.target.value)} /></label>
            <label><span>分类黑名单</span><input value={form.category_blocklist} onChange={(event) => updateField("category_blocklist", event.target.value)} /></label>
          </div>
        </div>
        {form.type === "search" ? (
          <>
            <label><span>关键词</span><input value={form.keyword} onChange={(event) => updateField("keyword", event.target.value)} /></label>
            <div className="draft-row">
              <label><span>排序</span><input value={form.order} onChange={(event) => updateField("order", event.target.value)} /></label>
              <label><span>地区</span><input value={form.region_code} onChange={(event) => updateField("region_code", event.target.value)} /></label>
            </div>
            <div className="draft-row">
              <label><span>频道 ID</span><input value={form.channel_id} onChange={(event) => updateField("channel_id", event.target.value)} /></label>
              <label><span>分类 ID</span><input value={form.video_category_id} onChange={(event) => updateField("video_category_id", event.target.value)} /></label>
            </div>
          </>
        ) : null}
        {form.type === "trending" ? (
          <div className="draft-row">
            <label><span>地区</span><input value={form.region_code} onChange={(event) => updateField("region_code", event.target.value)} /></label>
            <label><span>分类 ID</span><input value={form.video_category_id} onChange={(event) => updateField("video_category_id", event.target.value)} /></label>
          </div>
        ) : null}
        {form.type === "channel_uploads" ? (
          <div className="draft-row">
            <label><span>频道 ID</span><input value={form.channel_id} onChange={(event) => updateField("channel_id", event.target.value)} /></label>
            <label><span>Handle</span><input value={form.handle} onChange={(event) => updateField("handle", event.target.value)} /></label>
          </div>
        ) : null}
        <div className="toolbar">
          <IconButton icon={Save} className="primary" onClick={submit}>{selectedIndex === null ? "新增" : "保存"}</IconButton>
          <IconButton icon={Search} disabled={selectedIndex === null} onClick={() => onPreview(selectedIndex)}>预览</IconButton>
          <button onClick={resetForm}>清空</button>
          <button className="danger" disabled={selectedIndex === null} onClick={() => onDelete(selectedIndex)}>删除</button>
        </div>
        <DiscoveryPreview preview={preview} />
      </div>
    </div>
  );
}

function DiscoveryPreview({ preview }) {
  if (!preview) return <div className="muted">选择发现源后可执行预览。</div>;
  const accepted = preview.accepted || [];
  const rejected = preview.rejected || [];
  return (
    <section className="preview-box">
      <h2>预览结果</h2>
      <div className="badges">
        <span className="badge">候选 {preview.candidate_count}</span>
        <span className="badge ready_to_publish">通过 {preview.accepted_count}</span>
        <span className="badge failed">拒绝 {preview.rejected_count}</span>
      </div>
      <div className="preview-list">
        {accepted.slice(0, 8).map((item) => (
          <div className="preview-row" key={`accepted-${item.video_id}`}>
            <b>{item.title || item.video_id}</b>
            <span>{item.channel || "-"} · {fmtDuration(item.duration)} · {fmtCount(item.view_count)} views</span>
          </div>
        ))}
        {rejected.slice(0, 8).map((item) => (
          <div className="preview-row rejected" key={`rejected-${item.candidate?.video_id}`}>
            <b>{item.candidate?.title || item.candidate?.video_id}</b>
            <span>{item.reason}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
