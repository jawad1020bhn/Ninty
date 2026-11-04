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
    v = os.path.expandvars((value or '').strip().strip('"').strip())
    if not v:
        raise ValueError('Enter the full path to your PES 2017 save folder.')
    if not os.path.isdir(v):
        raise ValueError('Folder not found: %s' % v)
    return v


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
    patch = cfg.get('pes17_patch_dir') or ''
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
        patch_dir=patch,
        patch_exists=bool(patch) and os.path.isdir(patch),
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
