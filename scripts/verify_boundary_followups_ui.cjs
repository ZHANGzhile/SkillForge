const {chromium}=require(process.env.SKILLFORGE_PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.SKILLFORGE_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8080');
    await page.locator('nav button[data-view="reports"]').click();
    const card=title=>page.locator('#reportCards .report').filter({has:page.getByRole('heading',{name:title,exact:true})});
    await card('退款边界表达对照进度').getByText('状态：completed · 128 / 128',{exact:true}).waitFor();
    const checked=[];
    for(const [name,title] of [['boundary-representation','退款边界表达对照结果'],['boundary-adaptation','新规则下的有限边界适应']]){
      const report=card(title),expected=JSON.parse(fs.readFileSync(`results/${name}/v1/workbench.json`,'utf8'));
      await report.locator('table').first().waitFor();
      if(await report.locator('table').count()!==expected.boundary_tables.length)throw Error('Missing tables: '+name);
      for(let i=0;i<expected.boundary_tables.length;i++){
        const actual=await report.locator('table').nth(i).locator('tr').evaluateAll(rows=>rows.map(r=>[...r.cells].map(c=>c.textContent)));
        const table=expected.boundary_tables[i],wanted=[table.headers,...table.rows].map(r=>r.map(String));
        if(JSON.stringify(actual)!==JSON.stringify(wanted))throw Error('Rendered evidence differs: '+name);
      }
      await page.setViewportSize({width:1440,height:1000});
      await report.screenshot({path:`docs/assets/${name}-desktop.png`});
      await page.setViewportSize({width:390,height:844});
      if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
      await report.screenshot({path:`docs/assets/${name}-mobile.png`});
      checked.push({name,matched_tables:expected.boundary_tables.length});
    }
    if(errors.length)throw Error(JSON.stringify(errors));
    const receipt={passed:true,at:new Date().toISOString(),checked,mobile_overflow:false,page_errors:errors};
    fs.writeFileSync('results/workbench-acceptance/boundary-followups-ui.json',JSON.stringify(receipt,null,2));
    console.log(JSON.stringify(receipt));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
