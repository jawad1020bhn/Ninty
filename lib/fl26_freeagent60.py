"""60 MB format: slobodni igraci (free agents).

Autor: 60 MB tester papandreas5 (Evoweb), izvjestaj 03 od 30.10.2026, uz njegov test u igri (Severo, Ferreira).
U The Gaffer ugradjeno u pc235 bez promjene logike; ukljucuje se samo uz config.json "free60_beta": true.

App samo upise dogovor (red ugovora, dogadjaj 0x6e, placa na cekanju C0, serijski u SERLIST);
igra sljedeci dan sama obavi dolazak igraca. Igrac se trazi po punom kljucu (tag, PID), nikad samo po PID-u.
"""
import struct,datetime
from collections import Counter

def accept_existing_offer(s,ml,tag,pid):
 if not s.fmt60:raise ValueError('Only the sampled 60 MB layout is supported')
 key=struct.pack('<II',tag,pid);chunks,e=s._chunks();big=b''.join(chunks)
 matches=[r for r in range(144,len(big)-155,156) if big[r+44:r+52]==key]
 if len(matches)!=1:raise ValueError('Full player identity is not unique')
 r=matches[0]
 if struct.unpack_from('<I',big,r+140)[0]!=0xffffffff:raise ValueError('Player has a club owner')
 for k in range(2400):
  base=84+k*1680
  for i in range(40):
   pair=bytes(s.d[base+s.PAIR_OFF+8*i:base+s.PAIR_OFF+8*(i+1)])
   if struct.unpack_from('<I',pair)[0]&65535==65535:break
   if pair==key:raise ValueError('Player is already registered to a club')
 club=s.club_offset()
 owned=Counter()
 squad={bytes(s.d[club+s.PAIR_OFF+8*k:club+s.PAIR_OFF+8*(k+1)]) for k in range(s._squad_len(club))}
 for rr in range(144,len(big)-155,156):
  if big[rr+44:rr+52] in squad:
   owner=struct.unpack_from('<I',big,rr+140)[0]
   if owner not in (0,0xffffffff):owned[owner]+=1
 if not owned or owned.most_common(1)[0][1]<=len(squad)//2:raise ValueError('Managed club owner is ambiguous')
 mycode=owned.most_common(1)[0][0]
 if s._squad_len(club)>=40:raise ValueError('Managed squad is full')
 terms=[]
 for k in range(120):
  o=e+16+48*k
  if struct.unpack_from('<I',s.d,o+4)[0]==0xffffffff:break
  if bytes(s.d[o+28:o+36])==key:terms.append(o)
 if len(terms)!=1:raise ValueError('No single native offer for this full player identity')
 row=terms[0]
 if struct.unpack_from('<I',s.d,row+4)[0]!=mycode or s.d[row+8]!=3:
  raise ValueError('Native offer is not agreed and awaiting acceptance')
 salary,release,expiry=struct.unpack_from('<III',s.d,row+36)
 if not salary or salary>0x7fffffff:raise ValueError('Invalid offer salary')
 datetime.date(expiry&65535,expiry>>16&255,expiry>>24)
 today=s.game_date_code();move=s._next_day_code(today)
 qbase=ml.X(0x244eb70);q=None
 for k in range(200):
  o=qbase+56*k
  if bytes(s.d[o+4:o+12])==key and struct.unpack_from('<I',s.d,o)[0]!=255:
   raise ValueError('A player event is already pending')
  if q is None and struct.unpack_from('<I',s.d,o)[0]==255:q=o
 if q is None:raise ValueError('Native event queue is full')
 # C0 is the pending annual-salary list (tag, PID, salary/100), not
 # a year/end-date register. Its resolved address is native-pair verified.
 arrival_base=s.C0;arrival=None
 for k in range(40):
  o=arrival_base+12*k
  if bytes(s.d[o:o+8])==key:raise ValueError('Arrival is already pending')
  if arrival is None and struct.unpack_from('<I',s.d,o)[0]==65535:arrival=o
 if arrival is None:raise ValueError('Arrival list is full')
 serial=struct.unpack_from('<H',s.d,row)[0];serial_slot=None
 for k in range(40):
  o=e+s.SERLIST+2*k;v=struct.unpack_from('<H',s.d,o)[0]
  if v==serial:raise ValueError('Offer serial is already queued')
  if serial_slot is None and v==65535:serial_slot=o
 if serial_slot is None:raise ValueError('Execution serial list is full')
 # No mutation occurs until every preflight has succeeded. Only exact fields
 # established by the native slot9/slot10 pair are touched; no broad clears.
 writes=[(q,struct.pack('<III',0x6e,tag,pid)),(q+52,struct.pack('<I',today)),
         (arrival,struct.pack('<III',tag,pid,salary)),
         (row+8,b'\x04'),(row+12,struct.pack('<I',move)),
         (serial_slot,struct.pack('<H',serial))]
 for off,data in writes:s.d[off:off+len(data)]=data
 allowed=list(getattr(s,'_allow',[]))+[(o,o+len(b)) for o,b in writes]
 unexpected=s.changed_outside(allowed)
 if unexpected is not None:
  raise ValueError('Free-agent validation refused: unexpected change at 0x%x. The save was not touched.' % unexpected)
 # Do not set _beta_write: the whole-save native comparison is not complete.
 return {'key':[tag,pid],'salary':salary*100,'release':release*100,'serial':serial,'writes':allowed}

def free_identity(s,pid):
 """Choose a unique unregistered FREE full key; never the first PID hit."""
 big=b''.join(s._chunks()[0]);members=set()
 for k in range(2400):
  base=84+k*1680
  for i in range(40):
   key=bytes(s.d[base+s.PAIR_OFF+8*i:base+s.PAIR_OFF+8*(i+1)])
   if struct.unpack_from('<I',key)[0]&65535==65535:break
   members.add(key)
 found=[]
 for r in range(144,len(big)-155,156):
  tag,ident=struct.unpack_from('<II',big,r+44)
  if ident==pid and struct.unpack_from('<I',big,r+140)[0]==0xffffffff and big[r+44:r+52] not in members:
   found.append(tag)
 if len(found)!=1:raise ValueError('A single unregistered free-agent identity could not be verified')
 return found[0]

def queue_new_agreement(s,ml,pid,salary,end_year,release=0):
 """OFFLINE candidate for app-negotiated agreement; save guard stays LOCKED.

 The native engine performs all arrival registration on the following day.
 No player abilities, roster, source club or managed funds are edited here.
 """
 if not s.fmt60:raise ValueError('Unsupported save layout')
 if type(salary) is not int or salary<=0 or salary%100 or salary//100>0x7fffffff:raise ValueError('Invalid annual salary')
 if type(release) is not int or release<0 or release%100 or release//100>0x7fffffff:raise ValueError('Invalid release clause')
 if type(end_year) is not int or not 2000<end_year<2100:raise ValueError('Invalid contract year')
 expiry=(31<<24)|(8<<16)|end_year
 if (end_year,8,31)<=((s.game_date_code()&65535),(s.game_date_code()>>16&255),(s.game_date_code()>>24)):raise ValueError('Contract must end in the future')
 tag=free_identity(s,pid);key=struct.pack('<II',tag,pid)
 _,e=s._chunks();cbase=e+16;crows=[];used=set()
 for k in range(120):
  off=cbase+48*k;row=bytes(s.d[off:off+48])
  if struct.unpack_from('<I',row,4)[0]==0xffffffff:break
  serial=struct.unpack_from('<H',row)[0]
  if serial>=0x400:raise ValueError('Unexpected terms serial')
  if row[28:36]==key:raise ValueError('A native offer already exists; finish it in the game')
  if serial in used:raise ValueError('Duplicate contract serial')
  used.add(serial);crows.append(row)
 else:raise ValueError('Contract table is full')
 if not crows:raise ValueError('No validated native contract-table anchor')
 if [struct.unpack_from('<H',r)[0] for r in crows]!=sorted(used):raise ValueError('Contract rows are not sorted')
 # Same cross-table serial exclusion as the publisher's verified loan writer.
 for j in range(-7,60):
  off=e+s.META0+60*j
  if bytes(s.d[off+28:off+32])!=b'\xff'*4:
   serial=struct.unpack_from('<H',s.d,off)[0]
   if serial>=0x400:raise ValueError('Unexpected deal-table serial')
   used.add(serial)
 serial=next((i for i in range(0x400) if i not in used),None)
 if serial is None:raise ValueError('No free contract serial')
 # Resolve managed owner using the complete squad keys, as above.
 big=b''.join(s._chunks()[0]);club=s.club_offset()
 squad={bytes(s.d[club+s.PAIR_OFF+8*k:club+s.PAIR_OFF+8*(k+1)]) for k in range(s._squad_len(club))}
 owners=Counter(struct.unpack_from('<I',big,r+140)[0] for r in range(144,len(big)-155,156) if big[r+44:r+52] in squad)
 owners.pop(0xffffffff,None);owners.pop(0,None)
 if not owners or owners.most_common(1)[0][1]<=len(squad)//2:raise ValueError('Managed club owner is ambiguous')
 row=bytearray(48)
 struct.pack_into('<H',row,0,serial);struct.pack_into('<I',row,4,owners.most_common(1)[0][0]);row[8]=3
 struct.pack_into('<I',row,12,65535);row[16:26]=b'\xff'*10
 row[28:36]=key;struct.pack_into('<III',row,36,salary//100,release//100,expiry)
 rows=sorted(crows+[bytes(row)],key=lambda r:struct.unpack_from('<H',r)[0])
 before=bytes(s.d);allow_before=list(getattr(s,'_allow',[]))
 try:
  end=cbase+48*len(rows);s.d[cbase:end]=b''.join(rows)
  s._allow=allow_before+[(cbase,end)]
  result=accept_existing_offer(s,ml,tag,pid)
  s._allow=result['writes']
  if s.changed_outside(s._allow) is not None:raise ValueError('Unexpected mutation outside verified fields')
  if len(s.d)!=len(before):raise ValueError('Save size changed')
  # This helper never enables _beta_write. The caller's existing independent
  # operations (e.g. an app agent-fee debit) may already have set that flag.
  result.update(kind='new_app_agreement_candidate',arrival_date=s._next_day_code(s.game_date_code()),new_serial=serial)
  return result
 except Exception:
  s.d[:]=before;s._allow=allow_before
  raise

def free_catalog(s):
 """Conservative full-key free pool. National-team members are currently
 excluded too until domestic-vs-national membership is wired and tested.
 """
 members=set()
 for k in range(2400):
  base=84+k*1680
  for i in range(40):
   key=bytes(s.d[base+s.PAIR_OFF+8*i:base+s.PAIR_OFF+8*(i+1)])
   if struct.unpack_from('<I',key)[0]&65535==65535:break
   members.add(key)
 big=b''.join(s._chunks()[0]);candidates={};ambiguous=set()
 for r in range(144,len(big)-155,156):
  tag,pid=struct.unpack_from('<II',big,r+44)
  if 1000<pid<400000 and struct.unpack_from('<I',big,r+140)[0]==0xffffffff and big[r+44:r+52] not in members:
   if pid in candidates:ambiguous.add(pid)
   candidates[pid]=(tag,struct.unpack_from('<I',big,r+144)[0])
 return {pid:v for pid,v in candidates.items() if pid not in ambiguous}
