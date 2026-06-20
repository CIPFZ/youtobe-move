import React, { useEffect, useState } from "react";
import { Play, RefreshCw, Search } from "lucide-react";
import { IconButton } from "./components/IconButton";
import { usePipelineDashboard } from "./hooks/usePipelineDashboard";
import { ConfigSection } from "./sections/ConfigSection";
import { DetailSection } from "./sections/DetailSection";
import { DiscoverySection } from "./sections/DiscoverySection";
import { EventsSection } from "./sections/EventsSection";
import { FailuresSection } from "./sections/FailuresSection";
import { OverviewSection } from "./sections/OverviewSection";
import { QueueSection } from "./sections/QueueSection";
import { StorageSection } from "./sections/StorageSection";
import { WorkerSection } from "./sections/WorkerSection";

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

      <nav className="page-nav" aria-label="管理区导航">
        <a href="#overview">总览</a>
        <a href="#queue">队列</a>
        <a href="#failures">失败</a>
        <a href="#worker">Worker</a>
        <a href="#detail">详情</a>
        <a href="#config">配置</a>
        <a href="#storage">存储</a>
        <a href="#discovery">发现源</a>
        <a href="#events">事件</a>
      </nav>

      <main>
        <OverviewSection state={state} actions={actions} />
        <QueueSection state={state} actions={actions} />
        <FailuresSection state={state} actions={actions} />
        <WorkerSection state={state} actions={actions} />
        <DetailSection state={state} actions={actions} showToast={showToast} />
        <ConfigSection state={state} actions={actions} />
        <StorageSection state={state} actions={actions} />
        <DiscoverySection state={state} actions={actions} />
        <EventsSection state={state} actions={actions} />
      </main>

      {toast ? <div className="toast show">{toast}</div> : null}
    </>
  );
}

export default App;
