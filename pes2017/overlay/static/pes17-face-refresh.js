/* Refresh PES 2017 portraits when the local game/patch scan changes.
 * Additive to Classic: native routing, rendering and retry handlers stay intact. */
(function () {
  'use strict';
  if (!document.body || document.body.dataset.hud !== 'classic') return;
  const KEY = 'gaffer_pes17_face_revision';
  const VERSION = 'local-faces-2';
  const readRevision = () => {
    try { return localStorage.getItem(KEY) || '0'; } catch (_) { return '0'; }
  };
  let seen = readRevision();
  const token = () => VERSION + '-' + seen;

  // The old app cached successful images for an hour.  Give portrait URLs a
  // revision without touching avatars, app state, navigation or other images.
  function versionImage(img) {
    if (!(img instanceof HTMLImageElement)) return;
    const src = img.getAttribute('src');
    if (!src || src[0] === '#' || src.startsWith('data:')) return;
    try {
      const url = new URL(src, location.href);
      if (url.origin !== location.origin || url.pathname !== '/api/wiki/img') return;
      if (url.searchParams.get('face_rev') === token()) return;
      url.searchParams.set('face_rev', token());
      img.setAttribute('src', url.pathname + url.search + url.hash);
    } catch (_) { /* leave unrelated/native images untouched */ }
  }
  const pending = new WeakSet();
  function versionAfterLoad(img) {
    if (!(img instanceof HTMLImageElement)) return;
    const src = img.getAttribute('src') || '';
    if (!src.includes('/api/wiki/img') || src.includes('face_rev=')) return;
    // Do not cancel the browser's in-flight native request just to add a
    // revision. Wait for it to finish; a cached old image is then refreshed.
    if (img.complete) { if (img.naturalWidth) versionImage(img); return; }
    if (pending.has(img)) return;
    pending.add(img);
    img.addEventListener('load', () => { pending.delete(img); versionImage(img); }, {once:true});
    img.addEventListener('error', () => pending.delete(img), {once:true});
  }
  function versionTree(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    versionAfterLoad(node);
    node.querySelectorAll('img').forEach(versionAfterLoad);
  }
  const observer = new MutationObserver(records => records.forEach(record => {
    if (record.type === 'attributes') versionAfterLoad(record.target);
    else record.addedNodes.forEach(versionTree);
  }));
  observer.observe(document.documentElement, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['src']
  });
  document.querySelectorAll('img').forEach(versionAfterLoad);

  function refreshIfChanged() {
    const revision = readRevision();
    if (revision === seen) return;
    seen = revision;
    try {
      // Clear only player failures.  Club crest retry state remains native.
      if (typeof IMGBAD !== 'undefined') {
        Array.from(IMGBAD.keys()).forEach(key => {
          if (/^p\d+$/.test(String(key))) IMGBAD.delete(key);
        });
      }
    } catch (_) { /* a future Classic build may not expose this cache */ }
    document.querySelectorAll('img.av[data-pid]').forEach(img => {
      const pid = img.dataset.pid || '';
      if (!/^\d+$/.test(pid)) return;
      if (img.classList.contains('nf') && typeof imgRetry === 'function') {
        img.dataset.rt = '0';
        // Native helper swaps the silhouette only after the new image loads.
        imgRetry(img, '/api/wiki/img?pid=' + encodeURIComponent(pid) +
                      '&face_rev=' + encodeURIComponent(token()));
      } else {
        versionImage(img);
      }
    });
    // Player photos outside avatar lists also get the new cache revision.
    document.querySelectorAll('img').forEach(versionImage);
  }
  window.addEventListener('storage', e => { if (e.key === KEY) refreshIfChanged(); });
  window.addEventListener('pageshow', refreshIfChanged);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshIfChanged();
  });
}());
