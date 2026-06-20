import { DiscoverySection } from "../sections/DiscoverySection";

export function DiscoveryPage({ state, actions }) {
  return (
    <div className="page-stack">
      <DiscoverySection state={state} actions={actions} />
    </div>
  );
}
