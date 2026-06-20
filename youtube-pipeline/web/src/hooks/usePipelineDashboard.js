import { useMemo, useState } from "react";
import { api } from "../api";
import { configFields } from "../constants";
import { flattenConfig } from "../format";

export function usePipelineDashboard(showToast) {
  const [status, setStatus] = useState(null);
  const [videos, setVideos] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [config, setConfig] = useState(null);
  const [storage, setStorage] = useState(null);
  const [discoverySources, setDiscoverySources] = useState([]);
  const [sourcePreview, setSourcePreview] = useState(null);
  const [filters, setFilters] = useState({ status: "", draftStatus: "", errorType: "" });
  const [selectedVideoIds, setSelectedVideoIds] = useState([]);
  const [addUrls, setAddUrls] = useState("");
  const [addPriority, setAddPriority] = useState("100");
  const [addSourceLabel, setAddSourceLabel] = useState("web");
  const [loading, setLoading] = useState(false);

  const configByKey = useMemo(() => flattenConfig(config), [config]);
  async function loadConfig() {
    setConfig(await api("/api/config"));
  }

  async function loadStorage() {
    setStorage(await api("/api/storage"));
  }

  async function loadDiscoverySources() {
    const payload = await api("/api/discovery/sources");
    setDiscoverySources(payload.sources || []);
  }

  async function selectVideo(videoId) {
    setSelectedId(videoId);
    setDetail(await api(`/api/videos/${encodeURIComponent(videoId)}`));
  }

  async function loadAll(keepSelected = selectedId, nextFilters = filters) {
    const params = new URLSearchParams({ limit: "80" });
    if (nextFilters.status) params.set("status", nextFilters.status);
    if (nextFilters.draftStatus) params.set("draft_status", nextFilters.draftStatus);
    if (nextFilters.errorType) params.set("error_type", nextFilters.errorType);
    const [statusPayload, listPayload] = await Promise.all([
      api("/api/status?events_limit=5"),
      api(`/api/videos?${params.toString()}`),
    ]);
    const nextVideos = listPayload.videos || [];
    setStatus(statusPayload);
    setVideos(nextVideos);
    setSelectedVideoIds((prev) => {
      const visibleIds = new Set(nextVideos.map((item) => item.video.video_id));
      return prev.filter((videoId) => visibleIds.has(videoId));
    });
    if (keepSelected && nextVideos.some((item) => item.video.video_id === keepSelected)) {
      await selectVideo(keepSelected);
    } else {
      setSelectedId("");
      setDetail(null);
    }
  }

  async function refreshAll() {
    setLoading(true);
    try {
      await Promise.all([loadAll(), loadConfig(), loadStorage(), loadDiscoverySources()]);
    } catch (error) {
      showToast(error.message);
    } finally {
      setLoading(false);
    }
  }

  function updateFilters(updater) {
    setFilters((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      loadAll("", next).catch((error) => showToast(error.message));
      return next;
    });
  }

  async function runVideoAction(videoId, action) {
    const body = {};
    if (action === "publish") {
      if (!window.confirm("确认真实发布到 B 站？")) return;
      body.confirm = true;
    }
    if (action === "skip" && !window.confirm("确认跳过该视频？")) return;
    if (action === "cleanup-media") {
      if (!window.confirm("确认清理该视频的媒体文件？数据库记录会保留。")) return;
      body.confirm = true;
      body.dry_run = false;
    }
    try {
      const result = await api(`/api/videos/${encodeURIComponent(videoId)}/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      showToast(result);
      await loadAll(videoId);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function runWorker() {
    try {
      const result = await api("/api/worker-run", { method: "POST", body: "{}" });
      showToast(result);
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function discoverDryRun() {
    try {
      const result = await api("/api/discover", { method: "POST", body: JSON.stringify({ dry_run: true }) });
      showToast(result);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function saveConfig() {
    const values = {};
    for (const key of configFields) {
      const field = configByKey[key];
      if (!field) continue;
      const element = document.querySelector(`[data-config-key="${key}"]`);
      if (!element) continue;
      if (field.type === "bool") values[key] = element.value === "true";
      else if (field.type === "int") values[key] = Number.parseInt(element.value || "0", 10);
      else if (field.type === "float") values[key] = Number.parseFloat(element.value || "0");
      else values[key] = element.value;
    }
    try {
      const result = await api("/api/config", { method: "PATCH", body: JSON.stringify({ values }) });
      setConfig(result.config);
      showToast(`已保存配置：${result.updated.join(", ")}`);
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function addQueueUrls() {
    const value = addUrls.trim();
    if (!value) {
      showToast("请输入至少一个 YouTube 链接。");
      return;
    }
    try {
      const result = await api("/api/videos/add-urls", {
        method: "POST",
        body: JSON.stringify({
          urls: value,
          priority: Number.parseInt(addPriority || "100", 10),
          source_label: addSourceLabel.trim() || "web",
        }),
      });
      setAddUrls("");
      showToast(`添加完成：created=${result.created_count}, exists=${result.exists_count}, errors=${result.error_count}`);
      const firstCreated = (result.results || []).find((item) => item.status === "created");
      await loadAll(firstCreated?.video?.video_id || "");
    } catch (error) {
      showToast(error.message);
    }
  }

  async function runBatchAction(action) {
    if (!selectedVideoIds.length) {
      showToast("请先选择视频。");
      return;
    }
    if (action === "skip" && !window.confirm(`确认跳过 ${selectedVideoIds.length} 个视频？`)) return;
    try {
      const result = await api("/api/videos/batch", {
        method: "POST",
        body: JSON.stringify({ action, video_ids: selectedVideoIds }),
      });
      showToast(result);
      setSelectedVideoIds([]);
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  }

  function toggleSelectedVideo(videoId, checked) {
    setSelectedVideoIds((prev) => (checked ? [...new Set([...prev, videoId])] : prev.filter((item) => item !== videoId)));
  }

  async function runStorageCleanup(dryRun) {
    if (!dryRun && !window.confirm("确认清理符合条件的媒体文件？数据库记录会保留。")) return;
    try {
      const result = await api("/api/storage/cleanup", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, confirm: !dryRun }),
      });
      showToast(result);
      await Promise.all([loadStorage(), loadAll(selectedId)]);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function saveDiscoverySource(source, index = null) {
    try {
      const path = index === null ? "/api/discovery/sources" : `/api/discovery/sources/${index}`;
      const result = await api(path, {
        method: index === null ? "POST" : "PATCH",
        body: JSON.stringify(index === null ? { source } : source),
      });
      setDiscoverySources(result.sources || []);
      await loadConfig();
      showToast(result);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function deleteDiscoverySource(index) {
    if (!window.confirm("确认删除该发现源？")) return;
    try {
      const result = await api(`/api/discovery/sources/${index}`, { method: "DELETE", body: "{}" });
      setDiscoverySources(result.sources || []);
      await loadConfig();
      showToast(result);
    } catch (error) {
      showToast(error.message);
    }
  }

  async function previewDiscoverySource(index) {
    if (index === null || index === undefined) {
      showToast("请先选择发现源。");
      return;
    }
    try {
      const result = await api(`/api/discovery/sources/${index}`, {
        method: "POST",
        body: JSON.stringify({ action: "preview" }),
      });
      setSourcePreview(result);
      showToast(`预览完成：accepted=${result.accepted_count}, rejected=${result.rejected_count}`);
    } catch (error) {
      showToast(error.message);
    }
  }

  return {
    state: {
      status,
      videos,
      selectedId,
      detail,
      config,
      configByKey,
      storage,
      discoverySources,
      sourcePreview,
      filters,
      selectedVideoIds,
      addUrls,
      addPriority,
      addSourceLabel,
      loading,
    },
    actions: {
      setAddUrls,
      setAddPriority,
      setAddSourceLabel,
      setSelectedVideoIds,
      updateFilters,
      loadAll,
      loadConfig,
      loadStorage,
      loadDiscoverySources,
      refreshAll,
      selectVideo,
      runVideoAction,
      runWorker,
      discoverDryRun,
      saveConfig,
      addQueueUrls,
      runBatchAction,
      toggleSelectedVideo,
      runStorageCleanup,
      saveDiscoverySource,
      deleteDiscoverySource,
      previewDiscoverySource,
    },
  };
}
