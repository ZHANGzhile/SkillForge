// Local read-only browser QA using Node's native CDP transport; no dependencies.
import {spawn} from 'node:child_process';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';

const root = process.cwd();
const output = path.resolve(root, process.argv[2] || 'results/skill-evolution/v1.2/development/p5-preview-20261012');
await mkdir(output, {recursive:true});
const port = await new Promise(resolve => {const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p))})});
const browser=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  ['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
   `--remote-debugging-port=${port}`,`--user-data-dir=${path.join(root,'.runtime',`p5-preview-cdp-${Date.now()}`)}`,'about:blank'],
  {windowsHide:true,stdio:'ignore'});
let ws;
try {
  let targets;
  for(let i=0;i<100;i++) {try {targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(targets.some(t=>t.type==='page'))break}catch{}await new Promise(r=>setTimeout(r,100))}
  const target=targets.find(t=>t.type==='page');
  ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
  const waiting=new Map();let serial=0;
  ws.onmessage=e=>{const v=JSON.parse(e.data);if(v.id&&waiting.has(v.id)){const {resolve,reject,timer}=waiting.get(v.id);clearTimeout(timer);waiting.delete(v.id);v.error?reject(Error(JSON.stringify(v.error))):resolve(v.result)}};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;const timer=setTimeout(()=>reject(Error('CDP timeout '+method)),15000);waiting.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}))});
  const metrics=[];
  for(const [label,width,height] of [['desktop',1440,1500],['mobile',430,1800]]) {
    await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:label==='mobile'});
    await call('Page.navigate',{url:'http://127.0.0.1:8093/skill-evolution'});
    let result;
    for(let i=0;i<100;i++) {result=await call('Runtime.evaluate',{expression:'document.getElementById("testCount")?.textContent',returnByValue:true});if(result.result.value==='54 / 54')break;await new Promise(r=>setTimeout(r,100))}
    const actual=await call('Runtime.evaluate',{expression:`JSON.stringify({width:innerWidth,documentWidth:document.documentElement.scrollWidth,status:document.getElementById('status').textContent,test:document.getElementById('testCount').textContent,overflow:[...document.querySelectorAll('main > *, .card, .round')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>e.className||e.tagName)})`,returnByValue:true});
    const record={viewport:label,...JSON.parse(actual.result.value)};
    if(record.documentWidth>width||record.overflow.length||record.status!=='独立审计通过')throw Error('Preview QA failed '+JSON.stringify(record));
    metrics.push(record);
    const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,fromSurface:true});
    await writeFile(path.join(output,`evolution-trace-verified-${label}.png`),Buffer.from(shot.data,'base64'));
    const formal=await call('Runtime.evaluate',{expression:'document.getElementById("formalState")?.textContent',returnByValue:true});
    if(formal.result.value && /RUNNING|AUDITED|COMPLETE|FAILED/.test(formal.result.value)) {
      record.formalStatus=formal.result.value;
      await call('Runtime.evaluate',{expression:'document.getElementById("formalState").parentElement.scrollIntoView({block:"start"})'});
      const section=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,fromSurface:true});
      await writeFile(path.join(output,`boundary-formal-verified-${label}.png`),Buffer.from(section.data,'base64'));
    }
  }
  await writeFile(path.join(output,'browser-qa.json'),JSON.stringify({passed:true,metrics,new_model_calls:0,new_tokens:0},null,2)+'\n');
  console.log(JSON.stringify({passed:true,metrics}));
  await call('Browser.close');
} finally {if(ws)ws.close();if(browser.exitCode===null)browser.kill();}
