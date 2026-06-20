import { useEffect } from "react";
import { EventsSection } from "../sections/EventsSection";
import { FailuresSection } from "../sections/FailuresSection";
import { JobsSection } from "../sections/JobsSection";
import { WorkerSection } from "../sections/WorkerSection";

export function OperationsPage({ state, actions }) {
  useEffect(() => {
    actions.loadOperationsPage();
  }, []);

  return (
    <div className="operations-page">
      <WorkerSection state={state} actions={actions} />
      <FailuresSection state={state} actions={actions} />
      <JobsSection state={state} actions={actions} />
      <EventsSection state={state} actions={actions} />
    </div>
  );
}
