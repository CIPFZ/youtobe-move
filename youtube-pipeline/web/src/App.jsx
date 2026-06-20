import React, { useEffect, useState } from "react";
import { Play, RefreshCw, Search } from "lucide-react";
import { IconButton } from "./components/IconButton";
import { usePipelineDashboard } from "./hooks/usePipelineDashboard";
import { ConfigSection } from "./sections/ConfigSection";
import { DetailSection } from "./sections/DetailSection";
import { DiscoverySection } from "./sections/DiscoverySection";
import { QueueSection } from "./sections/QueueSection";
import { StorageSection } from "./sections/StorageSection";

function App() {
  const [toast, setToast] = useState("");

  function showToast(message) {
    setToast(typeof message === "string" ? message : JSON.stringify(message, null, 2));
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => setToast(""), 5200);
  }

  const { state, actions } = usePipelineDashboard(showToast);
  const {
    refreshAll,
    runWorker,
    discoverDryRun,
  } = actions;

  useEffect(() => {
    refreshAll();
  }, []);

  return (
    <>
      <header>
        <div>
          <h1>YouTube Pipeline</h1>
          <div className="muted">发现、下载、文案、发布队列</div>
        </div>
        <div className="toolbar">
          <IconButton icon={Play} onClick={runWorker}>运行一轮</IconButton>
          <IconButton icon={Search} onClick={discoverDryRun}>发现预览</IconButton>
          <IconButton icon={RefreshCw} className="primary" onClick={refreshAll} disabled={state.loading}>刷新</IconButton>
        </div>
      </header>

      <main>
        <QueueSection state={state} actions={actions} />
        <DetailSection state={state} actions={actions} showToast={showToast} />
        <ConfigSection state={state} actions={actions} />
        <StorageSection state={state} actions={actions} />
        <DiscoverySection state={state} actions={actions} />
      </main>

      {toast ? <div className="toast show">{toast}</div> : null}
    </>
  );
}

export default App;
