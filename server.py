#!/usr/bin/env python3
"""The Gaffer - FC 27 career server (stdlib only).

    python3 server.py --host 0.0.0.0 --port 8765 --no-browser

ONE game: EA SPORTS FC 27. The database in data/fc27 supplies static facts and
lib/engine runs the career against its own JSON saves in data/saves. There is no
other game's save format, install path, decrypter or process here.

API
  GET  /api/fc27/*       the database: players, clubs, leagues, cups, tuning
  GET  /api/engine/*     a career: state, squad, table, selection, history
  POST /api/engine/*     new, play, advance, finish, close_season, transfer,
                         save, delete
  GET  /api/{art,stadium,venue,clubcolors,i18n,fmtext,myscene}  shared assets
  GET  /api/crest        club/league/nation mark, or a generated shield
  GET  /api/face         player/manager portrait, or a generated avatar
  GET  /api/graphics/status  crest coverage and portrait-cache counts

The old PES/FL26 career backend was removed in r23. static/index.html is kept
only as a design reference: it calls those removed endpoints and will not run
against this server until a new UI is built on /api/engine/*.
"""
import argparse
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = 'pc414'
APP_BUILT = '2026-11-07'
sys.path.insert(0, os.path.join(HERE, 'lib'))

import fc27 as fc27db        # noqa: E402  EA SPORTS FC 27 database (data/fc27)
import engine as fcengine    # noqa: E402  the career engine (data/saves)
import clubcolors            # noqa: E402  club colour overrides
import wiki                  # noqa: E402  stadium photo cache
import venues                # noqa: E402  read-only venue metadata
import graphics              # noqa: E402  crests + generated fallbacks
import faces                 # noqa: E402  licence-gated portraits

DEFAULT_CFG = {
    'port': 8765,
    'lang': 'en',
    'wiki_web': False,       # offline by default; cached images still serve
    'faces_web': False,      # portraits: local cache only unless enabled
}
CFG = dict(DEFAULT_CFG)
LOCK = threading.Lock()


def _jdump(obj, path, **kw):
    """Atomic JSON write: a failed write leaves the previous file intact."""
    tmp = '%s.%d.%d.tmp' % (path, os.getpid(), threading.get_ident())
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, **kw)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    p = os.path.join(HERE, 'config.json')
    if os.path.exists(p):
        try:
            cfg.update(json.load(open(p, encoding='utf-8')))
        except (ValueError, OSError) as ex:
            print('[cfg] ignoring config.json:', ex)
    return cfg


def _cfg_update(**kv):
    p = os.path.join(HERE, 'config.json')
    try:
        cur = json.load(open(p, encoding='utf-8'))
    except (ValueError, OSError):
        cur = {}
    cur.update(kv)
    _jdump(cur, p, ensure_ascii=False, indent=1)
    CFG.update(kv)


def _qint(q, k, default=0):
    """Read an int query argument without throwing on junk input."""
    try:
        return int((q.get(k, [''])[0] or '').strip())
    except (ValueError, TypeError):
        return default


# --------------------------------------------------------------- career cache
_ENG_CACHE = {}
_ENG_LOCK = threading.RLock()


def _eng_get(sid):
    """Load a career once and keep it in memory.

    The save on disk stays authoritative: every mutating route writes through
    before returning, so a reload or a second process sees the same state.
    """
    sid = str(sid or '').strip()
    if not sid:
        raise fcengine.SaveError('a career id is required')
    with _ENG_LOCK:
        st = _ENG_CACHE.get(sid)
        if st is None:
            st = fcengine.load(sid)
            _ENG_CACHE[sid] = st
            while len(_ENG_CACHE) > 4:
                _ENG_CACHE.pop(next(iter(_ENG_CACHE)), None)
        return st


def _eng_put(st):
    with _ENG_LOCK:
        fcengine.save(st)
        _ENG_CACHE[st['id']] = st
    return st


# --------------------------------------------------------------------- assets
_STAD_FAIL = {}
CLOG_FILE = os.path.join(HERE, 'data', 'client_errors.log')
_CLOG_SEEN = {}


def venue_info(name):
    return venues.lookup(HERE, name)


def client_log(body):
    """Browser errors (window.onerror / unhandledrejection), last ~400 lines."""
    try:
        msg = str(body.get('msg') or '')[:400]
        key = msg + '|' + str(body.get('line'))
        now = time.time()
        if now - _CLOG_SEEN.get(key, 0) < 60:
            return dict(ok=True, dup=True)
        _CLOG_SEEN[key] = now
        row = '%s %s page=%s src=%s:%s:%s %s\n%s\n' % (
            time.strftime('%Y-%m-%d %H:%M:%S'), APP_VERSION,
            str(body.get('page') or '')[:40], str(body.get('src') or '')[-80:],
            body.get('line'), body.get('col'), msg, str(body.get('stack') or '')[:1500])
        os.makedirs(os.path.dirname(CLOG_FILE), exist_ok=True)
        old = open(CLOG_FILE, encoding='utf-8', errors='replace').read() if os.path.isfile(CLOG_FILE) else ''
        lines = (old + row).splitlines(True)[-400:]
        _jdump  # keep the atomic-write helper referenced for clarity
        with open(CLOG_FILE, 'w', encoding='utf-8') as fh:
            fh.write(''.join(lines))
    except Exception as ex:
        return dict(ok=False, error=str(ex)[:120])
    return dict(ok=True)


# --------------------------------------------------------- phone/tablet access
LAN_GET_BLOCK = ('/api/lan',)
LAN_POST_BLOCK = ('/api/quit', '/api/lan/set')
_LAN = dict(srv=None, port=None, err=None, fails={})


def _lan_token():
    import hmac
    sec = CFG.get('lan_secret') or ''
    return hmac.new(sec.encode(), ('pin:%s' % CFG.get('lan_pin', '')).encode(),
                    hashlib.sha256).hexdigest()[:40] if sec else ''


def _lan_ips():
    ips = []
    try:
        s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_.connect(('10.255.255.255', 1))   # sends nothing; just picks an interface
        ips.append(s_.getsockname()[0])
        s_.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass

    def priv(ip):
        return (ip.startswith(('192.168.', '10.'))
                or (ip.startswith('172.') and 16 <= int(ip.split('.')[1]) <= 31))
    return [ip for ip in ips if priv(ip) and not ip.startswith('127.')] or \
           [ip for ip in ips if not ip.startswith('127.')]


def lan_start():
    if _LAN['srv']:
        return True
    port = (CFG.get('_port') or 8765) + 1
    try:
        srv_ = _Srv(('0.0.0.0', port), H)
    except OSError as ex:
        _LAN['err'] = 'Port %d is busy (%s).' % (port, ex)
        return False
    _LAN.update(srv=srv_, port=port, err=None)
    threading.Thread(target=srv_.serve_forever, daemon=True).start()
    print('Phone & tablet access on port', port)
    return True


def lan_stop():
    srv_ = _LAN.get('srv')
    _LAN['srv'] = None
    if srv_:
        threading.Thread(target=lambda: (srv_.shutdown(), srv_.server_close()),
                         daemon=True).start()


def lan_view():
    on = bool(CFG.get('lan_on')) and bool(_LAN['srv'])
    port = _LAN.get('port') or (CFG.get('_port') or 8765) + 1
    urls = ['http://%s:%d/' % (ip, port) for ip in _lan_ips()]
    qr = None
    if on and urls:
        try:
            import qrmini
            qr = qrmini.svg(urls[0], scale=5)
        except Exception as ex:
            print('[lan] qr:', ex)
    return dict(ok=True, on=on, want=bool(CFG.get('lan_on')), port=port,
                pin=CFG.get('lan_pin') or '', urls=urls, qr=qr, err=_LAN.get('err'))


def lan_set(body):
    import secrets
    kv = {}
    if body.get('new_pin') or not CFG.get('lan_pin'):
        kv['lan_pin'] = '%06d' % secrets.randbelow(1000000)
        kv['lan_secret'] = secrets.token_hex(16)   # a new PIN signs every device out
    if 'on' in body:
        kv['lan_on'] = bool(body['on'])
    if kv:
        _cfg_update(**kv)
    if CFG.get('lan_on'):
        lan_start()
    else:
        lan_stop()
    return lan_view()


LAN_LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Gaffer</title><style>
:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1020;color:#e7ecf2;font:16px system-ui,sans-serif}
form{width:min(340px,88vw);padding:28px 24px;border:1px solid #26314a;border-radius:16px;background:#121a30;text-align:center}
h1{margin:0 0 4px;font:900 italic 28px system-ui;letter-spacing:.06em}p{margin:0 0 18px;color:#8b98a8;font-size:14px}
input{width:100%;box-sizing:border-box;padding:14px;border-radius:10px;border:1px solid #33405e;background:#0b1020;color:#fff;font:700 28px ui-monospace,monospace;letter-spacing:.35em;text-align:center}
button{margin-top:14px;width:100%;padding:14px;border:0;border-radius:10px;background:#f2c230;color:#1a1300;font:800 16px system-ui;letter-spacing:.06em;text-transform:uppercase}
.e{color:#ff8a8f;min-height:20px;margin-top:10px;font-size:14px}</style></head><body>
<form id="f"><h1>THE GAFFER</h1><p>Enter the PIN shown in Setup on your PC.</p>
<input id="p" inputmode="numeric" autocomplete="one-time-code" maxlength="6" autofocus><button>Open</button><div class="e" id="e"></div></form>
<script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/lan/login',{method:'POST',body:JSON.stringify({pin:document.getElementById('p').value})}).then(r=>r.json()).catch(()=>({}));
if(r.ok)location.replace('/');else document.getElementById('e').textContent=r.error||'Wrong PIN.'}</script></body></html>"""


_CODE_STAMP = {}


def _code_stamp():
    """Fingerprint of the code on disk, so a second launch can detect a change."""
    if 'v' in _CODE_STAMP:
        return _CODE_STAMP['v']
    h = hashlib.sha1()
    files = [os.path.join(HERE, 'server.py'), os.path.join(HERE, 'static', 'index.html')]
    for root in ('lib', os.path.join('lib', 'engine')):
        d = os.path.join(HERE, root)
        files += sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.py'))
    for f in files:
        try:
            st = os.stat(f)
            h.update(('%s|%d|%d;' % (os.path.basename(f), st.st_size, int(st.st_mtime))).encode())
        except OSError:
            pass
    _CODE_STAMP['v'] = h.hexdigest()[:12]
    return _CODE_STAMP['v']


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if len(a) > 1 and str(a[1]) not in ('200', '204'):
            print('HTTP', *a)

    def _remote(self):
        try:
            return self.client_address[0] not in ('127.0.0.1', '::1', '::ffff:127.0.0.1')
        except (IndexError, AttributeError):
            return True

    def _lan_guard(self, post=False):
        """A request from another device: True = allowed. Otherwise the response
        is already sent (PIN page / 401 / 403)."""
        if not self._remote():
            return True
        path = urlparse(self.path).path
        if not (CFG.get('lan_on') and _LAN.get('srv')):
            self.send(403, dict(error='Phone & tablet access is off.'))
            return False
        if path == '/api/lan/login':
            return True
        tok = _lan_token()
        ck = self.headers.get('Cookie') or ''
        if not tok or ('gaffer_lan=' + tok) not in ck:
            if path.startswith('/api/'):
                self.send(401, dict(error='Enter the PIN first.'))
            else:
                self.send(200, LAN_LOGIN_HTML.encode('utf-8'), 'text/html')
            return False
        blk = LAN_POST_BLOCK if post else LAN_GET_BLOCK
        if any(path == b or (b.endswith('/') and path.startswith(b)) for b in blk):
            self.send(403, dict(error='This can only be done on the PC.'))
            return False
        return True

    def _lan_login(self, body):
        ip = self.client_address[0]
        f = _LAN['fails'].get(ip, [0, 0])
        if f[0] >= 5 and time.time() - f[1] < 60:
            return self.send(200, dict(ok=False, error='Too many tries. Wait a minute.'))
        if str(body.get('pin', '')).strip() != str(CFG.get('lan_pin') or '') or not CFG.get('lan_pin'):
            _LAN['fails'][ip] = [f[0] + 1, time.time()]
            return self.send(200, dict(ok=False, error='Wrong PIN.'))
        _LAN['fails'].pop(ip, None)
        data = json.dumps(dict(ok=True)).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Set-Cookie', 'gaffer_lan=%s; Max-Age=2592000; Path=/; SameSite=Strict; HttpOnly' % _lan_token())
        self.end_headers()
        self.wfile.write(data)

    def send(self, code, obj, ctype='application/json'):
        data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        gz = False
        # Large text responses go compressed for a phone on Wi-Fi.
        try:
            if (len(data) > 16384
                    and (ctype.startswith('text') or ctype in ('application/json', 'image/svg+xml'))
                    and self._remote() and 'gzip' in (self.headers.get('Accept-Encoding') or '')):
                import gzip as _gz
                data = _gz.compress(data, 5)
                gz = True
        except Exception:
            pass
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith('text') or ctype == 'application/json' else ''))
        if gz:
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Vary', 'Accept-Encoding')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'private, max-age=3600'
                         if (code == 200 and ctype.startswith('image/')) else 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if not self._lan_guard():
            return
        try:
            if u.path == '/api/lan':
                return self.send(200, lan_view())
            if u.path == '/api/version':
                return self.send(200, dict(version=APP_VERSION, built=APP_BUILT,
                                           app='thegaffer', game='fc27',
                                           code=_code_stamp(), pid=os.getpid()))
            if u.path == '/api/fc27/status':
                return self.send(200, fc27db.summary())
            if u.path == '/api/fc27/attrs':
                # Schema for the engine: EA's 34 raw attributes plus the lossy
                # legacy 25-attribute projection the growth algorithm still reads.
                _m = fc27db.meta()
                return self.send(200, dict(ok=True, ea=fc27db.ea_ab(),
                                           ab25=_m.get('ab', []), ab25Source=_m.get('abSource', []),
                                           dropped=_m.get('ab25ProjectionDrops', []),
                                           posn=fc27db.POSN, eaPosEnum=_m.get('eaPos', {}),
                                           slotCompat=fc27db.slot_compat()))
            if u.path == '/api/fc27/national':
                _q = parse_qs(u.query)
                _tid = _qint(_q, 'id')
                if _tid:
                    _t = fc27db.national_team(_tid)
                    if not _t:
                        return self.send(404, dict(ok=False, error='No national team %d' % _tid))
                    _sq = [fc27db.player(_p) for _p in (_t.get('squad') or [])]
                    _sq = [_p for _p in _sq if _p]
                    _sq.sort(key=lambda x: -(x['ovr'] or 0))
                    return self.send(200, dict(ok=True, id=_tid, team=_t, squad=_sq))
                _w = _q.get('women', [''])[0]
                _out = []
                for _k, _v in sorted(fc27db.national_teams().items(), key=lambda kv: int(kv[0])):
                    if _w in ('0', '1') and int(_v.get('gender') or 0) != int(_w):
                        continue
                    _out.append(dict(id=int(_k), **{k: v for k, v in _v.items() if k != 'squad'},
                                     players=len(_v.get('squad') or [])))
                return self.send(200, dict(ok=True, teams=_out))
            if u.path == '/api/fc27/leagues':
                _q = parse_qs(u.query)
                _w = _q.get('women', [''])[0]
                _out = []
                for _k, _v in sorted(fc27db.leagues().items(), key=lambda kv: int(kv[0])):
                    if _w in ('0', '1') and int(_v.get('women') or 0) != int(_w):
                        continue
                    _out.append(dict(id=int(_k), **_v))
                return self.send(200, dict(ok=True, leagues=_out))
            if u.path == '/api/fc27/league':
                _lid = _qint(parse_qs(u.query), 'id')
                _lg = fc27db.league(_lid)
                if not _lg:
                    return self.send(404, dict(ok=False, error='No league %d' % _lid))
                return self.send(200, dict(ok=True, id=_lid, league=_lg, clubs=fc27db.league_clubs(_lid)))
            if u.path == '/api/fc27/club':
                _tid = _qint(parse_qs(u.query), 'id')
                _c = fc27db.club(_tid)
                if not _c:
                    return self.send(404, dict(ok=False, error='No club %d' % _tid))
                _sq = [fc27db.player(_p) for _p in fc27db.squad(_tid)]
                return self.send(200, dict(ok=True, id=_tid, club=_c, squad=[_p for _p in _sq if _p],
                                           stadium=fc27db.stadium(_tid), manager=fc27db.manager(_tid),
                                           formations=fc27db.club_formations(_tid),
                                           rivals=fc27db.club_rivals(_tid),
                                           xi=fc27db.starting_xi(_tid),
                                           prevPos=fc27db.prev_pos().get(str(_tid)) or {},
                                           teamsheet=fc27db.teamsheet(_tid),
                                           coefficient=fc27db.coefficients(tid=_tid),
                                           ownership=fc27db.ownership(_tid),
                                           group=fc27db.league_group(_tid),
                                           counterpart=fc27db.counterpart(_tid)))
            if u.path == '/api/fc27/matches':
                _q = parse_qs(u.query)
                _a, _b = _qint(_q, 'a'), _qint(_q, 'b')
                if _a and _b:
                    return self.send(200, dict(ok=True, a=_a, b=_b,
                                               aName=fc27db.team_name(_a), bName=fc27db.team_name(_b),
                                               big=fc27db.is_big_match(_a, _b),
                                               derby=any(r['id'] == _b for r in fc27db.club_rivals(_a)),
                                               sameOwner=fc27db.same_owner(_a, _b)))
                _ms = [dict(a=_x, b=_y, aName=fc27db.team_name(_x), bName=fc27db.team_name(_y))
                       for _x, _y in fc27db.big_matches()]
                return self.send(200, dict(ok=True, matches=_ms))
            if u.path == '/api/fc27/tuning':
                _q = parse_qs(u.query)
                _d, _m = _q.get('diff', [''])[0], _qint(_q, 'minute')
                _out = dict(ok=True, tuning=fc27db.match_tuning())
                if _d != '' and _m:
                    try:
                        _out.update(scoreDiff=int(_d), minute=_m,
                                    intensity=fc27db.match_intensity(int(_d), _m))
                    except ValueError:
                        return self.send(400, dict(ok=False, error='diff must be an integer'))
                return self.send(200, _out)
            if u.path == '/api/fc27/calendar':
                _q = parse_qs(u.query)
                _mo, _dy = _qint(_q, 'month'), _qint(_q, 'day')
                _out = dict(ok=True, windows=fc27db.transfer_windows(),
                            note='month/day only; the engine save owns the season year')
                if _mo and _dy:
                    _out.update(month=_mo, day=_dy, open=fc27db.in_transfer_window(_mo, _dy))
                return self.send(200, _out)
            if u.path == '/api/fc27/referees':
                _lid = _qint(parse_qs(u.query), 'league')
                if _lid:
                    _rs = [_r for _r in fc27db.referees(_lid) if _r]
                    return self.send(200, dict(ok=True, league=_lid, referees=_rs))
                return self.send(200, dict(ok=True, referees=fc27db.referees()))
            if u.path == '/api/fc27/regen':
                _n = fc27db.regen_names()
                _t = fc27db.regen_templates()
                return self.send(200, dict(ok=True,
                                           names={_k: len(_v) for _k, _v in _n.items()},
                                           pools=sorted({r[1] for _v in _n.values() for r in _v}),
                                           templates={_k: len(_t.get(_k) or [])
                                                      for _k in ('youth', 'regen', 'create')},
                                           youthAgeUnit=_t.get('youthAgeUnit'),
                                           regenAgeUnit=_t.get('regenAgeUnit'),
                                           note='pool ids are language/region groups, not nation ids'))
            if u.path == '/api/fc27/cups':
                _w = parse_qs(u.query).get('women', [''])[0]
                _out = []
                for _k, _v in sorted(fc27db.cups().items(), key=lambda kv: int(kv[0])):
                    if _w in ('0', '1') and int(_v.get('women') or 0) != int(_w):
                        continue
                    _out.append(dict(id=int(_k), **_v))
                return self.send(200, dict(ok=True, cups=_out))
            if u.path == '/api/fc27/loans':
                _tid = _qint(parse_qs(u.query), 'club')
                _all = fc27db.loans()
                return self.send(200, dict(ok=True, loans=[
                    _l for _l in _all if not _tid or _l.get('from') == _tid or _l.get('to') == _tid]))
            if u.path == '/api/fc27/player':
                _pid = _qint(parse_qs(u.query), 'id')
                _p = fc27db.player(_pid)
                if not _p:
                    return self.send(404, dict(ok=False, error='No player %d' % _pid))
                return self.send(200, dict(ok=True, player=_p))
            if u.path == '/api/fc27/search':
                _q = parse_qs(u.query)
                _cid = _qint(_q, 'club') or None
                _pos = _qint(_q, 'pos', -1)
                return self.send(200, dict(ok=True, players=fc27db.search(
                    _q.get('q', [''])[0], limit=min(200, max(1, _qint(_q, 'limit', 40))),
                    club_id=_cid, pos=None if _pos < 0 else _pos)))
            if u.path == '/api/engine/careers':
                return self.send(200, dict(ok=True, careers=fcengine.list_saves()))
            if u.path == '/api/engine/state':
                _q = parse_qs(u.query)
                try:
                    _st = _eng_get(_q.get('id', [''])[0])
                except fcengine.SaveError as _ex:
                    return self.send(404, dict(ok=False, error=str(_ex)))
                return self.send(200, dict(ok=True, career=fcengine.summary(_st),
                                           table=fcengine.table(_st),
                                           next=fcengine.next_fixture(_st),
                                           fixtures=fcengine.upcoming(_st, limit=10)))
            if u.path == '/api/engine/squad':
                _q = parse_qs(u.query)
                try:
                    _st = _eng_get(_q.get('id', [''])[0])
                except fcengine.SaveError as _ex:
                    return self.send(404, dict(ok=False, error=str(_ex)))
                _tid = _qint(_q, 'club') or _st['club']
                if str(_tid) not in _st['clubs']:
                    return self.send(404, dict(ok=False, error='No club %d in this career' % _tid))
                return self.send(200, dict(ok=True, club=_tid,
                                           clubName=fc27db.team_name(_tid),
                                           players=fcengine.squad(_st, _tid)))
            if u.path == '/api/engine/table':
                _q = parse_qs(u.query)
                try:
                    _st = _eng_get(_q.get('id', [''])[0])
                except fcengine.SaveError as _ex:
                    return self.send(404, dict(ok=False, error=str(_ex)))
                return self.send(200, dict(ok=True, table=fcengine.table(_st, _qint(_q, 'league') or None),
                                           scorers=fcengine.scorers(_st, _qint(_q, 'league') or None)))
            if u.path == '/api/engine/select':
                _q = parse_qs(u.query)
                try:
                    _st = _eng_get(_q.get('id', [''])[0])
                except fcengine.SaveError as _ex:
                    return self.send(404, dict(ok=False, error=str(_ex)))
                _tid = _qint(_q, 'club') or _st['club']
                _opp = _qint(_q, 'opp') or None
                try:
                    _sel = fcengine.select(_st, _tid, _opp)
                except fcengine.SaveError as _ex:
                    return self.send(400, dict(ok=False, error=str(_ex)))
                _sel = dict(_sel)
                # Resolve through the engine's save-aware roster, NOT fc27db:
                # a youth-intake player has no database row, so fc27db.name()
                # returned '' and positions() defaulted him to CMF.
                from engine import roster as _eng_roster
                _sel['xi'] = [dict(pid=_p, name=_eng_roster.name(_st, _p),
                                   pos=_eng_roster.pos(_st, _p),
                                   ovr=_eng_roster.ovr(_st, _p)) for _p in _sel['xi']]
                _sel['bench'] = [dict(pid=_p, name=_eng_roster.name(_st, _p),
                                      pos=_eng_roster.pos(_st, _p),
                                      ovr=_eng_roster.ovr(_st, _p)) for _p in _sel['bench']]
                return self.send(200, dict(ok=True, selection=_sel))
            if u.path == '/api/engine/history':
                _q = parse_qs(u.query)
                try:
                    _st = _eng_get(_q.get('id', [''])[0])
                except fcengine.SaveError as _ex:
                    return self.send(404, dict(ok=False, error=str(_ex)))
                _lim = min(50, max(1, _qint(_q, 'limit', 10)))
                return self.send(200, dict(ok=True, seasons=fcengine.history(_st, _lim)))
            if u.path == '/api/i18n':
                # pc317: prijevod sucelja (data/i18n/<lang>.json, engleski tekst -> prijevod); prazno = engleski
                lg = re.sub(r'[^a-z]', '', parse_qs(u.query).get('lang', [''])[0])[:5]
                try:
                    d = json.load(open(os.path.join(HERE, 'data', 'i18n', lg + '.json'), encoding='utf-8')) if lg else {}
                except Exception:
                    d = {}
                return self.send(200, dict(lang=lg, strings={k: v for k, v in d.items() if isinstance(v, str) and v.strip()}))
            if u.path == '/api/fmtext':
                try:
                    return self.send(200, open(os.path.join(HERE, 'data', 'fm_text.json'), 'rb').read(), 'application/json')
                except Exception:
                    return self.send(200, b'{}', 'application/json')
            if u.path == '/api/clubcolors':
                import clubcolors
                return self.send(200, clubcolors.merged(os.path.join(HERE, 'data')))
            if u.path == '/api/venue':
                return self.send(200, venue_info(parse_qs(u.query).get('club', [''])[0]))
            if u.path == '/api/myscene':
                # pc204: lokalne scene (Home ured, konferencija) iz data/myscenes; ne idu u paket za druge
                _n = re.sub(r'[^a-z-]', '', parse_qs(u.query).get('n', [''])[0].lower())
                _d = os.path.join(HERE, 'data', 'myscenes')
                if _n == 'meta':
                    try:
                        return self.send(200, json.load(open(os.path.join(_d, 'scenes.json'), encoding='utf-8')))
                    except Exception:
                        return self.send(200, {})
                _f = os.path.join(_d, _n + '.jpg')
                if _n and os.path.isfile(_f):
                    return self.send(200, open(_f, 'rb').read(), 'image/jpeg')
                return self.send(404, b'', 'image/jpeg')
            if u.path == '/api/myscene-m':
                _n = re.sub(r'[^a-z-]', '', parse_qs(u.query).get('n', [''])[0].lower())
                _f = os.path.join(HERE, 'data', 'myscenes', _n + '-m.png')
                if _n and os.path.isfile(_f):
                    return self.send(200, open(_f, 'rb').read(), 'image/png')
                return self.send(404, b'', 'image/png')
            if u.path == '/api/art':
                _q = parse_qs(u.query)
                _n = re.sub(r'[^a-z-]', '', _q.get('n', [''])[0].lower())
                _cl = re.sub(r'[^a-z0-9]+', '-', _q.get('club', [''])[0].lower()).strip('-')
                _base = os.path.join(HERE, 'data', 'art')
                for _d in ([os.path.join(_base, _cl)] if _cl else []) + [_base]:
                    for _e, _ct in (('jpg', 'image/jpeg'), ('jpeg', 'image/jpeg'), ('png', 'image/png'), ('webp', 'image/webp')):
                        _f = os.path.join(_d, _n + '.' + _e)
                        if _n and os.path.isfile(_f):
                            return self.send(200, open(_f, 'rb').read(), _ct)
                return self.send(404, b'', 'image/jpeg')
            if u.path == '/api/stadium':
                _c = parse_qs(u.query).get('club', [''])[0]
                _sd = os.path.join(HERE, 'data', 'stadiums')
                _p = None
                if time.time() - _STAD_FAIL.get(_c, 0) > 600:
                    _p = wiki.fetch_stadium(_sd, _c)
                    if not _p:
                        _STAD_FAIL[_c] = time.time()
                if not _p:
                    return self.send(404, b'', 'image/jpeg')
                return self.send(200, open(_p, 'rb').read(), 'image/jpeg')
            if u.path == '/api/crest':
                _q = parse_qs(u.query)
                if 'club' in _q:
                    _kind, _id = 'clubs', _q['club'][0]
                elif 'league' in _q:
                    _kind, _id = 'leagues', _q['league'][0]
                elif 'nation' in _q:
                    _kind, _id = 'nations', _q['nation'][0]
                else:
                    return self.send(400, {'error': 'need club, league or nation'})
                _id = re.sub(r'[^0-9]', '', str(_id))[:9]
                if not _id:
                    return self.send(400, {'error': 'id must be numeric'})
                _tbl = {'clubs': fc27db.clubs, 'leagues': fc27db.leagues,
                        'nations': fc27db.nations}[_kind]()
                _row = (_tbl or {}).get(_id) or {}
                if not _row:
                    return self.send(404, {'error': 'unknown ' + _kind + ' id'})
                _b, _mt, _src = graphics.crest(_kind, _id, _row.get('name', ''),
                                               _row.get('colors'),
                                               os.path.join(HERE, 'data', 'graphics'))
                if _q.get('meta', [''])[0] in ('1', 'true'):
                    return self.send(200, dict(kind=_kind, id=_id, name=_row.get('name'),
                                               source=_src, mime=_mt, bytes=len(_b)))
                return self.send(200, _b, _mt)
            if u.path == '/api/face':
                _q = parse_qs(u.query)
                _gd = os.path.join(HERE, 'data', 'graphics')
                if 'manager' in _q:
                    _cid = re.sub(r'[^0-9]', '', str(_q['manager'][0]))[:9]
                    _mg = (fc27db.managers() or {}).get(_cid) or {}
                    _nm, _key, _desc = _mg.get('name') or '', 'm' + _cid, 'football manager'
                else:
                    _pid = re.sub(r'[^0-9]', '', str(_q.get('pid', [''])[0]))[:9]
                    if not _pid:
                        return self.send(400, {'error': 'need pid or manager'})
                    _nm, _key, _desc = fc27db.name(int(_pid)) or '', 'p' + _pid, 'footballer'
                _b, _mt, _src, _att = faces.face(_key, _nm, _gd,
                                                allow_network=bool(CFG.get('faces_web')),
                                                description=_desc)
                if _q.get('meta', [''])[0] in ('1', 'true'):
                    return self.send(200, dict(name=_nm, source=_src, mime=_mt,
                                               bytes=len(_b), attribution=_att))
                return self.send(200, _b, _mt)
            if u.path == '/api/graphics/status':
                _gd = os.path.join(HERE, 'data', 'graphics')
                _st = graphics.status(_gd)
                _st['faces'] = faces.status(_gd)
                _st['faces_web'] = bool(CFG.get('faces_web'))
                return self.send(200, _st)
            if u.path == '/favicon.ico':
                return self.send(204, b'', 'image/x-icon')
            name = 'index.html' if u.path in ('/', '') else u.path.lstrip('/').replace('\\', '/')
            if '..' in name.split('/') or name.startswith('/'):
                return self.send(404, {'error': 'not found'})
            p = os.path.join(HERE, 'static', *name.split('/'))
            if not os.path.isfile(p):
                return self.send(404, {'error': 'missing: ' + u.path})
            ct = {'html': 'text/html', 'css': 'text/css', 'js': 'text/javascript',
                  'svg': 'image/svg+xml', 'png': 'image/png', 'jpg': 'image/jpeg',
                  'jpeg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif',
                  'mp3': 'audio/mpeg', 'mp4': 'video/mp4'}.get(
                      p.rsplit('.', 1)[-1].lower(), 'application/octet-stream')
            return self.send(200, open(p, 'rb').read(), ct)
        except Exception as e:
            return self.send(500, {'error': str(e)})

    def do_POST(self):
        if not self._lan_guard(post=True):
            return
        try:
            n = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(n) or b'{}')
            if self.path == '/api/engine/new':
                try:
                    _club = int(body.get('club') or 0)
                except (TypeError, ValueError):
                    return self.send(400, dict(ok=False, error='club must be an integer'))
                if not _club:
                    return self.send(400, dict(ok=False, error='club is required'))
                _seed = body.get('seed')
                try:
                    _seed = int(_seed) if _seed is not None else None
                except (TypeError, ValueError):
                    return self.send(400, dict(ok=False, error='seed must be an integer'))
                try:
                    _st = fcengine.new(_club, manager=str(body.get('manager') or 'You'),
                                       leagues=body.get('leagues'), seed=_seed)
                    _eng_put(_st)
                except fcengine.SaveError as _ex:
                    return self.send(400, dict(ok=False, error=str(_ex)))
                except (ValueError, KeyError) as _ex:
                    return self.send(400, dict(ok=False, error=str(_ex)))
                return self.send(200, dict(ok=True, career=fcengine.summary(_st)))
            if self.path in ('/api/engine/play', '/api/engine/advance',
                             '/api/engine/save', '/api/engine/delete',
                             '/api/engine/transfer', '/api/engine/close_season',
                             '/api/engine/finish'):
                _sid = str(body.get('id') or '').strip()
                if self.path == '/api/engine/delete':
                    try:
                        _gone = fcengine.delete(_sid)
                    except fcengine.SaveError as _ex:
                        return self.send(400, dict(ok=False, error=str(_ex)))
                    with _ENG_LOCK:
                        _ENG_CACHE.pop(_sid, None)
                    return self.send(200 if _gone else 404,
                                     dict(ok=_gone, deleted=_sid if _gone else None))
                try:
                    _st = _eng_get(_sid)
                except fcengine.SaveError as _ex:
                    return self.send(404, dict(ok=False, error=str(_ex)))
                try:
                    if self.path == '/api/engine/play':
                        with _ENG_LOCK:
                            _r = fcengine.play_next(_st, body.get('club'))
                            _eng_put(_st)
                        if _r is None:
                            return self.send(200, dict(ok=True, result=None,
                                                       note='season complete',
                                                       career=fcengine.summary(_st)))
                        return self.send(200, dict(ok=True, result=_r,
                                                   career=fcengine.summary(_st),
                                                   table=fcengine.table(_st)))
                    if self.path == '/api/engine/advance':
                        # `body.get('days') or 1` would silently turn an
                        # explicit 0 into 1, so test for None instead.
                        _dv = body.get('days')
                        try:
                            _days = 1 if _dv is None else int(_dv)
                        except (TypeError, ValueError):
                            return self.send(400, dict(ok=False, error='days must be an integer'))
                        if not 1 <= _days <= 400:
                            return self.send(400, dict(ok=False, error='days must be 1..400'))
                        with _ENG_LOCK:
                            _r = fcengine.advance(_st, days=_days)
                            _eng_put(_st)
                        return self.send(200, dict(ok=True, advanced=_r['count'],
                                                   date=_r['date'],
                                                   career=fcengine.summary(_st),
                                                   table=fcengine.table(_st)))
                    if self.path == '/api/engine/finish':
                        with _ENG_LOCK:
                            _r = fcengine.finish_season(_st)
                            _eng_put(_st)
                        return self.send(200, dict(ok=True, played=_r['count'],
                                                   date=_r['date'],
                                                   complete=_r['complete'],
                                                   career=fcengine.summary(_st),
                                                   table=fcengine.table(_st)))
                    if self.path == '/api/engine/close_season':
                        # Refuse before mutating: close_season raises on an
                        # unfinished season, and a half-applied rollover would
                        # corrupt the career.
                        if not fcengine.season_finished(_st):
                            return self.send(400, dict(
                                ok=False, error='season is not finished',
                                career=fcengine.summary(_st)))
                        with _ENG_LOCK:
                            _rep = fcengine.close_season(_st)
                            _eng_put(_st)
                        # The full report can hold thousands of rows; ship the
                        # headline counts plus the leading movers.
                        _out = dict(_rep)
                        for _k in ('risers', 'fallers', 'retired', 'youth',
                                   'released', 'walked'):
                            _out[_k] = _rep[_k][:25]
                        return self.send(200, dict(ok=True, report=_out,
                                                   career=fcengine.summary(_st),
                                                   table=fcengine.table(_st)))
                    if self.path == '/api/engine/transfer':
                        try:
                            _pid, _to = int(body.get('pid') or 0), int(body.get('to') or 0)
                        except (TypeError, ValueError):
                            return self.send(400, dict(ok=False, error='pid and to must be integers'))
                        with _ENG_LOCK:
                            _moved = fcengine.move_player(_st, _pid, _to)
                            _eng_put(_st)
                        return self.send(200, dict(ok=True, moved=_moved, pid=_pid, to=_to))
                    with _ENG_LOCK:
                        _eng_put(_st)
                    return self.send(200, dict(ok=True, career=fcengine.summary(_st)))
                except fcengine.SaveError as _ex:
                    return self.send(400, dict(ok=False, error=str(_ex)))
            if self.path == '/api/lan/login':
                return self._lan_login(body)
            if self.path == '/api/lan/set':
                return self.send(200, lan_set(body))
            if self.path == '/api/clientlog':
                return self.send(200, client_log(body))
            if self.path == '/api/quit':
                # Only the launcher may stop the app; a browser page cannot
                # send this header from another origin.
                if self.headers.get('X-Gaffer') != '1':
                    return self.send(403, dict(error='forbidden'))
                threading.Timer(0.4, lambda: os._exit(0)).start()
                return self.send(200, dict(ok=True, version=APP_VERSION))
            return self.send(404, dict(ok=False, error='unknown endpoint: ' + self.path))
        except (ValueError, TypeError) as e:
            return self.send(400, dict(ok=False, error=str(e)))
        except Exception as e:
            return self.send(500, dict(ok=False, error=str(e)))


class _Srv(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets TWO processes listen on one port; bind exclusively.
    allow_reuse_address = (os.name != 'nt')

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


def main():
    global CFG
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--host', default='127.0.0.1',
                    help='bind address (default 127.0.0.1; 0.0.0.0 for LAN/preview)')
    a = ap.parse_args()
    CFG = load_cfg()
    if not fc27db.available():
        print('[fc27] data/fc27/players.json is missing - rebuild it with: node tools/import_fc27.mjs')
    else:
        _fcs = fc27db.summary()
        print('[fc27] database: %d players, %d clubs, %d leagues'
              % (_fcs['players'], _fcs['clubs'], _fcs['leagues']))
    port = a.port or CFG['port']
    try:
        srv = _Srv((a.host, port), H)
        CFG['_port'] = port
        if CFG.get('lan_on') and CFG.get('lan_pin'):
            lan_start()
    except OSError as ex:
        print('Cannot start on port %d (%s). Is The Gaffer or another program already using it?' % (port, ex))
        return
    _code_stamp()
    url = 'http://127.0.0.1:%d/' % port
    print('The Gaffer running at', url, '(Ctrl+C to exit)')
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
