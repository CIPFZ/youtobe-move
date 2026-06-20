import { useEffect, useState } from "react";
import { Check, Download, Eye, FileText, HardDrive, RotateCcw, Save, Send, SkipForward, X } from "lucide-react";
import { api } from "../api";
import { draftLimits, draftOptions } from "../constants";
import { fmtCount, fmtDuration, parseTagText, parseTags, parseTidOptions, tagsToText } from "../format";
import { IconButton } from "./IconButton";

export function VideoDetail({ data, configByKey, onAction, onSaved, showToast }) {
  const video = data.video;
  const draft = data.publish_draft || {};
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
  const draftErrors = validateDraftForm(draftForm);

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
        <section className="section">
          <h2>{video.title || video.video_id}</h2>
          <div className="kv">
            <div>状态</div><div><span className={`badge ${video.status}`}>{video.status}</span></div>
            <div>频道</div><div>{video.channel || "-"}</div>
            <div>时长</div><div>{fmtDuration(video.duration)}</div>
            <div>播放</div><div>{fmtCount(video.view_count)}</div>
            <div>分类</div><div>{video.category || "-"}</div>
            <div>优先级</div><div>{video.priority ?? 100}</div>
            <div>来源标签</div><div>{video.source_label || "-"}</div>
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
            <IconButton icon={HardDrive} className="danger" disabled={!canCleanupMedia} onClick={() => onAction(video.video_id, "cleanup-media")}>清理媒体</IconButton>
          </div>
        </section>

        <section className="section">
          <h2>发布草稿</h2>
          {draft.title ? (
            <>
              <DraftSummary draft={draft} />
              <div className="draft-form">
                <label>
                  <span>标题 <em>{draftForm.title.length}/{draftLimits.title}</em></span>
                  <input value={draftForm.title} onChange={(event) => updateDraftField("title", event.target.value)} maxLength={80} />
                </label>
                <label>
                  <span>描述 <em>{draftForm.description.length}/{draftLimits.description}</em></span>
                  <textarea value={draftForm.description} onChange={(event) => updateDraftField("description", event.target.value)} rows={7} />
                </label>
                <label>
                  <span>标签</span>
                  <input value={draftForm.tags} onChange={(event) => updateDraftField("tags", event.target.value)} placeholder="使用逗号分隔" />
                  <small>最多 {draftLimits.tags} 个，每个不超过 {draftLimits.tagLength} 个字符。</small>
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
                {draftErrors.length ? <div className="form-error">{draftErrors[0]}</div> : null}
                <div className="toolbar">
                  <IconButton icon={Save} className="primary" onClick={saveDraft} disabled={savingDraft || Boolean(draftErrors.length)}>保存草稿</IconButton>
                  <span className="muted">保存后分区来源会标记为 manual。</span>
                </div>
              </div>
              <DraftTags draft={draft} />
              <DraftHistory versions={draftVersions} />
            </>
          ) : <div className="muted">暂无草稿。</div>}
        </section>

        <section className="section">
          <h2>任务状态</h2>
          <JobTimeline jobs={jobs} leaseSeconds={jobLeaseSeconds} />
        </section>

        <section className="section">
          <h2>发布记录</h2>
          <PublishRecords records={records} />
        </section>

        <section className="section">
          <h2>最近事件</h2>
          <RecentEvents events={events} />
        </section>
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
    <aside className="media-panel">
      {hasMerged ? (
        <video className="media-video" src={`${base}?type=merged`} controls preload="metadata" poster={hasPoster ? `${base}?type=poster` : undefined} />
      ) : hasPoster ? (
        <img className="poster" src={`${base}?type=poster`} alt="" />
      ) : (
        <div className="poster placeholder">暂无媒体预览</div>
      )}
      <div className="media-files">
        {rows.map(([type, label, path]) => (
          <div className="media-file-row" key={type}>
            <div>
              <b>{label}</b>
              <small>{path || "未生成"}</small>
            </div>
            {path ? (
              <a href={`${base}?type=${type}`} target="_blank" rel="noreferrer">打开</a>
            ) : <span className="badge">missing</span>}
          </div>
        ))}
      </div>
    </aside>
  );
}

function DraftSummary({ draft }) {
  const source = draft.tid_source || "-";
  const tone = sourceTone(source);
  const isFallback = source === "fallback";
  return (
    <div className="draft-summary">
      <div className="draft-state-card">
        <span>审核状态</span>
        <strong><span className={`badge ${draft.status || ""}`}>{draft.status || "-"}</span></strong>
        {draft.review_note ? <small>{draft.review_note}</small> : null}
      </div>
      <div className="draft-state-card">
        <span>发布分区</span>
        <strong>{draft.tid || "-"} {draft.tid_label || ""}</strong>
        <small>{draft.tid_reason || "暂无分区判断原因"}</small>
      </div>
      <div className={`draft-state-card ${tone}`}>
        <span>分区来源</span>
        <strong><span className={`source-pill ${tone}`}>{sourceLabel(source)}</span></strong>
        <small>{isFallback ? "fallback 分区需要人工确认后才能真实发布" : "保存草稿后会转为 manual"}</small>
      </div>
      {isFallback ? (
        <div className="draft-warning">
          当前分区来自兜底策略，真实发布已阻断。请人工选择正确分区并保存草稿。
        </div>
      ) : null}
    </div>
  );
}

function DraftTags({ draft }) {
  const tags = parseTags(draft.tags_json);
  if (!tags.length) return null;
  return (
    <div className="draft-tags">
      <span>当前标签</span>
      <div className="badges">
        {tags.map((tag) => <span className="badge" key={tag}>{tag}</span>)}
      </div>
    </div>
  );
}

function DraftHistory({ versions }) {
  if (!versions.length) return <div className="muted">暂无草稿历史。</div>;
  return (
    <div className="draft-history">
      <div className="section-headline">
        <h3>草稿历史</h3>
        <span>最近 {versions.length} 条</span>
      </div>
      <div className="history-list">
        {versions.map((version) => {
          const tags = parseTags(version.tags_json);
          return (
            <div className="history-row" key={version.id}>
              <div className="history-main">
                <div className="history-head">
                  <b>{draftActionLabel(version.action)}</b>
                  <span className={`badge ${version.status || ""}`}>{version.status || "-"}</span>
                  <span>{version.created_at}</span>
                </div>
                <div className="history-title">{version.title || "-"}</div>
                <div className="muted">
                  分区 {version.tid || "-"} {version.tid_label || ""} · 来源 {sourceLabel(version.tid_source || "")}
                </div>
                {version.review_note ? <div className="muted">审核备注：{version.review_note}</div> : null}
                {tags.length ? (
                  <div className="badges compact">
                    {tags.map((tag) => <span className="badge" key={`${version.id}-${tag}`}>{tag}</span>)}
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function JobTimeline({ jobs, leaseSeconds }) {
  if (!jobs.length) return <div className="muted">暂无任务记录。</div>;
  return (
    <div className="job-grid">
      {jobs.map(([name, job]) => {
        const attempts = `${job.attempts || 0}/${job.max_attempts || 0}`;
        const lockState = getLockState(job, leaseSeconds);
        const details = [
          job.error_type ? `错误类型 ${job.error_type}` : "",
          job.next_run_at ? `下次重试 ${job.next_run_at}` : "",
          lockState ? `锁定 ${job.lock_owner || "-"} ${job.locked_at}` : "",
        ].filter(Boolean);
        return (
          <div className={`job-card ${job.status}${lockState?.overdue ? " lock-overdue" : ""}`} key={name}>
            <div className="job-card-head">
              <b>{name}</b>
              <div className="job-card-badges">
                {lockState ? <span className={`badge ${lockState.overdue ? "failed" : "publishing"}`}>{lockState.label}</span> : null}
                <span className={`badge ${job.status}`}>{job.status}</span>
              </div>
            </div>
            <div className="job-meta">
              <span>尝试 {attempts}</span>
              {details.map((item) => <span key={item}>{item}</span>)}
            </div>
            {job.error ? <div className="job-error">{job.error}</div> : null}
          </div>
        );
      })}
    </div>
  );
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
  if (!records.length) return <div className="muted">暂无发布记录。</div>;
  return (
    <div className="record-list">
      {records.map((record) => (
        <div className="record-row" key={record.id}>
          <div>
            <b>{record.platform}</b>
            <div className="muted">{record.account} · {record.published_at || record.created_at}</div>
          </div>
          <span className={`badge ${record.status}`}>{record.status}</span>
        </div>
      ))}
    </div>
  );
}

function RecentEvents({ events }) {
  if (!events.length) return <div className="muted">暂无事件。</div>;
  return (
    <div className="events">
      {events.map((event) => (
        <div className="event" key={event.id}>
          <div className="event-head">
            <b>{event.event_type}</b>
            <span>{event.module}</span>
          </div>
          <div className="muted">{event.created_at}</div>
          <div>{event.message}</div>
        </div>
      ))}
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

function validateDraftForm(form) {
  const errors = [];
  const title = String(form.title || "").trim();
  const description = String(form.description || "").trim();
  const tags = parseTagText(form.tags);
  if (!title) errors.push("标题不能为空");
  if (title.length > draftLimits.title) errors.push(`标题不能超过 ${draftLimits.title} 个字符`);
  if (!description) errors.push("描述不能为空");
  if (description.length > draftLimits.description) errors.push(`描述不能超过 ${draftLimits.description} 个字符`);
  if (tags.length > draftLimits.tags) errors.push(`标签不能超过 ${draftLimits.tags} 个`);
  if (tags.some((tag) => tag.length > draftLimits.tagLength)) errors.push(`单个标签不能超过 ${draftLimits.tagLength} 个字符`);
  if (!form.tid) errors.push("请选择发布分区");
  return errors;
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
