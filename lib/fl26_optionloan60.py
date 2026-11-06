"""60 MB: dolazna posudba S opcijom otkupa (izravno prihvacen dogovor; igra dolazak izvrsi sljedeci dan).
Autor: tester 60 MB (The Gaffer Report 04, 30.10.2026), provjereno u igri (Endo, Liverpool -> Arsenal).
U The Gaffer ugradjeno u pc247 bez promjene logike upisa; slot-15 ogranicenje zamijenjeno prekidacem config.json "loan_opt60_beta": true.
Ne gradi nativnu povijest ponuda/odgovora iz igre (native_pending_ui_history_created = False).
"""
"""OFFLINE constructor for an accepted incoming option loan.

Uses verified native record shapes. Does not authorise Save.save or install an
endpoint. Unlike acceptance_draft, this starts with NO native offer. Full native
creation/history equivalence has NOT been established; isolated runtime testing
would need explicit authorisation. Never creates native pending-UI reply records.
"""
import struct,datetime
from collections import Counter

def queue_new_option(s,ml,pid,fee,end_code,option):
    if not s.fmt60:raise ValueError('Only the sampled 60 MB format is supported')
    if bytes(s.d)!=s._orig:raise ValueError('Option-loan input must be unmodified')
    if type(pid) is not int or not 1000<pid<400000:raise ValueError('Invalid player ID')
    values=[fee,option.get('buy'),option.get('wage'),option.get('release')]
    if any(type(v) is not int or v<0 or v%100 or v//100>0x7fffffff for v in values):
        raise ValueError('Invalid option-loan amount')
    if option['buy']==0 or option['wage']==0:raise ValueError('Option price and purchase wage must be positive')
    def date(v):
        if type(v) is not int or not 0<=v<=0xffffffff:raise ValueError('Invalid date code')
        return datetime.date(v&65535,(v>>16)&255,v>>24)
    today=s.game_date_code();now=date(today);purchase_end=option.get('end')
    if not now<date(end_code)<date(purchase_end):raise ValueError('Invalid loan/purchase expiry order')
    if (now.month,now.day) in ((8,31),(1,31)):
        raise ValueError('Last-day option-loan execution is not validated in this trial')
    chunks,e=s._chunks();big=b''.join(chunks)
    found=[]
    for r in range(144,len(big)-155,156):
        tag,ident=struct.unpack_from('<II',big,r+44)
        if ident==pid and struct.unpack_from('<I',big,r+140)[0] not in (0,0xffffffff):
            found.append((r,tag))
    if len(found)!=1:raise ValueError('A unique owned player instance could not be verified')
    r,tag=found[0];owner=struct.unpack_from('<I',big,r+140)[0]
    if struct.unpack_from('<I',big,r+136)[0]!=0xffffffff:raise ValueError('Player is already loaned')
    key=struct.pack('<II',tag,pid);club=s.club_offset();n=s._squad_len(club)
    if n>=40:raise ValueError('Managed squad is full')
    squad={bytes(s.d[club+s.PAIR_OFF+8*i:club+s.PAIR_OFF+8*(i+1)]) for i in range(n)}
    if key in squad:raise ValueError('Player is already in the managed squad')
    owners=Counter(struct.unpack_from('<I',big,o+140)[0] for o in range(144,len(big)-155,156) if big[o+44:o+52] in squad)
    owners.pop(0,None);owners.pop(0xffffffff,None)
    if not owners or owners.most_common(1)[0][1]<=n//2:raise ValueError('Managed club owner is ambiguous')
    managed=owners.most_common(1)[0][0]
    if managed==owner:raise ValueError('Target belongs to managed club')
    # Require an actual source roster, selected by the complete instance key.
    source_clubs=[]
    for ref in range(2400):
        off=84+1680*ref
        for j in range(40):
            pair=bytes(s.d[off+s.PAIR_OFF+8*j:off+s.PAIR_OFF+8*(j+1)])
            if struct.unpack_from('<I',pair)[0]&65535==65535:break
            if pair==key:source_clubs.append(ref)
    if not source_clubs:raise ValueError('Owned player has no verified source roster')
    terms=[];term_base=e+16
    for k in range(120):
        off=term_base+48*k
        if struct.unpack_from('<I',s.d,off+4)[0]==0xffffffff:break
        row=bytes(s.d[off:off+48])
        if row[28:36]==key:raise ValueError('A native offer/contract already exists for this player')
        terms.append(row)
    else:raise ValueError('Terms table full')
    if not terms:raise ValueError('No validated terms-table anchor')
    ts=[struct.unpack_from('<H',v)[0] for v in terms]
    if ts!=sorted(set(ts)) or max(ts)>=0x400:raise ValueError('Terms serials are invalid')
    meta=[];meta_start=None;meta_base=e+s.META0
    for k in range(-7,60):
        off=meta_base+60*k;row=bytes(s.d[off:off+60])
        if struct.unpack_from('<I',row,28)[0]==0xffffffff:continue
        if row[32:40]==key:raise ValueError('A native loan deal already exists for this player')
        if meta_start is None:meta_start=k
        meta.append(row)
    if meta_start is None:meta_start=-7
    ms=[struct.unpack_from('<H',v)[0] for v in meta]
    if ms!=sorted(set(ms)) or any(v>=0x400 for v in ms):raise ValueError('Deal serials are invalid')
    if meta_start+len(meta)+1>58:raise ValueError('Deal table full')
    used=set(ts)|set(ms)
    pair=next(((v,v+1) for v in range(0,0x3ff) if v not in used and v+1 not in used),None)
    if pair is None:raise ValueError('No free serial pair')
    term_serial,deal_serial=pair
    price_base=e+0x24e10;price_slot=None;price_ids=[]
    for i in range(30):
        off=price_base+12*i;ident=struct.unpack_from('<H',s.d,off)[0]
        value=struct.unpack_from('<I',s.d,off+4)[0]
        if ident==65535 and value==0:
            if price_slot is None:price_slot=off
        elif ident!=65535:price_ids.append(ident)
        else:raise ValueError('Unexpected empty option-price row')
    if price_slot is None:raise ValueError('Option-price table full')
    if len(price_ids)!=len(set(price_ids)):raise ValueError('Duplicate option-price IDs')
    option_id=max(price_ids)+1 if price_ids else 0
    if option_id>=65535:raise ValueError('No option-price identifier')
    queue=None
    for i in range(200):
        off=ml.X(0x244eb70)+56*i;kind=struct.unpack_from('<I',s.d,off)[0]
        if kind==0x6e:raise ValueError('Another arrival is already pending')
        if queue is None and kind==255:queue=off
    if queue is None:raise ValueError('Event queue full')
    log=None
    for i in range(1,61):
        off=ml.X(0x24ef0dc)+52*i
        if bytes(s.d[off:off+2])==b'\xff\xff':log=off;break
    if log is None:raise ValueError('Deal log full')
    serial_slot=None
    for i in range(40):
        off=e+s.SERLIST+2*i
        if struct.unpack_from('<H',s.d,off)[0]==65535:serial_slot=off;break
    if serial_slot is None:raise ValueError('Execution serial list full')
    budget=struct.unpack_from('<I',s.d,s.BUDGET)[0];f=fee//100
    if f>budget:raise ValueError('Insufficient transfer budget')
    term=bytearray(48)
    struct.pack_into('<H',term,0,term_serial);struct.pack_into('<I',term,4,managed)
    struct.pack_into('<II',term,8,4,65535);term[16:26]=b'\xff'*10;term[28:36]=key
    struct.pack_into('<III',term,36,option['wage']//100,option['release']//100,purchase_end)
    deal=bytearray(struct.pack('<HHIII',deal_serial,0,managed,4,s._next_day_code(today))+b'\xff'*8+
        struct.pack('<IIIIIIIII',65535,owner,tag,pid,f,f,end_code,65535,0))
    assert len(deal)==60
    struct.pack_into('<H',deal,16,option_id)
    all_terms=sorted(terms+[bytes(term)],key=lambda v:struct.unpack_from('<H',v)[0])
    all_meta=sorted(meta+[bytes(deal)],key=lambda v:struct.unpack_from('<H',v)[0])
    writes=[(s.BUDGET,struct.pack('<I',budget-f)),(queue,struct.pack('<III',0x6e,tag,pid)),
        (queue+52,struct.pack('<I',today)),(log,key),(log+32,struct.pack('<iI',-f,2)),
        (term_base,b''.join(all_terms)),(meta_base+60*meta_start,b''.join(all_meta)),
        (price_slot,struct.pack('<III',option_id,option['buy']//100,term_serial)),
        (serial_slot,struct.pack('<H',deal_serial))]
    before=bytes(s.d)
    try:
        for off,data in writes:s.d[off:off+len(data)]=data
        ranges=[(o,o+len(data)) for o,data in writes]
        if s.changed_outside(ranges) is not None:raise ValueError('Unexpected mutation outside prepared records')
        return {'key':[tag,pid],'term_serial':term_serial,'deal_serial':deal_serial,'option_id':option_id,
            'loan_fee':fee,'option_price':option['buy'],'ranges':ranges,
            'purchase_wage':option['wage'],'arrival_date':s._next_day_code(today),
            'native_pending_ui_history_created':False,'full_native_equivalence':False,
            'beta_write_enabled':getattr(s,'_beta_write',False)}
    except Exception:
        s.d[:]=before
        raise
