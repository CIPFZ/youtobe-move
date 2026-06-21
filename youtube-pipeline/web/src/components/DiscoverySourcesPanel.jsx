import { useEffect, useState } from "react";
import { Button, Card, Descriptions, Form, Input, InputNumber, Select, Space, Table, Tabs, Tag } from "antd";
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
    score_weight: "1",
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
    score_weight: Number.parseFloat(form.score_weight || "1"),
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

function TextField({ label, value, onChange }) {
  return (
    <Form.Item label={label}>
      <Input value={value} onChange={(event) => onChange(event.target.value)} allowClear />
    </Form.Item>
  );
}

function NumberTextField({ label, value, onChange }) {
  return (
    <Form.Item label={label}>
      <InputNumber className="full-input" value={value === "" ? null : Number(value)} min={0} onChange={(next) => onChange(next === null ? "" : String(next))} />
    </Form.Item>
  );
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

  const columns = [
    {
      title: "发现源",
      render: (_, source) => (
        <Space direction="vertical" size={2}>
          <Button type="link" className="table-title-link" onClick={() => editSource(source)}>{source.name || `${source.type}:${source.index}`}</Button>
          <span className="muted">{source.keyword || source.region_code || source.handle || source.channel_id || "-"}</span>
        </Space>
      ),
    },
    { title: "类型", dataIndex: "type", width: 130, render: (value) => <Tag>{value}</Tag> },
    { title: "状态", width: 92, render: (_, source) => <Tag color={source.enabled === false ? "error" : "success"}>{source.enabled === false ? "off" : "on"}</Tag> },
    { title: "优先级", width: 92, render: (_, source) => <Tag>P{source.priority ?? 100}</Tag> },
    { title: "权重", width: 86, render: (_, source) => source.score_weight ?? 1 },
    { title: "数量", width: 86, dataIndex: "max_results" },
  ];

  return (
    <div className="panel-body discovery-layout">
      <Card
        title="发现源列表"
        className="discovery-source-card"
        extra={<Tag>{sources?.length || 0} sources</Tag>}
      >
        <Table
          className="ops-table"
          columns={columns}
          dataSource={sources || []}
          rowKey="index"
          pagination={false}
          size="middle"
          rowClassName={(source) => source.index === selectedIndex ? "active-row" : ""}
          onRow={(source) => ({ onClick: () => editSource(source) })}
          scroll={{ x: 760 }}
        />
      </Card>
      <Card className="discovery-editor-card" title={selectedIndex === null ? "新增发现源" : `编辑发现源 #${selectedIndex}`}>
        <Tabs
          items={[
            {
              key: "form",
              label: "配置",
              children: (
                <DiscoverySourceForm
                  form={form}
                  selectedIndex={selectedIndex}
                  updateField={updateField}
                  submit={submit}
                  resetForm={resetForm}
                  onDelete={onDelete}
                  onPreview={onPreview}
                />
              ),
            },
            {
              key: "preview",
              label: "预览",
              children: <DiscoveryPreview preview={preview} />,
            },
          ]}
        />
      </Card>
    </div>
  );
}

function DiscoverySourceForm({ form, selectedIndex, updateField, submit, resetForm, onDelete, onPreview }) {
  return (
    <Form layout="vertical" className="source-form">
        <Descriptions bordered size="small" column={2} className="source-form-summary">
        <Descriptions.Item label="类型">{form.type}</Descriptions.Item>
        <Descriptions.Item label="状态">{form.enabled === "true" ? "enabled" : "disabled"}</Descriptions.Item>
      </Descriptions>
      <div className="draft-row">
        <Form.Item label="类型">
          <Select value={form.type} onChange={(value) => updateField("type", value)} options={["search", "trending", "channel_uploads"].map((item) => ({ value: item, label: item }))} />
        </Form.Item>
        <Form.Item label="数量">
          <InputNumber className="full-input" value={Number(form.max_results || 2)} min={1} max={50} onChange={(value) => updateField("max_results", String(value ?? 2))} />
        </Form.Item>
      </div>
      <div className="draft-row">
        <Form.Item label="启用">
          <Select value={form.enabled} onChange={(value) => updateField("enabled", value)} options={[{ value: "true", label: "true" }, { value: "false", label: "false" }]} />
        </Form.Item>
        <Form.Item label="优先级">
          <InputNumber className="full-input" value={Number(form.priority || 100)} min={0} max={10000} onChange={(value) => updateField("priority", String(value ?? 100))} />
        </Form.Item>
      </div>
      <Form.Item label="分数权重"><InputNumber className="full-input" value={Number(form.score_weight || 1)} min={0} step={0.1} onChange={(value) => updateField("score_weight", String(value ?? 1))} /></Form.Item>
      <TextField label="名称" value={form.name} onChange={(value) => updateField("name", value)} />
      {form.type === "search" ? (
        <>
          <TextField label="关键词" value={form.keyword} onChange={(value) => updateField("keyword", value)} />
          <div className="draft-row">
            <TextField label="排序" value={form.order} onChange={(value) => updateField("order", value)} />
            <TextField label="地区" value={form.region_code} onChange={(value) => updateField("region_code", value)} />
          </div>
          <div className="draft-row">
            <TextField label="频道 ID" value={form.channel_id} onChange={(value) => updateField("channel_id", value)} />
            <TextField label="分类 ID" value={form.video_category_id} onChange={(value) => updateField("video_category_id", value)} />
          </div>
        </>
      ) : null}
      {form.type === "trending" ? (
        <div className="draft-row">
          <TextField label="地区" value={form.region_code} onChange={(value) => updateField("region_code", value)} />
          <TextField label="分类 ID" value={form.video_category_id} onChange={(value) => updateField("video_category_id", value)} />
        </div>
      ) : null}
      {form.type === "channel_uploads" ? (
        <div className="draft-row">
          <TextField label="频道 ID" value={form.channel_id} onChange={(value) => updateField("channel_id", value)} />
          <TextField label="Handle" value={form.handle} onChange={(value) => updateField("handle", value)} />
        </div>
      ) : null}
      <Card size="small" title="过滤覆盖">
        <div className="draft-row">
          <NumberTextField label="最小时长秒" value={form.min_duration_seconds} onChange={(value) => updateField("min_duration_seconds", value)} />
          <NumberTextField label="最大时长秒" value={form.max_duration_seconds} onChange={(value) => updateField("max_duration_seconds", value)} />
        </div>
        <NumberTextField label="最低播放量" value={form.min_view_count} onChange={(value) => updateField("min_view_count", value)} />
        <TextField label="标题黑名单" value={form.title_blocklist} onChange={(value) => updateField("title_blocklist", value)} />
        <div className="draft-row">
          <TextField label="分类白名单" value={form.category_allowlist} onChange={(value) => updateField("category_allowlist", value)} />
          <TextField label="分类黑名单" value={form.category_blocklist} onChange={(value) => updateField("category_blocklist", value)} />
        </div>
      </Card>
      <Space wrap>
        <IconButton icon={Save} className="primary" onClick={submit}>{selectedIndex === null ? "新增" : "保存"}</IconButton>
        <IconButton icon={Search} disabled={selectedIndex === null} onClick={() => onPreview(selectedIndex)}>预览</IconButton>
        <Button onClick={resetForm}>清空</Button>
        <Button danger disabled={selectedIndex === null} onClick={() => onDelete(selectedIndex)}>删除</Button>
      </Space>
    </Form>
  );
}

function DiscoveryPreview({ preview }) {
  const [acceptedPage, setAcceptedPage] = useState(0);
  const [rejectedPage, setRejectedPage] = useState(0);
  const pageSize = 8;
  useEffect(() => {
    setAcceptedPage(0);
    setRejectedPage(0);
  }, [preview]);
  if (!preview) return <div className="muted">选择发现源后可执行预览。</div>;
  const accepted = preview.accepted || [];
  const rejected = preview.rejected || [];
  const acceptedItems = pageItems(accepted, acceptedPage, pageSize);
  const rejectedItems = pageItems(rejected, rejectedPage, pageSize);
  return (
    <section className="preview-box">
      <h2>预览结果</h2>
      <div className="badges">
        <span className="badge">候选 {preview.candidate_count}</span>
        <span className="badge ready_to_publish">通过 {preview.accepted_count}</span>
        <span className="badge failed">拒绝 {preview.rejected_count}</span>
      </div>
      <div className="preview-columns">
        <div>
          <PreviewColumnHead title="通过" page={acceptedPage} pageSize={pageSize} total={accepted.length} onPage={setAcceptedPage} />
          <div className="preview-list">
            {acceptedItems.length ? acceptedItems.map((item) => (
              <PreviewCandidate item={item} key={`accepted-${item.video_id}`} />
            )) : <div className="muted">暂无通过候选。</div>}
          </div>
        </div>
        <div>
          <PreviewColumnHead title="拒绝" page={rejectedPage} pageSize={pageSize} total={rejected.length} onPage={setRejectedPage} />
          <div className="preview-list">
            {rejectedItems.length ? rejectedItems.map((item) => (
              <PreviewCandidate item={item.candidate || {}} reason={item.reason} rejected key={`rejected-${item.candidate?.video_id || item.reason}`} />
            )) : <div className="muted">暂无拒绝候选。</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function PreviewColumnHead({ title, page, pageSize, total, onPage }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="preview-column-head">
      <h3>{title}</h3>
      <div>
        <Button size="small" disabled={page <= 0} onClick={() => onPage(Math.max(0, page - 1))}>上一页</Button>
        <span>{Math.min(page + 1, pageCount)}/{pageCount}</span>
        <Button size="small" disabled={page + 1 >= pageCount} onClick={() => onPage(page + 1)}>下一页</Button>
      </div>
    </div>
  );
}

function pageItems(items, page, pageSize) {
  const start = page * pageSize;
  return items.slice(start, start + pageSize);
}

function PreviewCandidate({ item, reason = "", rejected = false }) {
  const detail = item.score_detail || {};
  const sourceName = item.source_name || detail.source_name || "";
  const sourceQuery = item.source_query || detail.source_query || "";
  const sourceWeight = detail.source_weight ?? item.source_params?.score_weight;
  const sourcePriority = detail.source_priority ?? item.source_params?.priority;
  return (
    <div className={`preview-row${rejected ? " rejected" : ""}`}>
      <b>{item.title || item.video_id || "-"}</b>
      <span>{item.channel || "-"} · {fmtDuration(item.duration)} · {fmtCount(item.view_count)} views</span>
      <div className="preview-meta">
        {item.score !== undefined ? <span className="badge">score {Number(item.score).toFixed(1)}</span> : null}
        {sourceWeight !== undefined ? <span className="badge">weight {sourceWeight}</span> : null}
        {sourcePriority !== undefined ? <span className="badge">P{sourcePriority}</span> : null}
        {item.source_type ? <span className="badge">{item.source_type}</span> : null}
        {item.category ? <span className="badge">{item.category}</span> : null}
        {item.published_at ? <span className="badge">{item.published_at}</span> : null}
      </div>
      <div className="preview-detail-grid">
        <span>video</span><span>{item.video_id || "-"}</span>
        <span>source</span><span>{sourceName || "-"}</span>
        <span>query</span><span>{sourceQuery || "-"}</span>
        <span>channel</span><span>{item.channel_id || "-"}</span>
      </div>
      {item.source_url ? <a className="preview-link" href={item.source_url} target="_blank" rel="noreferrer">打开原视频</a> : null}
      {reason ? <div className="preview-reason">{reason}</div> : null}
    </div>
  );
}
