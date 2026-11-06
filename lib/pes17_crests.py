"""Read club crests from a PES 2017 game / patch folder (offline, read-only).

The original FL26/FL27 crest pipeline is unreliable on a patched PES 2017 install:

* ``_save_team_ids()`` uses FL26's 1680 B club stride (PES 2017 uses 1312),
* ``data/pes17/teamids.json`` holds BOTH the stable team id and the raw
  bit-packed club id for every name, so naive lookups can resolve a club name
  to a multi-million raw id that no ``emblem_<id>_r.png`` / ``e_<id>_r.dds`` uses,
* PES 2017 CPKs store club crests as ``emblem_%04d_r.png`` / ``flag_%04d.png``
  under ``common/render/symbol/flag/`` (as well as ``e_<id>_<variant>`` in some
  community packs), and ``download/*.cpk`` patches (ordered by ``DpFileList.bin``)
  must override vanilla ``Data/*.cpk`` archives.

Point ``pes17_patch_dir`` in config.json at the PES 2017 game or patch folder
(or let ``pes_exe`` auto-detect the PES 2017 installation), and this module will:

* walk loose logo/livecpk folders for crest PNG/JPG/DDS/FTEX/BMP/WEBP files,
* read ``emblem_<id>_<variant>``, ``flag_<id>`` and ``e_<id>_<variant>`` entries
  inside ``*.cpk`` archives via ``cpkread.Cpk`` in true ``DpFileList.bin``
  override order (``livecpk``/loose > ``download/*.cpk`` > ``Data/*.cpk``),
* auto-populate ``data/pes17/teamids.json`` from ``ML*`` + ``EDIT00000000`` so
  patched team IDs are available on first load,
* convert WESYS/zlib, DDS (``dds_to_png`` / BC7 / RGB) and FTEX to PNG in memory,
* serve the result through ``/api/crest?club=...``.

Nothing is written to the game or patch folder.  No network access, no external
dependency.  Every lookup is best-effort and read-only.
"""
import difflib
import hashlib
import json
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
MAX_CPK = 128
MAX_BYTES = 8 * 1024 * 1024
CACHE_TTL = 300.0

# Preferred emblem variants, best first: full-colour regular ('r') ahead of
# large ('r_l'), unsuffixed (''), plated ('r_w', 'r_b'), and monochrome last.
VARIANTS = ('r', 'r_l', '', 'l', 'r_w', 'r_b', 'r_ll', 'll',
            'r_w_l', 'r_b_l', 'r_w_ll', 'r_b_ll')
MONO_VARIANTS = ('w', 'b', 'w_l', 'b_l', 'w_ll', 'b_ll')

CREST_WORDS = ('logo', 'crest', 'emblem', 'badge', 'flag', 'club', 'team',
               'shields', 'symbols')
# Relative folder/file segments that are NOT club crest sources.
NOT_CREST_WORDS = ('kit', 'kits', 'uniform', 'player', 'coach', 'face', 'faces',
                   'stadium', 'ball', 'boots', 'glove', 'miniface', 'tattoo',
                   'banner', 'bg', 'emblemlc', 'adboard', 'trophy', 'sound', 'movie')

_ID = re.compile(r'^(?:e|emblem|flag|crest|logo)_0*(\d{1,6})_([a-z0-9_]+)$', re.I)
_NUM = re.compile(
    r'^(?:logo|crest|emblem|badge|club|team|shield|flag|e)[_\-]?0*(\d{1,6})(?:[_\-].*)?$',
    re.I)
_PLAIN_NUM = re.compile(r'^0*(\d{1,6})$')
_KIT_STEM = re.compile(r'^u\d{3,5}[pg]\d+', re.I)
_COMP_STEM = re.compile(r'^emb_\d+_lc$', re.I)
_TRAIL_TAG = re.compile(r'[\s._-]*(?:emblem|crest|logo|badge)$', re.I)

_HOMOGLYPHS = str.maketrans({
    '\u0391': 'A', '\u0392': 'B', '\u0395': 'E', '\u0396': 'Z', '\u0397': 'H',
    '\u0399': 'I', '\u039a': 'K', '\u039c': 'M', '\u039d': 'N', '\u039f': 'O',
    '\u03a1': 'P', '\u03a4': 'T', '\u03a5': 'Y', '\u03a7': 'X',
    '\u03b1': 'a', '\u03b2': 'b', '\u03b5': 'e', '\u03b9': 'i', '\u03ba': 'k',
    '\u03bd': 'n', '\u03bf': 'o', '\u03c1': 'p', '\u03c4': 't', '\u03c5': 'y',
    '\u03c7': 'x',
    '\u0410': 'A', '\u0412': 'B', '\u0415': 'E', '\u041a': 'K', '\u041c': 'M',
    '\u041d': 'H', '\u041e': 'O', '\u0420': 'P', '\u0421': 'C', '\u0422': 'T',
    '\u0423': 'Y', '\u0425': 'X',
    '\u0430': 'a', '\u0435': 'e', '\u043e': 'o', '\u0440': 'p', '\u0441': 'c',
    '\u0443': 'y', '\u0445': 'x',
    '\u00df': 'ss', '\u00f8': 'o', '\u00d8': 'O', '\u00e6': 'ae', '\u00c6': 'AE',
    '\u0153': 'oe', '\u0152': 'OE', '\u0142': 'l', '\u0141': 'L',
    '\u0111': 'd', '\u0110': 'D',
})

_STATE = {'key': None, 'time': 0.0, 'index': {}, 'by_name': {}, 'report': {}}
_PNG = {}


def _norm(s):
    t = re.sub(r'^\s*\d{1,3}[\s.\-]+', '', str(s or '')).translate(_HOMOGLYPHS)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]', '', t.lower())


def _norm_stripped(s):
    n = _norm(s)
    for suf in ('afc', 'ssc', 'fc', 'cf', 'sc', 'ac', 'bc', 'fk', 'sk',
                'club', 'cd', 'ud', 'ss', 'as'):
        if n.endswith(suf) and len(n) > len(suf) + 2:
            n = n[:-len(suf)]
            break
    for pre in ('afc', 'fc', 'cf', 'sc', 'ac', 'cd', 'ud', 'rcd'):
        if n.startswith(pre) and len(n) > len(pre) + 3:
            n = n[len(pre):]
            break
    return n


def _variant_rank(v):
    v = (v or '').lower()
    if v in VARIANTS:
        return VARIANTS.index(v)
    if v in MONO_VARIANTS or v.endswith(('_b', '_w')):
        return len(VARIANTS) + 20 + (MONO_VARIANTS.index(v) if v in MONO_VARIANTS else 9)
    return len(VARIANTS) + 4


def _ensure_pes17_teamids(cfg):
    """Build `data/pes17/teamids.json` from `save_dir` (`ML*` + `EDIT00000000`) if missing."""
    if not cfg or not (cfg.get('save_dir') or cfg.get('edit_dat')):
        return
    try:
        import pes17
        pes17.ensure_teamids(cfg, os.path.join(HERE, 'data', 'pes17'))
    except Exception:
        pass


def _team_map(cfg, extra=None):
    """{normalized club name -> stable team id} from the PES 2017 database.

    ``teamids.json`` can hold several ids for one name (stable tid plus the raw
    bit-packed cid).  The smallest id is the stable one -- raw ids are
    tid << 14 | index, i.e. in the millions.
    """
    _ensure_pes17_teamids(cfg)
    names = {}
    for rel in (os.path.join('data', 'pes17', 'teamids.json'),
                os.path.join('data', 'teamids.json')):
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            continue
        try:
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
    cfg = cfg or {}
    explicit = os.path.expandvars((cfg.get('pes17_patch_dir') or '').strip().strip('"'))
    if explicit and os.path.isfile(explicit) and explicit.lower().endswith(('.exe', '.cpk', '.bin')):
        explicit = os.path.dirname(explicit)
    harvest_dir = os.path.join(HERE, 'data', 'pes17', 'harvest', 'crest')
    has_harvest = False
    if os.path.isdir(harvest_dir):
        try:
            has_harvest = any(fn.lower().endswith(IMG_EXT) for fn in os.listdir(harvest_dir))
        except OSError:
            has_harvest = False

    if explicit:
        if not os.path.isdir(explicit):
            return ([harvest_dir] if has_harvest else []), False
        cands = [
            os.path.join(explicit, 'livecpk'),
            os.path.join(explicit, 'SiderAddons'),
            os.path.join(explicit, 'patch'),
            os.path.join(explicit, 'patches'),
            os.path.join(explicit, 'content'),
            os.path.join(explicit, 'WEPES'),
            os.path.join(explicit, 'download'),
            explicit,
            os.path.join(explicit, 'Data'),
        ]
        if has_harvest:
            cands.append(harvest_dir)
        out, seen = [], set()
        for c in cands:
            nc = os.path.normcase(os.path.normpath(c))
            if os.path.isdir(c) and nc not in seen:
                seen.add(nc)
                out.append(os.path.normpath(c))
        return out, False

    exe = os.path.expandvars((cfg.get('pes_exe') or '').strip().strip('"'))
    game = exe if os.path.isdir(exe) else (os.path.dirname(exe) if exe else '')
    cands = []
    if game and os.path.isdir(game):
        cands.extend([
            os.path.join(game, 'livecpk'),
            os.path.join(game, 'SiderAddons'),
            os.path.join(game, 'patch'),
            os.path.join(game, 'patches'),
            os.path.join(game, 'content'),
            os.path.join(game, 'WEPES'),
            os.path.join(game, 'download'),
            game,
            os.path.join(game, 'Data'),
        ])
    if has_harvest:
        cands.append(harvest_dir)
    out, seen = [], set()
    for c in cands:
        nc = os.path.normcase(os.path.normpath(c))
        if os.path.isdir(c) and nc not in seen:
            seen.add(nc)
            out.append(os.path.normpath(c))
    return out, True


def _dpfilelist_order(folder):
    """CPK basenames (lowercase) in `DpFileList.bin` mount order, if present."""
    p = os.path.join(folder, 'DpFileList.bin')
    if not os.path.isfile(p):
        return []
    try:
        with open(p, 'rb') as f:
            raw = f.read(262144)
    except OSError:
        return []
    if len(raw) < 20:
        return []
    names = []
    cnt = struct.unpack_from('<I', raw, 4)[0]
    if 0 < cnt <= 512 and 16 + cnt * 48 <= len(raw):
        for i in range(cnt):
            slot = raw[16 + i * 48 + 16:16 + (i + 1) * 48]
            nm = slot.split(b'\x00', 1)[0].decode('utf-8', 'ignore').strip()
            if nm.lower().endswith('.cpk'):
                names.append(os.path.basename(nm).lower())
    if names:
        return names
    for m in re.finditer(rb'([\x20-\x7e]{1,80}?\.cpk)\x00', raw, re.I):
        nm = os.path.basename(m.group(1).decode('ascii', 'ignore').strip()).lower()
        if nm and nm not in names:
            names.append(nm)
    return names


def _path_rank(path):
    low = path.replace('\\', '/').lower()
    if '/render/symbol/flag/' in ('/' + low):
        return 0
    parts = low.split('/')
    if any(w in p for p in parts[-3:] for w in CREST_WORDS):
        return 1
    return 2


def _has_not_crest_segment(rel_path):
    parts = [seg for seg in rel_path.replace('\\', '/').lower().split('/') if seg]
    dirs, fn = parts[:-1], (parts[-1] if parts else '')
    stem = fn.rsplit('.', 1)[0]
    if _KIT_STEM.match(stem) or _COMP_STEM.match(stem):
        return True
    for seg in dirs:
        if seg in NOT_CREST_WORDS or any(w in seg for w in (
                'kit', 'uniform', 'face', 'miniface', 'stadium', 'adboard',
                'emblemlc', 'boots', 'glove', 'ball', 'trophy')):
            return True
    return False


def _looks_crest(rel_path):
    low = rel_path.replace('\\', '/').lower()
    if _has_not_crest_segment(low):
        return False
    base = low.rsplit('/', 1)[-1]
    stem = base.rsplit('.', 1)[0]
    if _ID.match(stem) or _NUM.match(stem):
        return True
    if any(w in low for w in CREST_WORDS):
        return True
    # Direct loose image at root of an explicit logo/download folder (e.g. `Birmingham City FC.png`)
    if '/' not in low.lstrip('/'):
        return True
    return False


def _id_from_name(base, path, names):
    """Resolve a crest file to `(team_id, variant_rank)`, or `None`."""
    stem = base.rsplit('.', 1)[0]
    if _KIT_STEM.match(stem) or _COMP_STEM.match(stem):
        return None
    m = _ID.match(stem)
    if m:
        tid = int(m.group(1))
        var = m.group(2).lower()
        if stem.lower().startswith('crest_') and len(var) == 6 and all(
                c in '0123456789abcdef' for c in var):
            var = ''
        return tid, _variant_rank(var)
    m = _NUM.match(stem)
    if m:
        return int(m.group(1)), _variant_rank('')
    m = _PLAIN_NUM.match(stem)
    if m and any(w in path.lower() for w in CREST_WORDS):
        return int(m.group(1)), _variant_rank('')
    cleaned = _TRAIL_TAG.sub('', stem)
    for key in (_norm(cleaned), _norm_stripped(cleaned), _norm(stem), _norm_stripped(stem)):
        if key and key in names:
            return names[key], _variant_rank('')
    return None


def _signature(roots, cfg=None):
    _ensure_pes17_teamids(cfg)
    h = hashlib.sha256()
    for r in roots:
        try:
            st = os.stat(r)
            entries = sorted(os.listdir(r))
            cpk = []
            for e in entries:
                low = e.lower()
                if low.endswith(CPK_EXT) or low == 'dpfilelist.bin':
                    p = os.path.join(r, e)
                    try:
                        s = os.stat(p)
                        cpk.append((e, s.st_size, int(s.st_mtime)))
                    except OSError:
                        pass
            h.update(repr((r, int(st.st_mtime), len(entries), tuple(cpk))).encode('utf-8'))
        except Exception as e:
            h.update(repr((r, str(e))).encode('utf-8'))
    for rel in (os.path.join('data', 'pes17', 'teamids.json'),
                os.path.join('data', 'teamids.json')):
        tp = os.path.join(HERE, rel)
        if os.path.isfile(tp):
            try:
                tst = os.stat(tp)
                h.update(repr((rel, tst.st_size, int(tst.st_mtime_ns))).encode('utf-8'))
            except OSError:
                pass
    return h.hexdigest()


def scan(cfg, force=False):
    """Build ``{team_id: descriptor}`` and a diagnostic report."""
    cfg = cfg or {}
    roots, auto = roots_for(cfg)
    sig = _signature(roots, cfg)
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
    index, by_name = {}, {}
    report = dict(
        ok=True, source='pes17_patch', auto=auto, explicit=bool(cfg.get('pes17_patch_dir')),
        roots=roots, files_scanned=0, cpk_archives=0, cpk_entries=0,
        logos_found=0, clubs_matched=0, skipped=0, errors=[], sample=[],
        hint=('Expected: common/render/symbol/flag/emblem_<teamid>_r.png or '
              'e_<teamid>_r.dds inside a CPK (download/*.cpk), or a logos/crests '
              'folder with <club name>.png / <teamid>.png. Set pes17_patch_dir '
              'to your PES 2017 game or patch folder.'))
    found = []          # (rank tuple, tid, descriptor, display)
    found_names = []    # (rank tuple, norm_key, descriptor)
    cpk_queue = []      # ((cpk_tier, cpk_order), cpk_path)
    seen_dirs = set()
    seen_cpks = set()

    dpl_by_dir = {}
    for r in roots:
        order = _dpfilelist_order(r)
        if order:
            dpl_by_dir[os.path.normcase(os.path.realpath(r))] = {
                nm: idx for idx, nm in enumerate(order)
            }

    for root in roots:
        base_depth = root.rstrip(os.sep).count(os.sep)
        root_base = os.path.basename(root.rstrip('\\/')).lower()
        is_vanilla_data = (root_base == 'data')
        is_harvest = (root_base == 'crest' and 'harvest' in root.lower())

        for cur, dirs, files in os.walk(root):
            real_cur = os.path.normcase(os.path.realpath(cur))
            if real_cur in seen_dirs:
                dirs[:] = []
                continue
            seen_dirs.add(real_cur)

            keep_dirs = []
            for d in sorted(dirs):
                dl = d.lower()
                if dl in SKIP_DIRS or d.startswith('.'):
                    continue
                if cur.count(os.sep) - base_depth >= MAX_DEPTH:
                    continue
                # Defer `Data/` until the dedicated low-priority Data root at the end.
                if dl == 'data' and not is_vanilla_data:
                    continue
                child_real = os.path.normcase(os.path.realpath(os.path.join(cur, d)))
                if child_real in seen_dirs:
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs

            dpl = dpl_by_dir.get(real_cur) or {}
            local_cpks = []
            for fn in sorted(files):
                if report['files_scanned'] >= MAX_FILES:
                    break
                low = fn.lower()
                p = os.path.join(cur, fn)
                if low.endswith(CPK_EXT):
                    real_p = os.path.normcase(os.path.realpath(p))
                    if real_p not in seen_cpks:
                        seen_cpks.add(real_p)
                        local_cpks.append((low, p))
                    continue
                if not low.endswith(IMG_EXT):
                    continue
                report['files_scanned'] += 1
                rel = os.path.relpath(p, root).replace(os.sep, '/')
                if not _looks_crest(rel):
                    continue
                desc = dict(kind='file', path=p, ext=low.rsplit('.', 1)[-1])
                file_tier = 4 if is_harvest else 0
                got = _id_from_name(fn, rel, names)
                if got:
                    tid, vrank = got
                    rank = (file_tier, 0, _path_rank(rel), vrank, low.endswith('.dds'), len(rel))
                    found.append((rank, tid, desc, rel))
                else:
                    stem = _TRAIL_TAG.sub('', fn.rsplit('.', 1)[0])
                    nk = _norm(stem)
                    # Keep club-named loose PNGs available by name even if not in teamids yet,
                    # except obvious non-club filenames containing digits (e.g. `somefile201.png`).
                    if nk and not any(ch.isdigit() for ch in stem) and len(nk) >= 3:
                        rank = (file_tier, 0, _path_rank(rel), 0, low.endswith('.dds'), len(rel))
                        found_names.append((rank, nk, desc))
                        sk = _norm_stripped(stem)
                        if sk and sk != nk:
                            found_names.append((rank, sk, desc))
                    else:
                        report['skipped'] += 1

            non_dpl = [it for it in local_cpks if it[0] not in dpl]
            non_dpl.sort(key=lambda t: t[0], reverse=True)
            for low, full in local_cpks:
                if low in dpl:
                    cpk_queue.append(((1, -dpl[low]), full))
            for r_idx, (_, full) in enumerate(non_dpl):
                tier = 3 if is_vanilla_data else 2
                cpk_queue.append(((tier, r_idx), full))

    cpk_queue.sort(key=lambda item: item[0])
    for (cpk_tier, cpk_order), cpk_path in cpk_queue[:MAX_CPK]:
        report['cpk_archives'] += 1
        _scan_cpk(cpk_path, names, found, found_names, report, cpk_tier, cpk_order)

    for rank, tid, desc, display in sorted(found, key=lambda x: (x[0], x[1])):
        index.setdefault(tid, desc)
    for rank, nk, desc in sorted(found_names, key=lambda x: x[0]):
        by_name.setdefault(nk, desc)

    report['logos_found'] = len(index) + sum(
        1 for nk in by_name if nk not in names)
    report['clubs_matched'] = sum(1 for t in index if str(t) in idnames)
    # Prefer clubs present in the user's save database in the sample preview.
    sample_ids = sorted(index, key=lambda t: (0 if str(t) in idnames else 1, t))
    for tid in sample_ids[:12]:
        desc = index[tid]
        report['sample'].append(dict(
            id=tid, name=idnames.get(str(tid), ''),
            file=desc.get('path', '') if desc['kind'] == 'file' else desc.get('entry', ''),
            source=desc['kind']))
    _STATE.update(key=key, time=time.time(), index=index, by_name=by_name, report=report)
    return index, report


def _scan_cpk(archive, names, found, found_names, report, cpk_tier=2, cpk_order=0):
    try:
        import cpkread
        cp = cpkread.Cpk(archive)
    except Exception as e:
        report['errors'].append('%s: %s' % (os.path.basename(archive), str(e)[:120]))
        return
    for entry in cp.files:
        low = entry.replace('\\', '/').lower()
        base = low.rsplit('/', 1)[-1]
        if not base.endswith(('.png', '.dds', '.jpg', '.jpeg', '.ftex', '.bmp', '.webp')):
            continue
        if _has_not_crest_segment(low):
            continue
        if not ('/render/symbol/flag/' in ('/' + low) or _looks_crest(low)):
            continue
        report['cpk_entries'] += 1
        got = _id_from_name(base, low, names)
        if not got:
            report['skipped'] += 1
            continue
        tid, vrank = got
        rank = (cpk_tier, cpk_order, _path_rank(low), vrank, low.endswith('.dds'), len(low))
        found.append((rank, tid,
                      dict(kind='cpk', archive=archive, entry=entry,
                           ext=base.rsplit('.', 1)[-1]),
                      '%s!%s' % (os.path.basename(archive), entry)))


def _id_names(cfg):
    """{id string -> club name}, PES 2017 database preferred."""
    _ensure_pes17_teamids(cfg)
    out = {}
    for rel in (os.path.join('data', 'pes17', 'teamids.json'),
                os.path.join('data', 'teamids.json')):
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if v and str(k) not in out:
                        out[str(k)] = str(v)
        except Exception:
            pass
        if out and rel.startswith(os.path.join('data', 'pes17')):
            # Merge base teamids only for IDs absent from PES 2017 teamids.
            continue
    return out


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
        if key and key in names:
            return names[key]
    if names:
        target = _norm(s)
        if target:
            close = difflib.get_close_matches(target, list(names), n=1, cutoff=0.86)
            if close:
                return names[close[0]]
    return None


def _unwesys(raw):
    """WESYS/zlib wrapper found in PES 2017 / FL CPK entries and Sider extracts."""
    if not raw or len(raw) < 12:
        return raw
    if b'WESYS' in (raw[:5], raw[3:8]):
        for st in (16, 12, 20, 24, 8):
            try:
                return zlib.decompress(raw[st:])
            except Exception:
                pass
        try:
            return zlib.decompressobj(-15).decompress(raw[16:])
        except Exception:
            return raw
    if (raw[:8] == b'\x89PNG\r\n\x1a\n' or raw[:4] in (b'DDS ', b'FTEX', b'RIFF')
            or raw[:2] in (b'\xff\xd8', b'BM')):
        return raw
    if len(raw) > 16 and raw[0] == 0x78 and ((raw[0] * 256 + raw[1]) % 31 == 0):
        try:
            return zlib.decompress(raw)
        except Exception:
            pass
    return raw


def _dds_extra_to_png(raw):
    """Handle DX10 BC7/RGBA and 24-bit uncompressed RGB DDS emblems."""
    if len(raw) < 128 or raw[:4] != b'DDS ':
        return None
    import dds
    h, w = struct.unpack_from('<II', raw, 12)
    if not (0 < w <= 4096 and 0 < h <= 4096):
        return None
    pf_flags, fourcc, bits, rmask, gmask, bmask, amask = struct.unpack_from('<I4s5I', raw, 80)
    pos = 128
    if fourcc == b'DX10' and len(raw) >= 148:
        dxgi_fmt = struct.unpack_from('<I', raw, 128)[0]
        pos = 148
        if dxgi_fmt in (98, 99):
            import bc7
            return dds.to_png(w, h, bc7.decode(raw[pos:], w, h))
        if dxgi_fmt in (28, 29) and len(raw) >= pos + w * h * 4:
            return dds.to_png(w, h, raw[pos:pos + w * h * 4])
        if dxgi_fmt in (87, 88) and len(raw) >= pos + w * h * 4:
            src = raw[pos:pos + w * h * 4]
            out = bytearray(w * h * 4)
            out[0::4], out[1::4], out[2::4], out[3::4] = src[2::4], src[1::4], src[0::4], src[3::4]
            return dds.to_png(w, h, bytes(out))
    if not (pf_flags & 0x4) and bits == 24 and len(raw) >= pos + w * h * 3:
        src = raw[pos:pos + w * h * 3]
        out = bytearray(w * h * 4)
        bgr = (rmask == 0xff0000)
        out[0::4] = src[2::3] if bgr else src[0::3]
        out[1::4] = src[1::3]
        out[2::4] = src[0::3] if bgr else src[2::3]
        out[3::4] = b'\xff' * (w * h)
        return dds.to_png(w, h, bytes(out))
    return None


def _to_png(raw, ext):
    if not raw or len(raw) > MAX_BYTES:
        return None
    # Sniff magic bytes first so `.dds`-named PNGs and `.png`-named DDS files work.
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return raw
    if raw[:2] == b'\xff\xd8':
        return raw
    if raw[:2] == b'BM':
        return raw
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return raw
    if raw[:4] == b'DDS ':
        out = None
        try:
            import dds
            out = dds.dds_to_png(raw)
        except Exception:
            out = None
        if out:
            return out
        try:
            return _dds_extra_to_png(raw)
        except Exception:
            return None
    if raw[:4] == b'FTEX' or ext == 'ftex':
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


def _load_desc(ck, desc):
    if ck in _PNG:
        return _PNG[ck]
    try:
        if desc['kind'] == 'file':
            with open(desc['path'], 'rb') as f:
                raw = _unwesys(f.read(MAX_BYTES + 1))
        else:
            import cpkread
            raw = _unwesys(cpkread.Cpk(desc['archive']).read(desc['entry']))
        if not raw or len(raw) > MAX_BYTES:
            return None
        png = _to_png(raw, desc['ext'])
        if png and len(png) <= MAX_BYTES:
            if len(_PNG) > 256:
                _PNG.clear()
            _PNG[ck] = png
            return png
    except Exception:
        return None
    return None


def crest_img(name_or_id, cfg):
    """Image bytes for a club crest, or None (caller keeps its normal fallback)."""
    index, _ = scan(cfg)
    by_name = _STATE.get('by_name') or {}
    if not index and not by_name:
        return None
    s = str(name_or_id or '').strip()
    if s and not s.isdigit() and by_name:
        for nk in (_norm(s), _norm_stripped(s)):
            if nk and nk in by_name:
                desc = by_name[nk]
                ck = ('nm', nk, desc.get('path') or desc.get('archive'), desc.get('entry'))
                got = _load_desc(ck, desc)
                if got:
                    return got
    tid = resolve(cfg, name_or_id)
    if tid is None:
        return None
    desc = index.get(tid)
    if not desc:
        return None
    ck = (tid, desc.get('path') or desc.get('archive'), desc.get('entry'))
    return _load_desc(ck, desc)


def count(cfg):
    try:
        idx, _ = scan(cfg)
        return len(idx) + len(_STATE.get('by_name') or {})
    except Exception:
        return 0


def report(cfg, force=False):
    try:
        idx, rep = scan(cfg, force=force)
        out = dict(rep)
        extra_nm = sum(1 for nk in (_STATE.get('by_name') or {})
                       if nk not in _team_map(cfg))
        out['logos_found'] = len(idx) + extra_nm
        idnames = _id_names(cfg)
        out['clubs_matched'] = sum(1 for t in idx if str(t) in idnames)
        out['available'] = out['logos_found'] > 0
        return out
    except Exception as e:
        return dict(ok=False, available=False, error=str(e)[:200],
                    roots=roots_for(cfg)[0])


def clear():
    """Drop the in-memory index (called when pes17_patch_dir changes)."""
    _STATE.update(key=None, time=0.0, index={}, by_name={}, report={})
    _PNG.clear()
