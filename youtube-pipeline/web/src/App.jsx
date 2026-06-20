import React, { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { message } from "antd";
import { AppLayout } from "./layout/AppLayout";
import { usePipelineDashboard } from "./hooks/usePipelineDashboard";
import { DashboardPage } from "./pages/DashboardPage";
import { DiscoveryPage } from "./pages/DiscoveryPage";
import { OperationsPage } from "./pages/OperationsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VideosPage } from "./pages/VideosPage";

function App() {
  const [messageApi, contextHolder] = message.useMessage();

  function showToast(payload) {
    const content = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
    messageApi.open({
      type: "info",
      content: <pre className="toast-pre">{content}</pre>,
      duration: 5.2,
    });
  }

  const { state, actions } = usePipelineDashboard(showToast);
  const navigate = useNavigate();
  const routeActions = {
    ...actions,
    selectVideo: async (videoId) => {
      await actions.selectVideo(videoId);
      navigate(`/videos/${encodeURIComponent(videoId)}`);
    },
  };

  useEffect(() => {
    actions.refreshAll();
  }, []);

  return (
    <>
      {contextHolder}
      <Routes>
        <Route element={<AppLayout state={state} actions={routeActions} />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage state={state} actions={routeActions} />} />
          <Route path="/videos" element={<VideosPage state={state} actions={routeActions} showToast={showToast} />} />
          <Route path="/videos/:videoId" element={<VideoDetailRoute state={state} actions={routeActions} rawActions={actions} showToast={showToast} />} />
          <Route path="/discovery" element={<DiscoveryPage state={state} actions={routeActions} />} />
          <Route path="/operations" element={<OperationsPage state={state} actions={routeActions} />} />
          <Route path="/settings" element={<SettingsPage state={state} actions={routeActions} />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </>
  );
}

function VideoDetailRoute({ state, actions, rawActions, showToast }) {
  const { videoId } = useParams();

  useEffect(() => {
    if (videoId && state.selectedId !== videoId) {
      rawActions.selectVideo(videoId).catch((error) => showToast(error.message));
    }
  }, [videoId]);

  return <VideosPage state={state} actions={actions} showToast={showToast} />;
}

export default App;
