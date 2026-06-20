export function escapeText(value) {
  return String(value ?? "");
}

export function fmtDuration(seconds) {
  if (!seconds) return "-";
  const min = Math.floor(seconds / 60);
  const sec = String(seconds % 60).padStart(2, "0");
  return `${min}:${sec}`;
}

export function fmtCount(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString("zh-CN");
}

export function fmtBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function statusMap(rows) {
  const map = {};
  for (const row of rows || []) map[row.status] = row.count;
  return map;
}

export function flattenConfig(config) {
  const map = {};
  for (const fields of Object.values(config?.groups || {})) {
    for (const field of fields) map[field.key] = field;
  }
  return map;
}

export function parseTags(raw) {
  try {
    const parsed = JSON.parse(raw || "[]");
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

export function tagsToText(raw) {
  return parseTags(raw).join(", ");
}

export function parseTagText(raw) {
  return String(raw || "")
    .replaceAll("，", ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseTidOptions(raw) {
  return String(raw || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const [tid, ...labelParts] = item.split(":");
      return { tid: tid.trim(), label: labelParts.join(":").trim() };
    })
    .filter((item) => /^\d+$/.test(item.tid));
}
