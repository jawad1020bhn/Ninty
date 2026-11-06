"""Read-only standings destinations from this installation's active world/rules.

These are configured places, never a claim that a club has already qualified.
No real-world quotas, inferred countries or number-of-clubs heuristics are used.
"""
from pathlib import Path
import hashlib,json,re,zlib,struct

DEST={0:('cl','UCL · league phase','UEFA Champions League — league phase'),
      1:('el','UEL · league phase','UEFA Europa League — league phase'),
      2:('ec','UECL · league phase','UEFA Conference League — league phase'),
      10:('cl','UCL · qualifiers','UEFA Champions League — qualifying'),
      11:('el','UEL · qualifiers','UEFA Europa League — qualifying'),
      12:('ec','UECL · qualifiers','UEFA Conference League — qualifying'),
      3:('lib','Libertadores','Copa Libertadores'),
      4:('lib','Libertadores · qualifiers','Copa Libertadores — qualifying'),
      5:('afc','AFC Champions League','AFC Champions League')}
_CACHE={}
def digest(p):
 p=Path(p);st=p.stat();key=(str(p),st.st_size,st.st_mtime_ns)
 if key not in _CACHE:
  h=hashlib.sha256()
  with p.open('rb') as f:
   for b in iter(lambda:f.read(1048576),b''):h.update(b)
  _CACHE[key]=h.hexdigest()
 return _CACHE[key]

def read_sources(roots,sider,snapshot,exe):
 sider=Path(sider);world=sider/'modules/fl26world.txt'
 ini=(sider/'sider.ini').read_text('utf-8-sig',errors='replace')
 enabled={m.group(1).casefold() for line in ini.splitlines()
          if (m:=re.match(r'\s*lua\.module\s*=\s*"([^"\r\n]+)"',line))}
 if 'fl26umlcomptab.lua' not in enabled or not world.is_file():raise ValueError('Active world/table loader unavailable')
 raw=world.read_text('utf-8-sig');lines=raw.splitlines()
 name=re.search(r'^world\s+(\S+)\s*$',raw,re.M);assert name,'World identity missing'
 winning=next((Path(r)/'common/etc/pesdb/CompetitionRegulation.bin' for r in roots if (Path(r)/'common/etc/pesdb/CompetitionRegulation.bin').is_file()),None)
 if winning is None:raise ValueError('No winning regulation source')
 # The parameter and qualification source is the RUNTIME modules file, not a stale root copy.
 world_root=next((Path(r) for r in roots if Path(r).name==name.group(1)),None)
 if world_root is None:raise ValueError('Active world does not match database roots')
 regraw=winning.read_bytes()
 if regraw[3:8]!=b'WESYS':raise ValueError('Unknown regulation format')
 data=zlib.decompress(regraw[16:]);assert data and len(data)%2352==0
 regs={}
 for off in range(0,len(data),2352):
  r=data[off:off+2352];key=struct.unpack_from('<H',r,2)[0]
  if key in regs:raise ValueError('Duplicate rulebook identity')
  regs[key]=dict(key=key,parent=struct.unpack_from('<H',r,6)[0],cid=r[8],kind=r[9],n=r[11],name=r[20:135].split(b'\0')[0].decode('utf-8'))
 leagues={};splits={};access=[];cups=[]
 for no,line in enumerate(lines,1):
  if line.startswith('league '):
   m=re.match(r'league\s+(\d+)\s+(.*)',line);rid=int(m[1]);rest=m[2];info={k:int(v) for k,v in re.findall(r'\b(\w+)=(-?\d+)\b',rest)}
   info['name']=rest.split('name=',1)[1] if 'name=' in rest else regs.get(rid,{}).get('name','')
   if rid not in regs or info.get('cid')!=regs[rid]['cid']:raise ValueError('World/database identity mismatch '+str(rid))
   leagues[rid]=info
  elif line.startswith('split '):
   rid=int(line.split()[1]);reg=re.search(r'\bregular=(\d+)',line);groups=re.search(r'\bgroups=([\d,]+)',line)
   if reg and groups:splits[rid]={'regular':int(reg[1]),'groups':[int(x) for x in groups[1].split(',')]}
  elif line.startswith('uefa ') and 'dr_uefa_expanded.lua' in enabled:
   v=line.split('#',1)[0].split()
   if len(v)==5:access.append(dict(rid=int(v[1]),position=int(v[2]),code=int(v[3]),alt=int(v[4]),line=no))
  elif line.startswith('ccup ') and 'dr_uefa_expanded.lua' in enabled:
   m=re.match(r'ccup\s+(\d+)',line);entry=re.search(r'\bentry=([\d:,]+)',line);nm=re.search(r'\bname=(.*)',line)
   if m and entry and nm:cups.append(dict(rid=int(m[1]),name=nm[1].strip(),entries=[tuple(map(int,p.split(':'))) for p in entry[1].split(',')],line=no))
 counts={};verified=False;reason='No matching installed parameter-table capture'
 try:
  snap=json.loads(Path(snapshot).read_text('utf-8'))
  checks=[digest(sider/'modules'/Path(p).name)==h for p,h in snap['input_hashes'].items()]
  if all(checks) and digest(exe)==snap['exe_sha256']:
   counts={int(k):v for k,v in snap['rows'].items()};verified=True;reason=None
 except (OSError,KeyError,ValueError):pass
 return dict(regs=regs,leagues=leagues,splits=splits,access=access,cups=cups,counts=counts,counts_verified=verified,counts_reason=reason,
             source={'world':str(world),'world_sha256':digest(world),'regulations':str(winning),'regulations_sha256':digest(winning),'parameter_capture':str(snapshot),'counts_verified':verified})

def resolve(c,src):
 regs=src['regs'];tid=c.get('tid')
 if isinstance(tid,int) and tid in regs:return tid
 cid=c.get('competition_id')
 if cid is None and isinstance(tid,str) and tid.startswith('db:'):
  try:cid=int(tid[3:])
  except ValueError:return None
 if isinstance(cid,int):
  candidates=[k for k,v in src['leagues'].items() if v.get('cid')==cid]
  if len(candidates)==1:return candidates[0]
  candidates=[k for k,v in regs.items() if v['cid']==cid and v['parent']==0 and v['kind'] in (4,5,9)]
  totals=[k for k in candidates if regs[k]['kind'] in (5,9)]
  if len(totals)==1:return totals[0]
  if len(candidates)==1:return candidates[0]
 names={str(c.get(k,'')).casefold() for k in ('name','name_en')}- {''}
 candidates=[k for k,v in regs.items() if v['kind'] in (4,9) and v['name'].casefold() in names]
 return candidates[0] if len(candidates)==1 else None

def rules(c,src):
 rid=resolve(c,src);n=len(c.get('rows',[]));regs=src['regs']
 if rid is None or n<2:return {'available':False,'rows':{},'notes':['No verified rulebook identity for this table.']}
 parent=rid;part=None;offset=0;notes=[];rows={};full_n=n
 for root,sp in src['splits'].items():
  if rid==sp['regular']:parent=root;part='regular'
  elif rid in sp['groups']:
   parent=root;part='group';offset=sum(regs[g]['n'] for g in sp['groups'][:sp['groups'].index(rid)]);full_n=sum(regs[g]['n'] for g in sp['groups'])
 if part=='regular':
  groups=src['splits'][parent]['groups'];start=1
  if sum(regs[g]['n'] for g in groups)!=n:notes.append('Split-group size does not match this table; places withheld.')
  else:
   for g in groups:
    label=regs[g]['name'];end=start+regs[g]['n']-1
    for pos in range(start,end+1):rows[str(pos)]=[dict(key='po',short=label,label=label)]
    start=end+1
  notes.append('Regular season: these places lead to the next group phase. European places and relegation are decided by the final split standings.')
 else:
  for a in src['access']:
   if a['rid']!=parent or a['position']<1 or a['code'] not in DEST:continue
   pos=a['position']-offset
   if 1<=pos<=n:
    key,short,label=DEST[a['code']];item=dict(key=key,short=short,label=label)
    if item not in rows.setdefault(str(pos),[]):rows[str(pos)].append(item)
  for cup in src['cups']:
   for rulebook,pos0 in cup['entries']:
    pos=pos0-offset
    if rulebook==parent and 1<=pos<=n:
     item=dict(key='continental',short=cup['name'],label=cup['name'])
     if item not in rows.setdefault(str(pos),[]):rows[str(pos)].append(item)
  pd=src['counts'].get(parent)
  if pd:
   up,down=pd['promote'],pd['demote']
   if up+down>=full_n:notes.append('Movement counts inconsistent with table size; movement places withheld.')
   else:
    for pos in range(1,n+1):
     global_pos=pos+offset
     if global_pos<=up:rows.setdefault(str(pos),[]).append(dict(key='prom',short='Promotion',label='Promotion — eligible clubs'))
     if global_pos>full_n-down:rows.setdefault(str(pos),[]).append(dict(key='rel',short='Relegation',label='Relegation'))
   if not up and not down:notes.append('No promotion or relegation places are configured for this league in the installed game.')
  else:notes.append('Promotion/relegation counts are not verified for the current setup; those places are not guessed.')
  if parent in src['splits']:notes.append('Final positions shown provisionally; the split group phases decide the final outcome.')
  if part=='group':notes.append('Split group: positions are mapped to the final overall positions '+str(offset+1)+'–'+str(offset+n)+'.')
 cup_places=[]
 for a in src['access']:
  if a['position']==0 and a['alt']==parent and a['code'] in DEST:
   nm=regs.get(a['rid'],{}).get('name') or 'Cup '+str(a['rid']);label=DEST[a['code']][2]
   note=nm+' winner → '+label+'. If already qualified, this place can pass down the league.'
   if note not in cup_places:cup_places.append(note)
 notes.extend(cup_places)
 if any(item['key'] in ('cl','el','ec') for rr in rows.values() for item in rr) or cup_places:
  notes.append('Configured access places, not confirmed qualification. Cup winners, title holders, association coefficients and the installed DR qualification logic can change the final entries.')
 if regs[rid]['kind']==5:notes.append('Multi-stage season: later rounds/play-offs can decide the final title and qualification.')
 if not part and regs[rid]['kind'] in (4,9) and not rows.get('1'):
  rows['1']=[dict(key='champ',short='Champion',label='League champion')]
 if not any(rows.values()):notes.append('No additional position-based destination is verified for this table.')
 return dict(available=True,rulebook=rid,parent=parent,split_part=part,position_offset=offset,rows=rows,notes=notes,provisional=True,source=src['source'])

def enrich(result,roots,sider,snapshot,exe):
 try:src=read_sources(roots,sider,snapshot,exe)
 except Exception as e:
  result['league_places_status']={'available':False,'reason':str(e)}
  return result
 done=0
 for c in result.get('comps',[]):
  if c.get('kind')=='league':
   c['place_rules']=rules(c,src);done+=int(c['place_rules']['available'])
 result['league_places_status']=dict(available=True,leagues_identified=done,counts_verified=src['counts_verified'],source=src['source'])
 return result
