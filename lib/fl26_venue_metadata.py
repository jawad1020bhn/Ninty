"""Read-only, ID-bound venue metadata. Never changes career or kit cache files."""
from pathlib import Path
import json,unicodedata,threading,re
_LOCK=threading.Lock()
_CACHE={}
def _key(name):
    return ' '.join(unicodedata.normalize('NFKC',str(name)).casefold().split())
def lookup(app_folder, name):
    base=Path(app_folder);db=base/'data/venue_metadata.json';identity=base/'data/teamids.json'
    try:
        stamp=(str(base),db.stat().st_mtime_ns,db.stat().st_size,identity.stat().st_mtime_ns,identity.stat().st_size)
        with _LOCK:
            if _CACHE.get('stamp')!=stamp:
                with db.open(encoding='utf-8') as f:data=json.load(f)
                with identity.open(encoding='utf-8') as f:ids=json.load(f)
                if data.get('schema')!=1:return {}
                names={}
                for tid,club in ids.items():names.setdefault(_key(club),set()).add(str(tid))
                # Aliases are captured from verified career identity tables, never fuzzy or parent-club matches.
                for tid,row in data.get('teams',{}).items():
                    if tid not in ids or _key(ids[tid])!=_key(row.get('club','')):continue
                    for alias in row.get('aliases',[]):names.setdefault(_key(alias),set()).add(tid)
                _CACHE.clear();_CACHE.update(stamp=stamp,names=names,teams=data.get('teams',{}),ids=ids)
            candidates=_CACHE['names'].get(_key(name),set())
            if len(candidates)!=1:return {}
            tid=next(iter(candidates));row=_CACHE['teams'].get(tid)
            if not row or _key(row.get('club',''))!=_key(_CACHE['ids'].get(tid,'')):return {}
            result={k:row[k] for k in ('ground','city') if isinstance(row.get(k),str) and row[k].strip()}
            cap=row.get('cap')
            if isinstance(cap,int) and not isinstance(cap,bool) and 100<=cap<=200000:result['cap']=format(cap,',')
            if not result.get('ground'):return {}
            result.update(team_id=int(tid),venue_sources=row.get('sources',{}),venue_kind=row.get('kind',''))
            return result
    except (OSError,ValueError,TypeError,KeyError):return {}
def merge(app_folder,name,original):
    result=dict(original or {});metadata=lookup(app_folder,name)
    if metadata:
        # All three fields come from one linked venue. Do not keep a capacity/city for an older ground.
        for key in ('ground','cap','city'):result.pop(key,None)
        result.update(metadata)
    elif re.search(r'\s(?:B|II|III|U-?\d\d|Reserves?|Youth|Juniors?|Castilla|Atletic)$',name or '',re.I):
        # wiki._slug intentionally shares parent kits; it must not silently share a reserve team's stadium.
        for key in ('ground','cap','city'):result.pop(key,None)
    return result
