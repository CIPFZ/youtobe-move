import{s as f,f as y,j as e,B as b,r as g}from"./index-B-sEHwBE.js";import{c}from"./createLucideIcon-Jc7ij8gG.js";import{H as N}from"./hard-drive-XtKbnWfO.js";/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const C=c("CircleCheck",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m9 12 2 2 4-4",key:"dzmm74"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const $=c("CirclePause",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["line",{x1:"10",x2:"10",y1:"15",y2:"9",key:"c1nkhi"}],["line",{x1:"14",x2:"14",y1:"15",y2:"9",key:"h65svq"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const z=c("CirclePlay",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polygon",{points:"10 8 16 12 10 16 10 8",key:"1cimsy"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const A=c("Clock",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polyline",{points:"12 6 12 12 16 14",key:"68esgv"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const B=c("Database",[["ellipse",{cx:"12",cy:"5",rx:"9",ry:"3",key:"msslwz"}],["path",{d:"M3 5V19A9 3 0 0 0 21 19V5",key:"1wlel7"}],["path",{d:"M3 12A9 3 0 0 0 21 12",key:"mv7ke4"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const P=c("TriangleAlert",[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]]);function D({state:o,actions:d}){var p,u;const{status:s,storage:i}=o,{selectVideo:j,applyQueuePreset:_}=d,n=f(s==null?void 0:s.videos_by_status),t=(s==null?void 0:s.job_lock_status)||{},a=(s==null?void 0:s.settings)||{},r=(s==null?void 0:s.failed_videos)||[],v=(s==null?void 0:s.recent_events)||[],h=!!a.worker_enable_publish,x=!!a.worker_publish_dry_run,m=[i!=null&&i.over_max?"超过最大占用":"",i!=null&&i.over_warn?"超过警戒线":"",i!=null&&i.below_min_free?"磁盘剩余空间不足":""].filter(Boolean),k=[{label:"自动发布",value:h?x?"dry-run":"enabled":"disabled",icon:h?z:$,tone:h&&!x?"ok":"warn",sub:`mode ${a.publish_mode||"-"}`},{label:"活跃队列",value:(s==null?void 0:s.active_queue_count)||0,icon:A,tone:((s==null?void 0:s.active_queue_count)||0)>0?"ok":"",sub:`selected ${n.selected||0} / downloaded ${n.downloaded||0}`},{label:"待发布",value:n.ready_to_publish||0,icon:C,tone:(n.ready_to_publish||0)>0?"ok":"",sub:`published ${n.published||0}`},{label:"任务运行",value:t.running||0,icon:B,tone:(t.running||0)>0?"ok":"",sub:`locked ${t.locked||0}`},{label:"下载目录",value:i?y(i.total_size_bytes):"-",icon:N,tone:m.length?"warn":"",sub:i?`free ${y(i.disk_free_bytes)}`:"loading"},{label:"失败视频",value:n.failed||0,icon:P,tone:(n.failed||0)>0?"danger":"",sub:((p=r[0])==null?void 0:p.title)||((u=r[0])==null?void 0:u.video_id)||"no recent failures"}];return e.jsxs("section",{className:"panel wide overview-panel",id:"overview",children:[e.jsxs("div",{className:"panel-head",children:[e.jsx("h2",{children:"总览"}),e.jsxs("div",{className:"muted",children:["发布窗口 ",a.publish_window_start||"-"," - ",a.publish_window_end||"-"," · 每日上限 ",a.publish_daily_limit??"-"]})]}),e.jsx("div",{className:"overview-grid",children:k.map(l=>{const w=l.icon;return e.jsxs("div",{className:`overview-card ${l.tone}`,children:[e.jsx("div",{className:"overview-icon",children:e.jsx(w,{size:18})}),e.jsxs("div",{children:[e.jsx("span",{children:l.label}),e.jsx("b",{children:l.value}),e.jsx("small",{children:l.sub})]})]},l.label)})}),m.length?e.jsx("div",{className:"overview-alerts",children:m.map(l=>e.jsx("span",{className:"badge failed",children:l},l))}):null,e.jsxs("div",{className:"overview-lanes",children:[e.jsxs("div",{className:"overview-lane",children:[e.jsxs("div",{className:"overview-lane-head",children:[e.jsx("h3",{children:"最近失败"}),r.length?e.jsx(b,{size:"small",onClick:()=>_("failed"),children:"查看失败队列"}):null]}),r.length?e.jsx("div",{className:"overview-failures",children:r.slice(0,5).map(l=>e.jsxs(b,{type:"text",className:"overview-failure",onClick:()=>j(l.video_id),children:[e.jsx("span",{children:l.title||l.video_id}),e.jsxs("small",{children:[l.video_id," · ",l.last_error||"无错误详情"]})]},l.video_id))}):e.jsx("div",{className:"overview-empty",children:"暂无失败视频。"})]}),e.jsxs("div",{className:"overview-lane",children:[e.jsxs("div",{className:"overview-lane-head",children:[e.jsx("h3",{children:"最近事件"}),e.jsxs("span",{className:"muted",children:["最新 ",v.length," 条"]})]}),v.length?e.jsx("div",{className:"overview-events",children:v.slice(0,6).map(l=>e.jsxs("div",{className:"overview-event",children:[e.jsxs("div",{children:[e.jsx("b",{children:l.event_type}),e.jsx("span",{children:l.module})]}),e.jsx("small",{children:l.created_at}),e.jsx("p",{children:l.message})]},l.id))}):e.jsx("div",{className:"overview-empty",children:"暂无事件。"})]})]})]})}function V({state:o,actions:d}){return g.useEffect(()=>{d.loadDashboard()},[]),e.jsx("div",{className:"page-stack",children:e.jsx(D,{state:o,actions:d})})}export{V as DashboardPage};
