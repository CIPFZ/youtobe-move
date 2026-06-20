import { useEffect } from "react";
import { DiscoverySection } from "../sections/DiscoverySection";

export function DiscoveryPage({ state, actions }) {
  useEffect(() => {
    actions.loadDiscoveryPage();
  }, []);

  return (
    <div className="page-stack">
      <DiscoverySection state={state} actions={actions} />
    </div>
  );
}
