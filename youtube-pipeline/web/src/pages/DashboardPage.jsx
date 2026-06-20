import { OverviewSection } from "../sections/OverviewSection";

export function DashboardPage({ state, actions }) {
  return (
    <div className="page-stack">
      <OverviewSection state={state} actions={actions} />
    </div>
  );
}
