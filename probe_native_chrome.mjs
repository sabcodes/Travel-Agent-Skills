// Diagnostic only. Fresh Chrome profile, public flights, no Runtime.enable.
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';

const [urlFile, output, mode='unfiltered'] = process.argv.slice(2);
const enableAutomation=process.argv.includes('--enable-automation');
const enableRuntime=process.argv.includes('--enable-runtime');
if (!urlFile || !output) throw new Error('Usage: node probe_native_chrome.mjs URL_FILE OUTPUT_DIR');
if(!['unfiltered','filter-after-cheapest'].includes(mode))throw new Error('Unsupported filter mode');
await mkdir(output, {recursive:true, mode:0o700});
const address = (await readFile(urlFile, 'utf8')).trim();
if (!address.startsWith('https://www.google.com/travel/flights')) throw new Error('Only Google Flights is supported');
const profile = await mkdtemp('/tmp/travel-native-chrome-profile-');
const reservation = net.createServer();
await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
const port = reservation.address().port;
await new Promise(resolve => reservation.close(resolve));
const processHandle = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  [`--user-data-dir=${profile}`, `--remote-debugging-port=${port}`,
   '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check',
   ...(enableAutomation?['--enable-automation']:[]), 'about:blank'],
  {stdio:'ignore'});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const pending = new Map(), entries = new Map(), bodies = new Set(), methods = new Set();
const report = {checked_at:new Date().toISOString(),runtime_enable_sent:false, status:'unavailable', snapshots:[], enable_automation_flag:enableAutomation};
report.filter_mode=mode;
let socket, nextId=0;
function send(method, params={}) {
  methods.add(method);
  return new Promise((resolve,reject) => {
    const id=++nextId;
    const timer=setTimeout(() => {pending.delete(id); reject(new Error('CDP timeout: '+method));}, 10000);
    pending.set(id, {resolve,reject,timer});
    socket.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression) {
  const result=await send('Runtime.evaluate', {expression, returnByValue:true});
  if (result.exceptionDetails) throw new Error('Page expression failed');
  return result.result.value;
}
const stateExpression=`(() => ({body:document.body?.innerText || '',
  events:window.__priceEvents || [],
  labels:[...document.querySelectorAll('li [role=link][aria-label]')].map(e=>e.getAttribute('aria-label')),
  tabs:[...document.querySelectorAll('[role=tab]')].map(e=>({label:e.innerText,selected:e.getAttribute('aria-selected')}))}))()`;
async function settled(stage) {
  const end=Date.now()+25000;
  let state;
  do {
    state=await evaluate(stateExpression);
    if (/Oops, something went wrong|unusual traffic|not a robot/.test(state.body)) throw new Error('Google error at '+stage);
    if (/departing flights/i.test(state.body) && /(?:\d+ results returned|No results returned)/.test(state.body)) break;
    await delay(250);
  } while(Date.now()<end);
  if (!/departing flights/i.test(state.body)) throw new Error('Results did not load at '+stage);
  report.snapshots.push({stage,...state});
}
async function click(role, pattern, optional=false) {
  const box=await evaluate(`(() => {
    const name=e=>e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(' ').map(id=>document.getElementById(id)?.innerText || '').join(' ').trim() || [...(e.labels || [])].map(n=>n.innerText).join(' ').trim() || e.innerText;
    const e=[...document.querySelectorAll('[role=${role}]${role==='button'?',button':role==='checkbox'?',input[type=checkbox]':''}')].find(e=>new RegExp(${JSON.stringify(pattern)}).test(name(e)) && !e.closest('[aria-hidden=true]'));
    if(!e)return null;
    e.scrollIntoView({block:'center'});
    e.click();
    const r=e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};
  })()`);
  if(!box){if(optional)return false;throw new Error('Missing control: '+pattern);}
  return true;
}
try {
  let target;
  for(let attempt=0;attempt<50;attempt++) {
    try {const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();target=list.find(t=>t.type==='page');if(target)break;} catch{}
    await delay(200);
  }
  if(!target)throw new Error('Chrome startup timeout');
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  socket.addEventListener('message',event=>{
    const m=JSON.parse(event.data);
    if(m.id){const p=pending.get(m.id);if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);}return;}
    const p=m.params;
    if(m.method==='Network.requestWillBeSent')entries.set(p.requestId,{startedDateTime:new Date(p.wallTime*1000).toISOString(),time:0,
      request:{method:p.request.method,url:p.request.url,headers:Object.entries(p.request.headers).map(([name,value])=>({name,value})),
        postData:p.request.postData?{text:p.request.postData,mimeType:'application/x-www-form-urlencoded'}:undefined},response:{status:0,content:{}}});
    if(m.method==='Network.responseReceived'){
      const e=entries.get(p.requestId);if(e)e.response={status:p.response.status,httpVersion:p.response.protocol,
        headers:Object.entries(p.response.headers).map(([name,value])=>({name,value})),content:{mimeType:p.response.mimeType}};
    }
    if(m.method==='Network.loadingFinished'){
      const e=entries.get(p.requestId);if(!e)return;
      const job=send('Network.getResponseBody',{requestId:p.requestId}).then(r=>{e.response.content.text=r.body;if(r.base64Encoded)e.response.content.encoding='base64';}).catch(()=>{});
      bodies.add(job);job.finally(()=>bodies.delete(job));
    }
  });
  await send('Network.enable');
  await send('Page.enable');
  if(enableRuntime)await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`window.__priceEvents=[];let previous='';new MutationObserver(()=>{const rows=[...document.querySelectorAll('li')].filter(e=>e.innerText.includes('Singapore Airlines')).map(e=>e.innerText);const key=JSON.stringify(rows);if(rows.length&&key!==previous&&window.__priceEvents.length<1000){previous=key;window.__priceEvents.push({ms:performance.now(),rows});}}).observe(document,{subtree:true,childList:true,characterData:true});`});
  report.environment=await evaluate('({webdriver:navigator.webdriver,languages:navigator.languages})');
  await send('Page.navigate',{url:address});
  await settled('best');
  await click('tab','Cheapest');
  await delay(1000);
  await settled('cheapest');
  if(await click('button','^View more flights$',true))await settled('expanded_cheapest');
  if(mode==='filter-after-cheapest') {
    await click('button','^Airlines(?:,|$)');
    await delay(400);
    const selected=await evaluate("document.querySelector('[role=switch][aria-label=\"Select all airlines\"]')?.getAttribute('aria-checked')");
    if(selected==='true')await click('switch','^Select all airlines$');
    await delay(400);
    await evaluate(`(() => {
      const input=[...document.querySelectorAll('input[type=checkbox]')].find(e=>(e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(' ').map(id=>document.getElementById(id)?.innerText || '').join(' ').trim() || [...(e.labels || [])].map(n=>n.innerText).join(' ').trim()).startsWith('Singapore Airlines'));
      if(!input)throw new Error('Singapore checkbox missing');
      if(!input.checked)input.click();
    })()`);
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    await delay(1500);
    await settled('filtered_cheapest');
  }
  await delay(30000);
  report.snapshots.push({stage:'final',...await evaluate(stateExpression)});
  await evaluate('window.scrollTo(0,0)');
  const image=await send('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(output,'final.png'),Buffer.from(image.data,'base64'));
  report.status='complete_requires_price_verification';
} catch(error) {report.error=error.message;}
finally {
  if(socket?.readyState===WebSocket.OPEN){try{
    report.final_state=await evaluate(stateExpression);
    report.control_inventory=await evaluate("[...document.querySelectorAll('[role=checkbox],[role=switch]')].map(e=>({role:e.getAttribute('role'),label:e.getAttribute('aria-label'),labelled_by:e.getAttribute('aria-labelledby'),text:e.innerText,checked:e.getAttribute('aria-checked')}))");
  }catch{}await Promise.race([Promise.allSettled([...bodies]),delay(10000)]);socket.close();}
  for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('Probe closing'));}
  await writeFile(path.join(output,'browser.har'),JSON.stringify({log:{version:'1.2',creator:{name:'Native Chrome CDP probe',version:'1'},entries:[...entries.values()]}},null,2));
  report.runtime_enable_sent=methods.has('Runtime.enable');
  report.cdp_methods=[...methods].sort();
  await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  processHandle.kill('SIGTERM');
  await Promise.race([new Promise(resolve=>processHandle.once('exit',resolve)),delay(3000)]);
  if(processHandle.exitCode===null)processHandle.kill('SIGKILL');
  await rm(profile,{recursive:true,force:true});
  if(report.status==='unavailable')process.exitCode=1;
  console.log(JSON.stringify({status:report.status,error:report.error,environment:report.environment,runtime_enable_sent:report.runtime_enable_sent,snapshots:report.snapshots.map(s=>s.stage)}));
}
