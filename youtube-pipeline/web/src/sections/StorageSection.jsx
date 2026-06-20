import { HardDrive, RefreshCw, X } from "lucide-react";
import { IconButton } from "../components/IconButton";
import { StoragePanel } from "../components/StoragePanel";

export function StorageSection({ state, actions }) {
  const { storage } = state;
  const { loadStorage, runStorageCleanup } = actions;

  return (
    <section className="panel wide">
      <div className="panel-head">
        <h2>存储</h2>
        <div className="toolbar">
          <IconButton icon={RefreshCw} onClick={loadStorage}>刷新</IconButton>
          <IconButton icon={HardDrive} onClick={() => runStorageCleanup(true)}>清理预览</IconButton>
          <IconButton icon={X} className="danger" onClick={() => runStorageCleanup(false)}>执行清理</IconButton>
        </div>
      </div>
      <StoragePanel storage={storage} />
    </section>
  );
}
