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

const groupOrder = ["pipeline", "publish", "download", "storage", "youtube", "discovery", "llm", "jobs", "paths", "logging", "web"];

export function ConfigPanel({ config, configByKey }) {
  if (!config) return <div className="panel-body muted">正在加载配置。</div>;
  const groups = groupOrder
    .filter((group) => config.groups?.[group]?.length)
    .map((group) => [group, config.groups[group]]);
  return (
    <div className="panel-body">
      <div className="config-groups">
        {groups.map(([group, fields]) => (
          <section className="config-group" key={group}>
            <div className="config-group-head">
              <h3>{groupLabels[group] || group}</h3>
              <span>{group}</span>
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
