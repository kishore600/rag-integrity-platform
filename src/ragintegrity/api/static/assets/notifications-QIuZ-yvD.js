import{c as d,b0 as c,b1 as l,j as e,A as h,P as m,b2 as f,C as o,E as u,b3 as x,S as p}from"./index-DEb5k7Lu.js";import{a as k}from"./page-C7lS7tCS.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const j=d("BellOff",[["path",{d:"M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5",key:"o7mx20"}],["path",{d:"M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7",key:"16f1lm"}],["path",{d:"M10.3 21a1.94 1.94 0 0 0 3.4 0",key:"qgo35s"}],["path",{d:"m2 2 20 20",key:"1ooewy"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const y=d("CheckCheck",[["path",{d:"M18 6 7 17l-5-5",key:"116fxf"}],["path",{d:"m22 10-7.5 7.5L13 16",key:"ke71qq"}]]);function b(){var s;const a=c(100),t=l(),r=((s=a.data)==null?void 0:s.unread)??0;return e.jsxs(e.Fragment,{children:[e.jsx(k,{title:"Notifications",description:"What each audit found, and the next step. The same message is emailed after an audit when email is on.",actions:e.jsxs("div",{className:"flex items-center gap-2",children:[e.jsx(h,{variant:"secondary",to:"/alerts",children:"Alert settings"}),e.jsxs(m,{variant:"secondary",disabled:r===0,loading:t.isPending,onClick:()=>t.mutate(),children:[e.jsx(y,{className:"h-4 w-4","aria-hidden":!0})," Mark all read"]})]})}),e.jsx(f,{query:a,skeleton:e.jsx(p,{className:"h-64"}),children:i=>i.items.length===0?e.jsx(o,{children:e.jsx(u,{icon:j,title:"No notifications yet",description:"After an audit finishes, what it found and what to do about it appears here."})}):e.jsx(o,{children:e.jsx("ul",{className:"divide-y divide-line","aria-label":"Notifications",children:i.items.map(n=>e.jsx(x,{n},n.id))})})})]})}export{b as default};
