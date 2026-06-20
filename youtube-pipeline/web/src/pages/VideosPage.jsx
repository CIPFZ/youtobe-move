import { DetailSection } from "../sections/DetailSection";
import { QueueSection } from "../sections/QueueSection";

export function VideosPage({ state, actions, showToast }) {
  return (
    <div className="videos-page">
      <QueueSection state={state} actions={actions} />
      <DetailSection state={state} actions={actions} showToast={showToast} />
    </div>
  );
}
