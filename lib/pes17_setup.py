#!/usr/bin/env python3
"""r9: first-run PES 2017 save-folder detection and friendly status.

Pure stdlib, no app imports, no network.  server.py calls ``autodetect()`` from
``load_cfg()`` when no save folder is configured, ``status()`` for
``GET /api/pes17/setup``, ``validate_save_dir()`` for
``POST /api/pes17/setup/savefolder`` and ``unavailable()`` when a read fails.

pc414 shipped a machine-specific FL26 default
(``%USERPROFILE%\\OneDrive\\Dokumenti\\KONAMI\\eFootball PES 2021 SEASON UPDATE\\2026\\save``).
On a PES 2017 machine that folder does not exist, so ``os.listdir()`` threw a
raw ``[Errno 2]``/``[WinError 3]`` into the dashboard.  This module makes the
default empty, looks for a real PES 2017 save folder instead, and turns any
remaining failure into a human-readable message with a fix.
"""
import os
import re

PES17_SUB = os.path.join('KONAMI', 'Pro Evolution Soccer 2017', 'save')
SLOT_RE = re.compile(r'^ML[0-9A-F]{8}$')
# Windows localises "Documents"; OneDrive is often a subfolder of the profile
# or pointed at by an environment variable.
DOC_NAMES = (
    'Documents', 'Dokumenti', 'Documenti', 'Dokumente', 'Documentos',
    'Documenten', 'Dokumenty', 'Mes documents', 'Documents library',
    'Desktop', 'Downloads', 'Radna površina',
)


def home_roots():
    """Plausible profile / Documents / OneDrive roots, most likely first."""
    up = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    bases = [up]
    for key in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        v = os.environ.get(key)
        if v:
            bases.append(v)
    try:
        bases += [os.path.join(up, n) for n in os.listdir(up)
                  if n.lower().startswith('onedrive')]
    except OSError:
        pass
    out = []
    for b in dict.fromkeys(x for x in bases if x):
        out.append(b)
        out += [os.path.join(b, d) for d in DOC_NAMES]
    return list(dict.fromkeys(out))


def slots_in(save_dir):
    """ML slots in a folder, or [] if it is missing / unreadable."""
    try:
        return sorted(f for f in os.listdir(save_dir) if SLOT_RE.match(f))
    except OSError:
        return []


def candidates(roots=None):
    """Existing PES 2017 save folders; folders holding ML saves come first."""
    seen, good, other = set(), [], []
    for root in (roots if roots is not None else home_roots()):
        p = os.path.join(root, PES17_SUB)
        k = os.path.normcase(os.path.normpath(p))
        if k in seen or not os.path.isdir(p):
            continue
        seen.add(k)
        (good if slots_in(p) else other).append(p)
    return good + other


def autodetect(roots=None):
    """Best existing PES 2017 save folder, or '' (never an FL26 guess)."""
    c = candidates(roots)
    return c[0] if c else ''


def suggested(roots=None):
    """A path to prefill in the UI even when nothing has been found yet."""
    rs = roots if roots is not None else home_roots()
    return os.path.join(rs[0] if rs else os.path.expanduser('~'), PES17_SUB)


def validate_save_dir(value):
    """Normalise a pasted path; refuse anything that is not an existing dir."""
    v = os.path.expandvars((value or '').strip().strip('"').strip("'").strip())
    if not v:
        raise ValueError('Enter the full path to your PES 2017 save folder.')
    if os.path.isfile(v) and os.path.basename(v).upper().startswith(('ML0', 'EDIT0', 'SYSTEM0')):
        v = os.path.dirname(v)
    if not os.path.isdir(v):
        raise ValueError('Folder not found: %s' % v)
    return v


def is_fl26_exe(path):
    """True when `pes_exe` is empty or the inherited pc414 Football Life path."""
    p = (path or '').strip()
    if not p:
        return True
    low = p.replace('/', '\\').lower()
    if ('fl 26' in low or 'fl_2026' in low or 'fl 2026' in low
            or 'football life' in low):
        return not os.path.exists(p)
    return False


def needs_game_discovery(path):
    """Retry discovery for an empty, inherited, or no-longer-existing path."""
    p = os.path.expandvars((path or '').strip().strip('"'))
    return not p or not os.path.exists(p) or is_fl26_exe(p)


_GAME_NAMES = (
    'Pro Evolution Soccer 2017',
    'PRO EVOLUTION SOCCER 2017',
    'PES 2017',
    'PES2017',
)
_SKIP_TOP = {
    'windows', 'users', 'program files', 'program files (x86)', 'programdata',
    '$recycle.bin', 'system volume information', 'recovery', 'perflogs',
    'msocache', 'intel', 'amd', 'nvidia', 'appdata',
}


def _find_exe_in(folder):
    try:
        for fn in os.listdir(folder):
            if fn.lower() in ('pes2017.exe', 'pes2017_x64.exe'):
                p = os.path.join(folder, fn)
                if os.path.isfile(p):
                    return p
    except OSError:
        pass
    return ''


def _has_cpk_or_list(folder):
    try:
        for fn in os.listdir(folder):
            low = fn.lower()
            if low.endswith('.cpk') or low == 'dpfilelist.bin':
                return True
    except OSError:
        pass
    return False


def is_game_dir(path):
    """True when `path` looks like a PES 2017 game or patch installation."""
    if not path or not os.path.isdir(path):
        return False
    if _find_exe_in(path):
        return True
    for sub in ('download', 'Data', 'livecpk'):
        sd = os.path.join(path, sub)
        if os.path.isdir(sd) and _has_cpk_or_list(sd):
            return True
    return False


def _winreg_game_dirs():
    if os.name != 'nt':
        return []
    out = []
    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\KONAMI\PES2017', 'installdir'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\KONAMI\PES2017', 'installdir'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 456610', 'InstallLocation'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 456610', 'InstallLocation'),
        ]
        for root_k, sub_k, val_k in keys:
            try:
                with winreg.OpenKey(root_k, sub_k) as k:
                    v, _ = winreg.QueryValueEx(k, val_k)
                    if isinstance(v, str) and v.strip():
                        out.append(v.strip().strip('"'))
            except OSError:
                continue
    except Exception:
        pass
    return out


def _steam_library_dirs(drives):
    vdfs = []
    for drv in drives:
        vdfs.append(os.path.join(drv, 'Program Files (x86)', 'Steam', 'steamapps', 'libraryfolders.vdf'))
        vdfs.append(os.path.join(drv, 'Program Files', 'Steam', 'steamapps', 'libraryfolders.vdf'))
        vdfs.append(os.path.join(drv, 'Steam', 'steamapps', 'libraryfolders.vdf'))
    libs = []
    for vp in vdfs:
        if not os.path.isfile(vp):
            continue
        try:
            with open(vp, encoding='utf-8', errors='ignore') as f:
                txt = f.read(65536)
            for token in txt.split('"'):
                if (':\\' in token or ':/' in token) and len(token) < 260:
                    libs.append(token.replace('\\\\', '\\'))
        except OSError:
            continue
    out = []
    for lib in libs:
        for nm in _GAME_NAMES:
            out.append(os.path.join(lib, 'steamapps', 'common', nm))
    return out


def game_candidates(save_dir='', drives=None):
    """Existing PES 2017 game folders on this machine, best-first.  Offline only."""
    probe = []
    cur = save_dir or ''
    for _ in range(5):
        if not cur:
            break
        probe.append(cur)
        parent = os.path.dirname(cur.rstrip('\\/'))
        if parent == cur:
            break
        cur = parent

    probe.extend(_winreg_game_dirs())

    if drives is None:
        if os.name == 'nt':
            drives = ['%s:\\' % c for c in 'CDEFGHIJKLMNOPQRSTUVWXYZ'
                      if os.path.isdir('%s:\\' % c)]
        else:
            drives = []
    else:
        drives = [d for d in drives if d and os.path.isdir(d)]

    probe.extend(_steam_library_dirs(drives))

    for drv in drives:
        for base in (
            os.path.join(drv, 'Program Files (x86)', 'Steam', 'steamapps', 'common'),
            os.path.join(drv, 'Program Files', 'Steam', 'steamapps', 'common'),
            os.path.join(drv, 'SteamLibrary', 'steamapps', 'common'),
            os.path.join(drv, 'Program Files (x86)', 'KONAMI'),
            os.path.join(drv, 'Program Files', 'KONAMI'),
            os.path.join(drv, 'Games'),
            drv,
        ):
            for nm in _GAME_NAMES:
                probe.append(os.path.join(base, nm))
        try:
            tops = os.listdir(drv)
        except OSError:
            tops = []
        for top in tops[:80]:
            if top.lower() in _SKIP_TOP or top.startswith('.'):
                continue
            tp = os.path.join(drv, top)
            if not os.path.isdir(tp):
                continue
            if 'pes' in top.lower() or 'evolution soccer' in top.lower():
                probe.append(tp)
            for nm in _GAME_NAMES:
                probe.append(os.path.join(tp, nm))
                probe.append(os.path.join(tp, 'Games', nm))
            for sub in ('Games', 'games', 'KONAMI', 'SteamLibrary'):
                gp = os.path.join(tp, sub)
                if not os.path.isdir(gp):
                    continue
                try:
                    for child in os.listdir(gp)[:60]:
                        cl = child.lower()
                        if '2017' in cl or 'pes17' in cl or 'pes 17' in cl:
                            probe.append(os.path.join(gp, child))
                except OSError:
                    continue

    seen, found = set(), []
    for p in probe:
        if not p:
            continue
        key = os.path.normcase(os.path.normpath(p))
        if key in seen:
            continue
        seen.add(key)
        if is_game_dir(p):
            has_dl = _has_cpk_or_list(os.path.join(p, 'download'))
            has_exe = bool(_find_exe_in(p))
            found.append(((1 if has_dl else 0) + (1 if has_exe else 0), p))
    found.sort(key=lambda t: -t[0])
    return [p for _, p in found]


def autodetect_exe(save_dir='', drives=None):
    """Best PES 2017 executable (or game directory) found locally, else ''."""
    cands = game_candidates(save_dir=save_dir, drives=drives)
    if not cands:
        return ''
    best = cands[0]
    return _find_exe_in(best) or best


def version(here):
    try:
        with open(os.path.join(here, 'VERSION.txt'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return 'unknown'


def friendly_error(exc, save_dir):
    """Turn a Windows/POSIX path error into an actionable sentence."""
    win = getattr(exc, 'winerror', None)
    code = getattr(exc, 'errno', None)
    if isinstance(exc, OSError) and (win in (2, 3) or code in (2, 3, 20)):
        return ('The save folder does not exist: %s. Use "Save folder" above to '
                'pick the folder that contains ML00000011 and EDIT00000000 '
                '(usually ...\\KONAMI\\Pro Evolution Soccer 2017\\save).'
                % (save_dir or '(not set)'))
    return 'Could not read the save: %s' % exc


def status(cfg, here=''):
    """Everything the dashboard needs to explain and fix a first run."""
    sd = cfg.get('save_dir') or ''
    exists = bool(sd) and os.path.isdir(sd)
    slots = slots_in(sd) if exists else []
    edit = cfg.get('edit_dat') or (os.path.join(sd, 'EDIT00000000') if sd else '')
    pes_exe = cfg.get('pes_exe') or ''
    pes_exe_exists = bool(pes_exe) and os.path.exists(pes_exe) and not is_fl26_exe(pes_exe)
    if not sd:
        msg = ('No save folder is configured. Choose the folder that holds your '
               'PES 2017 Master League save (ML00000011) and EDIT00000000.')
    elif not exists:
        msg = ('The configured save folder does not exist: %s. Pick the correct '
               'PES 2017 save folder below.' % sd)
    elif not slots:
        msg = ('Save folder found, but it has no ML save slots yet: %s. Create a '
               'Master League save in PES 2017 first.' % sd)
    else:
        msg = 'Found %d PES 2017 save slot(s).' % len(slots)
    return dict(
        ok=bool(slots),
        version=version(here),
        save_dir=sd,
        save_dir_exists=exists,
        slots=slots,
        slot_count=len(slots),
        edit_dat=edit,
        edit_exists=bool(edit) and os.path.isfile(edit),
        pes_exe=pes_exe if pes_exe_exists else '',
        pes_exe_exists=pes_exe_exists,
        game_candidates=game_candidates(save_dir=sd)[:6],
        candidates=candidates() if not slots else [],
        suggested=suggested(),
        message=msg,
    )


def unavailable(cfg, slot, exc, here=''):
    """Structured 200 response for a failed read (never a raw 500 traceback)."""
    st = status(cfg, here)
    st.update(ok=False, error='save_unavailable', slot=slot or '',
              message=friendly_error(exc, cfg.get('save_dir') or ''))
    return st


if __name__ == '__main__':
    import json
    print(json.dumps(status({}, os.getcwd()), indent=1))
