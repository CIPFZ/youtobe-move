import { RefreshCw } from "lucide-react";
import { IconButton } from "../components/IconButton";

const eventModules = ["", "worker", "core", "operations", "download", "describe", "publish", "storage", "discovery", "config"];

export function EventsSection({ state, actions }) {
  const { events, eventFilters } = state;
  const { loadEvents, updateEventFilters } = actions;
  const rows = events?.events || [];
  const limit = Number(eventFilters.limit || 30);
  const offset = Number(eventFilters.offset || 0);

  return (
    <section className="panel wide" id="events">
      <div className="panel-head">
        <h2>事件</h2>
        <div className="toolbar">
          <select value={eventFilters.module} onChange={(event) => updateEventFilters((prev) => ({ ...prev, module: event.target.value, offset: 0 }))}>
            {eventModules.map((item) => <option value={item} key={item || "all"}>{item || "全部模块"}</option>)}
          </select>
          <select value={eventFilters.limit} onChange={(event) => updateEventFilters((prev) => ({ ...prev, limit: Number(event.target.value), offset: 0 }))}>
            {[20, 30, 50, 100].map((item) => <option value={item} key={item}>{item} 条</option>)}
          </select>
          <IconButton icon={RefreshCw} onClick={() => loadEvents(eventFilters)}>刷新</IconButton>
        </div>
      </div>
      <div className="events-toolbar">
        <button disabled={offset <= 0} onClick={() => updateEventFilters((prev) => ({ ...prev, offset: Math.max(0, offset - limit) }))}>上一页</button>
        <span className="muted">offset {offset} · 当前 {rows.length} 条</span>
        <button disabled={!events?.has_more} onClick={() => updateEventFilters((prev) => ({ ...prev, offset: offset + limit }))}>下一页</button>
      </div>
      {rows.length ? (
        <div className="event-table">
          {rows.map((event) => (
            <div className="event-row" key={event.id}>
              <div>
                <b>{event.event_type}</b>
                <span>{event.module} · {event.created_at}</span>
              </div>
              <p>{event.message || "-"}</p>
              <small>{event.video_id || "-"} {event.job_id ? `· job ${event.job_id}` : ""}</small>
            </div>
          ))}
        </div>
      ) : <div className="panel-body muted">暂无事件。</div>}
    </section>
  );
}
