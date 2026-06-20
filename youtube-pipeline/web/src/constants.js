export const statusOptions = ["selected", "downloaded", "ready_to_publish", "published", "failed", "skipped"];
export const draftOptions = ["pending", "approved", "rejected"];
export const errorOptions = ["youtube_403", "network_error", "llm_failed", "publish_failed", "unknown"];

export const draftLimits = {
  title: 80,
  description: 2000,
  tags: 8,
  tagLength: 20,
};

export const configFields = [
  "PIPELINE_ENABLED",
  "WORKER_INTERVAL_SECONDS",
  "WORKER_CRON",
  "WORKER_ENABLE_DISCOVERY",
  "WORKER_ENABLE_DOWNLOAD",
  "WORKER_ENABLE_DESCRIBE",
  "WORKER_ENABLE_PUBLISH",
  "WORKER_PUBLISH_DRY_RUN",
  "PROXY",
  "RETRIES",
  "FRAGMENT_RETRIES",
  "PUBLISH_MODE",
  "PUBLISH_DAILY_LIMIT",
  "PUBLISH_MIN_INTERVAL_SECONDS",
  "STORAGE_MAX_GB",
  "STORAGE_WARN_GB",
  "STORAGE_MIN_FREE_GB",
  "STORAGE_RETENTION_DAYS",
  "STORAGE_CLEANUP_ENABLED",
  "STORAGE_CLEANUP_STATUSES",
];
