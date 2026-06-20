import React, { Suspense, lazy, useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { message, Modal, Spin } from "antd";
import { AppLayout } from "./layout/AppLayout";
import { usePipelineDashboard } from "./hooks/usePipelineDashboard";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const DiscoveryPage = lazy(() => import("./pages/DiscoveryPage").then((module) => ({ default: module.DiscoveryPage })));
const OperationsPage = lazy(() => import("./pages/OperationsPage").then((module) => ({ default: module.OperationsPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const VideosPage = lazy(() => import("./pages/VideosPage").then((module) => ({ default: module.VideosPage })));

function App() {
  const [messageApi, contextHolder] = message.useMessage();
  const [modalApi, modalContextHolder] = Modal.useModal();

  function showToast(payload) {
    const content = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
    messageApi.open({
      type: "info",
      content: <pre className="toast-pre">{content}</pre>,
      duration: 5.2,
    });
  }

  function confirmAction(content) {
    return new Promise((resolve) => {
      modalApi.confirm({
        title: "请确认",
        content,
        okText: "确认",
        cancelText: "取消",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  }

  const { state, actions } = usePipelineDashboard(showToast, confirmAction);
  const navigate = useNavigate();
  const location = useLocation();
  const refreshCurrentPage = () => {
    if (location.pathname.startsWith("/videos")) return actions.loadVideosPage(state.selectedId);
    if (location.pathname.startsWith("/discovery")) return actions.loadDiscoveryPage();
    if (location.pathname.startsWith("/operations")) return actions.loadOperationsPage();
    if (location.pathname.startsWith("/settings")) return actions.loadSettingsPage();
    return actions.loadDashboard();
  };
  const routeActions = {
    ...actions,
    refreshCurrentPage,
    selectVideo: async (videoId) => {
      await actions.selectVideo(videoId);
      navigate(`/videos/${encodeURIComponent(videoId)}`);
    },
  };

  return (
    <>
      {contextHolder}
      {modalContextHolder}
      <Routes>
        <Route element={<AppLayout state={state} actions={routeActions} />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<PageFallback><DashboardPage state={state} actions={routeActions} /></PageFallback>} />
          <Route path="/videos" element={<PageFallback><VideosPage state={state} actions={routeActions} showToast={showToast} /></PageFallback>} />
          <Route path="/videos/:videoId" element={<PageFallback><VideoDetailRoute state={state} actions={routeActions} rawActions={actions} showToast={showToast} /></PageFallback>} />
          <Route path="/discovery" element={<PageFallback><DiscoveryPage state={state} actions={routeActions} /></PageFallback>} />
          <Route path="/operations" element={<PageFallback><OperationsPage state={state} actions={routeActions} /></PageFallback>} />
          <Route path="/settings" element={<PageFallback><SettingsPage state={state} actions={routeActions} /></PageFallback>} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </>
  );
}

function PageFallback({ children }) {
  return <Suspense fallback={<div className="page-loading"><Spin /> 加载页面...</div>}>{children}</Suspense>;
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
