import{c as m,V as p,r as s}from"./index-CICn-e3A.js";import{u as d}from"./use-debounced-BcHw_09k.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const S=m("CirclePlay",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polygon",{points:"10 8 16 12 10 16 10 8",key:"1cimsy"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k=m("SearchX",[["path",{d:"m13.5 8.5-5 5",key:"1cs55j"}],["path",{d:"m8.5 8.5 5 5",key:"a8mexj"}],["circle",{cx:"11",cy:"11",r:"8",key:"4ej97u"}],["path",{d:"m21 21-4.3-4.3",key:"1qie3q"}]]);function y(){const[t,n]=p(),u=s.useCallback((o,e={})=>{n(i=>{const a=new URLSearchParams(i);for(const[c,r]of Object.entries(o))r!==void 0&&(r===null||r===""?a.delete(c):a.set(c,r));return a},{replace:e.replace??!0,state:e.state})},[n]);return{params:t,set:u}}function x(t,n=300){const{params:u,set:o}=y(),e=u.get(t)??"",[i,a]=s.useState(e),c=d(i,n),r=s.useRef(e),l=s.useRef(e);l.current=e;const f=s.useRef(o);return f.current=o,s.useEffect(()=>{c!==l.current&&(r.current=c,f.current({[t]:c||null}))},[c,t]),s.useEffect(()=>{e!==r.current&&(r.current=e,a(e))},[e]),{input:i,setInput:a,value:e.trim()}}function R(t,n,u){return n.includes(t)?t:u}export{S as C,k as S,x as a,R as o,y as u};
