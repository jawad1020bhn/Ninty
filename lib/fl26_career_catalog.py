"""Read-only domestic membership from active database; IDs from selected save."""
import json, struct, re, zlib
from pathlib import Path
from fl26_team_identity import read_teams


def catalog(data, roots):
    identity = read_teams(data)
    paths = {}
    for root in roots:
        for name in ('Competition.bin', 'CompetitionEntry.bin'):
            path = Path(root)/'common/etc/pesdb'/name
            if name not in paths and path.is_file():
                paths[name] = path
    def table(name, stride):
        raw = paths[name].read_bytes()
        if raw[3:8] != b'WESYS':
            raise ValueError('Unknown competition database format')
        raw = zlib.decompress(raw[16:])
        if len(raw) % stride:
            raise ValueError('Invalid competition database length')
        return raw
    competition = table('Competition.bin', 36)
    entry = table('CompetitionEntry.bin', 12)
    leagues = {}
    names = {}
    # Metadata is accepted only beside the winning competition database root.
    root = paths['Competition.bin'].parents[3]
    plan = root/'leaguebuilder-plan.json'
    if plan.is_file():
        for row in json.loads(plan.read_text('utf-8')).get('leagues', []):
            if isinstance(row.get('cid'), int) and isinstance(row.get('name'), str):
                names[row['cid']] = row['name']
    for off in range(0, len(competition), 36):
        code = competition[off+8:off+36].split(b'\0')[0].decode('ascii', 'replace')   # pc257: UML baza ima i ne-ASCII imena
        if re.fullmatch(r'(?:[A-Z0-9_]+_D\d+|FL_\d+)_LEAGUE', code):
            cid = struct.unpack_from('>H', competition, off+4)[0]
            leagues[cid] = {'cid': cid, 'name': names.get(cid) or code.replace('_', ' ').title(), 'members': set()}
    team_by_id = {row['id']: row for row in identity['rows']}
    for off in range(0, len(entry), 12):
        tid, unused, cid = struct.unpack_from('<III', entry, off)
        cid &= 255
        if cid in leagues and tid in team_by_id:
            leagues[cid]['members'].add(team_by_id[tid]['ref'])
    domestic = set().union(*(l['members'] for l in leagues.values()))
    if len(domestic) < 100:
        raise ValueError('Domestic club membership could not be verified')
    return {'identity': identity, 'refs': domestic,
            'leagues': [v for v in leagues.values() if len(v['members']) >= 8],
            'paths': {k: str(v) for k, v in paths.items()}}
