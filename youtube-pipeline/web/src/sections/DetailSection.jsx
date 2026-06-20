import { VideoDetail } from "../components/VideoDetail";

export function DetailSection({ state, actions, showToast }) {
  const { selectedId, detail, configByKey, status } = state;
  const { loadAll, runVideoAction } = actions;

  return (
    <section className="panel" id="detail">
      <div className="panel-head">
        <h2>详情</h2>
        <div className="muted">{selectedId || "未选择"}</div>
      </div>
      <div className="panel-body">
        {detail ? (
          <VideoDetail
            data={detail}
            configByKey={configByKey}
            draftRules={status?.settings?.publish_draft_rules}
            onAction={runVideoAction}
            onSaved={async () => {
              await loadAll(detail.video.video_id);
            }}
            showToast={showToast}
          />
        ) : <div className="muted">请选择一个视频。</div>}
      </div>
    </section>
  );
}
