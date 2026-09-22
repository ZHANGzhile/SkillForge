// npm install --no-save playwright, or set SKILLFORGE_PLAYWRIGHT_MODULE.
const {chromium} = require(process.env.SKILLFORGE_PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const acceptance = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  if (!acceptance.passed) throw Error('Real HTTP acceptance must pass before browser signoff');
  const root = path.dirname(process.argv[2]);
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.SKILLFORGE_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const sample = acceptance.cases.find(row => row.name === 'refund');
    await page.goto('http://127.0.0.1:8080/?run=' + encodeURIComponent(sample.run_id));
    await page.waitForFunction(model => document.getElementById('connection').textContent.includes(model), acceptance.model);
    await page.waitForFunction(id => document.getElementById('runTitle').textContent.includes(id)
      && document.getElementById('outcome').textContent === '通过', sample.run_id);
    if (await page.locator('#protocol').inputValue() !== 'free_action') throw Error('Wrong deployed protocol');
    if (await page.locator('#submit').isDisabled()) throw Error('Released GPU still blocks tasks');
    if (await page.locator('#download').isHidden()) throw Error('Persisted trajectory is not downloadable');
    await page.screenshot({path: path.join(root, 'desktop.png'), fullPage: true});
    await page.reload();
    await page.waitForFunction(id => document.getElementById('runTitle').textContent.includes(id)
      && document.getElementById('outcome').textContent === '通过', sample.run_id);
    await page.setViewportSize({width: 390, height: 844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw Error('Mobile horizontal overflow');
    await page.screenshot({path: path.join(root, 'mobile.png'), fullPage: true});
    await page.locator('nav button[data-view="delivery"]').click();
    await page.waitForFunction(() => document.getElementById('trainingOverview').textContent.includes('同协议独立评测 已完成'));
    await page.locator('nav button[data-view="reports"]').click();
    await page.waitForFunction(() => document.getElementById('reportCards').textContent.includes('DPO'));
    await page.locator('nav button[data-view="history"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#historyRows tr').length > 0);
    if (errors.length) throw Error(JSON.stringify(errors));
    const report = {passed: true, at: new Date().toISOString(), model: acceptance.model,
      run_id: sample.run_id, desktop: true, mobile_overflow: false, refresh_restored: true,
      protocol: 'free_action', reports_accessible: true, history_accessible: true, page_errors: errors};
    fs.writeFileSync(path.join(root, 'browser.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
