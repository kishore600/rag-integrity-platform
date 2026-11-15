import{c as m,a0 as p,r as n}from"./index-CqEs4vKY.js";import{u as d}from"./use-debounced-D2-Gjue6.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const b=m("CirclePlay",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polygon",{points:"10 8 16 12 10 16 10 8",key:"1cimsy"}]]);function P(){const[t,c]=p(),a=n.useCallback((o,e={})=>{c(i=>{const u=new URLSearchParams(i);for(const[s,r]of Object.entries(o))r!==void 0&&(r===null||r===""?u.delete(s):u.set(s,r));return u},{replace:e.replace??!0,state:e.state})},[c]);return{params:t,set:a}}function x(t,c=300){const{params:a,set:o}=P(),e=a.get(t)??"",[i,u]=n.useState(e),s=d(i,c),r=n.useRef(e),l=n.useRef(e);l.current=e;const f=n.useRef(o);return f.current=o,n.useEffect(()=>{s!==l.current&&(r.current=s,f.current({[t]:s||null}))},[s,t]),n.useEffect(()=>{e!==r.current&&(r.current=e,u(e))},[e]),{input:i,setInput:u,value:e.trim()}}function C(t,c,a){return c.includes(t)?t:a}export{b as C,x as a,C as o,P as u};
