// npm install --no-save playwright; npx playwright install chromium
// Start python tests/ui_server.py, then: node tests/browser.cjs
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:8765');
    await page.locator('#question').fill('申请需要哪些材料？');
    await page.locator('#question').press('Enter');
    await page.getByText('生成中 · 内容待验证').waitFor();
    await page.locator('.assistant .note').filter({hasText:'引用编号已检查'}).waitFor();
    assert((await page.locator('.assistant .body').innerText()).includes('需要身份证。[1]'));
    assert.equal(await page.locator('.assistant img').count(), 0);
    await page.locator('summary').click();
    assert.equal(await page.getByRole('link', {name:'查看原文'}).getAttribute('href'), 'https://example.com/doc');
    assert((await page.locator('.source').innerText()).includes('第 2 页'));
    await page.screenshot({path:'/tmp/rag-chat-desktop.png', fullPage:true});
    await page.locator('#new-chat').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent === '已新建对话');
    await page.locator('#question').fill('测试错误');
    await page.locator('#send').click();
    await page.locator('.assistant.error').waitFor();
    assert((await page.locator('.assistant .note').innerText()).includes('未通过验证'));
    const turns = await page.evaluate(async () => (await (await fetch(`/conversations/${conversationId}`)).json()).turns);
    assert.deepEqual(turns, []);
    await page.locator('#new-chat').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent === '已新建对话');
    await page.locator('#question').fill('申请材料');
    await page.locator('#send').click();
    await page.waitForFunction(() => document.querySelector('.assistant .body').textContent.length > 0);
    await page.locator('#stop').click();
    await page.locator('.assistant.error').waitFor();
    await page.waitForTimeout(300);
    const cancelled = await page.evaluate(async () => (await (await fetch(`/conversations/${conversationId}`)).json()).turns);
    assert.deepEqual(cancelled, []);
    await page.setViewportSize({width:390,height:844});
    await page.locator('#new-chat').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent === '已新建对话');
    await page.locator('#question').fill('第一行');
    await page.locator('#question').press('Shift+Enter');
    assert((await page.locator('#question').inputValue()).includes('\n'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({path:'/tmp/rag-chat-mobile.png', fullPage:true});
    assert.deepEqual(errors, []);
    console.log('PASS: desktop/mobile, Enter/Shift+Enter, stream, sources, new conversation, XSS, citation failure, cancel history');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
