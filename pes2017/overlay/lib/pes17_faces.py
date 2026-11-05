"""Read player mini-faces (portraits) from a PES 2017 game / patch folder (offline, read-only).

In PES 2017 and community patches (T99 Patch, PTE, SmokePatch, Professionals,
Sider livecpk miniface packs), 2D player portraits live at:

* ``common/render/symbol/player/<pid>.(dds|png)`` inside ``download/*.cpk``
  (mounted in ``DpFileList.bin`` order) and vanilla ``Data/*.cpk`` (``dt15_win.cpk`` /
  ``dt14_win.cpk``),
* loose ``livecpk/*/common/render/symbol/player/<pid>.(dds|png)`` or dedicated
  ``minifaces/`` / ``faces/`` / ``portraits/`` folders,
* harvested ``data/pes17/harvest/face/face_<pid>_<hash>.png`` or ``data/gface/<pid>.png``.

Unlike 3D head UV skin textures under ``model/character/face/real/<pid>/`` (which
are unwrapped 3D meshes and intentionally excluded here), ``render/symbol/player``
holds the real 2D UI mini-faces keyed directly by Konami / EDIT00000000 player ID.

Nothing is written to the game, patch, or save folder.  No network access, no
external dependency.  Every lookup is best-effort and read-only.
"""
import hashlib
import json
import os
import re
import struct
import threading
import time
import zlib
from collections import OrderedDict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMG_EXT = ('.png', '.dds', '.jpg', '.jpeg', '.ftex', '.bmp', '.webp')
CPK_EXT = ('.cpk',)
SKIP_DIRS = frozenset((
    '__pycache__', '.git', '.svn', 'node_modules', 'backup', 'backups',
    'work', 'save', 'saves', 'cache', 'temp', 'tmp', 'logs', 'dist', 'build',
    'sound', 'movie',
))
MAX_FILES = 100000
MAX_DEPTH = 8
MAX_CPK = 128
MAX_BYTES = 8 * 1024 * 1024
MAX_CANDIDATES = 8
MAX_CACHED_CPKS = 6
MAX_CACHED_BYTES = 64 * 1024 * 1024
CACHE_TTL = 300.0
QUICK_CHECK_TTL = 2.0  # coalesce bursts of lookups without delaying manual rescan

FACE_WORDS = ('player', 'players', 'miniface', 'minifaces', 'face', 'faces',
              'portrait', 'portraits', 'coachml', 'gface')
# Directory segments that never hold 2D player portraits (notably 3D face UV
# meshes under model/character/face/real/, club emblems, kits, and FL26 regen slots).
NOT_FACE_WORDS = frozenset((
    'flag', 'flags', 'emblem', 'emblems', 'emblemlc', 'crest', 'crests',
    'logo', 'logos', 'badge', 'badges', 'kit', 'kits', 'uniform', 'uniforms',
    'stadium', 'stadiums', 'adboard', 'ball', 'balls', 'boots', 'boot',
    'glove', 'gloves', 'trophy', 'sound', 'movie', 'pesdb',
    'model', 'character', 'character0', 'character1', 'real',
    'hair', 'tattoo', 'eye', 'regen', 'coach',
))

_PREFIX_PID = re.compile(
    r'^(?:player|miniface|face|portrait|p)[_\-]?0*(\d{1,8})(?:_[0-9a-f]{6})?$',
    re.I)
_PLAIN_PID = re.compile(r'^0*(\d{1,8})$')
_CREST_OR_KIT = re.compile(
    r'^(?:u\d{3,5}[pg]\d+|emb_\d+|emblem_\d+|flag_\d+|crest_\d+|logo_\d+|e_\d+)',
    re.I)

_STATE = {'key': None, 'time': 0.0, 'index': {}, 'meta': {}}
# A threaded server can request dozens of portraits at once.  Only one thread
# builds the directory/CPK index; decoded bytes and open TOCs have separate,
# bounded caches.  A forced scan clears both so changed files really reload.
_SCAN_LOCK = threading.RLock()
_PNG_LOCK = threading.RLock()
_CPK_LOCK = threading.RLock()
_DB_LOCK = threading.RLock()
_PNG = OrderedDict()
_CPK = OrderedDict()
_CACHE_REV = {'value': 0}
_DB_CACHE = {'edit_key': None, 'players': {}, 'ml_key': None, 'squad': []}


def _sider_roots(base_dir):
    """Read optional `sider.ini` `cpk.root` directories inside `base_dir`."""
    out = []
    if not base_dir or not os.path.isdir(base_dir):
        return out
    ini = os.path.join(base_dir, 'sider.ini')
    if not os.path.isfile(ini):
        return out
    try:
        with open(ini, encoding='utf-8', errors='ignore') as f:
            for line in f:
                m = re.match(r'\s*cpk\.root\s*=\s*"?([^";\r\n]+)"?', line)
                if not m:
                    continue
                pth = m.group(1).strip().replace('\\', os.sep).replace('/', os.sep)
                if not os.path.isabs(pth):
                    pth = os.path.normpath(os.path.join(base_dir, pth))
                if os.path.isdir(pth) and pth not in out:
                    out.append(pth)
    except OSError:
        pass
    return out


def _dir_has_imgs(folder):
    if not os.path.isdir(folder):
        return False
    try:
        for fn in os.listdir(folder):
            if fn.lower().endswith(IMG_EXT):
                return True
    except OSError:
        pass
    return False


def roots_for(cfg):
    """Existing folders to scan, with an explicit patch first and game fallback.

    A user may choose the game's ``download`` directory rather than its parent.
    In that case include sibling ``Data`` / Sider directories as well; vanilla
    and loose portraits often live there.  A separately configured patch stays
    ahead of a separately configured game.  All sources are read-only.
    """
    cfg = cfg or {}
    explicit = os.path.expandvars((cfg.get('pes17_patch_dir') or '').strip().strip('"'))
    if explicit and os.path.isfile(explicit):
        explicit = os.path.dirname(explicit)
    exe = os.path.expandvars((cfg.get('pes_exe') or '').strip().strip('"'))
    game = exe if os.path.isdir(exe) else (os.path.dirname(exe) if exe else '')

    harvest_dir = os.path.join(HERE, 'data', 'pes17', 'harvest', 'face')
    gface_dir = os.path.join(HERE, 'data', 'gface')
    tail = [d for d in (harvest_dir, gface_dir) if _dir_has_imgs(d)]

    def _expand_base(base):
        try:
            children = {name.lower(): os.path.join(base, name) for name in os.listdir(base)}
        except OSError:
            children = {}
        cands = list(_sider_roots(base))
        for name in ('livecpk', 'SiderAddons', 'minifaces', 'miniface', 'faces',
                     'portraits', 'patch', 'patches', 'content', 'WEPES', 'download'):
            cands.append(children.get(name.lower(), os.path.join(base, name)))
        cands.extend((base, children.get('data', os.path.join(base, 'Data'))))
        return cands

    bases = []
    if explicit and os.path.isdir(explicit):
        bases.append(explicit)
        # Only infer a parent from known game subfolders and actual nearby game
        # evidence, never from an arbitrary standalone mini-face directory.
        parent = os.path.dirname(os.path.normpath(explicit))
        leaf = os.path.basename(os.path.normpath(explicit)).lower()
        if leaf in ('download', 'data', 'livecpk', 'sideraddons') and parent:
            try:
                siblings = {name.lower() for name in os.listdir(parent)}
            except OSError:
                siblings = set()
            if siblings.intersection(('pes2017.exe', 'pes2017_x64.exe', 'data',
                                      'download', 'livecpk', 'sideraddons')) - {leaf}:
                bases.append(parent)
    if game and os.path.isdir(game):
        bases.append(game)

    cands = []
    for base in bases:
        cands.extend(_expand_base(base))
    cands.extend(tail)
    out, seen = [], set()
    for c in cands:
        nc = os.path.normcase(os.path.realpath(c))
        if os.path.isdir(c) and nc not in seen:
            seen.add(nc)
            out.append(os.path.normpath(c))
    return out, not bool(explicit)


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


def _has_not_face_segment(rel_path):
    parts = [seg for seg in rel_path.replace('\\', '/').lower().split('/') if seg]
    dirs, fn = parts[:-1], (parts[-1] if parts else '')
    stem = fn.rsplit('.', 1)[0]
    if _CREST_OR_KIT.match(stem):
        return True
    for seg in dirs:
        if seg in NOT_FACE_WORDS:
            return True
        if any(w in seg for w in ('emblem', 'crest', 'uniform', 'stadium', 'adboard',
                                  'boots', 'glove', 'trophy')):
            return True
    return False


def _path_rank(low_path):
    p = '/' + low_path.lstrip('/')
    if '/render/symbol/player/' in p:
        return 0
    if '/render/symbol/coachml/' in p:
        return 2
    if any(w in p for w in ('/miniface', '/portrait', '/player/', '/faces/', '/face/', '/gface')):
        return 1
    return 2


def _pid_from_entry(base, low_rel, allow_root_plain=False):
    """Extract positive integer `pid` from a miniface filename + relative path, else None."""
    if _has_not_face_segment(low_rel):
        return None
    stem = base.rsplit('.', 1)[0]
    m = _PREFIX_PID.match(stem)
    if m:
        pid = int(m.group(1))
        return pid if pid > 0 else None
    m = _PLAIN_PID.match(stem)
    if not m:
        return None
    pid = int(m.group(1))
    if pid <= 0:
        return None
    p = '/' + low_rel.lstrip('/')
    if ('/render/symbol/player/' in p or '/render/symbol/coachml/' in p
            or any('/' + w + '/' in p for w in FACE_WORDS)):
        return pid
    parts = [seg for seg in low_rel.split('/') if seg]
    if len(parts) >= 2 and any(w in parts[-2] for w in FACE_WORDS):
        return pid
    if allow_root_plain and len(parts) == 1:
        return pid
    return None


def _signature(roots):
    h = hashlib.sha256()
    for r in roots:
        try:
            st = os.stat(r)
            entries = sorted(os.listdir(r))
            cpk = []
            for e in entries:
                low = e.lower()
                if low.endswith(CPK_EXT) or low in ('dpfilelist.bin', 'sider.ini'):
                    p = os.path.join(r, e)
                    try:
                        s = os.stat(p)
                        cpk.append((e, s.st_size, s.st_mtime_ns))
                    except OSError:
                        pass
            h.update(repr((r, st.st_mtime_ns, len(entries), tuple(cpk))).encode('utf-8'))
        except Exception as e:
            h.update(repr((r, str(e))).encode('utf-8'))
    return h.hexdigest()


def scan(cfg, force=False):
    """Build an ordered, bounded list of portrait candidates for each ID."""
    with _SCAN_LOCK:
        return _scan(cfg, force)


def _drop_portrait_caches():
    _CACHE_REV['value'] += 1
    with _PNG_LOCK:
        _PNG.clear()
    with _CPK_LOCK:
        _CPK.clear()


def _scan(cfg, force=False):
    cfg = cfg or {}
    now = time.time()
    quick_key = (cfg.get('pes17_patch_dir') or '', cfg.get('pes_exe') or '', HERE)
    if (not force and _STATE.get('quick_key') == quick_key
            and now - _STATE.get('checked', 0) < QUICK_CHECK_TTL
            and now - _STATE['time'] < CACHE_TTL):
        return _STATE['index'], _STATE['meta']
    if force:
        _drop_portrait_caches()
    roots, auto = roots_for(cfg)
    sig = _signature(roots)
    key = (tuple(roots), sig, cfg.get('pes17_patch_dir') or '', cfg.get('pes_exe') or '')
    if not force and _STATE['key'] == key and (now - _STATE['time']) < CACHE_TTL:
        _STATE.update(quick_key=quick_key, checked=now)
        return _STATE['index'], _STATE['meta']

    explicit_dir = os.path.expandvars((cfg.get('pes17_patch_dir') or '').strip().strip('"'))
    if explicit_dir and os.path.isfile(explicit_dir):
        explicit_dir = os.path.dirname(explicit_dir)
    explicit_real = (os.path.normcase(os.path.realpath(explicit_dir))
                     if (explicit_dir and os.path.isdir(explicit_dir)) else '')

    explicit_roots = set()
    if explicit_real:
        explicit_roots = {os.path.normcase(os.path.realpath(p))
                          for p in roots_for({'pes17_patch_dir': explicit_dir})[0]}
    meta = dict(
        ok=True, source='pes17_patch', auto=auto, explicit=bool(cfg.get('pes17_patch_dir')),
        explicit_valid=bool(explicit_real), roots=roots, files_scanned=0,
        cpk_archives=0, cpk_entries=0, candidate_truncated=0,
        faces_found=0, skipped=0, errors=[],
        hint=('Expected: common/render/symbol/player/<pid>.dds or <pid>.png '
              'inside download/*.cpk / Data/*.cpk, or loose livecpk / minifaces '
              'folders. Set pes17_patch_dir to your PES 2017 game or patch folder.'))

    best = {}           # pid -> [(rank_tuple, (kind, src, entry, ext)), ...]
    cpk_queue = []      # ((source_group, cpk_tier, cpk_order), cpk_path)
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
        root_norm = root.replace('\\', '/').lower().rstrip('/')
        root_base = root_norm.rsplit('/', 1)[-1]
        is_vanilla_data = (root_base == 'data')
        is_cache_tier = (root_base == 'gface' or ('/harvest/face' in root_norm))
        root_real = os.path.normcase(os.path.realpath(root))
        source_group = (2 if is_cache_tier else
                        1 if explicit_roots and root_real not in explicit_roots else 0)
        root_is_face_dir = (
            root_base in FACE_WORDS
            or any(w in root_base for w in ('miniface', 'portrait', 'gface'))
            or (explicit_real and root_real == explicit_real
                and root_base not in NOT_FACE_WORDS)
        )

        def walk_error(exc):
            if len(meta['errors']) < 20:
                meta['errors'].append('Cannot read %s: %s' % (getattr(exc, 'filename', root), str(exc)[:120]))

        for cur, dirs, files in os.walk(root, onerror=walk_error):
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
                if dl == 'data' and not is_vanilla_data:
                    continue
                # Prune huge 3D asset trees early so loose walks stay instant.
                if dl in ('model', 'character', 'character0', 'character1',
                          'stadium', 'uniform', 'boots', 'glove', 'ball', 'flag'):
                    continue
                child_real = os.path.normcase(os.path.realpath(os.path.join(cur, d)))
                if child_real in seen_dirs:
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs

            dpl = dpl_by_dir.get(real_cur) or {}
            local_cpks = []
            for fn in sorted(files):
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
                if meta['files_scanned'] >= MAX_FILES:
                    continue
                meta['files_scanned'] += 1
                rel = os.path.relpath(p, root).replace(os.sep, '/')
                low_rel = rel.lower()
                pid = _pid_from_entry(low, low_rel, allow_root_plain=root_is_face_dir)
                if pid is None:
                    meta['skipped'] += 1
                    continue
                ext = low.rsplit('.', 1)[-1]
                file_tier = 4 if is_cache_tier else 0
                rank = (source_group, file_tier, 0, _path_rank(low_rel),
                        1 if ext == 'dds' else 0, len(low_rel))
                _add_candidate(best, pid, rank, ('file', p, None, ext), meta)

            non_dpl = [it for it in local_cpks if it[0] not in dpl]
            non_dpl.sort(key=lambda t: t[0], reverse=True)
            for low, full in local_cpks:
                if low in dpl:
                    cpk_queue.append(((source_group, 1, -dpl[low]), full))
            for r_idx, (_, full) in enumerate(non_dpl):
                tier = 3 if is_vanilla_data else 2
                cpk_queue.append(((source_group, tier, r_idx), full))

    cpk_queue.sort(key=lambda item: item[0])
    meta['cpk_archives_seen'] = len(cpk_queue)
    meta['scan_truncated'] = (len(cpk_queue) > MAX_CPK or meta['files_scanned'] >= MAX_FILES)
    for (source_group, cpk_tier, cpk_order), cpk_path in cpk_queue[:MAX_CPK]:
        meta['cpk_archives'] += 1
        _scan_cpk(cpk_path, best, meta, cpk_tier, cpk_order, source_group)

    index = {pid: [rec for _, rec in rows] for pid, rows in best.items()}
    meta['faces_found'] = len(index)
    finished = time.time()
    _STATE.update(key=key, time=finished, checked=finished, quick_key=quick_key,
                  index=index, meta=meta)
    return index, meta


def _add_candidate(best, pid, rank, rec, meta):
    rows = best.setdefault(pid, [])
    if any(old == rec for _, old in rows):
        return
    rows.append((rank, rec))
    rows.sort(key=lambda row: row[0])
    if len(rows) > MAX_CANDIDATES:
        rows.pop()
        meta['candidate_truncated'] += 1


def _open_cpk(path):
    """Reuse immutable CPK TOCs, but never keep an archive file handle open."""
    st = os.stat(path)
    key = (os.path.normcase(os.path.realpath(path)), st.st_size,
           st.st_mtime_ns, _CACHE_REV['value'])
    with _CPK_LOCK:
        if key in _CPK:
            _CPK.move_to_end(key)
            return _CPK[key]
        import cpkread
        cp = cpkread.Cpk(path)
        _CPK[key] = cp
        while len(_CPK) > MAX_CACHED_CPKS:
            _CPK.popitem(last=False)
        return cp


def _scan_cpk(archive, best, meta, cpk_tier=2, cpk_order=0, source_group=0):
    try:
        cp = _open_cpk(archive)
    except Exception as e:
        if len(meta['errors']) < 20:
            meta['errors'].append('%s: %s: %s' % (archive, type(e).__name__, str(e)[:120]))
        return
    for entry in cp.files:
        low = entry.replace('\\', '/').lower()
        base = low.rsplit('/', 1)[-1]
        if not base.endswith(IMG_EXT):
            continue
        if not ('/render/symbol/player/' in ('/' + low)
                or '/render/symbol/coachml/' in ('/' + low)
                or 'miniface' in low or 'portrait' in low):
            continue
        meta['cpk_entries'] += 1
        pid = _pid_from_entry(base, low, allow_root_plain=False)
        if pid is None:
            meta['skipped'] += 1
            continue
        ext = base.rsplit('.', 1)[-1]
        rank = (source_group, cpk_tier, cpk_order, _path_rank(low),
                1 if ext == 'dds' else 0, len(low))
        _add_candidate(best, pid, rank, ('cpk', archive, entry, ext), meta)


def _limited_inflate(raw, wbits=zlib.MAX_WBITS):
    d = zlib.decompressobj(wbits)
    out = d.decompress(raw, MAX_BYTES + 1)
    if len(out) > MAX_BYTES:
        return b''
    if not d.eof:
        raise ValueError('incomplete compressed portrait')
    return out


def _unwesys(raw):
    """Unwrap WESYS / zlib using a fixed decompressed-size limit."""
    if not raw or len(raw) < 12:
        return raw
    if b'WESYS' in (raw[:5], raw[3:8]):
        for st in (16, 12, 20, 24, 8):
            try:
                return _limited_inflate(raw[st:])
            except Exception:
                pass
        try:
            return _limited_inflate(raw[16:], -15)
        except Exception:
            return raw
    if (raw[:8] == b'\x89PNG\r\n\x1a\n' or raw[:4] in (b'DDS ', b'FTEX', b'RIFF')
            or raw[:2] in (b'\xff\xd8', b'BM')):
        return raw
    if len(raw) > 16 and raw[0] == 0x78 and ((raw[0] * 256 + raw[1]) % 31 == 0):
        try:
            return _limited_inflate(raw)
        except Exception:
            pass
    return raw


def _dds_extra_to_png(raw):
    """Decode DX10 BC7/RGBA8/BGRA8 and uncompressed 24-bit RGB DDS portraits."""
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
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return raw
    if raw[:2] == b'\xff\xd8':
        return raw
    if raw[:2] == b'BM':
        return raw
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return raw
    if raw[:4] == b'DDS ':
        if len(raw) < 128:
            return None
        h, w = struct.unpack_from('<II', raw, 12)
        if not (0 < w <= 4096 and 0 < h <= 4096):
            return None
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
        if len(raw) < 14 or raw[:4] != b'FTEX':
            return None
        w0, h0 = struct.unpack_from('<HH', raw, 10)
        if not (0 < w0 <= 4096 and 0 < h0 <= 4096):
            return None
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


def _valid_png(raw):
    """Reject truncated/corrupt PNGs instead of reporting them as usable.

    The browser is still the final image decoder.  Checking chunks, CRCs and
    the bounded zlib stream catches invalid files without another dependency.
    """
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return False
    try:
        pos, header, parts, ended, palette = 8, None, [], False, False
        while pos + 12 <= len(raw):
            size = struct.unpack_from('>I', raw, pos)[0]
            if size > MAX_BYTES or pos + 12 + size > len(raw):
                return False
            kind = raw[pos + 4:pos + 8]
            data = raw[pos + 8:pos + 8 + size]
            crc = struct.unpack_from('>I', raw, pos + 8 + size)[0]
            if zlib.crc32(kind + data) & 0xffffffff != crc:
                return False
            if pos == 8:
                if kind != b'IHDR' or size != 13:
                    return False
                header = struct.unpack('>IIBBBBB', data)
            elif kind == b'IHDR':
                return False
            if kind == b'PLTE':
                palette = True
            elif kind == b'IDAT':
                parts.append(data)
            elif kind == b'IEND':
                ended = size == 0
                break
            pos += 12 + size
        if not (header and parts and ended):
            return False
        w, h, depth, color, compression, filtering, interlace = header
        depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                  4: (8, 16), 6: (8, 16)}
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
        if (not (0 < w <= 4096 and 0 < h <= 4096) or color not in depths
                or depth not in depths[color] or compression or filtering
                or interlace not in (0, 1) or (color == 3 and not palette)):
            return False
        passes = ((0, 0, 1, 1),) if not interlace else (
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
            (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
        rows = []
        for sx, sy, dx, dy in passes:
            pw = max(0, (w - sx + dx - 1) // dx)
            ph = max(0, (h - sy + dy - 1) // dy)
            if pw and ph:
                rows.append(((pw * channels[color] * depth + 7) // 8, ph))
        expected = sum((line + 1) * count for line, count in rows)
        if expected > 128 * 1024 * 1024:
            return False
        inf = zlib.decompressobj()
        pixels = inf.decompress(b''.join(parts), expected + 1)
        if len(pixels) != expected or not inf.eof or inf.unconsumed_tail or inf.unused_data:
            return False
        off = 0
        for line, count in rows:
            for _ in range(count):
                if pixels[off] > 4:
                    return False
                off += line + 1
        return True
    except (ValueError, TypeError, struct.error, zlib.error, OverflowError):
        return False


def _load_rec(pid, rec):
    kind, src, entry, ext = rec
    try:
        st = os.stat(src)
        revision = _CACHE_REV['value']
        ck = (src, entry, st.st_size, st.st_mtime_ns, revision)
    except OSError as e:
        return None, 'Cannot read source: %s' % str(e)[:140]
    with _PNG_LOCK:
        if ck in _PNG:
            _PNG.move_to_end(ck)
            return _PNG[ck]
    img = None
    error = ''
    try:
        if kind == 'file':
            with open(src, 'rb') as f:
                raw = f.read(MAX_BYTES + 1)
        else:
            cp = _open_cpk(src)
            item = cp.files.get(entry) or {}
            if any(int(item.get(field) or 0) > MAX_BYTES for field in ('FileSize', 'ExtractSize')):
                raise ValueError('portrait entry exceeds size limit')
            raw = cp.read(entry)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('empty or oversized portrait')
        raw = _unwesys(raw)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('empty or oversized decompressed portrait')
        img = _to_png(raw, ext)
        if not img or len(img) > MAX_BYTES:
            img = None
            error = 'Unsupported or corrupt %s portrait' % ext.upper()
        elif img.startswith(b'\x89PNG\r\n\x1a\n') and not _valid_png(img):
            img = None
            error = 'Corrupt or incomplete PNG portrait'
        elif img.startswith(b'\xff\xd8') and b'\xff\xd9' not in img[2:]:
            img = None
            error = 'Incomplete JPEG portrait'
    except Exception as e:
        img = None
        error = '%s: %s' % (type(e).__name__, str(e)[:140])
    result = (img, error)
    with _PNG_LOCK:
        # An in-flight old read must not repopulate a cache after a rescan.
        if revision == _CACHE_REV['value']:
            _PNG[ck] = result
            _PNG.move_to_end(ck)
            while (len(_PNG) > 512 or
                   sum(len(value[0] or b'') for value in _PNG.values()) > MAX_CACHED_BYTES):
                _PNG.popitem(last=False)
    return result


def _index_pid(index, pid):
    if pid in index:
        return pid
    masked = pid & 0xFFFFF
    return masked if pid >= (1 << 20) and masked in index else None


def _choose_rec(index, pid):
    """Use the highest-priority decodable record, not just the first name."""
    key = _index_pid(index, pid)
    failures = []
    if key is None:
        return None, None, failures
    for rec in index[key]:
        image, error = _load_rec(pid, rec)
        if image:
            return image, rec, failures
        if len(failures) < MAX_CANDIDATES:
            failures.append(dict(source=rec[1], entry=rec[2] or '', error=error))
    return None, None, failures


def face_img(pid, cfg):
    """Image bytes for a PES 2017 player mini-face, or None."""
    try:
        p = int(pid)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    index, _ = scan(cfg)
    return _choose_rec(index, p)[0]


def _player_names(cfg):
    """Prefer the configured EDIT database; use app-generated names as fallback."""
    cfg = cfg or {}
    sd = (cfg.get('save_dir') or '').strip()
    ep = (cfg.get('edit_dat') or (os.path.join(sd, 'EDIT00000000') if sd else '')).strip()
    if ep and os.path.isfile(ep):
        try:
            st = os.stat(ep)
            ek = ('edit', ep, st.st_size, st.st_mtime_ns)
            if _DB_CACHE['edit_key'] == ek:
                return _DB_CACHE['players']
            import pes17
            ed = pes17._edit_data(ep)
            out = {p['id']: p['name'] for p in pes17.parse_edit(ed)}
            _DB_CACHE.update(edit_key=ek, players=out)
            return out
        except Exception:
            pass
    pj = os.path.join(HERE, 'data', 'pes17', 'players.json')
    if os.path.isfile(pj):
        try:
            st = os.stat(pj)
            ek = ('json', pj, st.st_size, st.st_mtime_ns)
            if _DB_CACHE['edit_key'] == ek:
                return _DB_CACHE['players']
            with open(pj, encoding='utf-8') as f:
                rows = json.load(f)
            out = {int(r[0]): str(r[1]) for r in rows if isinstance(r, list) and len(r) >= 2}
            _DB_CACHE.update(edit_key=ek, players=out)
            return out
        except Exception:
            pass
    return {}


def _squad_file(cfg, slot=''):
    sd = (cfg.get('save_dir') or '').strip()
    if not sd or not os.path.isdir(sd):
        return ''
    if slot:
        if not re.fullmatch(r'ML[0-9A-F]{8}', slot, flags=re.I):
            raise ValueError('Invalid PES 2017 ML slot')
        target = os.path.join(sd, slot)
        return target if os.path.isfile(target) else ''
    mls = []
    for fn in os.listdir(sd):
        if re.fullmatch(r'ML[0-9A-F]{8}', fn, flags=re.I):
            fp = os.path.join(sd, fn)
            if os.path.isfile(fp):
                mls.append((os.path.getmtime(fp), fp))
    return max(mls)[1] if mls else ''


def _active_squad(cfg, names, slot=''):
    """List of `(pid, shirt, name)` for the selected (or newest) ML save."""
    try:
        mp = _squad_file(cfg or {}, slot)
        if not mp:
            return []
        st = os.stat(mp)
        mk = (mp, st.st_size, st.st_mtime_ns, _DB_CACHE['edit_key'])
        if _DB_CACHE['ml_key'] == mk:
            return _DB_CACHE['squad']
        import pes17, pescrypt
        with open(mp, 'rb') as f:
            parts = pescrypt.decrypt_bytes(f.read(), pes17.KEY_PES17)
        data = parts['data.dat']
        teams = pes17.team_records(data)
        desc_raw = parts.get('description.dat', b'')
        club_nm = ''
        try:
            dparts = [p for p in desc_raw.split(b'\x00') if p.strip()]
            desc_blk = b''
            for p in dparts[1:] or dparts[:1]:
                if b'/' in p and re.search(rb'\d{1,2}[./\-]\d{1,2}[./\-]\d{4}', p):
                    desc_blk = p
                    break
            if not desc_blk and len(dparts) > 1:
                desc_blk = dparts[1]
            dlines = [x.decode('utf-8', 'replace').strip()
                      for x in desc_blk.replace(b'\r\n', b'\n').split(b'\n') if x.strip()]
            head = dlines[0] if dlines else ''
            head = re.sub(r'^(?:Master\s+League|Become\s+a\s+Legend)\s+', '', head, flags=re.I).strip(' -')
            club_nm = head.split(' / ', 1)[0].strip() if ' / ' in head else head
        except Exception:
            pass
        mine = pes17.find_club(teams, club_nm) if club_nm else None
        if not mine:
            return []
        shirts = pes17.shirt_numbers(data, mine)
        sq = []
        for x in pes17.squad(data, mine, names):
            sq.append((x['id'], shirts[x['slot']] if x['slot'] < len(shirts) else 0, x['name']))
        _DB_CACHE.update(ml_key=mk, squad=sq)
        return sq
    except Exception:
        return []


def count(cfg):
    try:
        idx, _ = scan(cfg)
        return len(idx)
    except Exception:
        return 0


def report(cfg, force=False, slot=''):
    """Report indexed IDs separately from actual read/decode checks.

    Only the selected squad and up to twelve preview portraits are decoded;
    the other indexed files are not assumed to be usable.
    """
    try:
        cfg = cfg or {}
        if slot and not re.fullmatch(r'ML[0-9A-F]{8}', slot, flags=re.I):
            raise ValueError('Invalid PES 2017 ML slot')
        idx, meta = scan(cfg, force=force)
        out = dict(meta)
        with _DB_LOCK:
            names = _player_names(cfg)
            squad_file = _squad_file(cfg, slot)
            squad = _active_squad(cfg, names, slot)
        squad_ids = [pid for pid, _, _ in squad]
        squad_map = {pid: (sh, nm) for pid, sh, nm in squad}
        out['faces_found'] = len(idx)
        out['players_matched'] = sum(1 for pid in idx if pid in names) if names else 0
        out['squad_slot'] = os.path.basename(squad_file) if squad_file else slot
        out['squad_slot_found'] = bool(squad_file)
        out['squad_total'] = len(squad)
        matched = [pid for pid in squad_ids if _index_pid(idx, pid) is not None]
        out['squad_matched'] = len(matched)

        checks = {}
        def checked(pid):
            if pid not in checks:
                checks[pid] = _choose_rec(idx, pid)
            return checks[pid]

        out['squad_decoded'] = sum(1 for pid in matched if checked(pid)[0])
        # Sample order: selected squad -> matching EDIT names -> other IDs.
        ordered, seen, used_index_ids = [], set(), set()
        for pid in matched:
            if pid not in seen:
                seen.add(pid)
                used_index_ids.add(_index_pid(idx, pid))
                ordered.append(pid)
        if len(ordered) < 12 and names:
            for pid in sorted(p for p in idx if p in names and p not in used_index_ids):
                ordered.append(pid)
                seen.add(pid)
                used_index_ids.add(pid)
                if len(ordered) >= 12:
                    break
        if len(ordered) < 12:
            for pid in sorted(p for p in idx if p not in used_index_ids):
                ordered.append(pid)
                used_index_ids.add(pid)
                if len(ordered) >= 12:
                    break

        sample = []
        for pid in ordered[:12]:
            image, chosen, failures = checked(pid)
            key = _index_pid(idx, pid)
            kind, src, entry, _ = chosen or idx[key][0]
            sh, snm = squad_map.get(pid, (0, ''))
            sample.append(dict(
                id=pid, name=snm or names.get(pid, ''), shirt=sh,
                in_squad=(pid in squad_map), source=kind,
                file=src if kind == 'file' else ('%s!%s' % (src, entry)),
                decoded=bool(image), fallback_used=bool(image and failures),
                error=failures[0]['error'] if failures and not image else '',
            ))
        out['sample'] = sample
        out['sample_tested'] = len(sample)
        out['sample_decoded'] = sum(1 for row in sample if row['decoded'])
        out['available'] = bool(out['sample_decoded'] or out['squad_decoded'])
        failures = []
        for pid, (_, _, problems) in checks.items():
            for problem in problems:
                if len(failures) < 10:
                    failures.append(dict(id=pid, **problem))
        out['decode_errors'] = failures
        return out
    except Exception as e:
        return dict(ok=False, available=False, error=str(e)[:200],
                    roots=roots_for(cfg)[0], faces_found=0, sample=[])


def clear():
    """Drop in-memory face index, archive TOCs, decoded portraits and DB data."""
    with _SCAN_LOCK:
        _STATE.update(key=None, time=0.0, checked=0.0, quick_key=None, index={}, meta={})
        _drop_portrait_caches()
        with _DB_LOCK:
            _DB_CACHE.update(edit_key=None, players={}, ml_key=None, squad=[])
