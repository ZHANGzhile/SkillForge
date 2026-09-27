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
    const progress=card('决策提示实验进度');
    await progress.getByText(/状态：/).waitFor();
    const state=await progress.textContent();
    const reportPath='results/decision-guidance/v1/validation/evaluation.json';
    if(fs.existsSync(reportPath)){
      const report=JSON.parse(fs.readFileSync(reportPath,'utf8'));
      await card('决策提示 validation 双评测').getByText(`决策探针：${report.decision_level.correct} / ${report.decision_level.evaluated} · 跳过 ${report.decision_level.skipped}`,{exact:true}).waitFor();
      if(await card('决策提示 validation 双评测').locator('table').count()!==1)throw Error('Missing validation result');
    }
    if(state.includes('状态：rejected')){
      await progress.getByText('未通过预声明 validation 门槛；未进入新实例 test，部署保持不变。',{exact:true}).waitFor();
      for(const title of ['新实例原提示对照','新实例决策提示结果']){
        if(await card(title).locator('table').count())throw Error('Rejected run displays a test result');
      }
    }
    if(state.includes('状态：completed')){
      for(const title of ['新实例原提示对照','新实例决策提示结果']){
        await card(title).locator('table').waitFor();
        await card(title).getByText(/决策探针：/).waitFor();
      }
    }
    await page.screenshot({path:'docs/assets/decision-guidance-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Mobile overflow');
    await page.screenshot({path:'docs/assets/decision-guidance-mobile.png',fullPage:true});
    if(errors.length)throw Error(JSON.stringify(errors));
    const receipt={passed:true,at:new Date().toISOString(),state:state.match(/状态：[^·]+/)?.[0],validation_complete:fs.existsSync(reportPath),mobile_overflow:false,page_errors:errors,scope:'Actual browser UI, not model outcome verification'};
    fs.writeFileSync('results/workbench-acceptance/decision-guidance-ui.json',JSON.stringify(receipt,null,2));
    console.log(JSON.stringify(receipt));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
