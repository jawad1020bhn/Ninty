"""Read-only venue metadata (ground, capacity, city) keyed by club name.

The asset is data/venue_metadata.json. Its rows were collected for an older
game, so its numeric keys are NOT FC 27 club ids and are never exposed: a venue
is matched by club name only, and only when that name is unambiguous.

Nothing here writes to any file, and no career or kit cache is touched.
"""
from pathlib import Path
import json
import re
import threading
import unicodedata

_LOCK = threading.Lock()
_CACHE = {}


def _key(name):
    return ' '.join(unicodedata.normalize('NFKC', str(name)).casefold().split())


def lookup(app_folder, name):
    """Venue facts for a club name, or {} when unknown/ambiguous.

    A name must resolve to exactly one row, and that row must carry a ground.
    Aliases count as names, so an ambiguous alias resolves to nothing rather
    than to a guessed club.
    """
    base = Path(app_folder)
    db = base / 'data/venue_metadata.json'
    try:
        st = db.stat()
        stamp = (str(base), st.st_mtime_ns, st.st_size)
        with _LOCK:
            if _CACHE.get('stamp') != stamp:
                with db.open(encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('schema') != 1:
                    return {}
                teams = data.get('teams', {})
                names = {}
                for tid, row in teams.items():
                    club = row.get('club')
                    if not isinstance(club, str) or not club.strip():
                        continue
                    names.setdefault(_key(club), set()).add(tid)
                    for alias in row.get('aliases', []):
                        names.setdefault(_key(alias), set()).add(tid)
                _CACHE.clear()
                _CACHE.update(stamp=stamp, names=names, teams=teams)
            candidates = _CACHE['names'].get(_key(name), set())
            if len(candidates) != 1:
                return {}
            row = _CACHE['teams'].get(next(iter(candidates)))
            if not row:
                return {}
            result = {k: row[k] for k in ('ground', 'city')
                      if isinstance(row.get(k), str) and row[k].strip()}
            cap = row.get('cap')
            if isinstance(cap, int) and not isinstance(cap, bool) and 100 <= cap <= 200000:
                result['cap'] = format(cap, ',')
            if not result.get('ground'):
                return {}
            result.update(venue_sources=row.get('sources', {}),
                          venue_kind=row.get('kind', ''))
            return result
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def merge(app_folder, name, original):
    """Overlay venue facts on an existing info dict.

    All three fields come from one linked venue: a capacity or city from an
    older ground must never survive alongside a new one.
    """
    result = dict(original or {})
    metadata = lookup(app_folder, name)
    if metadata:
        for key in ('ground', 'cap', 'city'):
            result.pop(key, None)
        result.update(metadata)
    elif re.search(r'\s(?:B|II|III|U-?\d\d|Reserves?|Youth|Juniors?|Castilla|Atletic)$', name or '', re.I):
        # wiki._slug intentionally shares parent kits; it must not silently
        # share a reserve team's stadium.
        for key in ('ground', 'cap', 'city'):
            result.pop(key, None)
    return result
