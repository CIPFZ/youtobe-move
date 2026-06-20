import { useEffect } from "react";
import { ConfigSection } from "../sections/ConfigSection";
import { StorageSection } from "../sections/StorageSection";

export function SettingsPage({ state, actions }) {
  useEffect(() => {
    actions.loadSettingsPage();
  }, []);

  return (
    <div className="page-stack">
      <ConfigSection state={state} actions={actions} />
      <StorageSection state={state} actions={actions} />
    </div>
  );
}
