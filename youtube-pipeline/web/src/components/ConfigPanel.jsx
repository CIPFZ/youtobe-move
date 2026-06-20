const groupLabels = {
  pipeline: "自动流程",
  publish: "发布策略",
  storage: "存储策略",
  download: "下载配置",
  youtube: "YouTube API",
  discovery: "发现规则",
  llm: "LLM",
  jobs: "任务重试",
  paths: "路径",
  logging: "日志",
  web: "Web",
};

const groupDescriptions = {
  pipeline: "控制 worker 调度、阶段开关和自动流程是否运行。",
  publish: "控制自动发布模式、发布频率、发布窗口和 B 站账号分区。",
  storage: "控制下载内容占用阈值、保留时间和自动清理策略。",
  download: "控制 yt-dlp 下载格式、代理、cookie 和重试策略。",
  youtube: "YouTube Data API 查询配置。",
  discovery: "发现源 JSON 和全局发现过滤规则。",
  llm: "发布文案和分区判断使用的 LLM 接口。",
  jobs: "任务锁、失败重试和退避时间。",
  paths: "运行目录、下载目录、数据库路径和外部工具路径。",
  logging: "日志级别和日志文件路径。",
  web: "本地管理界面监听地址。",
};

const fieldDescriptions = {
  PIPELINE_ENABLED: "总开关。关闭后 worker 会跳过发现、下载、文案、发布和清理。",
  WORKER_INTERVAL_SECONDS: "interval 模式下每轮 worker 的间隔秒数。",
  WORKER_CRON: "5 段 cron。填写后 worker 按 cron 调度，--interval 会覆盖它。",
  WORKER_ENABLE_DISCOVERY: "是否允许 worker 自动发现新视频。",
  WORKER_ENABLE_DOWNLOAD: "是否允许 worker 自动执行下载任务。",
  WORKER_ENABLE_DESCRIBE: "是否允许 worker 自动生成发布草稿。",
  WORKER_ENABLE_PUBLISH: "是否允许 worker 执行发布流程。",
  WORKER_PUBLISH_DRY_RUN: "发布开关开启时，是否保持发布为 dry-run。",
  WORKER_DISCOVERY_MIN_QUEUE_SIZE: "活跃队列低于该值时触发 discovery 补充任务。",
  WORKER_DISCOVERY_SOURCE: "限制 worker 只运行某类发现源，空值表示全部。",
  PUBLISH_MODE: "manual 不自动发布；approved_auto 只发审核通过；full_auto 允许有效草稿自动发布。",
  PUBLISH_MIN_INTERVAL_SECONDS: "两次真实发布之间的最小间隔。",
  PUBLISH_DAILY_LIMIT: "本地自然日最多真实发布数量，0 表示不限制。",
  PUBLISH_WINDOW_START: "自动发布开始时间，HH:MM。",
  PUBLISH_WINDOW_END: "自动发布结束时间，HH:MM。",
  STORAGE_RETENTION_DAYS: "通用媒体保留天数。",
  STORAGE_PUBLISHED_RETENTION_DAYS: "已发布视频从成功发布记录起额外保留天数。",
  STORAGE_CLEANUP_STATUSES: "允许被清理媒体文件的视频状态列表。",
  PROXY: "下载和海报请求代理。",
  COOKIE_FILE: "yt-dlp cookie 文件路径。",
  DISCOVERY_SOURCES_JSON: "发现源配置。建议优先在发现源管理面板编辑。",
  BILIBILI_TID_OPTIONS: "允许 LLM 和人工选择的 B 站分区白名单。",
  YOUTUBE_API_KEY: "YouTube Data API key。",
  MINIMAX_ANTHROPIC_API_KEY: "MiniMax Anthropic-compatible API key。",
};

const summaryKeys = [
  "PIPELINE_ENABLED",
  "PUBLISH_MODE",
  "WORKER_CRON",
  "WORKER_INTERVAL_SECONDS",
  "WORKER_ENABLE_PUBLISH",
  "WORKER_PUBLISH_DRY_RUN",
  "STORAGE_CLEANUP_ENABLED",
  "STORAGE_WARN_GB",
  "PROXY",
];

const groupOrder = ["pipeline", "publish", "download", "storage", "youtube", "discovery", "llm", "jobs", "paths", "logging", "web"];

export function ConfigPanel({ config, configByKey }) {
  if (!config) return <div className="panel-body muted">正在加载配置。</div>;
  const groups = groupOrder
    .filter((group) => config.groups?.[group]?.length)
    .map((group) => [group, config.groups[group]]);
  return (
    <div className="panel-body">
      <ConfigSummary configByKey={configByKey} />
      <div className="config-nav" aria-label="配置分组导航">
        {groups.map(([group, fields]) => (
          <a href={`#config-${group}`} key={group}>
            <b>{groupLabels[group] || group}</b>
            <span>{fields.length}</span>
          </a>
        ))}
      </div>
      <div className="config-groups">
        {groups.map(([group, fields]) => (
          <section className="config-group" id={`config-${group}`} key={group}>
            <div className="config-group-head">
              <div>
                <h3>{groupLabels[group] || group}</h3>
                <p>{groupDescriptions[group] || group}</p>
              </div>
              <span>{group} · {fields.length}</span>
            </div>
            <div className="config-grid">
              {fields.map((field) => (
                <ConfigField field={configByKey[field.key] || field} key={field.key} />
              ))}
            </div>
          </section>
        ))}
      </div>
      <div className="muted config-path">配置文件：{config.env_path || "-"}</div>
    </div>
  );
}

function ConfigSummary({ configByKey }) {
  return (
    <div className="config-summary">
      {summaryKeys.map((key) => {
        const field = configByKey[key];
        return (
          <div className="config-summary-item" key={key}>
            <span>{key}</span>
            <strong>{field ? formatSummaryValue(field) : "-"}</strong>
          </div>
        );
      })}
    </div>
  );
}

function ConfigField({ field }) {
  const key = field.key;
  const value = field.value ?? "";
  const commonProps = {
    id: `cfg_${key}`,
    "data-config-key": key,
    "data-config-type": field.type,
    disabled: field.editable === false,
  };
  return (
    <div className={`config-field${field.sensitive ? " sensitive" : ""}`}>
      <label htmlFor={`cfg_${key}`}>
        {key}
        {field.sensitive ? <span>敏感</span> : null}
      </label>
      {fieldDescriptions[key] ? <small>{fieldDescriptions[key]}</small> : null}
      {field.type === "bool" ? (
        <select {...commonProps} defaultValue={value ? "true" : "false"}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : field.choices?.length ? (
        <select {...commonProps} defaultValue={String(value)}>
          {field.choices.map((choice) => <option value={choice} key={choice}>{choice || "(empty)"}</option>)}
        </select>
      ) : field.type === "json" ? (
        <textarea {...commonProps} defaultValue={formatConfigValue(value)} rows={5} />
      ) : (
        <input {...commonProps} defaultValue={formatConfigValue(value)} />
      )}
    </div>
  );
}

function formatConfigValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function formatSummaryValue(field) {
  if (field.sensitive) return field.value ? "已配置" : "未配置";
  if (field.type === "bool") return field.value ? "true" : "false";
  return formatConfigValue(field.value) || "(empty)";
}
