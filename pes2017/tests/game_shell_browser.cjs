/* Optional browser integration test; see GAME_SHELL_AUDIT.md for usage.
   Run only against a preview configured with COPIES of save files. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright-core');
const url = process.env.GAME_SHELL_URL;
if (!url) throw new Error('Set GAME_SHELL_URL to the copied-save preview server');

async function skipIntro(page) {
  const skip = page.locator('#introDlg #inSkip');
  if (await skip.isVisible().catch(() => false)) await skip.click();
}
async function dimensions(page) {
  return page.evaluate(() => {
    const panel = document.querySelector('main > section.panel.on');
    return {
      mode: window.GS && GS.mode,
      page: panel && panel.id.slice(2),
      windowHeight: document.scrollingElement.scrollHeight,
      innerHeight: innerHeight,
      windowWidth: document.scrollingElement.scrollWidth,
      innerWidth: innerWidth,
      panelHeight: panel && panel.clientHeight,
      panelScrollHeight: panel && panel.scrollHeight,
      panelScrollTop: panel && panel.scrollTop,
      panelOverflow: panel && getComputedStyle(panel).overflowY
    };
  });
}
(async () => {
  const options = {headless:true, args:['--no-sandbox', '--disable-dev-shm-usage']};
  if (process.env.CHROMIUM_PATH) options.executablePath = process.env.CHROMIUM_PATH;
  const browser = await chromium.launch(options);
  const errors = [], routes = [];
  try {
    const context = await browser.newContext({viewport:{width:1366, height:768}});
    await context.addInitScript(() => {
      try { localStorage.setItem('tourDone','1'); localStorage.setItem('lite','0'); }
      catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url, {waitUntil:'domcontentloaded'});
    await page.waitForTimeout(9000);
    await skipIntro(page);
    await page.waitForFunction(() => window.GS && GS.mode === 'game');
    const groups = await page.evaluate(() => GS.sections());
    assert.equal(groups.length, 6);
    assert.equal(groups.reduce((n, g) => n + g.pages.length, 0), 33);
    const aliases = {transfers:'signings', story:'news'};
    for (const group of groups) {
      await page.locator(`[data-gs-section="${group.id}"]`).click();
      for (const entry of group.pages) {
        await page.locator(`[data-gs-page="${entry.id}"]`).click();
        const expected = aliases[entry.id] || entry.id;
        await page.waitForFunction(id => document.querySelector('main > section.panel.on')?.id === 'p-' + id,
                                   expected, {timeout:10000});
        await page.evaluate(() => {
          const panel = document.querySelector('main > section.panel.on');
          panel.scrollTop = panel.scrollHeight;
        });
        const d = await dimensions(page);
        assert.equal(d.page, expected, entry.id);
        assert.equal(d.windowHeight, d.innerHeight, entry.id);
        assert.equal(d.windowWidth, d.innerWidth, entry.id);
        assert.equal(d.panelOverflow, 'auto', entry.id);
        if (d.panelScrollHeight > d.panelHeight + 1)
          assert(d.panelScrollTop >= d.panelScrollHeight - d.panelHeight - 2, entry.id);
        routes.push(entry.id);
      }
    }
    // Native league picker is a contextual control, not a duplicated nav tab.
    await page.locator('[data-gs-section="competitions"]').click();
    await page.locator('[data-gs-page="league"]').click();
    await page.waitForSelector('#p-league .subtabs [data-p-go="league"]', {state:'visible'});
    await page.evaluate(() => { document.getElementById('p-league').scrollTop = 16; });
    await page.evaluate(() => document.querySelector('#p-league .subtabs [data-p-go="league"]').click());
    const anchor = await page.evaluate(() => {
      const b = document.querySelector('#p-league .subtabs [data-p-go="league"]').getBoundingClientRect();
      const m = document.querySelector('#lgPills.open').getBoundingClientRect();
      return {bx:b.x, bottom:b.bottom, mx:m.x, top:m.top};
    });
    assert(Math.abs(anchor.bx - anchor.mx) < 3);
    assert(anchor.top >= anchor.bottom - 2 && anchor.top <= anchor.bottom + 12);
    await page.evaluate(() => document.querySelector('#p-league .subtabs [data-p-go="league"]').click());

    await page.locator('[data-gs-section="home"]').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.gsSection), 'squad');
    await page.keyboard.press('Alt+3');
    assert.equal(await page.locator('[data-gs-section="transfers"]').getAttribute('aria-current'), 'page');
    const remembered = (await dimensions(page)).page;
    assert(groups.find(g => g.id === 'transfers').pages.some(p => p.id === remembered));
    await page.keyboard.press('Control+k');
    await page.locator('#kpQ').fill('abc');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'kpQ');
    await page.keyboard.press('Escape'); // search inputs may clear on the first Escape
    if (await page.locator('#kPal').isVisible()) await page.keyboard.press('Escape');

    // Real dirty indicator and revert; never invoke a save/write operation.
    await page.locator('[data-gs-section="squad"]').click();
    await page.locator('[data-gs-page="squad"]').click();
    await page.locator('#fTabs [data-f="inp"]').click();
    const preset = await page.locator('#presetSel option').evaluateAll(items => items.find(x => x.value)?.value);
    if (preset) {
      await page.locator('#presetSel').selectOption(preset);
      assert(await page.locator('#dirtyTag').isVisible());
      assert(await page.locator('#revertBtn').isVisible());
      await page.locator('#revertBtn').click();
      assert(await page.locator('#dirtyTag').isHidden());
    }

    await page.locator('#sfLook summary').click();
    await page.locator('#gameShellBtn').click();
    assert.equal((await dimensions(page)).mode, null);
    assert(await page.locator('#nav').isVisible());
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => window.GS);
    assert.equal((await dimensions(page)).mode, null);
    if (!await page.locator('#gameShellBtn').isVisible()) await page.locator('#sfLook summary').click();
    await page.locator('#gameShellBtn').click();
    assert.equal((await dimensions(page)).mode, 'game');
    for (const [width, height] of [[1093,614], [1920,1080]]) {
      await page.setViewportSize({width, height});
      const d = await dimensions(page);
      assert.equal(d.windowHeight, d.innerHeight);
      assert.equal(d.windowWidth, d.innerWidth);
      assert(d.panelHeight >= 300);
    }
    await page.setViewportSize({width:390, height:844});
    await page.waitForFunction(() => GS.mode === null);
    assert.equal((await dimensions(page)).mode, null);
    assert(await page.locator('#mtab').isVisible());

    await page.goto(new URL('/pes17.html', url).href, {waitUntil:'domcontentloaded'});
    assert.equal(await page.evaluate(() => document.body.dataset.hud), 'tools');
    assert(!await page.evaluate(() => document.body.classList.contains('game-shell')));
    await context.close();

    // On a fresh browser, preserve the native tour before hiding its anchors.
    const firstRun = await browser.newContext({viewport:{width:1366, height:768}});
    const firstPage = await firstRun.newPage();
    firstPage.on('pageerror', error => errors.push(error.message));
    await firstPage.goto(url, {waitUntil:'domcontentloaded'});
    await firstPage.waitForTimeout(9000);
    await skipIntro(firstPage);
    assert.equal((await dimensions(firstPage)).mode, null);
    assert(await firstPage.locator('#nav').isVisible());
    await firstPage.waitForSelector('#tourO .tour-b', {state:'visible', timeout:20000});
    assert.equal(await firstPage.locator('#tourO .tour-b b').innerText(), 'Home');
    await firstPage.locator('#tourO [data-tour="skip"]').click();
    await firstPage.waitForFunction(() => GS.mode === 'game');
    await firstRun.close();
    assert.deepEqual(errors, []);
    console.log(`PASS: ${routes.length} original routes, bounded desktop/compact screens, ` +
      'native league picker, keyboard/search, dirty/revert, first-run tour, persistent switch, mobile and tools');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
