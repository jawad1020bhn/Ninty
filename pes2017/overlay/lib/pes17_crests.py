"""Read club crests from a PES 2017 patch folder (offline, read-only).

The original app looks for crests in Sider ``livecpk`` folders and in the
``Data/*.cpk`` / ``download/*.cpk`` archives next to ``pes_exe``.  That works
for FL26/FL27 but is unreliable for a patched PES 2017 install:

* ``_save_team_ids()`` uses FL26's 1680 B club stride (PES 2017 uses 1312),
* ``data/pes17/teamids.json`` holds BOTH the stable team id and the raw
  bit-packed club id for every name, so the app can resolve a club name to a
  multi-million id that no ``e_<id>_...dds`` file uses,
* patches often ship loose PNG/JPG/DDS logos named by club name, not CPK
  entries named ``e_<id>_r.dds``.

This module adds a separate, explicit source.  Point ``pes17_patch_dir`` in
config.json at the patch folder (or let it auto-derive candidates from
``pes_exe``), and the app will:

* walk the folder for crest-like PNG/JPG/DDS/FTEX files,
* read ``e_<id>_<variant>.(png|dds)`` and ``flag/e_<id>_...`` entries inside
  ``*.cpk`` archives via the shipped ``cpkread.Cpk`` reader,
* map files to clubs using ``data/pes17/teamids.json`` (stable ids preferred),
  filename normalization and an optional ``map.txt`` in the patch folder,
* convert DDS/FTEX/WESYS to PNG with the shipped ``dds``/``ftex``/``bc7`` libs,
* serve the result through the existing ``/api/crest?club=...`` endpoint.

Nothing is written to the game or patch folder.  No network access, no external
dependency.  Every lookup is best-effort: if a crest cannot be found or
decoded, the app falls back to its normal behaviour.
"""
import difflib
import hashlib
import os
import re
import struct
import time
import unicodedata
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMG_EXT = ('.png', '.jpg', '.jpeg', '.dds', '.ftex', '.bmp', '.webp')
CPK_EXT = ('.cpk',)
SKIP_DIRS = frozenset((
    '__pycache__', '.git', '.svn', 'node_modules', 'backup', 'backups',
    'work', 'save', 'saves', 'cache', 'temp', 'tmp', 'logs', 'dist', 'build',
))
MAX_FILES = 30000
MAX_DEPTH = 8
MAX_CPK = 40
MAX_BYTES = 8 * 1024 * 1024
CACHE_TTL = 300.0

# Preferred emblem variants, best first (same order server.py uses).
VARIANTS = ('r', 'r_l', 'r_w', 'r_b', 'r_ll', 'r_w_l', 'r_b_l',
            'r_w_ll', 'r_b_ll')

CREST_WORDS = ('logo', 'crest', 'emblem', 'badge', 'flag', 'club', 'team',
               'shields', 'symbols')
# Folders that almost certainly are NOT crest sources.
NOT_CREST_WORDS = ('kit', 'uniform', 'player', 'coach', 'face', 'stadium',
                   'ball', 'boots', 'miniface', 'tattoo', 'banner', 'bg')

_ID = re.compile(r'^e_(\d+)_(.+)$', re.I)
_NUM = re.compile(r'^(?:logo|crest|emblem|badge|club|team|shield|flag|e)[_\-]?(\d{1,6})(?:[_\-].*)?$', re.I)
_PLAIN_NUM = re.compile(r'^(\d{1,6})$')

_STATE = {'key': None, 'time': 0.0, 'index': {}, 'report': {}}
_PNG = {}


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _norm_stripped(s):
    n = _norm(s)
    for suf in ('fc', 'afc', 'cf', 'sc', 'ac', 'club', 'cd', 'ud', 'ss', 'as'):
        if n.endswith(suf) and len(n) > len(suf) + 2:
            return n[:-len(suf)]
    return n


def _team_map(cfg, extra=None):
    """{normalized club name -> stable team id} from the PES 2017 database.

    ``teamids.json`` can hold several ids for one name (stable tid plus the raw
    bit-packed cid).  The smallest id is the stable one -- raw ids are
    tid << 14 | index, i.e. in the millions.
    """
    names = {}
    for rel in (os.path.join('data', 'pes17', 'teamids.json'),
                os.path.join('data', 'teamids.json')):
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            continue
        try:
            import json
            with open(p, encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            continue
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            try:
                tid = int(k)
            except (TypeError, ValueError):
                continue
            if not v or tid <= 0 or tid > 100000000:
                continue
            nm = str(v).strip()
            for key in (_norm(nm), _norm_stripped(nm)):
                if not key:
                    continue
                if key not in names or tid < names[key]:
                    names[key] = tid
        if names:
            break
    if extra:
        for tid, nm in extra.items():
            for key in (_norm(nm), _norm_stripped(nm)):
                if key and (key not in names or tid < names[key]):
                    names[key] = tid
    return names


def _patch_map_file(root):
    """Optional id=name / id,name list shipped by some patches."""
    out = {}
    for fn in ('map.txt', 'teams.txt', 'teamids.txt', 'clubs.txt'):
        p = os.path.join(root, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(('#', ';', '//')):
                        continue
                    m = re.match(r'^(\d{1,6})\s*[=,:\t]\s*(.+)$', line)
                    if m:
                        out[int(m.group(1))] = m.group(2).strip().strip('"\'')
        except Exception:
            pass
    return out


def roots_for(cfg):
    """Existing folders to scan, in priority order.  Never the whole disk."""
    explicit = (cfg.get('pes17_patch_dir') or '').strip()
    if explicit:
        return ([explicit] if os.path.isdir(explicit) else []), False
    exe = cfg.get('pes_exe') or ''
    game = exe if os.path.isdir(exe) else os.path.dirname(exe)
    if not game:
        return [], True
    cands = [game,
             os.path.join(game, 'download'), os.path.join(game, 'Data'),
             os.path.join(game, 'patch'), os.path.join(game, 'patches'),
             os.path.join(game, 'content'), os.path.join(game, 'livecpk'),
             os.path.join(game, 'SiderAddons'),
             os.path.join(game, 'WEPES')]
    out = []
    for c in cands:
        c = os.path.normpath(c)
        if os.path.isdir(c) and c not in out:
            out.append(c)
    return out, True


def _path_rank(path):
    low = path.replace('\\', '/').lower()
    if '/render/symbol/flag/' in low:
        return 0
    parts = low.split('/')
    if any(w in p for p in parts[-3:] for w in CREST_WORDS):
        return 1
    return 2


def _looks_crest(path):
    low = path.replace('\\', '/').lower()
    if any(w in low for w in NOT_CREST_WORDS):
        return False
    base = low.rsplit('/', 1)[-1]
    if _ID.match(base.rsplit('.', 1)[0]):
        return True
    if any(w in low for w in CREST_WORDS):
        return True
    return False


def _id_from_name(base, path, names):
    """Resolve a crest file to a team id, or None."""
    stem = base.rsplit('.', 1)[0]
    m = _ID.match(stem)
    if m:
        return int(m.group(1)), (VARIANTS.index(m.group(2).lower())
                                if m.group(2).lower() in VARIANTS else len(VARIANTS))
    m = _NUM.search(stem)
    if m:
        return int(m.group(1)), len(VARIANTS)
    m = _PLAIN_NUM.match(stem)
    if m and any(w in path.lower() for w in CREST_WORDS):
        return int(m.group(1)), len(VARIANTS)
    # Loose patch logos are frequently named after the club.
    for key in (_norm(stem), _norm_stripped(stem)):
        if key and key in names:
            return names[key], len(VARIANTS)
    return None


def _signature(roots):
    h = hashlib.sha256()
    for r in roots:
        try:
            st = os.stat(r)
            entries = sorted(os.listdir(r))
            cpk = []
            for e in entries:
                if e.lower().endswith(CPK_EXT):
                    p = os.path.join(r, e)
                    try:
                        s = os.stat(p)
                        cpk.append((e, s.st_size, int(s.st_mtime)))
                    except OSError:
                        pass
            h.update(repr((r, int(st.st_mtime), len(entries), tuple(cpk))).encode('utf-8'))
        except Exception as e:
            h.update(repr((r, str(e))).encode('utf-8'))
    return h.hexdigest()


def scan(cfg, force=False):
    """Build ``{team_id: descriptor}`` and a diagnostic report."""
    roots, auto = roots_for(cfg)
    sig = _signature(roots)
    key = (tuple(roots), sig)
    if not force and _STATE['key'] == key and (time.time() - _STATE['time']) < CACHE_TTL:
        return _STATE['index'], _STATE['report']

    names = _team_map(cfg)
    extra = {}
    for r in roots:
        extra.update(_patch_map_file(r))
    if extra:
        names = _team_map(cfg, extra)

    idnames = _id_names(cfg)
    index, report = {}, dict(
        ok=True, source='pes17_patch', auto=auto, explicit=bool(cfg.get('pes17_patch_dir')),
        roots=roots, files_scanned=0, cpk_archives=0, cpk_entries=0,
        logos_found=0, clubs_matched=0, skipped=0, errors=[], sample=[],
        hint=('Expected: common/render/symbol/flag/e_<teamid>_r.dds inside a '
              'CPK, or a logos/crests folder with <club name>.png / '
              '<teamid>.png. Set pes17_patch_dir to the patch folder.'))
    found = []          # (rank tuple, tid, descriptor, display)

    for root in roots:
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS
                       and not d.startswith('.')
                       and cur.count(os.sep) - base_depth < MAX_DEPTH]
            for fn in files:
                if report['files_scanned'] >= MAX_FILES:
                    break
                low = fn.lower()
                p = os.path.join(cur, fn)
                if low.endswith(CPK_EXT):
                    if report['cpk_archives'] >= MAX_CPK:
                        continue
                    report['cpk_archives'] += 1
                    _scan_cpk(p, names, found, report)
                    continue
                if not low.endswith(IMG_EXT):
                    continue
                report['files_scanned'] += 1
                rel = os.path.relpath(p, root).replace(os.sep, '/')
                if not _looks_crest(rel):
                    continue
                got = _id_from_name(fn, rel, names)
                if not got:
                    report['skipped'] += 1
                    continue
                tid, vrank = got
                rank = (0, _path_rank(rel), vrank, low.endswith('.dds'), len(rel))
                found.append((rank, tid, dict(kind='file', path=p, ext=low.rsplit('.', 1)[-1]),
                              rel))

    for rank, tid, desc, display in sorted(found, key=lambda x: (x[0], x[1])):
        index.setdefault(tid, desc)
    report['logos_found'] = len(index)
    report['clubs_matched'] = sum(1 for t in index if str(t) in idnames)
    for tid, desc in list(index.items())[:12]:
        report['sample'].append(dict(
            id=tid, name=idnames.get(str(tid), ''),
            file=desc.get('path', '') if desc['kind'] == 'file' else desc.get('entry', ''),
            source=desc['kind']))
    _STATE.update(key=key, time=time.time(), index=index, report=report)
    return index, report


def _scan_cpk(archive, names, found, report):
    try:
        import cpkread
        cp = cpkread.Cpk(archive)
    except Exception as e:
        report['errors'].append('%s: %s' % (os.path.basename(archive), str(e)[:120]))
        return
    for entry in cp.files:
        low = entry.replace('\\', '/').lower()
        base = low.rsplit('/', 1)[-1]
        if not base.endswith(('.png', '.dds', '.jpg', '.jpeg', '.ftex')):
            continue
        if not ('/render/symbol/flag/' in low or _looks_crest(low)):
            continue
        if any(w in low for w in NOT_CREST_WORDS):
            continue
        report['cpk_entries'] += 1
        got = _id_from_name(base, low, names)
        if not got:
            report['skipped'] += 1
            continue
        tid, vrank = got
        rank = (1, _path_rank(low), vrank, low.endswith('.dds'), len(low))
        found.append((rank, tid,
                      dict(kind='cpk', archive=archive, entry=entry,
                           ext=base.rsplit('.', 1)[-1]),
                      '%s!%s' % (os.path.basename(archive), entry)))


def _id_names(cfg):
    """{id string -> club name}, PES 2017 database preferred."""
    out = {}
    for rel in (os.path.join('data', 'pes17', 'teamids.json'),
                os.path.join('data', 'teamids.json')):
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            continue
        try:
            import json
            with open(p, encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                out = {str(k): str(v) for k, v in raw.items() if v}
        except Exception:
            pass
        if out:
            break
    return out


def _name_for_id(cfg, tid, idnames=None):
    return (idnames if idnames is not None else _id_names(cfg)).get(str(tid))


def resolve(cfg, name_or_id):
    """Club name / id -> team id, using the PES 2017 database (tid preferred)."""
    extra = {}
    for r in roots_for(cfg)[0]:
        extra.update(_patch_map_file(r))
    names = _team_map(cfg, extra)
    s = str(name_or_id or '').strip()
    if not s:
        return None
    if re.match(r'^\d{1,8}$', s):
        return int(s)
    for key in (_norm(s), _norm_stripped(s)):
        if key in names:
            return names[key]
    if names:
        close = difflib.get_close_matches(_norm(s), list(names), n=1, cutoff=0.86)
        if close:
            return names[close[0]]
    return None


def _unwesys(raw):
    """FL27-style WESYS/zlib wrapper occasionally found in CPK entries."""
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
    if ext in ('png',):
        return raw if raw[:8] == b'\x89PNG\r\n\x1a\n' else None
    if ext in ('jpg', 'jpeg'):
        return raw if raw[:2] == b'\xff\xd8' else None
    if ext == 'bmp':
        return raw if raw[:2] == b'BM' else None
    if ext == 'webp':
        return raw if raw[:4] == b'RIFF' else None
    if ext == 'dds':
        try:
            import dds
            return dds.dds_to_png(raw)
        except Exception:
            return None
    if ext == 'ftex':
        try:
            import ftex, dds
            w, h, rgba = ftex.decode(raw, 2)
            return dds.to_png(w, h, rgba)
        except Exception:
            pass
        try:
            import ftex, bc7, dds
            data, lv = ftex.mip_data(raw, 2)
            hdr = struct.unpack_from('<HHH', raw, 8)[1:3]
            w, h = max(1, hdr[0] >> lv), max(1, hdr[1] >> lv)
            return dds.to_png(w, h, bc7.decode(data, w, h))
        except Exception:
            return None
    return None


def crest_img(name_or_id, cfg):
    """PNG bytes for a club crest, or None (caller keeps its normal fallback)."""
    index, _ = scan(cfg)
    if not index:
        return None
    tid = resolve(cfg, name_or_id)
    if tid is None:
        return None
    desc = index.get(tid)
    if not desc:
        return None
    ck = (tid, desc.get('path') or desc.get('archive'), desc.get('entry'))
    if ck in _PNG:
        return _PNG[ck]
    try:
        if desc['kind'] == 'file':
            with open(desc['path'], 'rb') as f:
                raw = f.read(MAX_BYTES + 1)
        else:
            import cpkread
            raw = cpkread.Cpk(desc['archive']).read(desc['entry'])
            raw = _unwesys(raw)
        if not raw or len(raw) > MAX_BYTES:
            return None
        png = _to_png(raw, desc['ext'])
        if png and len(png) <= MAX_BYTES:
            if len(_PNG) > 64:
                _PNG.clear()
            _PNG[ck] = png
            return png
    except Exception:
        return None
    return None


def count(cfg):
    try:
        return len(scan(cfg)[0])
    except Exception:
        return 0


def report(cfg, force=False):
    try:
        idx, rep = scan(cfg, force=force)
        out = dict(rep)
        out['logos_found'] = len(idx)
        idnames = _id_names(cfg)
        out['clubs_matched'] = sum(1 for t in idx if str(t) in idnames)
        out['available'] = len(idx) > 0
        return out
    except Exception as e:
        return dict(ok=False, available=False, error=str(e)[:200],
                    roots=roots_for(cfg)[0])


def clear():
    """Drop the in-memory index (called when pes17_patch_dir changes)."""
    _STATE.update(key=None, time=0.0, index={}, report={})
    _PNG.clear()
