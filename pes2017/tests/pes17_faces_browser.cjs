/* Optional integration test against a disposable server using COPIED saves and
   clearly synthetic solid-color portraits. Never point this at a real game. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright-core');
const url = process.env.FACE_TEST_URL;
const gameDir = process.env.FACE_TEST_GAME_DIR;
const replacement = process.env.FACE_TEST_REPLACEMENT;
const target = process.env.FACE_TEST_TARGET;
if (!url || !gameDir || !replacement || !target)
  throw new Error('Set FACE_TEST_URL, FACE_TEST_GAME_DIR, FACE_TEST_REPLACEMENT and FACE_TEST_TARGET to disposable fixtures');

async function colorFor(page, pid) {
  return page.evaluate(id => {
    const image = [...document.querySelectorAll(`img.av[data-pid="${id}"]`)]
      .find(i => i.offsetParent && !i.classList.contains('nf') && i.complete && i.naturalWidth);
    if (!image) return null;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(image, 0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data);
  }, pid);
}

(async () => {
  const options = {headless:true, args:['--no-sandbox', '--disable-dev-shm-usage']};
  if (process.env.CHROMIUM_PATH) options.executablePath = process.env.CHROMIUM_PATH;
  const browser = await chromium.launch(options);
  const errors = [];
  try {
    const context = await browser.newContext({viewport:{width:1366, height:768}});
    await context.addInitScript(() => {
      try { localStorage.setItem('tourDone','1'); localStorage.setItem('gaffer_shell','0'); }
      catch (_) {}
    });
    const classic = await context.newPage();
    classic.on('pageerror', e => errors.push('Classic: ' + e.message));
    await classic.goto(url, {waitUntil:'domcontentloaded'});
    await classic.waitForTimeout(9000);
    const skip = classic.locator('#introDlg #inSkip');
    if (await skip.isVisible().catch(() => false)) await skip.click();
    // Invoke the actual native route button; this secondary button is hidden in
    // the original Classic navigation but remains the authoritative route.
    await classic.evaluate(() => document.querySelector('#nav button[data-p="squad"]').click());
    await classic.waitForFunction(() => [...document.querySelectorAll('img.av[data-pid="55246"]')]
      .some(i => i.offsetParent && i.classList.contains('nf')), null, {timeout:20000});
    // Reproduce the native five-minute failed-image cache before configuration.
    await classic.evaluate(() => IMGBAD.set('p55246', {c:4, t:Date.now()}));

    const tools = await context.newPage();
    tools.on('pageerror', e => errors.push('Tools: ' + e.message));
    await tools.goto(new URL('/pes17.html', url).href, {waitUntil:'domcontentloaded'});
    await tools.waitForFunction(() => document.querySelector('#faceReport')?.textContent.includes('No game or patch folder found'), null, {timeout:30000});
    await tools.locator('#patchDir').fill(gameDir);
    await tools.locator('#setCrestsDir').click();
    await tools.waitForFunction(() => {
      const text = document.querySelector('#faceReport')?.textContent || '';
      return text.includes('3/26 IDs matched') && text.includes('3/3 readable portraits');
    }, null, {timeout:60000});
    const diagnostic = await tools.evaluate(() => LAST_FACE_REPORT);
    assert.equal(diagnostic.squad_slot, 'ML00000011');
    assert.equal(diagnostic.squad_decoded, 3);
    assert.equal(diagnostic.sample_decoded, 3);
    assert(diagnostic.roots.some(p => /(?:^|[/\\])Data$/i.test(p)));
    assert(diagnostic.roots.some(p => /SiderAddons/i.test(p)));
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin:new URL(url).origin});
    await tools.locator('#copyFaceReport').click();
    const copied = JSON.parse(await tools.evaluate(() => navigator.clipboard.readText()));
    assert.equal(copied.squad_slot, 'ML00000011');
    assert.equal(copied.squad_decoded, 3);
    await tools.waitForFunction(() => [...document.querySelectorAll('#faceGrid img.pf-img')]
      .filter(i => i.complete && i.naturalWidth > 0).length === 3, null, {timeout:20000});

    // The still-open Classic tab receives a storage event and retries its old
    // silhouettes immediately, without navigation or modifying native app JS.
    await classic.waitForFunction(() => [...document.querySelectorAll('img.av[data-pid="55246"]')]
      .some(i => i.offsetParent && !i.classList.contains('nf') && i.complete && i.naturalWidth > 0),
      null, {timeout:20000});
    assert.deepEqual(await colorFor(classic, '55246'), [240,50,30,255]);
    assert.equal(await classic.evaluate(() => IMGBAD.has('p55246')), false);

    // Replace only a synthetic fixture, rescan, and verify the same live image
    // switches to the new pixels despite the old one-hour browser cache.
    const oldRevision = await tools.evaluate(() => localStorage.getItem('gaffer_pes17_face_revision'));
    fs.copyFileSync(replacement, target);
    await tools.locator('#rescanFaces').click();
    await tools.waitForFunction(old => localStorage.getItem('gaffer_pes17_face_revision') !== old,
                                oldRevision, {timeout:60000});
    await classic.waitForFunction(() => {
      const i = [...document.querySelectorAll('img.av[data-pid="55246"]')]
        .find(x => x.offsetParent && !x.classList.contains('nf') && x.complete && x.naturalWidth);
      if (!i) return false;
      const c=document.createElement('canvas'); c.width=c.height=1;
      const cx=c.getContext('2d'); cx.drawImage(i,0,0,1,1);
      const px=cx.getImageData(0,0,1,1).data;
      return px[0]===30 && px[1]===220 && px[2]===70;
    }, null, {timeout:20000});
    assert.deepEqual(await colorFor(classic, '55246'), [30,220,70,255]);

    // Also cover navigating to Tools in the same tab and returning via Back;
    // browsers may restore the old page from their back-forward cache.
    await classic.evaluate(() => {
      IMGBAD.set('p55246', {c:4, t:Date.now()});
      document.querySelectorAll('img.av[data-pid="55246"]').forEach(i => {
        i.classList.add('nf'); i.dataset.rt='9'; i.src=AVPH;
      });
    });
    await classic.goto(new URL('/pes17.html', url).href, {waitUntil:'domcontentloaded'});
    await classic.waitForFunction(() => document.querySelector('#faceReport')?.textContent.includes('3/26 IDs matched'), null, {timeout:60000});
    const beforeBack = await classic.evaluate(() => localStorage.getItem('gaffer_pes17_face_revision'));
    await classic.locator('#rescanFaces').click();
    await classic.waitForFunction(old => localStorage.getItem('gaffer_pes17_face_revision') !== old,
                                  beforeBack, {timeout:60000});
    await classic.goBack({waitUntil:'domcontentloaded'});
    await classic.waitForFunction(() => [...document.querySelectorAll('img.av[data-pid="55246"]')]
      .some(i => i.offsetParent && !i.classList.contains('nf') && i.complete && i.naturalWidth > 0),
      null, {timeout:30000});
    assert.deepEqual(await colorFor(classic, '55246'), [30,220,70,255]);

    await tools.locator('#langBtn').click();
    assert.equal(await tools.locator('html').getAttribute('lang'), 'ar');
    assert((await tools.locator('#faceReport').innerText()).includes('التشكيلة المحددة'));
    assert.deepEqual(errors, []);
    await context.close();
    console.log('PASS: no assets → selected game → selected-squad diagnostic → synthetic images in Classic → changed image after rescan; Arabic report.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
