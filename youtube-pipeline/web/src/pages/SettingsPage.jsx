import { ConfigSection } from "../sections/ConfigSection";
import { StorageSection } from "../sections/StorageSection";

export function SettingsPage({ state, actions }) {
  return (
    <div className="page-stack">
      <ConfigSection state={state} actions={actions} />
      <StorageSection state={state} actions={actions} />
    </div>
  );
}
