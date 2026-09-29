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
    await card('动作级反事实进度').getByText('状态：completed · 30 / 30',{exact:true}).waitFor();
    const report=card('Skill与primitive的动作反事实');
    await report.locator('table').waitFor();
    for(const arm of ['skill','primitive']){
      const row=report.locator('tr').filter({has:page.getByText(arm,{exact:true})});
      if(await row.count()!==1)throw Error('Missing arm '+arm);
      const cells=await row.locator('td').allTextContents();
      if(cells[1]!=='15'||cells[2]!=='100.0%')throw Error('Wrong metrics '+cells);
    }
    await report.getByText('观察复用上下文 15 对 · 改善 0 · 退步 0 · 条件负迁移率（primitive成功分母）：0.00%；总体NTR未估计。',{exact:true}).waitFor();
    await page.screenshot({path:'docs/assets/action-counterfactual-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Mobile overflow');
    await page.screenshot({path:'docs/assets/action-counterfactual-mobile.png',fullPage:true});
    if(errors.length)throw Error(JSON.stringify(errors));
    const receipt={passed:true,at:new Date().toISOString(),contexts:15,branches:30,completed:true,both_arms_visible:true,conditional_ntr_and_population_caveat_visible:true,mobile_overflow:false,page_errors:errors,scope:'Actual browser UI; model outcomes independently audited by report generator'};
    fs.writeFileSync('results/workbench-acceptance/action-counterfactual-ui.json',JSON.stringify(receipt,null,2));
    console.log(JSON.stringify(receipt));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
