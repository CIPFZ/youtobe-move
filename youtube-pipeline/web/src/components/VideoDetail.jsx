import { useEffect, useState } from "react";
import { Alert, Card, Descriptions, Form, Input, List, Progress, Select, Space, Table, Tag, Typography } from "antd";
import { Check, Download, Eye, FileText, HardDrive, RotateCcw, Save, Send, SkipForward, X } from "lucide-react";
import { api } from "../api";
import { draftOptions } from "../constants";
import { fmtCount, fmtDuration, parseTagText, parseTags, parseTidOptions, tagsToText } from "../format";
import { IconButton } from "./IconButton";

const { Text } = Typography;

const fallbackDraftRules = {
  title_max_length: 80,
  description_max_length: 2000,
  tag_max_count: 8,
  tag_max_length: 20,
};

export function VideoDetail({ data, configByKey, draftRules, onAction, onSaved, showToast }) {
  const video = data.video;
  const draft = data.publish_draft || {};
  const rules = { ...fallbackDraftRules, ...(draftRules || {}) };
  const draftVersions = data.publish_draft_versions || [];
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
  const canCleanupMedia = Boolean(data.media_files?.merged_path || data.media_files?.video_path || data.media_files?.audio_path || data.media_files?.poster_path);
  const tidOptions = parseTidOptions(configByKey?.BILIBILI_TID_OPTIONS?.value);
  const jobLeaseSeconds = Number(configByKey?.JOB_LEASE_SECONDS?.value || 0);
  const [draftForm, setDraftForm] = useState(() => makeDraftForm(draft));
  const [savingDraft, setSavingDraft] = useState(false);
  const draftErrors = validateDraftForm(draftForm, rules);
  const parsedDraftTags = parseTagText(draftForm.tags);

  useEffect(() => {
    setDraftForm(makeDraftForm(draft));
  }, [video.video_id, draft.updated_at]);

  function updateDraftField(field, value) {
    setDraftForm((prev) => ({ ...prev, [field]: value }));
  }

  async function saveDraft() {
    if (!draft.title) return;
    if (draftErrors.length) {
      showToast(draftErrors[0]);
      return;
    }
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
        <Card title={video.title || video.video_id} className="detail-card">
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="状态"><StatusTag status={video.status} /></Descriptions.Item>
            <Descriptions.Item label="频道">{video.channel || "-"}</Descriptions.Item>
            <Descriptions.Item label="时长">{fmtDuration(video.duration)}</Descriptions.Item>
            <Descriptions.Item label="播放">{fmtCount(video.view_count)}</Descriptions.Item>
            <Descriptions.Item label="分类">{video.category || "-"}</Descriptions.Item>
            <Descriptions.Item label="优先级">{video.priority ?? 100}</Descriptions.Item>
            <Descriptions.Item label="来源标签">{video.source_label || "-"}</Descriptions.Item>
            <Descriptions.Item label="原链接">
              <a href={video.source_url} target="_blank" rel="noreferrer">{video.source_url}</a>
            </Descriptions.Item>
          </Descriptions>
          {video.last_error ? <Alert className="detail-alert" type="error" message={video.last_error} /> : null}
          <Space className="actions" wrap>
            <IconButton icon={Download} disabled={!canDownload} onClick={() => onAction(video.video_id, "download")}>下载</IconButton>
            <IconButton icon={FileText} disabled={!canDescribe} onClick={() => onAction(video.video_id, "describe")}>生成文案</IconButton>
            <IconButton icon={Check} disabled={!canReview || draft.status === "approved"} onClick={() => onAction(video.video_id, "approve")}>通过</IconButton>
            <IconButton icon={X} disabled={!canReview || draft.status === "rejected"} onClick={() => onAction(video.video_id, "reject")}>拒绝</IconButton>
            <IconButton icon={Eye} disabled={!canPublish} onClick={() => onAction(video.video_id, "publish-dry-run")}>发布预览</IconButton>
            <IconButton icon={Send} className="primary" disabled={!canPublish} onClick={() => onAction(video.video_id, "publish")}>真实发布</IconButton>
            <IconButton icon={RotateCcw} disabled={!canRetry} onClick={() => onAction(video.video_id, "retry")}>重试</IconButton>
            <IconButton icon={SkipForward} className="danger" disabled={!canSkip} onClick={() => onAction(video.video_id, "skip")}>跳过</IconButton>
            <IconButton icon={HardDrive} className="danger" disabled={!canCleanupMedia} onClick={() => onAction(video.video_id, "cleanup-media")}>清理媒体</IconButton>
          </Space>
        </Card>

        <Card title="发布草稿" className="detail-card">
          {draft.title ? (
            <>
              <DraftSummary draft={draft} />
              <Form layout="vertical" className="draft-form">
                <Form.Item label={`标题 ${draftForm.title.length}/${rules.title_max_length}`} validateStatus={fieldHasError(draftErrors, "标题") ? "error" : ""}>
                  <Input value={draftForm.title} onChange={(event) => updateDraftField("title", event.target.value)} maxLength={rules.title_max_length} />
                </Form.Item>
                <Form.Item label={`描述 ${draftForm.description.length}/${rules.description_max_length}`} validateStatus={fieldHasError(draftErrors, "描述") ? "error" : ""}>
                  <Input.TextArea value={draftForm.description} onChange={(event) => updateDraftField("description", event.target.value)} rows={7} />
                </Form.Item>
                <Form.Item
                  label={`标签 ${parsedDraftTags.length}/${rules.tag_max_count}`}
                  extra={`最多 ${rules.tag_max_count} 个，每个不超过 ${rules.tag_max_length} 个字符。当前最长 ${longestTagLength(parsedDraftTags)} 个字符。`}
                  validateStatus={fieldHasError(draftErrors, "标签") ? "error" : ""}
                >
                  <Input value={draftForm.tags} onChange={(event) => updateDraftField("tags", event.target.value)} placeholder="使用逗号分隔" />
                </Form.Item>
                <div className="draft-row">
                  <Form.Item label="分区" validateStatus={fieldHasError(draftErrors, "分区") ? "error" : ""}>
                    <Select
                      value={draftForm.tid}
                      onChange={(value) => updateDraftField("tid", value)}
                      options={[
                        { value: "", label: "请选择" },
                        ...tidOptions.map((item) => ({ value: item.tid, label: `${item.tid} ${item.label}` })),
                        ...(!tidOptions.some((item) => item.tid === String(draft.tid || "")) && draft.tid ? [{ value: String(draft.tid), label: `${draft.tid} ${draft.tid_label || ""}` }] : []),
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label="审核">
                    <Select value={draftForm.status} onChange={(value) => updateDraftField("status", value)} options={draftOptions.map((item) => ({ value: item, label: item }))} />
                  </Form.Item>
                </div>
                {draftErrors.length ? <Alert type="error" message={draftErrors[0]} /> : null}
                <Space wrap>
                  <IconButton icon={Save} className="primary" onClick={saveDraft} disabled={savingDraft || Boolean(draftErrors.length)}>保存草稿</IconButton>
                  <Text type="secondary">保存后分区来源会标记为 manual。</Text>
                </Space>
              </Form>
              <DraftTags draft={draft} />
              <DraftHistory versions={draftVersions} />
            </>
          ) : <Text type="secondary">暂无草稿。</Text>}
        </Card>

        <Card title="任务状态" className="detail-card">
          <JobTimeline jobs={jobs} leaseSeconds={jobLeaseSeconds} />
        </Card>

        <Card title="发布记录" className="detail-card">
          <PublishRecords records={records} />
        </Card>

        <Card title="最近事件" className="detail-card">
          <RecentEvents events={events} />
        </Card>
      </div>
      <div>
        <MediaPreview videoId={video.video_id} mediaFiles={data.media_files || {}} />
      </div>
    </div>
  );
}

function MediaPreview({ videoId, mediaFiles }) {
  const base = `/api/videos/${encodeURIComponent(videoId)}/file`;
  const hasMerged = Boolean(mediaFiles.merged_path);
  const hasPoster = Boolean(mediaFiles.poster_path);
  const rows = [
    ["merged", "合并视频", mediaFiles.merged_path],
    ["video", "视频流", mediaFiles.video_path],
    ["audio", "音频流", mediaFiles.audio_path],
    ["poster", "海报", mediaFiles.poster_path],
    ["meta", "Meta", mediaFiles.meta_path],
  ];
  return (
    <Card className="media-panel" title="媒体文件">
      {hasMerged ? (
        <video className="media-video" src={`${base}?type=merged`} controls preload="metadata" poster={hasPoster ? `${base}?type=poster` : undefined} />
      ) : hasPoster ? (
        <img className="poster" src={`${base}?type=poster`} alt="" />
      ) : (
        <div className="poster placeholder">暂无媒体预览</div>
      )}
      <List
        className="media-files"
        dataSource={rows}
        renderItem={([type, label, path]) => (
          <List.Item
            actions={path ? [<a href={`${base}?type=${type}`} target="_blank" rel="noreferrer" key="open">打开</a>] : [<Tag key="missing">missing</Tag>]}
          >
            <List.Item.Meta title={label} description={path || "未生成"} />
          </List.Item>
        )}
      />
    </Card>
  );
}

function DraftSummary({ draft }) {
  const source = draft.tid_source || "-";
  const tone = sourceTone(source);
  const isFallback = source === "fallback";
  return (
    <div className="draft-summary">
      <Card size="small" title="审核状态"><StatusTag status={draft.status || "-"} />{draft.review_note ? <Text type="secondary">{draft.review_note}</Text> : null}</Card>
      <Card size="small" title="发布分区"><b>{draft.tid || "-"} {draft.tid_label || ""}</b><Text type="secondary">{draft.tid_reason || "暂无分区判断原因"}</Text></Card>
      <Card size="small" title="分区来源" className={`draft-source-card ${tone}`}><Tag color={sourceColor(source)}>{sourceLabel(source)}</Tag><Text type="secondary">{isFallback ? "fallback 分区需要人工确认后才能真实发布" : "保存草稿后会转为 manual"}</Text></Card>
      {isFallback ? (
        <Alert className="draft-warning" type="warning" message="当前分区来自兜底策略，真实发布已阻断。请人工选择正确分区并保存草稿。" />
      ) : null}
    </div>
  );
}

function DraftTags({ draft }) {
  const tags = parseTags(draft.tags_json);
  if (!tags.length) return null;
  return (
    <div className="draft-tags">
      <Text type="secondary">当前标签</Text>
      <div className="detail-tags">
        {tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
      </div>
    </div>
  );
}

function DraftHistory({ versions }) {
  if (!versions.length) return <Text type="secondary">暂无草稿历史。</Text>;
  const columns = [
    { title: "动作", dataIndex: "action", render: (value) => draftActionLabel(value), width: 92 },
    { title: "状态", dataIndex: "status", render: (value) => <StatusTag status={value || "-"} />, width: 110 },
    { title: "标题", dataIndex: "title", render: (value) => value || "-", ellipsis: true },
    { title: "分区", render: (_, row) => `${row.tid || "-"} ${row.tid_label || ""}`, width: 130 },
    { title: "来源", dataIndex: "tid_source", render: (value) => sourceLabel(value || ""), width: 110 },
    { title: "时间", dataIndex: "created_at", width: 160 },
  ];
  return (
    <div className="draft-history">
      <div className="section-headline">
        <h3>草稿历史</h3>
        <span>最近 {versions.length} 条</span>
      </div>
      <Table
        className="detail-table"
        columns={columns}
        dataSource={versions}
        rowKey="id"
        pagination={false}
        size="small"
        expandable={{
          expandedRowRender: (version) => (
            <Space direction="vertical" size={6}>
              {version.review_note ? <Text type="secondary">审核备注：{version.review_note}</Text> : null}
              <Space wrap>{parseTags(version.tags_json).map((tag) => <Tag key={`${version.id}-${tag}`}>{tag}</Tag>)}</Space>
            </Space>
          ),
        }}
      />
    </div>
  );
}

function JobTimeline({ jobs, leaseSeconds }) {
  if (!jobs.length) return <Text type="secondary">暂无任务记录。</Text>;
  const columns = [
    { title: "任务", dataIndex: "name", width: 100 },
    { title: "状态", dataIndex: "status", render: (_, row) => <JobStatus job={row.job} leaseSeconds={leaseSeconds} />, width: 180 },
    { title: "尝试", render: (_, row) => `${row.job.attempts || 0}/${row.job.max_attempts || 0}`, width: 90 },
    { title: "进度", render: (_, row) => <DownloadProgress job={row.job} />, width: 180 },
    { title: "下次重试", render: (_, row) => row.job.next_run_at || "-", width: 160 },
    { title: "错误类型", render: (_, row) => row.job.error_type || "-", width: 130 },
  ];
  return (
    <Table
      className="detail-table"
      columns={columns}
      dataSource={jobs.map(([name, job]) => ({ name, job, key: name }))}
      rowKey="key"
      pagination={false}
      size="small"
      expandable={{
        expandedRowRender: (row) => (
          <Space direction="vertical" size={6}>
            {row.job.locked_at ? <Text type="secondary">锁定 {row.job.lock_owner || "-"} {row.job.locked_at}</Text> : null}
            {row.job.error ? <Alert type="error" message={row.job.error} /> : <Text type="secondary">暂无错误详情。</Text>}
          </Space>
        ),
      }}
    />
  );
}

function DownloadProgress({ job }) {
  const percent = Number(job.progress_percent || 0);
  if (job.job_type !== "download" || (!percent && job.status !== "running")) {
    return <Text type="secondary">-</Text>;
  }
  return (
    <Space direction="vertical" size={2} style={{ width: "100%" }}>
      <Progress percent={Math.round(percent)} size="small" status={job.status === "failed" ? "exception" : "active"} />
      <Text type="secondary">{job.progress_stage || "download"} · {formatBytes(job.progress_downloaded_bytes)} / {formatBytes(job.progress_total_bytes)}</Text>
    </Space>
  );
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "-";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GiB`;
}

function draftActionLabel(action) {
  const labels = {
    draft_created: "生成",
    draft_regenerated: "重新生成",
    draft_updated: "编辑",
    draft_approved: "审核通过",
    draft_rejected: "审核拒绝",
    draft_pending: "退回待审",
  };
  return labels[action] || action || "-";
}

function getLockState(job, leaseSeconds) {
  if (!job.locked_at || !leaseSeconds) return null;
  const lockedAt = new Date(`${String(job.locked_at).replace(" ", "T")}Z`);
  if (Number.isNaN(lockedAt.getTime())) return { overdue: false, label: "locked" };
  const ageSeconds = Math.max(0, (Date.now() - lockedAt.getTime()) / 1000);
  return {
    overdue: ageSeconds > leaseSeconds,
    label: ageSeconds > leaseSeconds ? "lock overdue" : "locked",
  };
}

function PublishRecords({ records }) {
  if (!records.length) return <Text type="secondary">暂无发布记录。</Text>;
  const columns = [
    { title: "平台", dataIndex: "platform", width: 120 },
    { title: "账号", dataIndex: "account" },
    { title: "状态", dataIndex: "status", render: (value) => <StatusTag status={value} />, width: 120 },
    { title: "时间", render: (_, row) => row.published_at || row.created_at || "-", width: 180 },
  ];
  return <Table className="detail-table" columns={columns} dataSource={records} rowKey="id" pagination={false} size="small" />;
}

function RecentEvents({ events }) {
  if (!events.length) return <Text type="secondary">暂无事件。</Text>;
  const columns = [
    { title: "类型", dataIndex: "event_type", width: 140 },
    { title: "模块", dataIndex: "module", width: 120 },
    { title: "消息", dataIndex: "message", ellipsis: true },
    { title: "时间", dataIndex: "created_at", width: 180 },
  ];
  return <Table className="detail-table" columns={columns} dataSource={events} rowKey="id" pagination={false} size="small" />;
}

function StatusTag({ status }) {
  return <Tag color={statusColor(status)}>{status || "-"}</Tag>;
}

function JobStatus({ job, leaseSeconds }) {
  const lockState = getLockState(job, leaseSeconds);
  return (
    <Space size={4} wrap>
      {lockState ? <Tag color={lockState.overdue ? "red" : "gold"}>{lockState.label}</Tag> : null}
      <StatusTag status={job.status} />
    </Space>
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

function validateDraftForm(form, rules) {
  const errors = [];
  const title = String(form.title || "").trim();
  const description = String(form.description || "").trim();
  const tags = parseTagText(form.tags);
  if (!title) errors.push("标题不能为空");
  if (title.length > rules.title_max_length) errors.push(`标题不能超过 ${rules.title_max_length} 个字符`);
  if (!description) errors.push("描述不能为空");
  if (description.length > rules.description_max_length) errors.push(`描述不能超过 ${rules.description_max_length} 个字符`);
  if (tags.length > rules.tag_max_count) errors.push(`标签不能超过 ${rules.tag_max_count} 个`);
  if (tags.some((tag) => tag.length > rules.tag_max_length)) errors.push(`单个标签不能超过 ${rules.tag_max_length} 个字符`);
  if (!form.tid) errors.push("请选择发布分区");
  return errors;
}

function longestTagLength(tags) {
  return tags.reduce((max, tag) => Math.max(max, tag.length), 0);
}

function sourceTone(source) {
  if (source === "llm") return "ok";
  if (source === "manual") return "manual";
  if (source === "fallback") return "warning";
  return "neutral";
}

function sourceLabel(source) {
  if (source === "llm") return "LLM 判断";
  if (source === "manual") return "人工确认";
  if (source === "fallback") return "兜底策略";
  return source || "-";
}

function statusColor(status) {
  if (["ready_to_publish", "published", "approved"].includes(status)) return "green";
  if (["failed", "rejected"].includes(status)) return "red";
  if (["publishing", "downloading", "describing", "running", "pending"].includes(status)) return "gold";
  if (["skipped"].includes(status)) return "default";
  return "blue";
}

function sourceColor(source) {
  if (source === "llm") return "green";
  if (source === "manual") return "cyan";
  if (source === "fallback") return "gold";
  return "default";
}

function fieldHasError(errors, fieldName) {
  return errors.some((error) => error.includes(fieldName));
}
