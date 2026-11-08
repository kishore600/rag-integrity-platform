import{c as i,O as p,r as s}from"./index-Dur4hh6T.js";import{u as d}from"./use-debounced-DqEbICB2.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const P=i("CirclePlay",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polygon",{points:"10 8 16 12 10 16 10 8",key:"1cimsy"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const S=i("SearchX",[["path",{d:"m13.5 8.5-5 5",key:"1cs55j"}],["path",{d:"m8.5 8.5 5 5",key:"a8mexj"}],["circle",{cx:"11",cy:"11",r:"8",key:"4ej97u"}],["path",{d:"m21 21-4.3-4.3",key:"1qie3q"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const b=i("Wrench",[["path",{d:"M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z",key:"cbrjhi"}]]);function y(){const[t,a]=p(),u=s.useCallback((o,e={})=>{a(l=>{const n=new URLSearchParams(l);for(const[c,r]of Object.entries(o))r!==void 0&&(r===null||r===""?n.delete(c):n.set(c,r));return n},{replace:e.replace??!0,state:e.state})},[a]);return{params:t,set:u}}function x(t,a=300){const{params:u,set:o}=y(),e=u.get(t)??"",[l,n]=s.useState(e),c=d(l,a),r=s.useRef(e),f=s.useRef(e);f.current=e;const m=s.useRef(o);return m.current=o,s.useEffect(()=>{c!==f.current&&(r.current=c,m.current({[t]:c||null}))},[c,t]),s.useEffect(()=>{e!==r.current&&(r.current=e,n(e))},[e]),{input:l,setInput:n,value:e.trim()}}function R(t,a,u){return a.includes(t)?t:u}export{P as C,S,b as W,x as a,R as o,y as u};
