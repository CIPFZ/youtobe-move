import { RefreshCw } from "lucide-react";
import { DiscoverySourcesPanel } from "../components/DiscoverySourcesPanel";
import { IconButton } from "../components/IconButton";

export function DiscoverySection({ state, actions }) {
  const { discoverySources, sourcePreview } = state;
  const {
    loadDiscoverySources,
    saveDiscoverySource,
    deleteDiscoverySource,
    previewDiscoverySource,
  } = actions;

  return (
    <section className="panel wide">
      <div className="panel-head">
        <h2>发现源</h2>
        <div className="toolbar">
          <IconButton icon={RefreshCw} onClick={loadDiscoverySources}>刷新</IconButton>
        </div>
      </div>
      <DiscoverySourcesPanel
        sources={discoverySources}
        preview={sourcePreview}
        onSave={saveDiscoverySource}
        onDelete={deleteDiscoverySource}
        onPreview={previewDiscoverySource}
      />
    </section>
  );
}
