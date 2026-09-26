const {chromium}=require(process.env.SKILLFORGE_PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.SKILLFORGE_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8080');
    await page.locator('nav button[data-view="reports"]').click();
    const progress=page.locator('#reportCards .report').filter({has:page.getByRole('heading',{name:'main-v3 无Skill对照进度',exact:true})});
    await progress.getByText(/状态：/).waitFor();
    const paired=page.locator('#reportCards .report').filter({has:page.getByRole('heading',{name:'main-v3 SFT 无Skill B0 与冻结 B3 的配对结果',exact:true})});
    await paired.waitFor();
    const state=await progress.textContent();
    const complete=state.includes('状态：completed');
    if(complete){
      await paired.getByText('B0 无Skill',{exact:true}).waitFor();
      await paired.getByText('B3 冻结Skill',{exact:true}).waitFor();
      await paired.getByText(/配对改善/).waitFor();
    }else if(await paired.locator('table').count())throw Error('Partial run must not show a completed summary table');
    await page.screenshot({path:'docs/assets/reuse-ablation-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Mobile overflow');
    await page.screenshot({path:'docs/assets/reuse-ablation-mobile.png',fullPage:true});
    if(errors.length)throw Error(JSON.stringify(errors));
    const report={passed:true,at:new Date().toISOString(),evaluation_complete:complete,scope:'Actual ablation progress/report UI, not model outcome verification',mobile_overflow:false,page_errors:errors};
    fs.writeFileSync('results/workbench-acceptance/reuse-ablation-ui.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
