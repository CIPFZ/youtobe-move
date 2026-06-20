import { useEffect } from "react";
import { OverviewSection } from "../sections/OverviewSection";

export function DashboardPage({ state, actions }) {
  useEffect(() => {
    actions.loadDashboard();
  }, []);

  return (
    <div className="page-stack">
      <OverviewSection state={state} actions={actions} />
    </div>
  );
}
