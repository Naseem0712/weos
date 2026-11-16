// Run: node WEOS/test_login_ui.cjs
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(__dirname + '/website/index.html', 'utf8');
for (const [, script] of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script);
function source(name) {
  const match = html.match(new RegExp('(?:async )?function ' + name + '\\([^]*?\\n}', 'm'));
  assert.ok(match, name);
  return match[0];
}
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {value:'old customer',textContent:'old project',hidden:false,title:'old project',dataset:{},style:{},classList:{add(){},remove(){}},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}});
  return elements.get(id);
};
function storage(){const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};}
let loggedIn=false;
const state={workspaceRestored:false,projectId:null,lines:[]};
const ctx=vm.createContext({state,$,isCompanyLoggedIn:()=>loggedIn,savedCompanyGst:()=> 'COMPANY_A',sessionStorage:storage(),localStorage:storage(),WEOS_CART_KEY:'weos.cart.v1',WEOS_GST_KEY:'gst',WEOS_SESSION_KEY:'session',clearTimeout,hydrateCartLines:x=>x,adoptCartQuoteGroups(){},isPlaceholderProjectName:x=>!x,console});
for(const name of ['restoreCartSession','persistCartSession','projectDisplayName','refreshSetupSummary','updatePdfLinks','wipeLoggedOutUi','pingEngine'])vm.runInContext(source(name),ctx);
const pack={companyGst:'COMPANY_A',projectId:'P1',name:'Private project',customer:'Private customer',lines:[{lineId:'1'}]};
ctx.sessionStorage.setItem('weos.cart.v1',JSON.stringify(pack));
assert.equal(ctx.restoreCartSession(),false);
assert.equal(state.projectId,null);
assert.equal(ctx.projectDisplayName(),'');
ctx.updatePdfLinks();assert.equal($('projPill').hidden,true);assert.equal($('projPill').textContent,'');
loggedIn=true;
assert.equal(ctx.restoreCartSession(),true);assert.equal(state.projectId,'P1');
state.projectId=null;ctx.sessionStorage.setItem('weos.cart.v1',JSON.stringify({...pack,companyGst:'COMPANY_B'}));
assert.equal(ctx.restoreCartSession(),false);assert.equal(state.projectId,null);
ctx.sessionStorage.setItem('weos.cart.v1',JSON.stringify({...pack,companyGst:undefined}));
assert.equal(ctx.restoreCartSession(),false); // Unowned legacy caches must not cross accounts.
loggedIn=false;state.projectId='P1';state.lines=[{lineId:'1'}];
ctx.wipeLoggedOutUi();assert.equal(state.projectId,null);assert.equal(state.lines.length,0);
for(const id of ['cartName','cartCustomer','projCustName','projMobile'])assert.equal($(id).value,'');
assert.equal($('projPill').hidden,true);assert.equal(ctx.sessionStorage.getItem('weos.cart.v1'),null);
(async()=>{
 ctx.api=async()=>({status:'ok'});const pending=ctx.pingEngine();assert.equal($('enginePill').style.background,'#eab308');await pending;assert.equal($('enginePill').style.background,'#166534');
 ctx.api=async()=>{throw Error('offline')};await ctx.pingEngine();assert.equal($('enginePill').style.background,'#b91c1c');
 assert.equal($('enginePill').textContent,'');
 const init=html.slice(html.indexOf('(async function init(){'));
 assert.ok(init.indexOf('await restoreCompanyWorkspace()')<init.indexOf('restoreCartSession()'));
 console.log('PASS: script syntax, logged-out privacy, company cache isolation, logout clearing, connection states, startup order');
})().catch(e=>{console.error(e);process.exitCode=1;});
