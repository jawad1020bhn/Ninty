"""Inventory and harvest PES 2021 / FL2x CPK assets for a PES 2017 build.

The original The Gaffer reads a whole family of assets out of Sider
``livecpk`` folders and ``Data/*.cpk`` / ``download/*.cpk`` archives.  Before
those PES 2021-era files are cleaned out of a pure PES 2017 edition, this
module catalogues (and optionally copies) everything the shipped readers can
reach, and says which classes are actually reusable on PES 2017.

Asset classes (internal CPK paths, case-insensitive):

    crest   common/render/symbol/flag/e_<id>_<variant>.(png|dds)
    emblem  common/render/symbol/emblem*/emb_<id>_<variant>.(png|dds)
    kit     Asset/model/character/uniform/texture/.../u<tid>p<k>.ftex
    face    common/render/symbol/player/<pid>.(dds|png)
    coach   common/render/symbol/coach/coach_<id>.(png|dds)
    pesdb   common/etc/pesdb/*.bin
    art     other loose images / backgrounds / stadium photos
    other   everything else (binaries, text, unknown)

PES 2017 reusability:

    art         YES      ID-independent; safe to keep as generic decoration.
    crest       MAP      needs a PES 2017 team-id map (r6 pes17_crests does it).
    emblem      MAP      competition ids differ between PES 2021 and PES 2017.
    kit         MAP      texture format is Fox FTEX in both, but team ids differ.
    face/coach  MAP      player / staff ids differ; only usable with a mapping.
    pesdb       NO       binary competition tables are version-specific; the
                         PES 2017 save already carries its own league names.
    other       MAYBE    unknown; catalogued but never extracted by default.

Read-only with respect to the source.  No network access, no new dependency:
``cpkread`` / ``dds`` / ``ftex`` / ``bc7`` are the readers already shipped
with pc414.  Extracted files go to the app's own work/data folder, never
into the game or patch folder.
"""
import hashlib
import json
import os
import re
import struct
import time
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLASSES = ('crest', 'emblem', 'kit', 'face', 'coach', 'pesdb', 'art', 'other')
MAP_NEEDED = ('crest', 'emblem', 'kit', 'face', 'coach')
DEFAULT_EXTRACT = ('crest', 'emblem', 'art')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.dds', '.ftex', '.bmp', '.webp', '.gif')
MAX_FILES = 40000
MAX_ARCHIVES = 128
MAX_DEPTH = 8
MAX_BYTES = 8 * 1024 * 1024
CACHE_TTL = 300.0

RE_CREST = re.compile(
    r'(?:^|/)render/symbol/flag/(?:e|emblem|flag|crest|logo)_0*(\d+)(?:_([^/.]+?))?\.(png|dds)$',
    re.I)
RE_EMBLEM = re.compile(r'/render/symbol/emblem[^/]*/emb_(\d+)_([^/]+?)\.(png|dds)$', re.I)
RE_KIT = re.compile(r'/uniform/texture/.*?u(\d{3,4})p(\d+)\.ftex$', re.I)
RE_FACE = re.compile(r'/render/symbol/player/(\d+)\.(dds|png)$', re.I)
RE_COACH = re.compile(r'/render/symbol/coach/coach_(\d+)\.(png|dds)$', re.I)
RE_PESDB = re.compile(r'^common/etc/pesdb/[^/]+\.bin$', re.I)

_STATE = {'key': None, 'time': 0.0, 'rows': [], 'summary': {}}


def _rel(path):
    return str(path).replace('\\', '/').lower()


def classify(path):
    """-> (class, id or None, variant, extension, usable, reason)."""
    p = _rel(path)
    base = p.rsplit('/', 1)[-1]
    ext = ('.' + base.rsplit('.', 1)[-1]) if '.' in base else ''
    m = RE_CREST.search(p)
    if m:
        return ('crest', int(m.group(1)), m.group(2) or '', ext, 'MAP',
                'Team emblem; mapped by PES 2017 stable team ID.')
    m = RE_EMBLEM.search(p)
    if m:
        return ('emblem', int(m.group(1)), m.group(2), ext, 'MAP',
                'Competition logo; competition ids differ between versions.')
    m = RE_KIT.search(p)
    if m:
        return ('kit', int(m.group(1)), 'p' + m.group(2), ext, 'MAP',
                'Fox FTEX kit texture; team ids differ, format may be reusable.')
    m = RE_FACE.search(p)
    if m:
        return ('face', int(m.group(1)), '', ext, 'MAP',
                'Player portrait; PES 2017 player ids differ.')
    m = RE_COACH.search(p)
    if m:
        return ('coach', int(m.group(1)), '', ext, 'MAP',
                'Coach portrait; staff ids differ.')
    if RE_PESDB.match(p.lstrip('/')):
        return ('pesdb', None, '', ext, 'NO',
                'Version-specific competition database; PES 2017 has its own.')
    if ext in ('.ftex',):
        return ('kit', None, '', ext, 'MAP', 'FTEX texture outside the uniform path; needs a team-id map.')
    if ext in IMG_EXT:
        return ('art', None, '', ext, 'YES',
                'ID-independent image; safe to keep as generic artwork.')
    return ('other', None, '', ext, 'MAYBE',
            'Unknown asset; catalogued but not extracted by default.')


def _root_list(source):
    """Existing folders to scan.  A single .cpk file is also accepted."""
    source = (source or '').strip()
    if not source:
        return [], []
    if os.path.isfile(source) and source.lower().endswith('.cpk'):
        return [os.path.dirname(os.path.abspath(source))], [source]
    if os.path.isdir(source):
        return [os.path.abspath(source)], []
    return [], []


def _signature(roots, archives):
    h = hashlib.sha256()
    for r in roots:
        try:
            st = os.stat(r)
            h.update(repr((r, int(st.st_mtime), len(os.listdir(r)))).encode('utf-8'))
        except Exception as e:
            h.update(repr((r, str(e))).encode('utf-8'))
    for a in archives:
        try:
            st = os.stat(a)
            h.update(repr((a, st.st_size, int(st.st_mtime))).encode('utf-8'))
        except Exception:
            pass
    return h.hexdigest()


def _cpk_files(path):
    """[(entry, size)] from the CPK TOC only (never reads file contents)."""
    import cpkread
    cp = cpkread.Cpk(path)
    out = []
    for n, r in cp.files.items():
        try:
            sz = int(r.get('FileSize') or 0)
        except (TypeError, ValueError):
            sz = 0
        out.append((n, sz))
    return out


def scan(source, force=False):
    """Read-only inventory.  Returns (rows, summary)."""
    roots, explicit_archives = _root_list(source)
    archives = list(explicit_archives)
    loose = []
    for root in roots:
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs
                       if not d.startswith('.') and d.lower() not in
                       ('__pycache__', 'node_modules', 'work', 'backup', 'backups')
                       and cur.count(os.sep) - base_depth < MAX_DEPTH]
            for f in files:
                p = os.path.join(cur, f)
                if f.lower().endswith('.cpk'):
                    if len(archives) < MAX_ARCHIVES and p not in archives:
                        archives.append(p)
                elif len(loose) < MAX_FILES:
                    loose.append(p)
            if len(loose) >= MAX_FILES or len(archives) >= MAX_ARCHIVES:
                break
    sig = _signature(roots, archives)
    key = (tuple(roots), sig)
    if not force and _STATE['key'] == key and (time.time() - _STATE['time']) < CACHE_TTL:
        return _STATE['rows'], _STATE['summary']

    rows, errors = [], []
    for a in archives:
        try:
            for entry, size in _cpk_files(a):
                cls, aid, var, ext, usable, why = classify(entry)
                rows.append(dict(source=a, entry=entry, size=size, cls=cls,
                                 id=aid, variant=var, ext=ext, usable=usable,
                                 why=why, in_cpk=True))
        except Exception as e:
            errors.append('%s: %s' % (os.path.basename(a), str(e)[:120]))
    for p in loose:
        rel = _rel(os.path.relpath(p, roots[0])) if roots else _rel(p)
        cls, aid, var, ext, usable, why = classify(rel)
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        rows.append(dict(source='', entry=rel, _abs=p, size=size, cls=cls,
                         id=aid, variant=var, ext=ext, usable=usable,
                         why=why, in_cpk=False))

    counts = {c: sum(1 for r in rows if r['cls'] == c) for c in CLASSES}
    usable_counts = {u: sum(1 for r in rows if r['usable'] == u)
                     for u in ('YES', 'MAP', 'NO', 'MAYBE')}
    summary = dict(
        ok=True, source=source or '', roots=roots, archives=len(archives),
        cpk_entries=sum(1 for r in rows if r['in_cpk']),
        loose_files=len(loose), files=len(rows), counts=counts,
        usable=usable_counts, errors=errors,
        classes=list(CLASSES), default_extract=list(DEFAULT_EXTRACT),
        note=('No real CPK archive was available in this workspace; run this '
              'against the actual patch folder to get the true inventory.'))
    _STATE.update(key=key, time=time.time(), rows=rows, summary=summary)
    return rows, summary


def _unwesys(raw):
    if b'WESYS' not in (raw[:5], raw[3:8]):
        return raw
    for st in (16, 12, 20, 8):
        try:
            return zlib.decompress(raw[st:])
        except Exception:
            pass
    try:
        return zlib.decompressobj(-15).decompress(raw[16:])
    except Exception:
        return raw


def _to_png(raw, ext):
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return raw, '.png'
    if raw[:2] == b'\xff\xd8':
        return raw, '.jpg'
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return raw, '.webp'
    if raw[:4] == b'DDS ' or ext == '.dds':
        try:
            import dds
            return dds.dds_to_png(raw), '.png'
        except Exception:
            return None, ext
    if raw[:4] == b'FTEX' or ext == '.ftex':
        try:
            import ftex, dds
            w, h, rgba = ftex.decode(raw, 2)
            return dds.to_png(w, h, rgba), '.png'
        except Exception:
            pass
        try:
            import ftex, bc7, dds
            data, lv = ftex.mip_data(raw, 2)
            w0, h0 = struct.unpack_from('<HH', raw, 10)  # w,h at 10,12
            w, h = max(1, w0 >> lv), max(1, h0 >> lv)
            return dds.to_png(w, h, bc7.decode(data, w, h)), '.png'
        except Exception:
            return None, ext
    return raw, ext


def _read_row(row):
    if row['in_cpk']:
        import cpkread
        return _unwesys(cpkread.Cpk(row['source']).read(row['entry']))
    p = row.get('_abs') or row['entry']
    with open(p, 'rb') as f:
        return _unwesys(f.read(MAX_BYTES + 1))


def harvest(source, out_dir, classes=None, limit=200, max_bytes=MAX_BYTES,
            rows=None, root=None):
    """Copy selected assets into the APP's own folder.  Never touches source.

    Returns a summary dict.  Source archives/folders are opened read-only.
    """
    classes = tuple(classes or DEFAULT_EXTRACT)
    if rows is None:
        rows, _ = scan(source, force=True)
    src_roots = _root_list(source)[0]
    out_real = os.path.realpath(out_dir)
    for r in src_roots:
        if out_real == os.path.realpath(r) or out_real.startswith(os.path.realpath(r) + os.sep):
            raise ValueError('Refusing to extract into the source folder: %s' % r)
    os.makedirs(out_dir, exist_ok=True)
    written = skipped = failed = total = 0
    files = []
    for row in rows:
        if written >= limit:
            break
        if row['cls'] not in classes or row['usable'] == 'NO':
            continue
        if row['size'] > max_bytes:
            skipped += 1
            continue
        try:
            raw = _read_row(row)
            if not raw or len(raw) > max_bytes:
                skipped += 1
                continue
            data, ext = _to_png(raw, row['ext'])
            if not data:
                skipped += 1
                continue
            safe = re.sub(r'[^A-Za-z0-9._-]', '_',
                          row['entry'].replace('\\', '/').rsplit('/', 1)[-1])[:120]
            suffix = (str(row['id']) if row['id'] is not None else
                      hashlib.sha1(row['entry'].encode('utf-8')).hexdigest()[:10])
            name = '%s_%s_%s%s' % (row['cls'], suffix,
                                   hashlib.sha1(row['entry'].encode('utf-8')).hexdigest()[:6], ext)
            dst = os.path.join(out_dir, row['cls'], name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(data)
            written += 1
            total += len(data)
            if len(files) < 20:
                files.append(dict(cls=row['cls'], id=row['id'],
                                  path=os.path.relpath(dst, out_dir).replace(os.sep, '/'),
                                  bytes=len(data)))
        except Exception as e:
            failed += 1
            if len(files) < 20:
                files.append(dict(error=str(e)[:120], entry=row['entry'][:100]))
    return dict(ok=True, out=out_dir, classes=list(classes), written=written,
                skipped=skipped, failed=failed, bytes=total, sample=files,
                source_read_only=True)


def source_for(cfg):
    """Best local folder to scan: explicit patch dir, else a PES 2017 game subfolder."""
    explicit = (cfg.get('pes17_patch_dir') or '').strip()
    if explicit:
        return explicit
    exe = cfg.get('pes_exe') or ''
    game = exe if os.path.isdir(exe) else os.path.dirname(exe)
    for sub in ('download', 'Data', 'patch', 'content', 'livecpk'):
        cand = os.path.join(game, sub) if game else ''
        if cand and os.path.isdir(cand):
            return cand
    return game


def manifest(cfg, force=False):
    """Diagnostic for GET /api/pes17/assets (plus a small top-level sample)."""
    source = source_for(cfg)
    roots = []
    if not (cfg.get('pes17_patch_dir') or '').strip():
        exe = cfg.get('pes_exe') or ''
        game = exe if os.path.isdir(exe) else os.path.dirname(exe)
        if game:
            roots = [os.path.normpath(os.path.join(game, d)) for d in
                     ('download', 'Data', 'patch', 'content', 'livecpk')]
    rows, summary = scan(source, force=force)
    out = dict(summary)
    out['auto'] = not bool(cfg.get('pes17_patch_dir'))
    out['candidate_roots'] = [r for r in roots if os.path.isdir(r)]
    out['sample'] = [{k: r[k] for k in ('cls', 'id', 'entry', 'size', 'usable')}
                     for r in rows[:15]]
    out['hint'] = ('Expected in a patch: common/render/symbol/flag/e_<id>_r.dds, '
                   'common/render/symbol/emblem*/emb_<id>_*.png, '
                   'Asset/model/character/uniform/texture/.../u<tid>p1.ftex, '
                   'common/render/symbol/player/<pid>.dds, '
                   'common/etc/pesdb/Competition.bin. '
                   'Set pes17_patch_dir to the folder that holds them.')
    return out


def clear():
    _STATE.update(key=None, time=0.0, rows=[], summary={}, root='')
