import { configFields } from "../constants";

export function ConfigPanel({ config, configByKey }) {
  if (!config) return <div className="panel-body muted">正在加载配置。</div>;
  return (
    <div className="panel-body">
      <div className="config-grid">
        {configFields.map((key) => {
          const field = configByKey[key];
          if (!field) return null;
          const value = field.value ?? "";
          return (
            <div className="config-field" key={key}>
              <label htmlFor={`cfg_${key}`}>{key}</label>
              {field.type === "bool" ? (
                <select id={`cfg_${key}`} data-config-key={key} defaultValue={value ? "true" : "false"}>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : field.choices?.length ? (
                <select id={`cfg_${key}`} data-config-key={key} defaultValue={String(value)}>
                  {field.choices.map((choice) => <option value={choice} key={choice}>{choice || "(empty)"}</option>)}
                </select>
              ) : (
                <input id={`cfg_${key}`} data-config-key={key} defaultValue={String(value)} />
              )}
            </div>
          );
        })}
      </div>
      <div className="muted config-path">配置文件：{config.env_path || "-"}</div>
    </div>
  );
}
