// Run: node WEOS/test_navigation_ui.cjs
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(__dirname+'/website/index.html','utf8');
function source(name){const m=html.match(new RegExp('function '+name+'\\([^]*?\\n}','m'));assert.ok(m,name);return m[0];}
function el(){const classes=new Set();return {inert:false,classList:{contains:c=>classes.has(c),remove:c=>classes.delete(c),toggle(c,on){if(on===undefined)on=!classes.has(c);on?classes.add(c):classes.delete(c);return on;}},setAttribute(k,v){this[k]=v;}};}
const els={side:el(),burger:el()},store=new Map();let loggedIn=true,gst='A';
const ctx=vm.createContext({$:id=>els[id],isCompanyLoggedIn:()=>loggedIn,savedCompanyGst:()=>gst,state:{view:'cart'},window:{scrollY:642},sessionStorage:{setItem:(k,v)=>store.set(k,v),getItem:k=>store.get(k)||null},WEOS_VIEW_KEY:'view',RESUMABLE_VIEWS:['cart','projects','company'],viewPersistenceReady:true,cancelScrollRestore:null});
for(const n of ['saveViewPosition','readViewPosition','closeSideNav','toggleSideNav','restoreSideNav'])vm.runInContext(source(n),ctx);
ctx.saveViewPosition();assert.equal(ctx.readViewPosition().view,'cart');assert.equal(ctx.readViewPosition().scrollY,642);
ctx.state.view='projects';ctx.window.scrollY=25;ctx.saveViewPosition();assert.equal(ctx.readViewPosition().view,'projects');
gst='B';assert.equal(ctx.readViewPosition(),null);gst='A';loggedIn=false;assert.equal(ctx.readViewPosition(),null);
const before=store.get('view');ctx.saveViewPosition();assert.equal(store.get('view'),before);
loggedIn=true;store.set('view','{');assert.equal(ctx.readViewPosition(),null);
ctx.restoreSideNav();assert.equal(els.side.inert,true);assert.equal(els.burger['aria-expanded'],'false');
ctx.toggleSideNav();assert.equal(els.side.classList.contains('open'),true);assert.equal(els.side.inert,false);
ctx.closeSideNav();assert.equal(els.side.classList.contains('open'),false);assert.equal(els.side.inert,true);
assert.ok(source('setView').includes('closeSideNav()'));
assert.ok(html.includes("!side.contains(ev.target)"));
assert.ok(html.includes("setView(resumeView ? resumeView.view"));
console.log('PASS: page/scroll persistence, auth/company isolation, invalid storage, menu open/close, navigation close');
