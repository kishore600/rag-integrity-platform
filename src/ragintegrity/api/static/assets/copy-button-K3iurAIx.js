import{c as n,r as p,j as t,B as u,K as s}from"./index-Dur4hh6T.js";import{C as y}from"./check-Mgf_O4Gi.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const d=n("Copy",[["rect",{width:"14",height:"14",x:"8",y:"8",rx:"2",ry:"2",key:"17jyea"}],["path",{d:"M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2",key:"zix9uf"}]]);function h({text:c,label:e="Copy",size:r="sm"}){const[o,a]=p.useState(!1);async function i(){try{await navigator.clipboard.writeText(c),a(!0),s.success("Copied to clipboard"),window.setTimeout(()=>a(!1),1500)}catch{s.error("Couldn't copy. Select the text and copy it manually.")}}return t.jsxs(u,{variant:"secondary",size:r,onClick:i,"aria-label":e,children:[o?t.jsx(y,{className:"h-3.5 w-3.5 text-success"}):t.jsx(d,{className:"h-3.5 w-3.5"}),o?"Copied":e]})}export{h as C};
