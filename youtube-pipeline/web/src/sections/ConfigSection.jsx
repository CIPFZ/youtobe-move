import { RefreshCw, Settings } from "lucide-react";
import { ConfigPanel } from "../components/ConfigPanel";
import { IconButton } from "../components/IconButton";

export function ConfigSection({ state, actions }) {
  const { config, configByKey } = state;
  const { loadConfig, saveConfig } = actions;

  return (
    <section className="panel wide">
      <div className="panel-head">
        <h2>配置</h2>
        <div className="toolbar">
          <IconButton icon={RefreshCw} onClick={loadConfig}>重新加载</IconButton>
          <IconButton icon={Settings} className="primary" onClick={saveConfig}>保存配置</IconButton>
        </div>
      </div>
      <ConfigPanel config={config} configByKey={configByKey} />
    </section>
  );
}
