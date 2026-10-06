// Local headless browser QA. Separate temporary profile, no GPU or experiment writes.
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';

const base = process.cwd();
const out = path.join(base, 'results/active-evolution/v1.1/development/workbench-qa-AB-final');
const profile = await fs.mkdtemp(path.join(base, '.runtime/execution-page-qa-'));
await fs.mkdir(out, {recursive:true});
const browser = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless', '--disable-gpu', '--disable-background-networking', '--disable-component-update',
  '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
  '--user-data-dir='+profile, 'about:blank'
], {windowsHide:true, stdio:'ignore'});
const delay = ms=>new Promise(resolve=>setTimeout(resolve,ms));
const deadline = Date.now()+45000;
const watchdog = setTimeout(()=>browser.kill(), 47000);
let socket;
try {
  let port;
  while(!port && Date.now()<deadline) {
    try {port=Number((await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0])} catch {}
    if(!port) await delay(100);
  }
  if(!port) throw Error('Headless browser startup timed out');
  const tabs = await (await fetch('http://127.0.0.1:'+port+'/json')).json();
  socket = new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),errors=[];
  socket.onmessage = event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}else if(m.method==='Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1200,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:'http://127.0.0.1:8091'});
  while(Date.now()<deadline && !(await evaluate("document.querySelectorAll('#groups tr').length === 11"))) await delay(100);
  const initial=await evaluate("({groups:document.querySelectorAll('#groups tr').length,tasks:document.querySelectorAll('#tasks tr').length,error:document.getElementById('error').textContent,body:document.body.scrollWidth,width:innerWidth})");
  if(initial.groups!==11 || !initial.tasks || initial.error || initial.body>initial.width)throw Error(JSON.stringify(initial));
  await fs.writeFile(path.join(out,'desktop.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate("document.querySelector('#runtimeSelect').value='new';document.querySelector('#runtimeSelect').dispatchEvent(new Event('change'));document.querySelector('#modeSelect').value='full';document.querySelector('#modeSelect').dispatchEvent(new Event('change'));document.querySelector('#tasks button').click()");
  while(Date.now()<deadline && !(await evaluate("!document.getElementById('trace').hidden"))) await delay(100);
  const trace=await evaluate("({visible:!document.getElementById('trace').hidden,receipts:document.getElementById('receipts').textContent,actions:document.getElementById('actions').textContent,error:document.getElementById('error').textContent})");
  if(!trace.visible || !trace.actions || trace.error)throw Error(JSON.stringify(trace));
  await evaluate("document.getElementById('trace').scrollIntoView({behavior:'instant',block:'start'})");
  await delay(200);
  await fs.writeFile(path.join(out,'trace.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  while(Date.now()<deadline && !(await evaluate("document.querySelectorAll('#bRunSelect option').length > 0 && document.querySelectorAll('#regressionLinks button').length > 0"))) await delay(100);
  const retention = await evaluate("document.getElementById('retentionVerdict').textContent");
  if(!retention.includes('未通过'))throw Error('Missing continual retention limitation');
  await evaluate("document.querySelector('#regressionLinks button').click()");
  while(Date.now()<deadline && !(await evaluate("document.getElementById('actions').textContent.includes('escalate')"))) await delay(100);
  const regression = await evaluate("document.getElementById('actions').textContent.includes('escalate')");
  if(!regression)throw Error('Regression trace did not open');
  await evaluate("const options=[...document.getElementById('bRunSelect').options];const chosen=options.find(o=>JSON.parse(o.value)[2]!=='no_adapt')||options[0];document.getElementById('bRunSelect').value=chosen.value;document.getElementById('bTraceButton').click()");
  while(Date.now()<deadline && !(await evaluate("!document.getElementById('bTrace').hidden"))) await delay(100);
  const acquisition = await evaluate("({status:document.getElementById('bStatus').textContent,trace:!document.getElementById('bTrace').hidden,body:document.getElementById('bTrace').textContent,error:document.getElementById('error').textContent})");
  if(!acquisition.trace || !acquisition.body.includes('queries') || acquisition.error)throw Error('B trace failed: '+JSON.stringify(acquisition));
  await evaluate("document.getElementById('acquisition').scrollIntoView({behavior:'instant',block:'start'})");
  await delay(200);
  await fs.writeFile(path.join(out,'acquisition.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate('scrollTo(0,0)');await delay(200);
  const mobile=await evaluate('({body:document.body.scrollWidth,width:innerWidth})');
  if(mobile.body>mobile.width)throw Error('Mobile page overflows: '+JSON.stringify(mobile));
  await fs.writeFile(path.join(out,'mobile.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  if(errors.length)throw Error(JSON.stringify(errors));
  const report={passed:true,initial,mobile,trace_opened:trace.visible,receipt_visible:trace.receipts.includes('receipt_id'),retention,regression_trace_opened:regression,b_status:acquisition.status,b_trace_opened:acquisition.trace,console_errors:errors,profile,scope:'local read-only page, isolated Chrome profile, GPU disabled'};
  await fs.writeFile(path.join(out,'browser.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
  await send('Browser.close').catch(()=>{});
} finally {
  clearTimeout(watchdog);socket?.close();browser.kill();
}
