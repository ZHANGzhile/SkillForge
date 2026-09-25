const {chromium} = require(process.env.SKILLFORGE_PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.SKILLFORGE_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8080');
    await page.waitForFunction(()=>document.getElementById('connection').textContent.includes('预留 GPU'));
    if (!(await page.locator('#submit').isDisabled())) throw Error('Training must reserve the GPU');
    await page.locator('nav button[data-view="delivery"]').click();
    await page.waitForFunction(()=>document.getElementById('recoveryOverview').textContent.includes('validation进行中'));
    if (!(await page.locator('#deliveryOverview').textContent()).includes('尚未通过')) throw Error('Premature delivery success');
    await page.screenshot({path:'docs/assets/recovery-progress-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)) throw Error('Mobile overflow');
    await page.screenshot({path:'docs/assets/recovery-progress-mobile.png',fullPage:true});
    await page.locator('nav button[data-view="reports"]').click();
    await page.waitForFunction(()=>document.getElementById('reportCards').textContent.includes('main-v3 SFT 新实例测试'));
    if(errors.length) throw Error(JSON.stringify(errors));
    const result={passed:true,at:new Date().toISOString(),scope:'Recovery progress UI during training, not trained-model business acceptance',
      mobile_overflow:false,page_errors:errors,gpu_reserved:true,delivery_not_claimed:true};
    fs.writeFileSync('results/workbench-acceptance/recovery-progress-ui.json',JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
