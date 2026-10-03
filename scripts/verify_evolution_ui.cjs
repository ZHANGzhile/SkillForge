// Read-only browser acceptance; no task submission or model calls.
const fs = require('fs');
const path = require('path');
const {chromium} = require(process.env.SKILLFORGE_PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[2] || 'http://127.0.0.1:8081';
const output = process.argv[3] || 'results/active-evolution/v1/development/ui-preview-v1';
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, executablePath:process.env.SKILLFORGE_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page = await browser.newPage({viewport:{width:1440,height:1100}});
  const errors = [];
  page.on('pageerror', e=>errors.push(e.message));
  const check = (truth, message)=>{if(!truth)throw Error(message)};
  async function visit(run){
    await page.goto(base+'/evolution?run='+encodeURIComponent(run));
    await page.waitForFunction(key=>document.getElementById('loadState').textContent.includes('正在查看 '+key),run);
    check(await page.locator('#error').isHidden(), 'Visible evidence loading error');
  }
  try {
    if (new URL(base).port === '8080') {
      await page.goto(base+'/');
      await page.locator('#evolutionLink').click();
      await page.waitForFunction(()=>document.getElementById('loadState').textContent.includes('正在查看'));
      const index = await (await page.request.get(base+'/api/evolution/index')).json();
      check(index.model_complete && index.delivery_audit?.passed, 'Formal delivery evidence is incomplete');
      check(index.delivery.proposals.length===4 && index.delivery.proposals.every(r=>!r.agent_admitted), 'Rejected Agent proposals are missing');
    }
    await visit('cpu/W3/101/active');
    check((await page.locator('#cpuCount').textContent())==='120 / 120','Incomplete CPU matrix');
    check((await page.locator('#researchNotice').textContent()).includes('未通过'),'Failed research gate hidden');
    await page.locator('[data-step="7"]').click();
    check((await page.locator('#stepTitle').textContent())==='Probe 08','Query navigation did not change step');
    check((await page.locator('#publication').textContent()).includes('已发布'),'Published boundary missing');
    check((await page.locator('#observations dd').count())>0,'Observation values missing');
    await page.screenshot({path:path.join(output,'trace-desktop.png'),fullPage:true});
    await visit('cpu/W5/401/active');
    check((await page.locator('#publicationNote').textContent()).includes('不是验收通过'),'H0 false convergence hidden');
    await page.reload();
    await page.waitForFunction(()=>document.getElementById('loadState').textContent.includes('cpu/W5/401/active'));
    check((await page.locator('#seed').inputValue())==='401','Reload lost selected run');
    await page.screenshot({path:path.join(output,'negative-result.png'),fullPage:true});
    await visit('cpu/W1/101/no_adapt');
    check(await page.locator('#stepRange').isDisabled(),'No Adaptation shows exploration');
    await visit('cpu/W6/101/active');
    check((await page.locator('#runStatus').textContent())==='INCONCLUSIVE','Non-converged result changed');
    await page.locator('[data-tab="lineage"]').click();
    check((await page.locator('#lineageCards').textContent()).includes('Epoch 2'),'Second epoch not represented');
    await page.locator('[data-tab="results"]').click();
    check((await page.locator('#cpuRows tr').count())===4,'Methods omitted');
    if (new URL(base).port === '8080') {
      check((await page.locator('#modelCount').textContent())==='20 / 20','Model matrix incomplete');
      check((await page.locator('#agentResults').textContent()).includes('正常任务退步'),'Proposal rejection explanation missing');
    }
    await page.screenshot({path:path.join(output,'results-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    for (const tab of ['trace','lineage','results']) {
      await page.locator('[data-tab="'+tab+'"]').click();
      check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow: '+tab);
      await page.screenshot({path:path.join(output,tab+'-mobile.png'),fullPage:true});
    }
    check(!errors.length,JSON.stringify(errors));
    const report={passed:true,at:new Date().toISOString(),base,desktop:true,mobile:true,read_only:true,
      checks:['successful trace','H0 false convergence','unchanged baseline','inconclusive trace','query navigation','reload selection','lineage','all methods','no mobile overflow'],page_errors:errors};
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report));
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
