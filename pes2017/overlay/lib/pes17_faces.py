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
import time
import zlib

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
CACHE_TTL = 300.0

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
_PNG = {}
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
    """Existing folders to scan for player mini-faces, in priority order."""
    cfg = cfg or {}
    explicit = os.path.expandvars((cfg.get('pes17_patch_dir') or '').strip().strip('"'))
    if explicit and os.path.isfile(explicit) and explicit.lower().endswith(('.exe', '.cpk', '.bin')):
        explicit = os.path.dirname(explicit)

    harvest_dir = os.path.join(HERE, 'data', 'pes17', 'harvest', 'face')
    gface_dir = os.path.join(HERE, 'data', 'gface')
    tail = [d for d in (harvest_dir, gface_dir) if _dir_has_imgs(d)]

    def _expand_base(base):
        cands = list(_sider_roots(base))
        cands.extend([
            os.path.join(base, 'livecpk'),
            os.path.join(base, 'SiderAddons'),
            os.path.join(base, 'minifaces'),
            os.path.join(base, 'miniface'),
            os.path.join(base, 'faces'),
            os.path.join(base, 'portraits'),
            os.path.join(base, 'patch'),
            os.path.join(base, 'patches'),
            os.path.join(base, 'content'),
            os.path.join(base, 'WEPES'),
            os.path.join(base, 'download'),
            base,
            os.path.join(base, 'Data'),
        ])
        return cands

    if explicit:
        if not os.path.isdir(explicit):
            return tail, False
        cands = _expand_base(explicit) + tail
        out, seen = [], set()
        for c in cands:
            nc = os.path.normcase(os.path.normpath(c))
            if os.path.isdir(c) and nc not in seen:
                seen.add(nc)
                out.append(os.path.normpath(c))
        return out, False

    exe = os.path.expandvars((cfg.get('pes_exe') or '').strip().strip('"'))
    game = exe if os.path.isdir(exe) else (os.path.dirname(exe) if exe else '')
    cands = (_expand_base(game) if (game and os.path.isdir(game)) else []) + tail
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
                        cpk.append((e, s.st_size, int(s.st_mtime)))
                    except OSError:
                        pass
            h.update(repr((r, int(st.st_mtime), len(entries), tuple(cpk))).encode('utf-8'))
        except Exception as e:
            h.update(repr((r, str(e))).encode('utf-8'))
    return h.hexdigest()


def scan(cfg, force=False):
    """Build ``{pid: (kind, path_or_archive, entry_or_none, ext)}`` and scan stats."""
    cfg = cfg or {}
    roots, auto = roots_for(cfg)
    sig = _signature(roots)
    key = (tuple(roots), sig)
    if not force and _STATE['key'] == key and (time.time() - _STATE['time']) < CACHE_TTL:
        return _STATE['index'], _STATE['meta']

    explicit_dir = os.path.expandvars((cfg.get('pes17_patch_dir') or '').strip().strip('"'))
    if explicit_dir and os.path.isfile(explicit_dir):
        explicit_dir = os.path.dirname(explicit_dir)
    explicit_real = (os.path.normcase(os.path.realpath(explicit_dir))
                     if (explicit_dir and os.path.isdir(explicit_dir)) else '')

    meta = dict(
        ok=True, source='pes17_patch', auto=auto, explicit=bool(cfg.get('pes17_patch_dir')),
        roots=roots, files_scanned=0, cpk_archives=0, cpk_entries=0,
        faces_found=0, skipped=0, errors=[],
        hint=('Expected: common/render/symbol/player/<pid>.dds or <pid>.png '
              'inside download/*.cpk / Data/*.cpk, or loose livecpk / minifaces '
              'folders. Set pes17_patch_dir to your PES 2017 game or patch folder.'))

    best = {}           # pid -> (rank_tuple, (kind, src, entry, ext))
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
        root_norm = root.replace('\\', '/').lower().rstrip('/')
        root_base = root_norm.rsplit('/', 1)[-1]
        is_vanilla_data = (root_base == 'data')
        is_cache_tier = (root_base == 'gface' or ('/harvest/face' in root_norm))
        root_real = os.path.normcase(os.path.realpath(root))
        root_is_face_dir = (
            root_base in FACE_WORDS
            or any(w in root_base for w in ('miniface', 'portrait', 'gface'))
            or (explicit_real and root_real == explicit_real
                and root_base not in NOT_FACE_WORDS)
        )

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
                rank = (file_tier, 0, _path_rank(low_rel), 1 if ext == 'dds' else 0, len(low_rel))
                prev = best.get(pid)
                if prev is None or rank < prev[0]:
                    best[pid] = (rank, ('file', p, None, ext))

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
        meta['cpk_archives'] += 1
        _scan_cpk(cpk_path, best, meta, cpk_tier, cpk_order)

    index = {pid: rec for pid, (_, rec) in best.items()}
    meta['faces_found'] = len(index)
    _STATE.update(key=key, time=time.time(), index=index, meta=meta)
    return index, meta


def _scan_cpk(archive, best, meta, cpk_tier=2, cpk_order=0):
    try:
        import cpkread
        cp = cpkread.Cpk(archive)
    except Exception as e:
        meta['errors'].append('%s: %s' % (os.path.basename(archive), str(e)[:120]))
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
        rank = (cpk_tier, cpk_order, _path_rank(low), 1 if ext == 'dds' else 0, len(low))
        prev = best.get(pid)
        if prev is None or rank < prev[0]:
            best[pid] = (rank, ('cpk', archive, entry, ext))


def _unwesys(raw):
    """Unwrap WESYS / raw zlib wrappers used in PES 2017 CPKs and loose extracts."""
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


def _load_rec(pid, rec):
    kind, src, entry, ext = rec
    ck = (pid, src, entry)
    if ck in _PNG:
        return _PNG[ck]
    try:
        if kind == 'file':
            with open(src, 'rb') as f:
                raw = _unwesys(f.read(MAX_BYTES + 1))
        else:
            import cpkread
            raw = _unwesys(cpkread.Cpk(src).read(entry))
        if not raw or len(raw) > MAX_BYTES:
            return None
        img = _to_png(raw, ext)
        if img and len(img) <= MAX_BYTES:
            if len(_PNG) > 512:
                _PNG.clear()
            _PNG[ck] = img
            return img
    except Exception:
        return None
    return None


def face_img(pid, cfg):
    """Image bytes for a PES 2017 player mini-face, or None."""
    try:
        p = int(pid)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    index, _ = scan(cfg)
    if not index:
        return None
    rec = index.get(p)
    if rec is None and p >= (1 << 20):
        rec = index.get(p & 0xFFFFF)
    if rec is None:
        return None
    return _load_rec(p, rec)


def _player_names(cfg):
    """Read `{pid: name}` from `data/pes17/players.json` or `EDIT00000000`."""
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
    return {}


def _active_squad(cfg, names):
    """List of `(pid, shirt, name)` for the user's club in the newest `ML*` save."""
    cfg = cfg or {}
    sd = (cfg.get('save_dir') or '').strip()
    if not sd or not os.path.isdir(sd):
        return []
    try:
        mls = []
        for fn in os.listdir(sd):
            if fn.upper().startswith('ML') and len(fn) >= 10:
                fp = os.path.join(sd, fn)
                if os.path.isfile(fp):
                    mls.append((os.path.getmtime(fp), fp))
        if not mls:
            return []
        mls.sort(reverse=True)
        mp = mls[0][1]
        st = os.stat(mp)
        mk = (mp, st.st_size, st.st_mtime_ns, len(names))
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


def report(cfg, force=False):
    try:
        idx, meta = scan(cfg, force=force)
        out = dict(meta)
        names = _player_names(cfg)
        squad = _active_squad(cfg, names)
        squad_ids = [pid for pid, _, _ in squad]
        squad_map = {pid: (sh, nm) for pid, sh, nm in squad}
        out['faces_found'] = len(idx)
        out['players_matched'] = sum(1 for pid in idx if pid in names) if names else 0
        out['squad_total'] = len(squad)
        out['squad_matched'] = sum(1 for pid in squad_ids if pid in idx)
        out['available'] = len(idx) > 0

        # Sample order: user's squad players with faces -> matched EDIT players -> other IDs
        ordered = []
        seen = set()
        for pid in squad_ids:
            if pid in idx and pid not in seen:
                seen.add(pid)
                ordered.append(pid)
        if len(ordered) < 12 and names:
            for pid in sorted(p for p in idx if p in names and p not in seen)[:12 - len(ordered)]:
                seen.add(pid)
                ordered.append(pid)
        if len(ordered) < 12:
            for pid in sorted(p for p in idx if p not in seen)[:12 - len(ordered)]:
                seen.add(pid)
                ordered.append(pid)

        sample = []
        for pid in ordered[:12]:
            kind, src, entry, _ = idx[pid]
            sh, snm = squad_map.get(pid, (0, ''))
            nm = snm or names.get(pid, '')
            sample.append(dict(
                id=pid,
                name=nm,
                shirt=sh,
                in_squad=(pid in squad_map),
                source=kind,
                file=src if kind == 'file' else ('%s!%s' % (os.path.basename(src), entry)),
            ))
        out['sample'] = sample
        return out
    except Exception as e:
        return dict(ok=False, available=False, error=str(e)[:200],
                    roots=roots_for(cfg)[0], faces_found=0, sample=[])


def clear():
    """Drop in-memory face index and decoded portrait cache."""
    _STATE.update(key=None, time=0.0, index={}, meta={})
    _PNG.clear()
    _DB_CACHE.update(edit_key=None, players={}, ml_key=None, squad=[])
