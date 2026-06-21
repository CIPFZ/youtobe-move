import { useEffect } from "react";
import { QueueSection } from "../sections/QueueSection";

export function VideosPage({ state, actions }) {
  useEffect(() => {
    actions.loadVideosPage(state.selectedId);
  }, []);

  return (
    <div className="videos-page">
      <QueueSection state={state} actions={actions} />
    </div>
  );
}
