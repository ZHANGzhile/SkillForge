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
    const progress=card('边界学习对照进度');
    await progress.getByText(/状态：/).waitFor();
    const gate=card('固定程序的边界判断对照');
    await gate.locator('table').waitFor();
    const rows=await gate.locator('table tr').allTextContents();
    if(rows.length!==5||!rows[1].includes('25.00%'))throw Error('Wrong Gate table');
    const data=JSON.parse(fs.readFileSync('results/boundary-study/v1/report.json','utf8'));
    if(data.system_complete){
      await progress.getByText('状态：completed · '+data.actual_runs+' / '+data.actual_runs,{exact:true}).waitFor();
      const system=card('边界学习系统与拦截点反事实');
      await system.locator('table').first().waitFor();
      if(await system.locator('table').count()!==3)throw Error('Missing full system/cost/counterfactual tables');
      const cells=await system.locator('table').first().locator('tr').allTextContents();
      if(cells.length!==5)throw Error('Missing ABCD system rows');
    }else if(await card('边界学习系统与拦截点反事实').locator('table').count())throw Error('Partial scores displayed');
    await page.screenshot({path:'docs/assets/boundary-study-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
    await page.screenshot({path:'docs/assets/boundary-study-mobile.png',fullPage:true});
    if(errors.length)throw Error(JSON.stringify(errors));
    const receipt={passed:true,at:new Date().toISOString(),system_complete:data.system_complete,gate_rows:4,model_scores_complete_only:true,mobile_overflow:false,page_errors:errors,scope:'Actual browser presentation check; independent experiment audit supplies results'};
    fs.writeFileSync('results/workbench-acceptance/boundary-study-ui.json',JSON.stringify(receipt,null,2));
    console.log(JSON.stringify(receipt));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
