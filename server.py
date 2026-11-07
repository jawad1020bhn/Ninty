#!/usr/bin/env python3
"""The Gaffer (prije Karijera 26) - lokalni poslužitelj (samo stdlib).

Pokretanje (na računalu s igrom):  python server.py
Razvoj bez igre:                   python server.py --dev-folder <mapa dekriptiranog save-a>

API
  GET  /api/state?slot=ML00000007   stanje karijere iz save-a (klub, tablica, sastav, formacije)
  GET  /api/slots                   popis ML save-ova
  POST /api/assign                  {preset, pool:[id]} -> XI poslozen po pozicijama
  POST /api/apply                   {slot, formations:{kickoff,in,out:[{pos,x,y}]}, xi:[id], bench:[id]}
  GET  /api/poll?slot=              vrijeme izmjene save-a + je li igra pokrenuta (za automatsko osvjezavanje)
  GET  /api/deals?slot=             prihvaceni dogovori koji se mogu prenamijeniti + budzet
  POST /api/swap                    {slot, old, new, fee, salary, release, end_year} prenamjena dogovora
  POST /api/launch                  pokreni igru
"""
import argparse, glob, hashlib, json, os, re, shutil, socket, struct, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = 'pc414'
APP_BUILT = '2026-11-07'
sys.path.insert(0, os.path.join(HERE, 'lib'))
import dds  # noqa: E402
import dbimport  # noqa: E402
import facemap  # noqa: E402
import mlsave, mlwrite, negotiate, seasonstats, aitransfers, market, aimanager, persona, wiki, growth, press, formengine, story  # noqa: E402
import world as worldlib  # noqa: E402
import nego2  # noqa: E402
import coaches  # noqa: E402
import press2  # noqa: E402
import talks as talkslib  # noqa: E402
import nlu  # noqa: E402
import awards as awardslib  # noqa: E402
import ailineup  # noqa: E402
import board as boardlib  # noqa: E402
import jobintro  # noqa: E402
import layoutscan  # noqa: E402
import pes17  # noqa: E402  (PES 2017 compatibility, read-only)
import loanscan  # noqa: E402
import realmoves  # noqa: E402  pc307 stvarni transferi (Wikipedia)
import regrules  # noqa: E402  pc195 pravila registracije (Michele & Claude)
import revalue  # noqa: E402  pc197 revalorizacija (Michele & Claude)
import fc27 as fc27db  # noqa: E402  EA SPORTS FC 27 database (data/fc27)

DEFAULT_CFG = {
    'save_dir': '',   # r9: never inherit pc414's machine-specific FL26 path; load_cfg() finds a real PES 2017 folder
    'decrypter': r'C:\pes_test\tool\Lib\decrypter21.exe',
    'encrypter': r'C:\pes_test\tool\Lib\encrypter21.exe',
    'work': r'C:\pes_test\ml_work',
    'pes_exe': '',   # r11: never inherit pc414's FL26 exe; load_cfg() finds a local PES 2017 install
    'pes_process': 'FL_2026',
    'port': 8765,
    'pes17_date_order': 'dmy',       # PES 2017 writes D/M/YYYY; set 'mdy' for US locales
    'pes17_allow_writes': False,     # safety: PES 2017 save writing is not mapped yet
    'dump': r'D:\FL 26\SiderAddons\content\ml-immersion\bridge\players_dump.bin',
    'telemetry': r'D:\FL 26\SiderAddons\content\ml-immersion\bridge\telemetry.json',
}
LOCK = threading.Lock()


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    p = os.path.join(HERE, 'config.json')
    if os.path.exists(p):
        cfg.update(json.load(open(p, encoding='utf-8')))
    for k in ('save_dir', 'decrypter', 'encrypter', 'work', 'pes_exe', 'dump', 'telemetry'):
        cfg[k] = os.path.expandvars(cfg[k])
    if not cfg.get('save_dir'):
        import pes17_setup
        cfg['save_dir'] = pes17_setup.autodetect()
    import pes17_setup as _p17s
    if _p17s.needs_game_discovery(cfg.get('pes_exe')):
        _detected_exe = _p17s.autodetect_exe(cfg.get('save_dir') or '')
        if _detected_exe:
            cfg['pes_exe'] = _detected_exe
    # alati iz paketa (mapa tools) i radna mapa uz app, ako zadane putanje ne postoje na ovom racunalu
    for k, fn in (('decrypter', 'decrypter21.exe'), ('encrypter', 'encrypter21.exe')):
        tp = os.path.join(HERE, 'tools', fn)
        if not os.path.isfile(cfg[k]) and os.path.isfile(tp):
            cfg[k] = tp
    if not os.path.isdir(os.path.dirname(cfg['work'])):
        cfg['work'] = os.path.join(HERE, 'work')
    return cfg



_JDUMP_LOCK = threading.Lock()


def _jdump(obj, path, **kw):
    """pc251: sigurno spremanje JSON-a (privremena datoteka + zamjena). Ako pisanje pukne (pad appa, nepodrzan tip u podacima,
    dvije niti istovremeno), stara datoteka ostaje cijela; prije se datoteka prvo ispraznila pa bi se podaci (karijera, pregovori...) izgubili."""
    tmp = '%s.%d.%d.tmp' % (path, os.getpid(), threading.get_ident())
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, **kw)
        with _JDUMP_LOCK:
            # pc254: na Windowsima zamjena ne uspije dok drugu nit drzi datoteku otvorenom (citanje) -> kratko ponovi;
            # ako i dalje ne ide, upisi izravno (kao prije pc251), da spremanje nikad ne bude losije nego prije
            for _k in range(12):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    time.sleep(0.05)
            else:
                with open(tmp, 'r', encoding='utf-8') as src, open(path, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

CFG = DEFAULT_CFG
mlwrite.BETA_FLAG = lambda k: bool(CFG.get(k, True))   # pc247: beta prekidaci iz config.json; pc301: za javni test zadano UKLJUCENO (iskljuci s "...": false)
DEV = None
NAMES = {}
POS = {}
RAT = {}
RATAB = []
PLAYPOS = {}   # {pid: '13 znamenki' razina pozicije po kodu 0..12: 0 nema, 1 B, 2 A (natural/registrirana)}
_PP_BITS = (274, 268, 270, 272, 260, 262, 264, 266, 258, 253, 256, 251, 249)


_GR = dict(t=0.0, v=False)


def _hidden_kw(kw):
    """pc186: pomocni programi (tasklist, decrypter, encrypter, powershell) bez konzolnog prozora koji bljesne i igri ukrade fokus
    (tester 29.10.: tasklist pokrenut iz appa dok igra radi)."""
    if os.name == 'nt':
        kw['creationflags'] = kw.get('creationflags', 0) | getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        if 'startupinfo' not in kw:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= getattr(subprocess, 'STARTF_USESHOWWINDOW', 1)
            si.wShowWindow = 0
            kw['startupinfo'] = si
    return kw


def _run(args, **kw):
    return subprocess.run(args, **_hidden_kw(kw))


def game_running():
    """pc147: tasklist traje 0.1-0.3 s, a zove se vise puta po zahtjevu: rezultat vrijedi 3 s."""
    if DEV:
        return False
    if time.time() - _GR['t'] < 3:
        return _GR['v']
    if os.name != 'nt':
        # pc380: Linux (Wine/Proton/Lutris): tasklist ne postoji pa je app mislio da igra nikad ne radi (i nije cuvao upis)
        v = False
        try:
            want = (CFG['pes_process'] + '.exe').lower()
            want17 = 'pes2017.exe' if _GAME['save'] == 'pes17' else ''
            for p_ in os.listdir('/proc'):
                if not p_.isdigit() or int(p_) == os.getpid():
                    continue
                try:
                    cl = open('/proc/%s/cmdline' % p_, 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace').lower()
                except Exception:
                    continue
                if want in cl.replace('\\', '/') or (want17 and want17 in cl.replace('\\', '/')):
                    v = True
                    break
        except Exception:
            v = False
        _GR.update(t=time.time(), v=v)
        return v
    try:   # pc413: popis procesa bez pokretanja tasklist.exe (novi proces svake 3 s dok igra radi mogao je trgati igru)
        import gamemem
        _pnames = [CFG['pes_process'] + '.exe']
        if _GAME['save'] == 'pes17' and 'PES2017.exe' not in _pnames:
            _pnames.append('PES2017.exe')
        v = any(gamemem._win_pid(n) for n in _pnames)
        _GR.update(t=time.time(), v=v)
        return v
    except Exception:
        pass
    try:
        out = _run(['tasklist', '/FI', 'IMAGENAME eq %s.exe' % CFG['pes_process'], '/NH'],
                             capture_output=True, text=True, timeout=10).stdout
        v = CFG['pes_process'].lower() in out.lower()
    except Exception:
        v = False
    _GR.update(t=time.time(), v=v)
    return v


_MENU = dict(on=False)


def _sys_mtime():
    """Vrijeme zadnjeg spremanja igre: igra pri svakom spremanju (samo u Master Ligi) prepise i SYSTEM00000000."""
    try:
        return os.path.getmtime(os.path.join(CFG['save_dir'], 'SYSTEM00000000'))
    except Exception:
        return None


_MEMST = dict(started=False)


def _save_sig():
    try:
        sd = CFG['save_dir']
        return tuple(sorted((f, os.path.getsize(os.path.join(sd, f)), int(os.path.getmtime(os.path.join(sd, f)) * 1000))
                            for f in os.listdir(sd) if f.startswith(('ML', 'SYSTEM'))))
    except Exception:
        return None


def _memwatch():
    """pc391: svake sekunde dok igra radi procita datum iz memorije igre (lib/gamemem.py, samo citanje).
    Stanja: 'ml' (datum valjan), 'home' (65535-00-00), 'null' (prije prvog ucitavanja), 'unknown'."""
    import gamemem
    pr = None
    while True:
        try:
            if (CFG.get('auto_menu', True) and not DEV and _GAME['save'] != 'pes17'
                    and game_running()):
                if pr is None:
                    pr = gamemem.Probe(CFG.get('pes_process') or '')
                r = pr.probe()
                now = time.time()
                _MEMST['polled'] = now
                perr = getattr(pr, 'err', '')
                if perr and perr != _MEMST.get('lasterr'):
                    print('[menu auto] %s' % perr)
                _MEMST['lasterr'] = perr
                if not r:
                    # pc394: igra je pokrenuta kao administrator (WinError 5) ili drugi razlog: stanje iz Sider modula
                    # GrowthBridge 1.6 (bridge\\game_state.txt, cita isti lanac iz same igre)
                    L = _lua_game_state()
                    if L:
                        st, sess, changed, seen = L
                        if st == 'ml':
                            # pc401: pri izlasku iz ML-a igra cesto ne pozove nijedan Sider dogadjaj nakon sto datum postane nevaljan,
                            # pa modul ostane na 'ml'. Sider tada u sider.log zapise "context reset" (izmjereno: 3 izlaska = 3 retka).
                            cr = _sider_ctx_reset()
                            if cr and cr >= changed:
                                st, changed = 'home', cr
                        if _MEMST.get('pid') != 'lua:%s' % sess:
                            _MEMST.update(pid='lua:%s' % sess, seen_ml=False, seen_home=False, state=None)
                        if seen or st == 'ml':
                            _MEMST['seen_ml'] = True
                        if st == 'home':
                            _MEMST['seen_home'] = True
                        if st != _MEMST.get('state') or _MEMST.get('since') != changed:
                            if st != _MEMST.get('state'):
                                print('[menu auto] game (Sider): %s' % st)
                            _MEMST.update(state=st, since=changed, home_ok=False)
                        sig = _save_sig()
                        if sig != _MEMST.get('sig'):
                            _MEMST.update(sig=sig)
                            if not _MEMST.get('home_ok'):
                                _MEMST['sig_since'] = now
                        if (st == 'home' and _MEMST.get('seen_ml') and now - changed >= 3
                                and now - _MEMST.get('sig_since', now) >= 3):
                            _MEMST['home_ok'] = True
                    else:
                        _MEMST.update(state=None, pid=None)
                else:
                    pid, st, dt = r
                    if _MEMST.get('pid') != pid:
                        _MEMST.update(pid=pid, seen_ml=False, seen_home=False, state=None, since=now)
                    if st == 'ml':
                        _MEMST['seen_ml'] = True     # lanac radi na ovom exeu (valjan datum)
                    if st == 'home':
                        _MEMST['seen_home'] = True
                    if st != _MEMST.get('state'):
                        print('[menu auto] game %s: %s%s' % (pid, st, (' %d-%02d-%02d' % dt) if dt else ''))
                        _MEMST.update(state=st, since=now, date=dt, home_ok=False)
                    sig = _save_sig()
                    if sig != _MEMST.get('sig'):
                        # dok je pocetni zaslon vec potvrdjen, igra ne sprema (sprema samo u ML-u): promjena je upis appa
                        _MEMST.update(sig=sig)
                        if not _MEMST.get('home_ok'):
                            _MEMST['sig_since'] = now
                    if (st == 'home' and _MEMST.get('seen_ml') and now - _MEMST.get('since', now) >= 3
                            and now - _MEMST.get('sig_since', now) >= 3):
                        _MEMST['home_ok'] = True
            else:
                if pr is not None:
                    pr.close()
                    pr = None
                _MEMST.update(state=None, pid=None)
        except Exception as ex:
            _MEMST.update(state=None, err=str(ex)[:120])
        time.sleep(1)


def _sider_ctx_reset():
    """pc401: vrijeme izmjene sider.log ako mu je zadnji redak 'context reset' (Sider ga pise pri izlasku iz Master Lige), inace None."""
    try:
        fp = os.path.join(_sider_root() or '', 'sider.log')
        if not os.path.isfile(fp):
            return None
        sz = os.path.getsize(fp)
        with open(fp, 'rb') as f_:
            f_.seek(max(0, sz - 3000))
            tail = f_.read().decode('latin-1', 'replace')
        lines = [x.strip() for x in tail.splitlines() if x.strip()]
        if 'context reset' in lines:
            k = len(lines) - 1 - lines[::-1].index('context reset')
            # pc403: FL26 nakon toga jos zapise izbornik (BroadcastServer: ...TopMenu\TopMenuNew.json); to je i dalje glavni izbornik
            if all('TopMenu' in x for x in lines[k + 1:]):
                return os.path.getmtime(fp)
    except Exception:
        pass
    return None


def _lua_game_state():
    """pc394: (stanje, sesija, vrijeme promjene, vidio_ml) iz bridge\\game_state.txt (GrowthBridge 1.6) ili None."""
    try:
        root = _sider_root()
        fp = os.path.join(root, 'content', 'ml-immersion', 'bridge', 'game_state.txt') if root else ''
        if not fp or not os.path.isfile(fp):
            return None
        parts = open(fp, encoding='utf-8', errors='ignore').read().split()
        st, sess, changed, seen = parts[0], parts[1], float(parts[2]), parts[3] == '1'
        if st not in ('ml', 'home', 'null', 'unknown', 'error'):
            return None
        return st, sess, changed, seen
    except Exception:
        return None


def _auto_menu():
    """pc391 (tester, FL26/FL27): True = sigurno na pocetnom zaslonu (datum u memoriji 65535-00-00 bar 3 s, a lanac je u ovoj
    igri vec dao valjan datum, i saveovi se 3 s nisu mijenjali); False = sigurno u Master Ligi (valjan datum, a lanac je vec
    pokazao i pocetni zaslon); None = ne zna se (drugi exe, nema citanja...) -> rucna potvrda kao prije."""
    if not _MEMST.get('started'):
        _MEMST['started'] = True
        threading.Thread(target=_memwatch, daemon=True).start()
        return None
    if time.time() - _MEMST.get('polled', 0) > 3:
        return None
    st = _MEMST.get('state')
    if st == 'home' and _MEMST.get('home_ok'):
        return True
    if st == 'ml' and _MEMST.get('seen_home'):
        return False
    return None


def menu_ok():
    """Korisnik je potvrdio da je igra u glavnom meniju (ne u Master Ligi): save se smije pisati dok igra radi.
    Gasi se kad se igra zatvori, nakon svakog upisa iz appa (potvrda vrijedi za jedan upis) i kad igra spremi (znaci da je bila u ML-u).
    pc391: ako app iz memorije igre zna gdje je igra, ne treba klik (vidi _auto_menu)."""
    if not game_running():
        _MENU['on'] = False
    a = _auto_menu() if game_running() else None
    if a is True:
        return True
    if a is False:
        _MENU['on'] = False
        return False
    if _MENU['on'] and _MENU.get('sys') != _sys_mtime():
        _MENU['on'] = False
    return bool(_MENU['on'])


def set_menu(on):
    _MENU['on'] = bool(on) and game_running()
    _MENU['sys'] = _sys_mtime()
    return dict(ok=True, menu_ok=menu_ok(), game_running=game_running())


WRITES = []   # upisi iz appa koji moraju 'prezivjeti' u igri: dict(slot, kind, pid, t) - provjera u state()


def _overwritten(slot, s):
    """Upisi iz appa koje je igra prepisala (igra je spremila preko njih jer je bila u Master Ligi): [{kind, pid, name}]."""
    out = []
    try:
        mt = os.path.getmtime(os.path.join(CFG['save_dir'], slot))
    except Exception:
        return out
    keep = []
    for w in WRITES:
        if w['slot'] != slot or mt <= w['t'] + 2:
            keep.append(w)
            continue
        pid = w['pid']
        alive = pid in s.my_squad_tags()
        if not alive and w['kind'] == 'loan_in':
            try:
                QB = mlwrite.X(0x244eb70)
                alive = any(struct.unpack_from('<I', s.d, QB + 56 * k)[0] == 0x6e and struct.unpack_from('<I', s.d, QB + 56 * k + 8)[0] == pid for k in range(200))
            except Exception:
                alive = True
        if not alive:
            try:
                if pid in {p for p, _f in s.cancelled_loans()}:
                    continue   # posudbu je ponistila igra (vidi 'Moji potpisi' -> povrat), nije prepisana
            except Exception:
                pass
            out.append(dict(kind=w['kind'], pid=pid, name=NAMES.get(pid, str(pid))))
    WRITES[:] = keep
    return out


def game_blocks():
    """Blokira pisanje u save: igra radi i nije potvrdjen glavni meni."""
    return game_running() and not menu_ok()


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


KEY_MARK = 'gaffer_key.txt'   # pc264: u dekriptiranoj mapi: save je kriptiran kljucem Football Life 2027 (FL_key.bin), ne PES 2021


def _fl_key():
    """pc264: kljuc saveova Football Life 2027 (64 B, FL_key.bin): config 'fl_key', mapa appa, mapa igre ili mapa saveova."""
    cands = [CFG.get('fl_key'), os.path.join(HERE, 'FL_key.bin')]
    for k in ('pes_exe', 'save_dir'):
        if CFG.get(k):
            b = CFG[k] if os.path.isdir(CFG[k]) else os.path.dirname(CFG[k])
            cands += [os.path.join(b, 'FL_key.bin'), os.path.join(os.path.dirname(b), 'FL_key.bin')]
    for c in cands:
        try:
            if c and os.path.isfile(c) and os.path.getsize(c) == 64:
                return open(c, 'rb').read()
        except Exception:
            pass
    return None


def decrypt(src, outdir):
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    os.makedirs(os.path.dirname(outdir), exist_ok=True)
    err = None
    # pc361: saveovi se dekriptiraju ugradjenim Pythonom (pesXdecrypter algoritam, byte-za-byte isto kao decrypter21.exe).
    # decrypter21.exe vise ne ide u paket (antivirusi ga prijavljuju kao 'encoder'); koristi se samo ako ga netko ima i Python ne uspije.
    # Proba PES 2021 pa FL kljuc; uspjeh se provjerava zbrojem velicina blokova (kriv kljuc = ne poklapa se).
    import pescrypt
    raw = open(src, 'rb').read()
    # PES 2017 compatibility: try every known master key and remember which
    # one opened this save, so re-encryption always uses the same key.
    for name, key in pescrypt.key_candidates(_fl_key()):
        if not key:
            continue
        try:
            parts = pescrypt.decrypt_bytes(raw, key)
        except ValueError:
            continue
        if os.path.exists(outdir):
            shutil.rmtree(outdir)
        os.makedirs(outdir)
        for k_, v_ in parts.items():
            with open(os.path.join(outdir, k_), 'wb') as fh:
                fh.write(v_)
        with open(os.path.join(outdir, KEY_MARK), 'w') as fh:
            fh.write(name)
        return
    try:
        if os.path.isfile(CFG.get('decrypter') or ''):
            if os.path.exists(outdir):
                shutil.rmtree(outdir)
            _run([CFG['decrypter'], src, outdir], check=True, capture_output=True, timeout=120)
            if os.path.exists(os.path.join(outdir, 'data.dat')):
                return
    except Exception as ex:
        err = ex
    raise RuntimeError('decryption failed (%s). Tried the PES 2021, Football Life 2027 and PES 2017 save keys. '
                       'FL27 saves need FL_key.bin in the app folder.' % err)


ENC_BLOCKED = ('Windows Defender (or another antivirus) blocked or deleted encrypter21.exe, so the app cannot write the save. '
               'Restore it from the quarantine / allow it, or add an exclusion for the app\'s tools folder (%s). Nothing was written; the save is unchanged.')


def _enc_check(rr):
    if rr.returncode != 0:
        raise RuntimeError('encrypter21.exe failed (exit code %s%s). Nothing was written; the save is unchanged.%s' % (
            rr.returncode, ', ' + str(rr.stderr or rr.stdout or '').strip()[-160:] if (rr.stderr or rr.stdout) else '',
            ' It may have been blocked by the antivirus: add an exclusion for %s.' % os.path.dirname(CFG.get('encrypter') or '') if rr.returncode in (225, -1, 1) else ''))
    return rr


def encrypter_status():
    """pc316 (Michele & Alex): postoji li encrypter21.exe i moze li se pokrenuti (antivirus ga zna obrisati: WinError 225).
    pc361: enkripcija je ugradjena (pescrypt), exe vise ne treba."""
    return dict(ok=True, builtin=True)


def encrypt(new_dec, newfile):
    """pc264: PES 2021 save ide kroz encrypter21.exe kao prije; FL 2027 save (oznaka u mapi) kroz pescrypt s FL kljucem."""
    key_name = ''
    try:
        with open(os.path.join(new_dec, KEY_MARK), encoding='utf-8', errors='ignore') as fh:
            key_name = fh.read().strip()
    except OSError:
        pass
    # PES 2017 compatibility: hard stop until its write tables are mapped.
    # This also catches paths that do not go through mlwrite.Save.save().
    if key_name == 'pes17' and not CFG.get('pes17_allow_writes', False):
        raise RuntimeError(pes17.READ_ONLY_MSG)
    if key_name and key_name != 'pes21':
        import pescrypt
        key = pescrypt.key_for(key_name, _fl_key())
        if not key:
            raise RuntimeError('Missing save key for %s (FL_key.bin / PES 2017 key). Nothing was written.' % key_name)
        parts = {}
        for k_ in ('encryptHeader.dat', 'header.dat', 'description.dat', 'logo.png', 'data.dat', 'version.txt'):
            p_ = os.path.join(new_dec, k_)
            parts[k_] = open(p_, 'rb').read() if os.path.exists(p_) else b''
        out = pescrypt.encrypt_parts(parts, key)
        pescrypt.decrypt_bytes(out, key)   # provjera prije upisa
        with open(newfile + '.tmp', 'wb') as fh:
            fh.write(out)
        os.replace(newfile + '.tmp', newfile)
        return type('R', (), dict(returncode=0, stdout='', stderr=''))()
    # pc361: PES 2021 / FL26 / vanilla save: ugradjena enkripcija (isti rezultat kao encrypter21.exe, provjereno byte-za-byte),
    # uz provjeru dekriptom prije upisa. encrypter21.exe samo kao rezerva ako ga netko ima.
    try:
        import pescrypt
        parts = {}
        for k_ in ('encryptHeader.dat', 'header.dat', 'description.dat', 'logo.png', 'data.dat', 'version.txt'):
            p_ = os.path.join(new_dec, k_)
            parts[k_] = open(p_, 'rb').read() if os.path.exists(p_) else b''
        if not parts['encryptHeader.dat'] or not parts['header.dat'] or not parts['data.dat']:
            raise ValueError('incomplete decrypted save')
        out = pescrypt.encrypt_parts(parts, pescrypt.KEY_PES21)
        chk = pescrypt.decrypt_bytes(out, pescrypt.KEY_PES21)
        if chk['data.dat'] != parts['data.dat']:
            raise ValueError('verification failed')
        with open(newfile + '.tmp', 'wb') as fh:
            fh.write(out)
        os.replace(newfile + '.tmp', newfile)
        return type('R', (), dict(returncode=0, stdout='', stderr=''))()
    except Exception as ex:
        if not os.path.isfile(CFG.get('encrypter') or ''):
            raise RuntimeError('Encrypting the save failed (%s). Nothing was written; the save is unchanged.' % ex)
    exe = CFG['encrypter']
    if not os.path.isfile(exe):
        raise RuntimeError(ENC_BLOCKED % os.path.dirname(exe))
    try:
        return _run([exe, new_dec, newfile], capture_output=True, timeout=120)
    except OSError as ex:
        if getattr(ex, 'winerror', None) == 225 or 'virus' in str(ex).lower():
            raise RuntimeError(ENC_BLOCKED % os.path.dirname(exe))
        raise RuntimeError('encrypter21.exe could not be started (%s). Nothing was written; the save is unchanged.' % ex)


def slot_folder(slot):
    """Dekriptirani save u kešu (po slotu + vremenu izmjene)."""
    if DEV:
        _sync_game(DEV)
        return DEV
    src = os.path.join(CFG['save_dir'], slot)
    if not os.path.isfile(src) or not slot.startswith('ML0'):
        raise FileNotFoundError(slot)
    # pc148: jedan dekript odjednom; save koji se upravo pise (vrijeme izmjene se jos mijenja) pricekamo, inace jedan zahtjev
    # dekriptira poluzapisan save, a drugi mu obrise mapu (greska "No such file ... description.dat" odmah nakon upisa)
    with _SF_LOCK:
        for _ in range(10):
            mt = os.path.getmtime(src)
            if time.time() - mt >= 1.5:
                break
            time.sleep(0.5)
            if os.path.getmtime(src) == mt:
                break
        key = '%s_%d' % (slot, int(os.path.getmtime(src)))
        if _save_year(CFG.get('save_dir') or '') not in ('', '2026'):   # pc266: isti slot u drugoj igri (FL27) ima svoju mapu u kesu
            key += '_' + _save_year(CFG.get('save_dir') or '')
        cd = os.path.join(CFG['work'], 'cache')
        d = os.path.join(cd, key)
        if not os.path.exists(os.path.join(d, 'data.dat')) or not os.path.exists(os.path.join(d, 'description.dat')):
            # pc175: dekript u privremenu mapu pa preimenovanje (nikad poluzapisana mapa), a stare mape istog slota se NE brisu
            # odmah: drugi zahtjev ih mozda jos cita (tester 28.10.: "No such file ... description.dat" pri Confirm loan).
            # Ostaju 3 najnovije; starije od 2 minute se brisu.
            tmp = d + '.tmp%d' % threading.get_ident()
            shutil.rmtree(tmp, ignore_errors=True)
            decrypt(src, tmp)
            shutil.rmtree(d, ignore_errors=True)
            try:
                os.replace(tmp, d)
            except OSError:   # Windows ponekad ne da preimenovati (antivirus): dekriptiraj ravno u mapu
                shutil.rmtree(tmp, ignore_errors=True)
                decrypt(src, d)
            try:
                olds = sorted((x for x in os.listdir(cd) if x.startswith(slot + '_') and x != key and '.tmp' not in x),
                              key=lambda x: os.path.getmtime(os.path.join(cd, x)), reverse=True)
                for x in olds[2:]:
                    if time.time() - os.path.getmtime(os.path.join(cd, x)) > 120:
                        shutil.rmtree(os.path.join(cd, x), ignore_errors=True)
            except Exception:
                pass
        _sync_game(d)
        return d


_SF_LOCK = threading.RLock()


def rows_json(save, k):
    if getattr(save, 'pes17', False):
        return save.formation_rows(k)
    rows = []
    for i in range(11):
        F0 = getattr(save, 'F0', mlwrite.F0)   # pc306: reprezentacija ima svoj blok
        f = save.d[F0 + mlwrite.FORM_SZ * k:F0 + mlwrite.FORM_SZ * (k + 1)]
        rows.append(dict(pos=f[i], x=f[11 + 2 * i], y=f[12 + 2 * i]))
    return rows


_DN = {}


def dump_names():
    """{pid: (ime, dob)} iz zivog dumpa (za regene i igrace koji nisu u statickoj bazi)."""
    p = CFG.get('dump') or ''
    if not os.path.exists(p):
        return {}
    mt = os.path.getmtime(p)
    if _DN.get('mt') == mt:
        return _DN['d']
    d = open(p, 'rb').read()
    out = {}
    for i in range(len(d) // 380):
        b = d[i * 380:(i + 1) * 380]
        pid = struct.unpack_from('<I', b, 0x30)[0]
        nm = b[0x38:0x38 + 46].split(b'\0')[0].decode('utf-8', 'replace')
        if pid and nm:
            out[pid] = (nm, b[0x1C] & 63)
    _DN['mt'], _DN['d'] = mt, out
    return out


def live_name(pid, dn):
    v = dn.get(pid)
    if not v:
        return NAMES.get(pid, str(pid))
    if pid not in NAMES:
        return v[0]
    try:
        _o, a = rat(pid)
    except Exception:
        a = 0
    return v[0] if (v[1] <= 17 and a and a >= v[1] + 3) else NAMES.get(pid, v[0])


_RAT0, _AR = {}, {}
_REGEN = set()   # pc236: samo pravi regeni (novi igrac na ID-u umirovljenog); _RAT0 ima i obicne igrace kojima je igra promijenila OVR/dob


def apply_regens():
    """Regeni su umirovljeni igraci na istom ID-u: staticka baza (ime, dob, OVR, atributi, pozicija) vrijedi za starca. Kad postoji dump, pregazi ih zivim podacima."""
    p = CFG.get('dump') or ''
    if not os.path.exists(p):
        return
    bp = dbimport.BASE_PATH
    # pc289: kljuc ukljucuje i FL27 nacin (zivi OVR) i osnovnu tablicu - inace prvi poziv prije prepoznavanja igre ostane zapamcen
    mt = (os.path.getmtime(p), dbimport.USE_GAME_OVR, os.path.getmtime(bp) if bp and os.path.exists(bp) else None)
    if _AR.get('mt') == mt:
        return
    _AR['mt'] = mt
    d = open(p, 'rb').read()
    for i in range(len(d) // 380):
        b = d[i * 380:(i + 1) * 380]
        pid = struct.unpack_from('<I', b, 0x30)[0]
        r0 = _RAT0.get(pid) or RAT.get(pid)
        if not r0 or pid not in NAMES:
            continue
        age = b[0x1C] & 63
        go = dbimport.game_ovr(b)   # pc289: FL27 zivi OVR (vidi dbimport.game_ovr); pc193: OVR koji racuna sama igra (zivi zapis, +0x179; izvor: Michele & Claude, TECHNICAL_MAP)
        if not (age <= 17 and r0[1] >= age + 3):
            if 40 <= go <= 99 and (r0[0] != go or r0[1] != age):
                # obican igrac: OVR i dob iz igre (s rastom/treningom, i u bazama gdje uvoz OVR-a nije tocan)
                _RAT0.setdefault(pid, r0)
                RAT[pid] = list(r0)
                RAT[pid][0], RAT[pid][1] = go, age
            continue
        try:
            att = growth.attrs_from_block(b)
            lv = _youth_block(b)
            gl = [_YPOS[k] for k, x in enumerate(lv) if x == 2] or [_YPOS[k] for k, x in enumerate(lv) if x == 1] or ['CMF']
            _pr = ['GK', 'CMF', 'DMF', 'CB', 'RB', 'LB', 'AMF', 'CF', 'SS', 'LWF', 'RWF', 'LMF', 'RMF']
            mp = sorted(gl, key=lambda q: _pr.index(q))[0]
            ovr = go if 40 <= go <= 99 else _youth_ovr(att, mp)   # pc193: OVR iz igre, procjena samo ako ga nema
            nm = b[0x38:0x38 + 46].split(b'\0')[0].decode('utf-8', 'replace')
            if not nm:
                continue
            _RAT0.setdefault(pid, r0)
            _REGEN.add(pid)
            RAT[pid] = list(r0[:10]) + [[att.get(k, 0) for k in RATAB]]
            RAT[pid][0], RAT[pid][1] = ovr, age
            NAMES[pid] = nm
            POS[pid] = _YPOS.index(mp)
            _v = int.from_bytes(b[30:40], 'little')
            PLAYPOS[pid] = ''.join(str((_v >> (l - 240)) & 3) for l in _PP_BITS)
        except Exception:
            continue


def pes17_readonly(slot=None):
    """Early, friendly refusal for every endpoint that writes into the save."""
    if _GAME['save'] == 'pes17':
        raise ValueError(pes17.READ_ONLY_MSG)


def pes17_auto_db(folder):
    """First PES 2017 load: build data/pes17/*.json from EDIT00000000.

    The FL26 player database has different player IDs, so without this the
    squad would show FL26 names (or just numbers).  Sider/F7 dumps do not
    exist for PES 2017 in this build, so the EDIT file is the source.
    """
    if _GAME['save'] != 'pes17':
        return
    out = os.path.join(HERE, 'data', 'pes17')
    if os.path.exists(os.path.join(out, 'players.json')):
        return
    cands = [CFG.get('edit_dat') or '']
    sd = CFG.get('save_dir') or ''
    if sd:
        cands.append(os.path.join(sd, 'EDIT00000000'))
    if DEV:
        cands += [os.path.join(os.path.dirname(DEV), 'EDIT00000000'),
                  os.path.join(DEV, 'EDIT00000000')]
    src = next((p for p in cands if p and os.path.isfile(p)), '')
    try:
        pes17.import_teams(folder, out)
    except Exception as ex:
        print('[pes17] team ids:', ex)
    if not src:
        print('[pes17] EDIT00000000 not found: player names stay unknown. '
              'Put it next to the save or set edit_dat in config.json.')
        return
    try:
        st = pes17.import_edit(src, out)
        reload_db()
        print('[pes17] EDIT database:', st)
    except Exception as ex:
        print('[pes17] EDIT import:', ex)


def pes17_tools_info(slot):
    # Real-save PES 2017 info (read side), independent of the FL26 views.
    import pes17_write
    if _GAME['save'] != 'pes17':
        _GAME['save'] = 'pes17'
    try:
        pes17.ensure_teamids(CFG, os.path.join(HERE, 'data', 'pes17'))
    except Exception as _ex:
        print('[pes17] teamids:', _ex)
    src = os.path.join(CFG['save_dir'], slot)
    c = pes17_write.Pes17Container.load(src)
    ep = CFG.get('edit_dat') or os.path.join(CFG['save_dir'], 'EDIT00000000')
    ec = None
    if os.path.isfile(ep):
        try:
            ec = pes17_write.load_edit(ep)
        except Exception as ex:
            print('[pes17] EDIT load:', ex)
    return pes17_write.info(c, ec)


def pes17_tools_apply(slot, ops, dry=False, layout_check=True):
    # Measured, round-trip-verified PES 2017 writes.  All FL26 write
    # endpoints remain blocked by pes17_readonly().  r5: verify the measured
    # t99p17v20 layout BEFORE any op runs (see lib/pes17_pairs.py).
    import pes17_write
    src = os.path.join(CFG['save_dir'], slot)
    with LOCK:
        c = pes17_write.Pes17Container.load(src)
        ep = CFG.get('edit_dat') or os.path.join(CFG['save_dir'], 'EDIT00000000')
        ec = None
        if os.path.isfile(ep):
            try:
                ec = pes17_write.load_edit(ep)
            except Exception:
                ec = None
        results, changed = pes17_write.apply_ops(
            c, ops, ec.data if ec else None, layout_check=layout_check)
        lay = getattr(c, 'layout', None)
        if dry:
            c.encrypt()          # prove the modified container re-encrypts
            return dict(ok=True, dry=True, changed_bytes=changed,
                        results=results, layout=lay)
        r = pes17_write.save_with_backup(src, c, CFG['work'])
        PCACHE.clear()
        _REV[0] += 1
        r.update(dict(changed_bytes=changed, results=results, layout=lay))
        return r


def state(slot):
    _CUR_SLOT['slot'] = slot
    try:
        if not DEV and slot.startswith('ML0') and slot not in auto_view():   # pc413: kesirano citanje (autotransfer.json zna imati 10 MB)
            with AUTO_LOCK:
                _st = auto_load()
                if slot not in _st:
                    _st[slot] = dict(enabled=True, fresh=True)   # pc413: nova karijera -> _auto_default ukljuci i AI taktike
                    auto_save(_st)
    except Exception:
        pass
    d = slot_folder(slot)
    apply_regens()   # pc289: nakon slota (prepoznavanje igre)
    if pes17.is_pes17(d):
        try:
            pes17_auto_db(d)
        except Exception as ex:
            print('[pes17] database:', ex)
        ed = None
        try:
            ep = CFG.get('edit_dat') or os.path.join(CFG['save_dir'], 'EDIT00000000')
            if ep and os.path.isfile(ep):
                ed = pes17._edit_data(ep)
        except Exception as ex:
            print('[pes17] EDIT data:', ex)
        r = pes17.read_save(d, date_order=CFG.get('pes17_date_order', 'dmy'), edit_data=ed)
    else:
        r = mlsave.read_save(d, None)
    s = mlwrite.Save(d)
    try:
        career_guard(slot, s)
    except Exception as ex:
        print('[career]', ex)
    ids = s.squad_ids()
    squad = []
    nums = s.squad_numbers()
    try:
        _dn = dump_names()
    except Exception:
        _dn = {}
    for i, pid in enumerate(ids):
        if pid:
            squad.append(dict(idx=i, id=pid, name=live_name(pid, _dn), pos=POS.get(pid, 5), no=nums.get(i, 0)))
    try:   # pc316: ozljeda, kondicija, zuti kartoni iz savea
        _stt = s.read_status([x['id'] for x in squad])
        for x in squad:
            v = _stt.get(x['id'])
            if v:
                x['inj'], x['cond'] = v['inj'], v['cond']
                if v['yc']:
                    x['yc'] = max(v['yc'].values())
    except Exception as ex:
        print('[status]', ex)
    lu = s.lineup()
    idx2id = {i: p for i, p in enumerate(ids) if p}
    xi = [idx2id.get(i) for i in lu[:11]]
    bench = [idx2id.get(i) for i in lu[11:23] if i != 0xff and idx2id.get(i)]
    tbl = r.get('league_table', [])
    try:
        _cv = comps_view(slot)
        _m = next((c for c in _cv['comps'] if c['kind'] == 'league' and c['mine']), None)
        if _m and _m['rows']:
            tbl = _m['rows']
    except Exception:
        pass
    try:
        threading.Thread(target=history_tick, args=(slot,), daemon=True).start()   # pc241: arhiva sezone u pozadini
    except Exception:
        pass
    try:
        threading.Thread(target=growth_auto_tick, args=(slot,), daemon=True).start()   # pc288: automatski mjesecni trening
    except Exception:
        pass
    try:
        realmoves_fetch_bg()   # pc307
    except Exception:
        pass
    try:
        _ledger_snap(slot, s)   # pc316
    except Exception:
        pass
    try:
        _board_money_auto(slot, s)   # pc316: bonus uprave se upise sam kad je save siguran za upis
    except Exception as ex:
        print('[board] auto bonus:', ex)
    try:   # pc350: zaustavljanje igre iskljuceno (srusilo igru): makni zaustavljanja koja je app upisao
        _stops_cleanup(slot, s)
    except Exception as ex:
        print('[stops] cleanup:', ex)
    try:   # pc317: sponzor (godisnja rata, bonus za plasman, isplata kad je save siguran)
        _club_switch(slot, s)
        _spon_tick(slot, s)
        _spon_auto(slot, s)
        _kitsp_guard(slot, s)
    except Exception as ex:
        print('[sponsor]', ex)
    return dict(
        layout=dict(ok=bool(s.known_format), note=s.layout_note, dx=s.dx,
                   pes17=bool(getattr(s, 'pes17', False)), beta=bool(getattr(s, 'beta_ok', False)), game27=bool(getattr(s, 'game27', False)), fmt60=bool(getattr(s, 'fmt60', False)), mb=round(len(s.d) / 1e6)),
        slot=slot, info=r['info'], manager=s.manager(), clubs=r['clubs'], career=_career_id(slot, s), save_dir=CFG.get('save_dir', ''),
        table=tbl, squad=squad, xi=xi, bench=bench,
        formations=dict(kickoff=rows_json(s, 0), inp=rows_json(s, 1), out=rows_json(s, 2)),
        presets={k: [dict(pos=p, x=x, y=y) for p, x, y in v] for k, v in mlwrite.PRESETS.items()},
        posnames=mlwrite.RPOS, game_running=game_running(), menu_ok=menu_ok(), mauto=(_MEMST.get('state') if game_running() else None), dev=bool(DEV),
        tactics=s.my_tactics(), adv_att={str(k): v for k, v in s.ADV_ATT.items()}, adv_def={str(k): v for k, v in s.ADV_DEF.items()},
        adv_own=list(s.ADV_NEEDS_OWN), adv_opp=list(s.ADV_NEEDS_OPP),
        loan_cancelled=_loan_cancelled(slot, s), loan_queue=loan_queue_view(slot, s), overwritten=_overwritten(slot, s), loan_stale=_loan_stale(s), auto_default=_auto_default(slot, s),
        comp_names=_comp_names_all(slot, s), comp_user=_comp_user(), nation=_nation_team_info(s), conf=_my_conf(slot, s))


_CONF_KW = (('CONMEBOL', ('argentin', 'brasil', 'brazil', 'chile', 'colomb', 'urugu', 'paragu', 'peru', 'ecuad', 'bolivi', 'venezuel', 'libertadores')),
            ('CONCACAF', ('mls', 'liga mx', 'mexic', 'usl', 'canad', 'costa ric')),
            ('AFC', ('j1', 'j.league', 'j league', 'saudi', 'k league', 'k1', 'chinese super', 'a-league', 'qatar', 'uae', 'emirat', 'persian', 'indian super', 'thai')))


def _goal_txt(slot, s, goal):
    """pc397: 'Qualify for Europe' samo za europske lige; Argentina -> Copa Libertadores itd."""
    if goal == 'europe':
        c = _my_conf(slot, s)
        q = {'CONMEBOL': 'Qualify for the Copa Libertadores', 'AFC': 'Qualify for the AFC Champions League',
             'CONCACAF': 'Qualify for the CONCACAF Champions Cup'}.get(c)
        if q:
            return q
    return boardlib.GOAL_TXT.get(goal, '')


def _my_conf(slot, s):
    """pc397: konfederacija lige mog kluba (UEFA, CONMEBOL, CONCACAF, AFC) za nazive zona tablice i cilj sezone.
    Iz imena lige (uprava u appu ili tablica natjecanja); nepoznato -> UEFA kao prije."""
    try:
        ck = (slot, os.path.getmtime(BOARD_FILE) if os.path.exists(BOARD_FILE) else 0, os.path.getmtime(slot_folder(slot)) if os.path.exists(slot_folder(slot)) else 0)
    except Exception:
        ck = None
    if ck and _GL.get('conf_k') == ck:
        return _GL.get('conf_v') or 'UEFA'
    v = _my_conf_calc(slot, s)
    _GL['conf_k'], _GL['conf_v'] = ck, v
    return v


def _my_conf_calc(slot, s):
    try:
        lg = ''
        try:
            B = (json.load(open(BOARD_FILE, encoding='utf-8')) or {}).get(_career_id(slot, s)) or {}
            lg = ((B.get('cur') or {}).get('league')) or ''
        except Exception:
            lg = ''
        if not lg:
            try:
                for c in comps_view(slot).get('comps') or []:
                    if c.get('kind') == 'league' and any(r_.get('idx') == (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE for r_ in c.get('rows') or []):
                        lg = c.get('name') or ''
                        break
            except Exception:
                lg = ''
        if lg in LEAGUE_LAND:
            return LEAGUE_LAND[lg][2]
        low = lg.lower()
        for conf, kws in _CONF_KW:
            if any(k in low for k in kws):
                return conf
    except Exception:
        pass
    return 'UEFA'


def _nation_team_info(s):
    """pc306: reprezentacija koju vodim i moze li app urediti njen sastav (blok iza mog). -> dict ili None"""
    try:
        ref = _my_nation(s)
        if ref is None:
            return None
        nm = seasonstats.club_name(s.d, ref)
        try:
            mlwrite.Save(s.folder, ro=True).use_nation(ref)
            return dict(ref=ref, name=nm, ok=True)
        except Exception as ex:
            return dict(ref=ref, name=nm, ok=False, note=str(ex))
    except Exception:
        return None


def team_squad(slot, team='nation'):
    """pc306: sastav, postava, formacije i upute reprezentacije (isti oblik kao u state()) za stranicu Squad."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    name = s.club_name()
    if team == 'nation':
        ref = _my_nation(s)
        if ref is None:
            raise ValueError('You do not manage a national team in this career.')
        s.use_nation(ref)
        name = seasonstats.club_name(s.d, ref)
    ids = s.squad_ids()
    nums = s.squad_numbers()
    try:
        _dn = dump_names()
    except Exception:
        _dn = {}
    squad = [dict(idx=i, id=pid, name=live_name(pid, _dn), pos=POS.get(pid, 5), no=nums.get(i, 0)) for i, pid in enumerate(ids) if pid]
    try:   # pc316: ozljeda, kondicija, zuti kartoni iz savea
        _stt = s.read_status([x['id'] for x in squad])
        for x in squad:
            v = _stt.get(x['id'])
            if v:
                x['inj'], x['cond'] = v['inj'], v['cond']
                if v['yc']:
                    x['yc'] = max(v['yc'].values())
                    x['ycc'] = {str(k): n for k, n in v['yc'].items()}
    except Exception as ex:
        print('[status]', ex)
    lu = s.lineup()
    idx2id = {i: p for i, p in enumerate(ids) if p}
    return dict(team=team, name=name, squad=squad, xi=[idx2id.get(i) for i in lu[:11]],
                bench=[idx2id.get(i) for i in lu[11:23] if i != 0xff and idx2id.get(i)],
                formations=dict(kickoff=rows_json(s, 0), inp=rows_json(s, 1), out=rows_json(s, 2)), tactics=s.my_tactics())


def _comp_user():
    """pc411: imena natjecanja koja je korisnik upisao kod uvoza baze (comps.json): imaju prednost pred zadanim imenima po broju."""
    try:
        return {str(k): v.get('name') for k, v in json.load(open(_dbf('comps.json'), encoding='utf-8')).items() if v.get('name')}
    except Exception:
        return {}


def _comp_names_all(slot, s):
    """pc303: imena svih natjecanja iz rasporeda (baza igre, CompetitionRegulation) za ona koja app ne zna napamet (prije 'Competition #14')."""
    out = {}
    try:
        M = _season(slot, s)
        for t_ in {m['tid'] for m in M['matches']}:
            if t_ in COMP_LEAGUES or t_ in COMP_GROUPS:
                continue
            nm_ = _reg_comp_name(t_)
            if nm_:
                out[t_] = nm_
    except Exception:
        pass
    return out


def _auto_default(slot, s):
    """Nova karijera (prvo ljeto, prije 1.9. prve sezone) koju app jos nije vidio: AI transferi i AI taktike se ukljuce sami.
    Postojece karijere se ne diraju (iskljuceno/ukljuceno ostaje kako je korisnik postavio)."""
    try:
        code = s.game_date_code()
        y, mo = code & 0xffff, (code >> 16) & 0xff
        if y != 2025 or mo not in (7, 8):   # pc413: datum prije citanja velike datoteke
            return False
        e0 = auto_view().get(slot)
        _new = lambda x: x.get('fresh') or str(x.get('status', '')).startswith('new career')
        if e0 and (e0.get('user_set') or (e0.get('enabled') and (e0.get('tac') or {}).get('on')) or not _new(e0)):
            return False
        with AUTO_LOCK:
            st = auto_load()
            e = st.get(slot)
            # pc147: i nova karijera u STAROM slotu (career_guard je resetirao plan): sve AI ukljuceno dok korisnik sam ne promijeni
            if e and (e.get('user_set') or (e.get('enabled') and (e.get('tac') or {}).get('on'))):
                return False
            if e and not _new(e):
                return False
            e = st.setdefault(slot, {})
            e.pop('fresh', None)
            e['enabled'] = True
            e.setdefault('tac', {})['on'] = True
            e.pop('last_mtime', None)
            for k in ('coach', 'lu'):
                if isinstance(e.get(k), dict):
                    e[k].pop('off', None)
            auto_save(st)
        return True
    except Exception:
        return False


def _loan_stale(s):
    try:
        return [dict(pid=p, name=NAMES.get(p, str(p))) for p in s.stale_pending()]
    except Exception:
        return []


def loan_fixdate(body):
    """Zadnji dan roka: dogovorenim dolaznim posudbama s datumom dolaska sutra postavi danasnji datum (inace ih igra ponisti)."""
    slot = body['slot']

    def fn(sv):
        p = sv.stale_pending(fix=True)
        if not p:
            raise ValueError('no loans to fix')
        return 'Datum dolaska ispravljen na danas: %s.' % ', '.join(NAMES.get(x, str(x)) for x in p)
    return _write_slot(slot, 'fixdate', fn)


REFUND_FILE = os.path.join(HERE, 'data', 'loan_refunds.json')


def _refunds():
    try:
        return json.load(open(REFUND_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _loan_cancelled(slot, s):
    """Posudbe koje je igra ponistila, a naknada jos nije vracena: [{pid, name, fee}]."""
    try:
        done = {(int(x['pid']), int(x['fee'])) for x in _refunds().get(slot, [])}
        return [dict(pid=p, name=NAMES.get(p, str(p)), fee=f) for p, f in s.cancelled_loans() if (p, f) not in done]
    except Exception:
        return []


def loan_refund(body):
    """Vrati naknade ponistenih posudbi u transfer budzet (svaku samo jednom; popis u data/loan_refunds.json)."""
    slot = body['slot']
    s = mlwrite.Save(slot_folder(slot))
    todo = _loan_cancelled(slot, s)
    if not todo:
        return dict(ok=True, message='No cancelled loans to refund.', refunded=[])
    tot = sum(x['fee'] for x in todo)

    def fn(sv):
        sv.adjust_budget(tot)
        return 'Vraceno %d EUR.' % tot
    r = _write_slot(slot, 'refund', fn)
    for x in todo:   # pc152: otkazana posudba ne broji se kao prelazak u ovom roku (moze se ponoviti)
        try:
            _neg_store().drop(slot, -10 ** 9 - int(x['pid']))
        except Exception:
            pass
    try:   # i automatska provjera posudbi je vise ne vraca
        la = _lp_all()
        for x in todo:
            (la.get(slot) or {}).pop(str(x['pid']), None)
        _lp_save(la)
    except Exception:
        pass
    a = _refunds()
    a.setdefault(slot, []).extend(dict(pid=x['pid'], fee=x['fee'], when=time.strftime('%Y-%m-%d %H:%M')) for x in todo)
    os.makedirs(os.path.dirname(REFUND_FILE), exist_ok=True)
    _jdump(a, REFUND_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, message='Refunded {:,} EUR to the transfer budget: {}.'.format(tot, ', '.join(x['name'] for x in todo)), refunded=todo, detail=r)


PCACHE = {}


def rat(pid):
    r = RAT.get(pid)
    if not r:
        return (0, 0)
    o = r[0]
    if o and o > 99:
        o = 99   # pc380: baze s pojacanim atributima (FL Mod Studio) daju izracun 100+; igra ne ide iznad 99
    return (o, r[1])


def db_speed(pid):
    """pc199: brzina iz baze (ratings.json) - stalna, da sudbina igraca ne ovisi o tome koliko je vec usporio."""
    try:
        r = RAT.get(pid)
        return r[-1][RATAB.index('Speed')] if r and isinstance(r[-1], list) else None
    except Exception:
        return None


def _dump_player(pid):
    """pc283: igrac kojeg nema u uvezenoj bazi (junior/regen kojeg je igra tek napravila): podaci iz zivog F7 dumpa."""
    p = CFG.get('dump') or ''
    if not os.path.exists(p):
        return None
    mt = os.path.getmtime(p)
    c = _GL.get('dumpp')
    if not c or c[0] != mt:
        try:
            c = (mt, dbimport.players_from_dump(open(p, 'rb').read()))
        except Exception:
            c = (mt, {})
        _GL['dumpp'] = c
    return c[1].get(pid)


def player_detail(pid):
    apply_regens()
    r = RAT.get(pid)
    if not r:
        q = _dump_player(pid)
        if q:
            return dict(id=pid, name=q['name'], pos=q['pos'], ovr=q['ovr'], age=q['age'], height=q['h'], weight=q['w'], foot='L' if q['foot'] else 'D',
                        style=q['style'], wfu=q['wfu'], wfa=q['wfa'], form=q['form'], inj=q['inj'], stats=dict(zip(RATAB, q['attrs'])), source='dump')
        return dict(id=pid, name=NAMES.get(pid, ''), unknown=True)
    return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=r[0], age=r[1], height=r[2], weight=r[3],
                foot='L' if r[4] == 'True' else 'D', style=r[5], wfu=r[6], wfa=r[7], form=r[8], inj=r[9],
                stats=dict(zip(RATAB, r[10])))


SKB = {291: 'Scissors Feint', 292: 'Flip Flap', 293: 'Marseille Turn', 294: 'Sombrero', 295: 'Cut Behind & Turn', 296: 'Scotch Move',
       297: 'Heading', 298: 'Long Range Drive', 300: 'Acrobatic Finishing', 301: 'Heel Trick', 302: 'First-time Shot', 303: 'One-touch Pass',
       304: 'Weighted Pass', 305: 'Pinpoint Crossing', 306: 'Outside Curler', 308: 'Low Lofted Pass', 309: 'GK Low Punt', 310: 'Long Throw',
       311: 'GK Long Throw', 312: 'Gamesmanship', 313: 'Man Marking', 314: 'Track Back', 315: 'Acrobatic Clear', 316: 'Captaincy',
       318: 'Fighting Spirit', 320: 'Penalty Specialist', 322: 'Chip Shot Control', 323: 'Step On Ball Control', 324: 'Dipping Shot',
       325: 'Rising Shots', 327: 'Interception', 328: 'Double Touch', 329: 'Cross Over Turn', 330: 'Long Range Shooting', 331: 'Through Passing'}
COMB = {223: 'Trickster', 255: 'Mazing Run', 286: 'Speeding Bullet', 287: 'Incisive Run', 288: 'Long Ball Expert', 289: 'Early Cross', 290: 'Long Ranger'}
_TR = {'mt': None, 'd': {}}


def traits_all():
    """{pid: (skills, com)} iz zivog dumpa; cache po mtime."""
    import struct
    p = CFG.get('dump') or ''
    if not os.path.exists(p):
        return {}
    mt = os.path.getmtime(p)
    if _TR['mt'] == mt:
        return _TR['d']
    d = open(p, 'rb').read()
    S = 380
    out = {}
    for i in range(len(d) // S):
        b = d[i * S:(i + 1) * S]
        pid = struct.unpack_from('<I', b, 0x30)[0]
        v = int.from_bytes(b, 'little')
        sk = [n for k, n in SKB.items() if (v >> k) & 1]
        cm = [n for k, n in COMB.items() if (v >> k) & 1]
        if sk or cm:
            out[pid] = (sk, cm)
    _TR['mt'], _TR['d'] = mt, out
    return out


_CUR_SLOT = dict(slot=None)


def _dump_before_career(slot, dmt):
    """pc147: dump je napravljen prije nego sto je app prvi put vidio ovu karijeru u slotu = dump je iz prosle karijere."""
    if DEV or not slot:
        return False
    try:
        rec = (json.load(open(CAREER_FILE, encoding='utf-8')) or {}).get(slot) or {}
        t0 = time.mktime(time.strptime(rec.get('seen', ''), '%Y-%m-%d %H:%M'))
        return dmt < t0 - 120
    except Exception:
        return False


def _dump_stale(dmt):
    """Dump je iz druge sesije/karijere: puno stariji od save-a otvorene karijere ili (dok igra ne radi) puno noviji.
    Tada su zastavice (lista, posudba), moral, plaće i ugovori iz dumpa krivi za ovu karijeru pa ga ne koristimo."""
    slot = _CUR_SLOT.get('slot')
    if DEV or not slot:
        return False
    try:
        smt = os.path.getmtime(os.path.join(CFG['save_dir'], slot))
    except Exception:
        return False
    if dmt < smt - 3 * 3600 or _dump_before_career(slot, dmt):
        return True
    if dmt > smt + 3 * 3600 and not game_running():
        return True
    return False


_growth_read_live0 = growth.read_live


def _read_live_fresh(path, pids, *a, **k):
    """growth.read_live, ali zastarjeli dump (druga karijera/sesija) se ne koristi: moral/forma/ozljede iz njega su krivi."""
    try:
        if path and os.path.exists(path) and _dump_stale(os.path.getmtime(path)):
            return {}
    except Exception:
        pass
    r = _growth_read_live0(path, pids, *a, **k)
    # pc329: "osnovna" tablica igraca (F7 izvan izbornika kluba / na pocetku karijere): moral i ozljede su svima 0. Tada se moral
    # ne zna (prije: svi "Unhappy" na Liverpoolu 1.8. u klasicnom saveu).
    try:
        if r and len(r) >= 5 and not any(v.get('aff') for v in r.values()):
            for v in r.values():
                v['aff'] = None
                v['inj'] = None
    except Exception:
        pass
    return r


growth.read_live = _read_live_fresh


def read_dump():
    """Zivi podaci iz memorije igre (Sider PlayerDump): {id: dict}. Blokovi od 380 B."""
    import struct
    p = CFG.get('dump') or ''
    if not os.path.exists(p):
        return None, 0
    mt = os.path.getmtime(p)
    if _dump_stale(mt):
        return None, 0
    return _parse_dump(p, mt), mt


def read_dump_any():
    """pc165: dump i kad je star (druga karijera): samo za trzisnu vrijednost, koja se bitno ne mijenja (bolje od procjene iz OVR-a)."""
    p = CFG.get('dump') or ''
    if not os.path.exists(p):
        return {}
    return _parse_dump(p, os.path.getmtime(p)) or {}


def _parse_dump(p, mt):
    import struct
    # pc147: parsiranje dumpa (~0.3 s) kesirano po datoteci i vremenu izmjene; prije se radilo pri svakom pozivu (skauting 53x = 10 s)
    if _RDC.get('k') == (p, mt, len(NAMES)):
        return _RDC['v']
    d = open(p, 'rb').read()
    S = 380
    out = {}
    for i in range(len(d) // S):
        b = d[i * S:(i + 1) * S]
        pid = struct.unpack_from('<I', b, 0x30)[0]
        if pid not in NAMES:
            continue
        _v = int.from_bytes(b[30:40], 'little')
        out[pid] = dict(pp=''.join(str((_v >> (l - 240)) & 3) for l in _PP_BITS), tl=bool(b[0x14A] & 2), loan=bool(b[0x14A] & 4), age=b[0x1C] & 63,
                        mv=struct.unpack_from('<I', b, 0x174)[0] * 100,
                        sal=struct.unpack_from('<I', b, 0x15C)[0] * 100,
                        cy=struct.unpack_from('<H', b, 0x138)[0], cm=b[0x13A], cd=b[0x13B],
                        aff=growth.aff_of(b), form=(b[0x17] >> 4) & 7, ovr=dbimport.game_ovr(b) if 40 <= b[0x179] <= 99 else None,
                        nat=struct.unpack_from('<H', b, 0x144)[0] & 0x1ff, inj=b[0x148])
    # pc210: PlayerDump je mogao uzeti "osnovnu" tablicu igraca (moral, OVR, ozljede i placa svugdje 0; postoji kad igra nije
    # u izborniku kluba). Tada moral i ozljede nisu poznati (prije: svi "Unhappy" i bez ozljeda).
    if out and sum(1 for r_ in out.values() if r_['aff']) < 0.01 * len(out):
        for r_ in out.values():
            r_['aff'] = None
            r_['inj'] = None
    _RDC.update(k=(p, mt, len(NAMES)), v=out)
    try:
        # pc194: baza fer vrijednosti iz same igre (medijan po OVR-u, 24-27 god.) -> negotiate.value_band
        import statistics as _st
        _by = {}
        for _r in out.values():
            if _r.get('ovr') and _r.get('mv') and 24 <= _r['age'] <= 27:
                _by.setdefault(_r['ovr'], []).append(_r['mv'])
        negotiate.set_value_base({o: _st.median(v) for o, v in _by.items() if len(v) >= 5})
    except Exception as _ex:
        print('[value base]', _ex)
    return out


_RDC = {}


def table_ghosts(slot):
    """pc202: lazne utakmice u tablici lige koje su stare verzije appa dodavale mom klubu pri posudbama."""
    try:
        g = mlwrite.Save(slot_folder(slot), ro=True).table_ghosts()
    except Exception as ex:
        return dict(ok=False, n=0, message=str(ex)[:200])
    if not g:
        return dict(ok=True, n=0)
    return dict(ok=True, **g)


def table_fix(body):
    slot = (body or {}).get('slot') or ''
    g = table_ghosts(slot)
    if not g.get('n'):
        return dict(ok=False, message='Nothing to fix: your league record matches the matches played.')
    r = _write_slot(slot, 'tablefix', lambda sv: sv.fix_table_ghosts())
    r = dict(r) if isinstance(r, dict) else dict(ok=True)
    r['message'] = ('Fixed: removed %d fake league match(es) (%d:%d goals) that an old app version added to your club when loans were made. '
                    'The game keeps showing the old table until the next match is played; after that it shows the corrected one.' % (g['n'], g['dgf'], g['dga']))
    return r


def squad_tail_check(slot):
    """pc206b: igraci koje je stara verzija appa potpisala bez reda ugovora u repu (igra na njima padne u Team Management)."""
    try:
        sv = mlwrite.Save(slot_folder(slot), ro=True)
        miss = sv.join_tail_missing()
        # pc381: upozorenje samo za igrace koje je doveo app (bug starih verzija appa). Michele (45 MB, UML baza): 7 igraca FC Andorre
        # bez ikakvog upisa appa javljalo se kao 'missing contract rows', a igra je sastav otvarala bez problema (drugaciji zapis baze).
        if miss:
            try:
                mine_ = {-k - 10 ** 9 for k in _neg_store().for_slot(slot) if isinstance(k, int) and k <= -10 ** 9}
            except Exception:
                mine_ = set()
            miss = [q for q in miss if q in mine_]
    except Exception as ex:
        return dict(ok=False, n=0, message=str(ex)[:200])
    names = []
    try:
        P = {p['id']: p for p in players_data(slot)['players']}
        names = [P.get(q, {}).get('name') or str(q) for q in miss]
    except Exception:
        names = [str(q) for q in miss]
    return dict(ok=True, n=len(miss), pids=miss, names=names)


def squad_tail_fix(body):
    slot = (body or {}).get('slot') or ''
    g = squad_tail_check(slot)
    if not g.get('n'):
        return dict(ok=False, message='Nothing to fix: every player of yours has his contract rows in the save.')
    r = _write_slot(slot, 'tailfix', lambda sv: sv.fix_join_tail())
    r = dict(r) if isinstance(r, dict) else dict(ok=True)
    if r.get('ok', True):
        r['message'] = ('Fixed: added the missing contract rows for %s. Load the save in the game; he can now be opened in Team Management.'
                        % ', '.join(g['names']))
    return r


def news_world(slot):
    """pc200: podaci za rubrike novina 'Around the world': ozljede poznatih igraca, ugovori koji istjecu na kraju sezone,
    mladi talenti. Sve iz savea / dumpa / Injuries For All; nista se ne izmislja."""
    pd = players_data(slot)
    P = {p['id']: p for p in pd['players']}
    out = dict(injuries=[], expiring=[], talents=[], inj_source=None)
    try:
        W, src = world_injuries()
        out['inj_source'] = src
        inj = [dict(pid=q, name=P[q]['name'], club=P[q]['club'], ovr=P[q]['ovr'], age=P[q]['age'], pos=P[q]['pos'], days=d, mine=P[q].get('mine'))
               for q, d in W.items() if q in P and P[q].get('club') and (P[q]['ovr'] or 0) >= 74 and d >= 14]
        inj.sort(key=lambda x: (-(x['ovr'] or 0), -x['days']))
        out['injuries'] = inj[:12]
        out['injured_total'] = len(W)
    except Exception as ex:
        print('[news world] inj', ex)
    try:
        s = mlwrite.Save(slot_folder(slot), ro=True)
        gd = s.game_date_code()
        y, mo = gd & 0xffff, (gd >> 16) & 0xff
        now = y * 12 + mo
        C = s.all_contracts()
        # ugovori u igri istjecu 31.1. ili 31.8.: 'istjece' = u sljedecih 8 mjeseci (bez onih koji su vec istekli)
        ex_ = [dict(pid=q, name=P[q]['name'], club=P[q]['club'], ovr=P[q]['ovr'], age=P[q]['age'], pos=P[q]['pos'], y=c['y'], m=c['m'],
                    until='%s.%02d.%d' % ('31' if c['m'] in (1, 3, 5, 7, 8, 10, 12) else '30', c['m'], c['y']), mine=P[q].get('mine'))
               for q, c in C.items() if q in P and P[q].get('club') and (P[q]['ovr'] or 0) >= 76 and 0 <= c['y'] * 12 + c['m'] - now <= 8]
        ex_.sort(key=lambda x: -(x['ovr'] or 0))
        out['expiring'] = ex_[:12]
    except Exception as ex:
        print('[news world] contracts', ex)
    tal = [dict(pid=p['id'], name=p['name'], club=p['club'], ovr=p['ovr'], age=p['age'], pos=p['pos'], mine=p.get('mine'))
           for p in pd['players'] if p.get('club') and p.get('age') and p['age'] <= 20 and (p['ovr'] or 0) >= 72]
    tal.sort(key=lambda x: (-(x['ovr'] or 0), x['age']))
    out['talents'] = tal[:10]
    return out


def world_injuries():
    """pc198: ozljede svih igraca u svijetu -> ({pid: dani}, izvor). Izvor 'module' = bridge\\injuries.csv koji pise
    Injuries For All (Michele & Claude, gaffer1) dok igra radi; inace 'dump' (bajt 0x148 F7 dumpa); None = nema podataka."""
    p = os.path.join(os.path.dirname(CFG.get('dump') or ''), 'injuries.csv')
    try:
        mt = os.path.getmtime(p)
        if not _dump_stale(mt):
            out = {}
            for ln in open(p, encoding='utf-8', errors='ignore'):
                a = ln.strip().split(',')
                if len(a) == 2 and a[0].isdigit() and a[1].isdigit() and int(a[1]) > 0:
                    out[int(a[0])] = int(a[1])
            return out, 'module'
    except OSError:
        pass
    live, _ = read_dump()
    if live:
        return {q: v['inj'] for q, v in live.items() if v.get('inj')}, 'dump'
    return {}, None


# ---------------------------------------------------------------- Youth (regeni i omladina)
YOUTH_HIST = os.path.join(HERE, 'data', 'youth_hist.json')
_YG = dict(att=('Finishing', 'OffensiveAwareness', 'Curl', 'Dribbling'), tech=('BallControl', 'LowPass', 'LoftedPass', 'TightPossession'),
           phys=('Speed', 'Acceleration', 'Stamina', 'PhysicalContact', 'Jump', 'Balance'), dfn=('DefensiveAwareness', 'BallWinning', 'Aggression', 'Heading'))
_YW = {'CB': dict(dfn=.55, phys=.3, tech=.15), 'LB': dict(dfn=.35, phys=.4, tech=.25), 'RB': dict(dfn=.35, phys=.4, tech=.25),
       'DMF': dict(dfn=.4, tech=.3, phys=.3), 'CMF': dict(tech=.5, phys=.25, dfn=.1, att=.15), 'LMF': dict(tech=.4, phys=.4, att=.2),
       'RMF': dict(tech=.4, phys=.4, att=.2), 'AMF': dict(tech=.45, att=.35, phys=.2), 'LWF': dict(att=.35, phys=.4, tech=.25),
       'RWF': dict(att=.35, phys=.4, tech=.25), 'SS': dict(att=.5, tech=.3, phys=.2), 'CF': dict(att=.55, phys=.25, tech=.2)}
_YPOS = 'GK CB LB RB DMF CMF LMF RMF AMF LWF RWF SS CF'.split()


def _youth_ovr(a, pos):
    """Procjena OVR-a iz atributa (kalibrirano na 17 igraca iz igre, greska oko 2). Nije igrin broj."""
    if pos == 'GK':
        raw = sum(a[k] for k in ('GKAwareness', 'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach')) / 5.0
    else:
        g = {k: sum(a[x] for x in v) / float(len(v)) for k, v in _YG.items()}
        raw = sum(w * g[k] for k, w in _YW[pos].items())
    return int(round(1.318 * raw - 25.3))


def _youth_block(b):
    v = int.from_bytes(b[30:40], 'little')
    lv = [(v >> (l - 240)) & 3 for l in _PP_BITS]
    return lv


_YDC = {}


BROKEN_FILE = os.path.join(HERE, 'data', 'broken_players.json')


def broken_players(slot):
    """pc208: juniori/igraci na kojima se igra rusi (Attigah, Man City 29.10.: pad u Team Planu i kad ga potpise igra). {pid: ime}."""
    try:
        A = json.load(open(BROKEN_FILE, encoding='utf-8'))
    except Exception:
        A = {}
    return {int(k): v for k, v in (A.get(slot) or {}).items()}


def broken_set(body):
    slot, pid = body.get('slot') or '', int(body.get('pid') or 0)
    try:
        A = json.load(open(BROKEN_FILE, encoding='utf-8'))
    except Exception:
        A = {}
    e = A.setdefault(slot, {})
    if body.get('on', True):
        e[str(pid)] = body.get('name') or NAMES.get(pid, str(pid))
    else:
        e.pop(str(pid), None)
    os.makedirs(os.path.dirname(BROKEN_FILE), exist_ok=True)
    _jdump(A, BROKEN_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, broken=sorted(int(k) for k in e))


def youth_data(slot):
    v = _youth_data_c(slot)
    if isinstance(v, dict) and v.get('rows'):
        bk = broken_players(slot)
        if bk:
            v = dict(v)
            v['rows'] = [dict(r, broken=True) if r.get('id') in bk else r for r in v['rows']]
    return v


def _youth_data_c(slot):
    """pc147: kes po (save, dump, karijera) - trazenje zapisa juniora u saveu traje 1-3 s."""
    try:
        d = slot_folder(slot)
        dp = CFG.get('dump') or ''
        k = (slot, os.path.getmtime(os.path.join(d, 'data.dat')), os.path.getmtime(dp) if dp and os.path.exists(dp) else 0, game_running() if not DEV else 0,
             _career_id(slot))
    except Exception:
        return _youth_data0(slot)
    if _YDC.get('k') == k:
        return _YDC['v']
    v = _youth_data0(slot)
    _YDC.update(k=k, v=v)
    return v


def _youth_data0(slot):
    """Omladina tvog kluba: zapisi od 368 B iza sastava u save-u + zivi dump (ime/dob/atributi). Regen = dob<=17 a baza kaze da je bio stariji."""
    d = slot_folder(slot)
    data = open(os.path.join(d, 'data.dat'), 'rb').read()
    desc = mlsave.read_description(d)
    dp = CFG.get('dump') or ''
    if not os.path.exists(dp):
        return dict(ok=False, why='nodump')
    # imena/dob juniora postoje samo u dumpu: dump iz druge karijere ili davno prije zadnjeg spremanja bi pokazao krive igrace
    if not DEV:
        try:
            dmt = os.path.getmtime(dp)
            smt = os.path.getmtime(os.path.join(CFG['save_dir'], slot))
            if dmt < smt - 12 * 3600 or (dmt > smt + 3 * 3600 and not game_running()) or _dump_before_career(slot, dmt):
                return dict(ok=False, why='stale', dump_date=time.strftime('%d.%m.%Y %H:%M', time.localtime(dmt)))
        except Exception:
            pass
    raw = open(dp, 'rb').read()
    S = 380
    B = {}
    for i in range(len(raw) // S):
        b = raw[i * S:(i + 1) * S]
        B[struct.unpack_from('<I', b, 0x30)[0]] = b
    squad = []
    _names = mlsave.team_names(data, max(693, mlsave.club_layout(data)[0]))
    _club = desc.get('club')
    if _club in _names:
        _o = mlsave.REC0 + _names.index(_club) * mlsave.STRIDE + mlsave.SQUAD_OFF
        for _i in range(mlsave.SQUAD_SLOTS):
            _pid = struct.unpack_from('<I', data, _o + _i * 8)[0]
            if 0 < _pid < 400000:
                squad.append(_pid)
    if len(squad) < 2:
        return dict(ok=False, why='nosquad')
    sset = set(squad)
    p0 = struct.pack('<I', squad[0])
    p1 = struct.pack('<I', squad[1]) if len(squad) > 1 else None
    lo = -1
    o = data.find(p0)
    while o != -1:
        if o + 368 + 4 <= len(data) and (p1 is None or data[o + 368:o + 372] == p1):
            lo = o
            break
        o = data.find(p0, o + 1)
    if lo < 0:
        # nakon transfera/posudbi redoslijed u tablici vise ne prati sastav (nova karijera, Wolfsburg 26.10.):
        # tablicu nadji po tome sto na koraku od 368 B stoji vecina igraca iz sastava
        best = (0, -1)
        for q in squad[:6]:
            o = data.find(struct.pack('<I', q))
            while o != -1:
                sc = sum(1 for k in range(-40, 60) if 0 <= o + k * 368 and o + k * 368 + 4 <= len(data)
                         and struct.unpack_from('<I', data, o + k * 368)[0] in sset)
                if sc > best[0]:
                    best = (sc, o)
                o = data.find(struct.pack('<I', q), o + 1)
        if best[0] >= max(8, len(squad) // 2):
            o = best[1]
            k0 = 0
            while k0 > -40 and o + (k0 - 1) * 368 >= 0:
                v = struct.unpack_from('<I', data, o + (k0 - 1) * 368)[0]
                if not (1000 <= v < 400000):
                    break
                k0 -= 1
            lo = o + k0 * 368
    if lo < 0:
        return dict(ok=False, why='notable')
    rows = []
    # junior = zapis igraca bez ugovora (+64..+76 = ffff0000 x3); igraci s ugovorom (prva momcad, posudbe) nisu omladina bez obzira na dob
    _pro = set()
    try:
        _cand = []
        _k = 0
        while lo + (_k + 1) * 368 <= len(data) and _k < 160:
            _q = struct.unpack_from('<I', data, lo + _k * 368)[0]
            _k += 1
            if 1000 <= _q < 400000 and _q not in sset:
                _cand.append(_q)
        _big, _, _, _recs = mlwrite.Save(d)._player_recs(_cand)
        for _q, _r in _recs.items():
            if bytes(_big[_r + 64:_r + 76]) != b'\xff\xff\x00\x00' * 3:
                _pro.add(_q)
    except Exception:
        _pro = set()
    k = 0
    gap = 0
    miss = 0
    while lo + (k + 1) * 368 <= len(data) and gap < 3:
        pid = struct.unpack_from('<I', data, lo + k * 368)[0]
        k += 1
        if pid == 0:
            gap += 1
            continue
        if pid not in B:
            if pid > 400000 or pid < 1000:
                break
            if pid not in sset and pid not in _pro:
                miss += 1     # pc329: junior kojeg dump ne poznaje (novi regen nakon zadnjeg F7 ili dump iz drugog savea)
            continue
        gap = 0
        if pid in sset:
            continue
        b = B[pid]
        age = b[0x1C] & 63
        if pid in _pro:
            continue                      # ima profesionalni ugovor: nije junior (npr. A. Lunin, posudba iz baze koja nije u sastavu)
        nm = b[0x38:0x38 + 46].split(b'\0')[0].decode('utf-8', 'replace')
        r = _RAT0.get(pid) or RAT.get(pid)
        regen = bool(r and age <= 17 and r[1] >= age + 3)
        att = growth.attrs_from_block(b)
        lv = _youth_block(b)
        gl = [_YPOS[i] for i, x in enumerate(lv) if x == 2] or [_YPOS[i] for i, x in enumerate(lv) if x == 1] or ['CMF']
        _pr = ['GK', 'CMF', 'DMF', 'CB', 'RB', 'LB', 'AMF', 'CF', 'SS', 'LWF', 'RWF', 'LMF', 'RMF']
        _mp = sorted(gl, key=lambda q: _pr.index(q))[0]
        best = (_mp, _youth_ovr(att, _mp))
        pot = growth.potential(pid, age, best[1], POS.get(pid))
        rows.append(dict(id=pid, name=nm, age=age, pos=best[0], pos2=[p for p in gl if p != best[0]], ovr=best[1], pot=pot, regen=regen,
                         attrs=dict(att=round(sum(att[x] for x in _YG['att']) / 4), tech=round(sum(att[x] for x in _YG['tech']) / 4),
                                    phys=round(sum(att[x] for x in _YG['phys']) / 6), dfn=round(sum(att[x] for x in _YG['dfn']) / 4))))
    # pc329: omladina se cita iz dumpa igre; kad dump ne odgovara ovom saveu (drugi save, ili novi juniori nakon zadnjeg F7),
    # popis bi bio kriv ili nepotpun -> ne prikazuje se, nego se trazi F7
    try:
        if miss or _dump_stale(os.path.getmtime(dp)):
            return dict(ok=False, why='stale', missing=miss, dump_date=time.strftime('%d.%m. %H:%M', time.localtime(os.path.getmtime(dp))))
    except Exception:
        pass
    # povijest razvoja po datumu save-a
    date = desc.get('date', '')
    try:
        hist = json.load(open(YOUTH_HIST, encoding='utf-8'))
    except Exception:
        hist = {}
    h = hist.setdefault(slot, {})
    for r_ in rows:
        e = h.setdefault(str(r_['id']), [])
        if not e or e[-1][0] != date:
            e.append([date, r_['ovr'], r_['age']])
            del e[:-12]
        r_['hist'] = e[:-1][-6:]
        r_['d_ovr'] = (r_['ovr'] - e[-2][1]) if len(e) > 1 else None
    try:
        os.makedirs(os.path.dirname(YOUTH_HIST), exist_ok=True)
        _jdump(hist, YOUTH_HIST)
    except Exception:
        pass
    rows.sort(key=lambda x: (-int(x['regen']), -x['pot'], -x['ovr']))
    return dict(ok=True, date=date, club=desc.get('club'), rows=rows, n=len(rows), regens=sum(1 for x in rows if x['regen']),
                dump_mtime=os.path.getmtime(dp), save_mtime=os.path.getmtime(os.path.join(d, 'data.dat')))


def pes17_players(slot):
    """Player search for PES 2017: from EDIT00000000 + the ML club table."""
    d = slot_folder(slot)
    if pes17.is_pes17(d):
        r = pes17.read_save(d, date_order=CFG.get('pes17_date_order', 'dmy'))
        with open(os.path.join(d, 'data.dat'), 'rb') as f:
            data = f.read()
        club_of = {}
        for t in pes17.team_records(data):
            for p in pes17.squad(data, t):
                club_of.setdefault(p['id'], t['name'])
        mine = r['info']['club']
        mkey = pes17._norm(mine)
        rows = []
        for pid, name in NAMES.items():
            o, a = rat(pid)
            club = club_of.get(pid, '')
            rows.append(dict(id=pid, name=name, pos=POS.get(pid, 5), club=club,
                             mine=(pes17._norm(club) == mkey and bool(mkey)), no=0,
                             ovr=o, age=a, mv=0, sal=0, mv_e=0, pp=PLAYPOS.get(pid, ''),
                             until='', tl=False, loan=False, tl_save=False, loan_save=False,
                             tl_live=False, loan_live=False, has_live=False))
        rows.sort(key=lambda x: (-x['ovr'], x['name']))
        return dict(players=rows, transfer_list=[], loan_list=[], source='EDIT00000000',
                    clubs=sorted({x['club'] for x in rows if x['club']}),
                    mine=mine, loaned_in=[])
    return None


def players_data(slot):
    if pes17.is_pes17(slot_folder(slot)):
        return pes17_players(slot)
    d = slot_folder(slot)   # pc289: prvo slot (prepozna igru FL26/FL27), pa zivi OVR
    apply_regens()
    live, dmt = read_dump()
    key = (d, dmt, _AR.get('mt'))   # pc289: i stanje zivog OVR-a (FL27)
    if key in PCACHE:
        return PCACHE[key]
    data = open(os.path.join(d, 'data.dat'), 'rb').read()
    pl = mlsave.all_players(data)
    mine = mlsave.read_description(d)['club']
    fm = mlwrite.Save.flag_map(data)
    sv_tl = {pid for pid, (a, b) in fm.items() if a}
    sv_lo = {pid for pid, (a, b) in fm.items() if b}

    try:
        _sv = mlwrite.Save(d)
        _ct = _sv.read_contracts(list(_sv.my_squad_tags()))
    except Exception:
        _ct = {}

    def mk(pid, club):
        lv = (live or {}).get(pid) or {}
        c = _ct.get(pid)
        if c and c['y']:
            lv = dict(lv, sal=c['sal'] or lv.get('sal', 0), cy=c['y'], cm=c['m'])
        o, a = rat(pid)
        return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), club=club, mine=(club == mine), no=NOS.get(pid, 0),
                    ovr=o, age=lv.get('age') or a, mv=lv.get('mv', 0), sal=lv.get('sal', 0),
                    mv_e=(0 if lv.get('mv') else (negotiate.estimate_value(o or 50, lv.get('age') or a or 25) if o else 0)),
                    pp=lv.get('pp') or PLAYPOS.get(pid, ''),
                    until='%s/%s' % (lv['cm'], lv['cy']) if lv.get('cy') else '', tl=bool(lv.get('tl', False) or pid in sv_tl), loan=bool(lv.get('loan', False) or pid in sv_lo),
                    tl_save=(pid in sv_tl), loan_save=(pid in sv_lo), tl_live=bool(lv.get('tl', False)), loan_live=bool(lv.get('loan', False)), has_live=bool(lv))
    NOS = {}
    try:
        _ix = 0
        while mlwrite.REC0 + (_ix + 1) * mlwrite.STRIDE <= len(data):
            _o = mlwrite.REC0 + _ix * mlwrite.STRIDE
            _n = data[_o + 1058]
            if 0 < _n <= 40:
                for _i in range(_n):
                    _pid = struct.unpack_from('<I', data, _o + 328 + 8 * _i + 4)[0]
                    _no = struct.unpack_from('<H', data, _o + 662 + 2 * _i)[0]
                    if _pid in NAMES and 0 < _no < 100 and _pid not in NOS:
                        NOS[_pid] = _no
            _ix += 1
    except Exception:
        NOS = {}
    rows = [mk(pid, c[1]) for pid, c in pl.items()]
    rows.sort(key=lambda r: (-r['ovr'], r['name']))
    if live:
        tl = [mk(pid, pl[pid][1] if pid in pl else 'no club') for pid, v in live.items() if v['tl'] or pid in sv_tl]
        loans = [mk(pid, pl[pid][1] if pid in pl else 'no club') for pid, v in live.items() if v['loan'] or pid in sv_lo]
        src = 'igra'
    else:
        tl = []
        for t in mlsave.transfer_list(data):
            r = mk(t['id'], t['club']); r['date'] = t['date']; tl.append(r)
        loans = []
        src = 'save'
    for L in (tl, loans):
        L.sort(key=lambda r: (-r['ovr'], r['name']))
    try:
        _lin = sorted(mlwrite.Save(d).loaned_in_pids())
    except Exception:
        _lin = []
    res = dict(players=rows, transfer_list=tl, loan_list=loans, source=src, clubs=sorted({r['club'] for r in rows}), mine=mine, loaned_in=_lin)
    PCACHE.clear()
    PCACHE[key] = res
    return res


def _gdate(m):
    import datetime
    try:
        return datetime.date(m['y'], m['m'], m['dd']).toordinal()
    except Exception:   # pc260: smeceni datum u zapisu rasporeda ne smije srusiti pogled
        return 0


def _gfmt(o):
    import datetime
    return datetime.date.fromordinal(o).strftime('%d.%m.%Y') if o and o > 0 else ''


def _gnow(slot):
    """Datum u igri (ordinal) = zadnja odigrana utakmica; inace fiksni pocetak sezone."""
    import datetime
    try:
        s = mlwrite.Save(slot_folder(slot), ro=True)
        M = _season(slot, s)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        ms = [m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])]
        if ms:
            return max(_gdate(m) for m in ms)
    except Exception:
        pass
    return datetime.date(2025, 7, 1).toordinal()


def growth_state(slot, commit=False, force=False):
    """Pregled (ili, uz commit, obracun) mjesecnog rasta. Obracun je deterministican po razdoblju, pa je pregled = ono sto ce se poslati."""
    import datetime
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    pdn = players_data(slot)
    mine = [r for r in pdn['players'] if r['mine']]
    live = growth.read_live(CFG.get('dump'), [r['id'] for r in mine])
    _award_grants_safe(slot)
    gs = growth.load_state(HERE)
    sl = gs.setdefault(slot, {})
    pst = sl.setdefault('players', {})
    awb = sl.setdefault('award_bonus', {})
    cfg = growth.load_focus(HERE)
    latest = _gdate(ms[-1]) if ms else None
    last = sl.get('last_ord') or (latest - 30 if latest else None)
    can, why_not = True, ''
    if latest is None:
        can, why_not = False, 'nema_utakmica'
    elif latest <= (sl.get('last_ord') or 0):
        can, why_not = False, 'nema_novih'
    win = [m for m in ms if latest and _gdate(m) > last] if latest else []
    months = max(0.02, min(2.0, ((latest - last) / 30.0))) if latest else 1.0
    period = 'g%d' % (latest or 0)
    # ucinak u razdoblju
    appr = {}
    pstat = {}
    for m in win:
        conc = seasonstats.match_score_for(m, my)[1]
        for pid, ci, g, a, r in m['rows']:
            if ci == my:
                x = appr.setdefault(pid, [0, 0.0]); x[0] += 1; x[1] += r
                y = pstat.setdefault(pid, dict(app=0, g=0, a=0, cs=0, rs=0.0))
                y['app'] += 1; y['g'] += g; y['a'] += a; y['rs'] += r
                if conc == 0: y['cs'] += 1
    # osoblje
    staff = sl.setdefault('staff', dict(hired=[], assign={}))
    now = latest or _gnow(slot)
    ctr = staff.setdefault('contracts', {})
    for i_ in staff.get('hired', []):
        ctr.setdefault(i_, now + 730)
    pool = {c['id']: c for c in growth.coach_pool()}
    hired_all = [pool[i] for i in staff.get('hired', []) if i in pool]
    try:
        _sv0, _gd0, _season0 = _coach_season(slot)
        _tb0 = _sv0.budget()
    except Exception:
        _season0, _tb0 = None, None
    _paid = staff.setdefault('paid', {})
    if _season0 is not None:
        for i_ in staff.get('hired', []):
            _paid.setdefault(i_, _season0)   # stari zapisi: tekuca sezona se smatra placenom
    _unpaid = lambda cid_: _season0 is not None and _paid.get(cid_, _season0) < _season0
    hired = [c for c in hired_all if ctr.get(c['id'], 0) >= now and not _unpaid(c['id'])]
    active_ids = {c['id'] for c in hired}
    wbill = sum(r.get('sal', 0) or 0 for r in mine)
    sbud0 = growth.default_staff_budget(wbill)
    sbud = staff.get('budget') or sbud0
    assigned_n = {}
    for pid_, cid_ in staff.get('assign', {}).items():
        if cid_ in active_ids:
            assigned_n[cid_] = assigned_n.get(cid_, 0) + 1
    # mentori: stariji (29+) suigrac iste linije i barem +2 jaci
    def has_mentor(r):
        g = growth.pos_group(r['pos'])
        return any(o['id'] != r['id'] and o['age'] >= 29 and growth.pos_group(o['pos']) == g and o['ovr'] >= r['ovr'] + 2 for o in mine)
    rows, adds, total = [], [], 0
    _fac = _inv_factors(slot)   # pc316: ulaganja kluba
    for r in sorted(mine, key=lambda x: (-x['ovr'], x['name'])):
        pid = r['id']
        ps = pst.get(str(pid)) or {}
        base = ps.get('base_ovr', r['ovr'])
        pot = ps.get('pot') or growth.potential(pid, r['age'], base, r.get('pos'))
        net = ps.get('net', 0)
        eff = base + int(round(net / growth.PTS_PER_OVR))
        if live.get(pid) and r.get('ovr'):
            eff = r['ovr']   # pc289: s dumpom je OVR zivi broj iz igre (ukljucuje i rast u igri i vec upisane bodove iz appa)
        st = growth.settings_for(pid, r['pos'], cfg)
        lv = live.get(pid)
        if lv is not None:
            lv = dict(lv); lv['_prog'] = ps.get('prog') or {}
        ap = appr.get(pid)
        perf = dict(share=(ap[0] / len(win)) if (ap and win) else (0.0 if win else 0.5), rating=(ap[1] / ap[0]) if ap else 6.5)
        cid = staff['assign'].get(str(pid))
        coach = pool.get(cid) if cid in active_ids else None
        load = 1.0
        if coach:
            load = min(1.0, growth.GRADE[coach['grade']][4] / float(max(1, assigned_n.get(cid, 1))))
        ps_ = pstat.get(pid)
        bon, bwhy = growth.performance_bonus(r['pos'], dict(ps_, rating=ps_['rs'] / ps_['app']) if ps_ else None, len(win))
        pl = growth.month_plan(dict(id=pid, pos=r['pos'], age=r['age'], ovr=eff, dbspeed=db_speed(pid)), st, lv, perf, has_mentor(r), months, period, pot,
                               coach=coach, load=load, bonus=bon, bonus_why=bwhy, bump=ps.get('bump', 0), award=float(awb.get(str(pid), 0) or 0), fac=_fac) if lv else None
        ch = (pl or {}).get('add', [])
        total += len(ch)
        for a_, d_ in ch:
            adds.append((pid, a_, d_))
        if pl and pl['dform']:
            adds.append((pid, 'Form', pl['dform']))
        rows.append(dict(id=pid, name=r['name'], pos=r['pos'], age=r['age'], ovr=eff, pot=pot, f1=st['f1'], f2=st['f2'], int=st['int'], auto=st['auto'],
                         live=bool(lv), plan=[dict(f=a_, d=d_, v=(lv['attrs'].get(a_) if lv else None)) for a_, d_ in ch], points=(pl or {}).get('points', 0),
                         factors=(pl or {}).get('factors', []), destiny=(growth.destiny(pid, r['pos'], db_speed(pid)) if (r['age'] or 0) >= growth.DESTINY_SHOW_AGE else None), apps=(ap[0] if ap else 0), rating=(round(ap[1] / ap[0], 1) if ap else None),
                         attrs=((lv or {}).get('attrs') if lv else None), progall={k_: round(v_, 2) for k_, v_ in (((pl or {}).get('prog')) or {}).items()}, aff=(lv or {}).get('aff'),
                         form=(lv or {}).get('form'), inj=(lv or {}).get('inj', 0), dform=(pl or {}).get('dform', 0),
                         coach=(cid if coach else None), load=round(load, 2), stats=(dict(app=ps_['app'], g=ps_['g'], a=ps_['a'], cs=ps_['cs']) if ps_ else None),
                         prog=sorted(((a_, round(v_, 2)) for a_, v_ in ((pl or {}).get('prog') or {}).items()), key=lambda kv: -abs(kv[1]))[:3],
                         award=round(float(awb.get(str(pid), 0) or 0), 2)))
        if commit and pl:
            ps2 = dict(base_ovr=base, pot=pl.get('pot', pot), bump=ps.get('bump', 0) + pl.get('pot_up', 0), prog=pl['prog'], net=net + sum(d_ for _, d_ in ch))
            # povijest OVR-a za graf razvoja u profilu: [datum obracuna, OVR nakon, potencijal]
            oh = list(ps.get('oh') or [])
            oh.append([_gfmt(latest) if latest else '', base + int(round(ps2['net'] / growth.PTS_PER_OVR)), ps2['pot']])
            ps2['oh'] = oh[-60:]
            pst[str(pid)] = ps2
            awb.pop(str(pid), None)
    queued = 0
    if commit:
        if not can and not force:
            return dict(ok=False, msg=why_not)
        queued = growth.queue(CFG, adds, period) if adds else 0
        sl['last_ord'] = latest
        hist = sl.setdefault('history', [])
        hist.append(dict(date=_gfmt(latest), period=period, matches=len(win), months=round(months, 2),
                         players=[dict(id=x['id'], name=x['name'], plan=x['plan'], factors=x['factors'], apps=x['apps'], rating=x['rating'], dform=x['dform']) for x in rows if x['plan'] or x['dform']]))
        del hist[:-12]
        for c_ in hired_all:
            if c_['id'] not in active_ids:
                staff['assign'] = {k: v for k, v in staff['assign'].items() if v != c_['id']}
        growth.save_state(HERE, gs)
        return dict(ok=True, queued=queued, period=period, enabled=growth.enabled(CFG))
    res = growth.read_results(CFG)
    _rx = {x['tx']: x for x in res}
    hist_out = []
    for h_ in sl.get('history', [])[-6:]:
        h2 = dict(h_)
        h2['players'] = []
        for p_ in h_.get('players', []):
            p2 = dict(p_)
            p2['res'] = {x_['f']: [_rx[k_]['status'], _rx[k_]['old'], _rx[k_]['new']]
                         for x_ in p_.get('plan', []) for k_ in ['%s-%s-%s' % (h_.get('period'), p_['id'], x_['f'])] if k_ in _rx}
            h2['players'].append(p2)
        hist_out.append(h2)
    cnt = {}
    for x in res:
        k = x['status'].split(':')[0]
        cnt[k] = cnt.get(k, 0) + 1
    return dict(rows=rows, total=total, period=period, enabled=growth.enabled(CFG), dump=bool(live), can=can, why_not=why_not,
                auto=sl.get('auto') is not False, auto_last=sl.get('auto_last'),
                days=((latest - sl['last_ord']) if (latest and sl.get('last_ord')) else None), date=(_gfmt(latest) if latest else None), last=(_gfmt(sl['last_ord']) if sl.get('last_ord') else None), matches=len(win), months=round(months, 2),
                history=hist_out, counts=cnt, results=res[-40:], groups=growth.GROUP_NAMES,
                staff=dict(budget=sbud, default_budget=sbud0, used=growth.staff_wages(hired), wage_bill=wbill, tb=_tb0,
                           season=('%d/%02d' % (_season0, (_season0 + 1) % 100)) if _season0 else '',
                           due=sum(growth.coach_wage(c) for c in hired_all if ctr.get(c['id'], 0) >= now and _unpaid(c['id'])),
                           prorata=(lambda _m: max(0.25, ((6 - _m) % 12 + 1) / 12.0))(_date_tuple(_gd0)[1]) if _season0 else 1,
                           hired=[dict(c, n=assigned_n.get(c['id'], 0), wage=growth.coach_wage(c), end=_gfmt(ctr[c['id']]), days=ctr[c['id']] - now, expired=ctr[c['id']] < now,
                                       unpaid=_unpaid(c['id']), sev=(_coach_sev(c, ctr[c['id']], _season0) if _season0 and ctr[c['id']] >= now else 0)) for c in hired_all],
                           now=_gfmt(now),
                           market=[dict(c, wage=growth.coach_wage(c)) for c in pool.values() if c['id'] not in staff.get('hired', [])],
                           roles={k: [v[0], v[1]] for k, v in growth.ROLES.items()},
                           grades={g[0]: dict(hr=g[1], en=g[2], mult=g[3], cap=g[4], cost=g[5]) for g in growth.GRADES},
                           traits=[list(t) for t in growth.TRAITS]))


def growth_apply(body):
    return growth_state(body.get('slot', ''), commit=True, force=bool(body.get('force')))


def growth_focus(body):
    foc = growth.load_focus(HERE)
    k = str(int(body['pid']))
    c = foc.get(k)
    c = dict(f1=c) if isinstance(c, str) else dict(c or {})
    for key, ok in (('f1', growth.GROUPS), ('f2', growth.GROUPS), ('int', growth.INTENSITY)):
        if key in body:
            if body[key] in ok:
                c[key] = body[key]
            else:
                c.pop(key, None)
    foc[k] = c
    growth.save_focus(HERE, foc)
    return dict(ok=True)


GROWTH_EVERY = 30
_GAUTO = threading.Lock()


def growth_auto_tick(slot):
    """pc288: automatski trening. Pri svakom novom saveu app (u pozadini) pogleda je li proslo >= 30 dana u igri od zadnje obrade
    (ili jos nikad nije obradjena, a ima utakmica). Ako jest, obradi mjesec sam: bodovi idu u growth.csv, a GrowthBridge ih upise u igru
    cim je igra ukljucena (F7 jednom po pokretanju). Ritam ostaje mjesecni (jednako kao rucna obrada), pa se ravnoteza rasta ne mijenja.
    Uvjeti: auto ukljucen za slot (zadano: da), ukljucen upis u igru (growth.enabled) i svjez dump ove karijere."""
    if DEV or not _GAUTO.acquire(blocking=False):
        return None
    try:
        sl = growth.load_state(HERE).get(slot, {})
        if sl.get('auto') is False or not growth.enabled(CFG):
            return None
        d = growth_due(slot)
        if not d.get('due'):
            return None
        ds = dump_status(slot)
        if not (ds.get('exists') and ds.get('career_ok')):
            return None
        pv = growth_state(slot)
        if not pv.get('can') or not pv.get('dump'):
            return None
        r = growth_state(slot, commit=True)
        if r.get('ok'):
            gs = growth.load_state(HERE)
            gs.setdefault(slot, {})['auto_last'] = dict(date=pv.get('date'), queued=r.get('queued', 0), at=int(time.time()))
            growth.save_state(HERE, gs)
            print('[growth] auto: %s %s, %d naredbi' % (slot, pv.get('date'), r.get('queued', 0)))
        return r
    except Exception as ex:
        print('[growth] auto:', ex)
        return None
    finally:
        _GAUTO.release()


def growth_auto_set(body):
    slot = body.get('slot', '')
    gs = growth.load_state(HERE)
    gs.setdefault(slot, {})['auto'] = bool(body.get('on'))
    growth.save_state(HERE, gs)
    return dict(ok=True, auto=gs[slot]['auto'])


def growth_due(slot):
    """Lagani podsjetnik: je li u igri proslo >= 30 dana od zadnje obrade rasta."""
    sl = growth.load_state(HERE).get(slot, {})
    now = _gnow(slot)
    last = sl.get('last_ord')
    played = now > __import__('datetime').date(2025, 7, 1).toordinal()
    days = (now - last) if last else None
    return dict(due=bool(played and (last is None or days >= GROWTH_EVERY)), days=days, date=_gfmt(now), every=GROWTH_EVERY)


def growth_player(slot, pid):
    """Karton igraca za Trening: nastupi po datumima (golovi, asistencije, ocjena, rezultat), zbroj po sezoni, razvoj atributa i povijest obrada."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    allm = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    gs = growth.load_state(HERE)
    sl = gs.get(slot, {})
    last_ord = sl.get('last_ord') or 0
    rows = []
    tot = {}
    for m in allm:
        mine = [r for r in m['rows'] if r[1] == my]
        theirs = [r for r in m['rows'] if r[1] != my]
        gf, ga = seasonstats.match_score_for(m, my)
        home = m['home'] == my
        opp = m['away'] if home else m['home']
        me = [r for r in mine if r[0] == pid]
        e = dict(date=_gfmt(_gdate(m)), season=m['season'], tid=m['tid'], home=home, opp=seasonstats.club_name(s.d, opp), gf=gf, ga=ga,
                 res='W' if gf > ga else 'L' if gf < ga else 'D', played=bool(me), new=_gdate(m) > last_ord)
        if me:
            r = me[0]
            e.update(g=r[2], a=r[3], rating=round(r[4], 1), cs=(ga == 0))
            t = tot.setdefault(m['season'], dict(app=0, g=0, a=0, rs=0.0, cs=0, team=0))
            t['app'] += 1; t['g'] += r[2]; t['a'] += r[3]; t['rs'] += r[4]; t['cs'] += 1 if ga == 0 else 0
        tot.setdefault(m['season'], dict(app=0, g=0, a=0, rs=0.0, cs=0, team=0))['team'] += 1
        rows.append(e)
    res = {x['tx']: x for x in growth.read_results(CFG)}
    hist = []
    for h_ in sl.get('history', []):
        for p_ in h_.get('players', []):
            if p_.get('id') == pid:
                hist.append(dict(date=h_.get('date'), matches=h_.get('matches'), factors=p_.get('factors', []), apps=p_.get('apps', 0), rating=p_.get('rating'),
                                 plan=[dict(f=x_['f'], d=x_['d'], st=(res.get('%s-%s-%s' % (h_.get('period'), pid, x_['f'])) or {}).get('status', ''),
                                            old=(res.get('%s-%s-%s' % (h_.get('period'), pid, x_['f'])) or {}).get('old', ''),
                                            new=(res.get('%s-%s-%s' % (h_.get('period'), pid, x_['f'])) or {}).get('new', '')) for x_ in p_.get('plan', [])]))
    ps = (sl.get('players') or {}).get(str(pid)) or {}
    seasons = [dict(season=k, avg=(round(v['rs'] / v['app'], 2) if v['app'] else None), **{kk: vv for kk, vv in v.items() if kk != 'rs'}) for k, v in sorted(tot.items())]
    return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), matches=rows[::-1][:60], seasons=seasons, history=hist[::-1][:12],
                prog=sorted(((a_, round(v_, 2)) for a_, v_ in (ps.get('prog') or {}).items()), key=lambda kv: -abs(kv[1])), base_ovr=ps.get('base_ovr'), pot=ps.get('pot'), last=(_gfmt(last_ord) if last_ord else None))


def _ev_month(w):
    """events.json 'when' (dd/mm/yyyy ili dd.mm.yyyy) -> (y, m) ili None"""
    try:
        a = re.split(r'[/.]', str(w))
        return (int(a[2]), int(a[1]))
    except Exception:
        return None


def journal_view(slot):
    """Dnevnik sezone: mjesecna poglavlja iz odigranih utakmica mog kluba + dogadjaja + razvoja (strukturirani podaci; tekst slaze front)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    chap = {}
    for m in ms:
        home = m['home'] == my
        mine = [r for r in m['rows'] if r[1] == my]
        theirs = [r for r in m['rows'] if r[1] != my]
        gf, ga = seasonstats.match_score_for(m, my)
        opp = seasonstats.club_name(s.d, m['away'] if home else m['home'])
        key = (m['y'], m['m'])
        c = chap.setdefault(key, dict(y=m['y'], m=m['m'], season=m['season'], games=[], pl={}))
        res = 'W' if gf > ga else 'L' if gf < ga else 'D'
        g = dict(date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']), opp=opp, home=home, gf=gf, ga=ga, res=res)
        c['games'].append(g)
        for r in mine:
            pl = c['pl'].setdefault(r[0], dict(pid=r[0], name=NAMES.get(r[0], str(r[0])), g=0, a=0, app=0, rs=0.0, ht=[]))
            pl['g'] += r[2]; pl['a'] += r[3]; pl['app'] += 1; pl['rs'] += r[4]
            if r[2] >= 3:
                pl['ht'].append(dict(opp=opp, date=g['date'], g=r[2]))
    try:
        evs = json.load(open(EV_FILE, encoding='utf-8')).get(slot, [])
    except Exception:
        evs = []
    gs = growth.load_state(HERE).get(slot, {})
    out = []
    for key in sorted(chap):
        c = chap[key]
        G = c['games']
        w = sum(1 for g in G if g['res'] == 'W'); d_ = sum(1 for g in G if g['res'] == 'D'); l_ = len(G) - w - d_
        best = max(G, key=lambda g: (g['gf'] - g['ga'], g['gf']))
        worst = min(G, key=lambda g: (g['gf'] - g['ga'], -g['ga']))
        # najduzi niz
        run, bs = None, dict(t='', n=0)
        for g in G:
            if run and run[0] == g['res']:
                run[1] += 1
            else:
                run = [g['res'], 1]
            if run[1] > bs['n']:
                bs = dict(t=run[0], n=run[1])
        pls = list(c['pl'].values())
        for p_ in pls:
            p_['avg'] = round(p_['rs'] / p_['app'], 2) if p_['app'] else 0
            p_.pop('rs', None)
        top = sorted([p_ for p_ in pls if p_['g'] or p_['a']], key=lambda p_: (-p_['g'], -p_['a']))[:3]
        mvp = max([p_ for p_ in pls if p_['app'] >= max(2, len(G) // 2)], key=lambda p_: p_['avg'], default=None)
        hts = [dict(pid=p_['pid'], name=p_['name'], **h) for p_ in pls for h in p_['ht']]
        cev = [e for e in evs if _ev_month(e.get('when')) == (c['y'], c['m']) and e.get('kind') in ('sold', 'bought', 'signed', 'renewed', 'loan_out', 'loan_in', 'listed')]
        seen, ev2 = set(), []
        for e in cev:
            k = (e.get('kind'), e.get('pid'))
            if k in seen:
                continue
            seen.add(k)
            ev2.append(dict(kind=e.get('kind'), pid=e.get('pid'), name=e.get('name'), ovr=e.get('ovr'), to=e.get('to'), fee=e.get('fee'), until=e.get('until'), years=e.get('years'), wage=e.get('wage')))
        ups = []
        for h_ in gs.get('history', []):
            ds = str(h_.get('date') or '')
            try:
                dd_, mm_, yy_ = [int(x) for x in ds.split('.')]
            except Exception:
                continue
            if (yy_, mm_) != (c['y'], c['m']):
                continue
            for p_ in h_.get('players', []):
                pl_ = [x_ for x_ in p_.get('plan', []) if (x_.get('d') or 0) > 0]
                if pl_:
                    ups.append(dict(pid=p_.get('id'), name=p_.get('name'), f=[x_['f'] for x_ in pl_]))
        out.append(dict(y=c['y'], m=c['m'], season=c['season'], n=len(G), w=w, d=d_, l=l_,
                        gf=sum(g['gf'] for g in G), ga=sum(g['ga'] for g in G), form=''.join(g['res'] for g in G),
                        best=best, worst=worst, streak=bs, top=top, mvp=mvp, hattricks=hts, events=ev2, growth=ups[:6]))
    return dict(club=seasonstats.club_name(s.d, my), date=_fmt_date(s.game_date_code()), chapters=out)


MS_APPS = (50, 100, 150, 200, 250, 300, 400)
MS_GOALS = (10, 25, 50, 75, 100, 150, 200)
MS_AST = (25, 50, 100)


def records_view(slot):
    """Knjiga rekorda kluba (samo ovaj save) i prekretnice igraca: nastupi, golovi, asistencije za moj klub, hat-trickovi,
    prvi gol za klub; rekordi: najvise nastupa/golova/asistencija, najvise golova u sezoni, najbolja sezona po ocjeni,
    najveca pobjeda i poraz, najduzi niz pobjeda i neporazenosti."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    tot, seas, miles = {}, {}, []
    res = []
    for m in ms:
        date = '%02d.%02d.%d' % (m['dd'], m['m'], m['y'])
        opp_i = m['away'] if m['home'] == my else m['home']
        opp = seasonstats.club_name(s.d, opp_i)
        gf = seasonstats.match_score_for(m, my)[0]
        ga = seasonstats.match_score_for(m, my)[1]
        res.append(dict(date=date, opp=opp, gf=gf, ga=ga, home=(m['home'] == my), season=m['season']))
        for r in m['rows']:
            if r[1] != my:
                continue
            pid = r[0]
            t = tot.setdefault(pid, dict(pid=pid, app=0, g=0, a=0, rs=0.0))
            a0, g0, as0 = t['app'], t['g'], t['a']
            t['app'] += 1; t['g'] += r[2]; t['a'] += r[3]; t['rs'] += r[4]
            st = seas.setdefault((m['season'], pid), dict(pid=pid, season=m['season'], app=0, g=0, a=0, rs=0.0))
            st['app'] += 1; st['g'] += r[2]; st['a'] += r[3]; st['rs'] += r[4]
            base = dict(pid=pid, name=NAMES.get(pid, str(pid)), date=date, opp=opp)
            if a0 == 0:
                pass
            for th in MS_APPS:
                if a0 < th <= t['app']:
                    miles.append(dict(base, kind='apps', n=th))
            if g0 == 0 and t['g'] > 0:
                miles.append(dict(base, kind='first_goal', n=1))
            for th in MS_GOALS:
                if g0 < th <= t['g']:
                    miles.append(dict(base, kind='goals', n=th))
            for th in MS_AST:
                if as0 < th <= t['a']:
                    miles.append(dict(base, kind='assists', n=th))
            if r[2] >= 3:
                miles.append(dict(base, kind='hattrick', n=r[2]))
    def nm(pid):
        return NAMES.get(pid, str(pid))
    P = list(tot.values())
    rec = []
    def top(key, lab):
        L = sorted(P, key=lambda x: -x[key])
        if L and L[0][key]:
            rec.append(dict(k=key, label=lab, pid=L[0]['pid'], name=nm(L[0]['pid']), v=L[0][key],
                            top=[dict(pid=x['pid'], name=nm(x['pid']), v=x[key]) for x in L[:5] if x[key]]))
    top('app', 'Most appearances')
    top('g', 'Most goals')
    top('a', 'Most assists')
    SL = list(seas.values())
    if SL:
        b = max(SL, key=lambda x: (x['g'], -x['app']))
        if b['g']:
            rec.append(dict(k='season_g', label='Most goals in a season', pid=b['pid'], name=nm(b['pid']), v=b['g'], season=b['season']))
        q = [x for x in SL if x['app'] >= 10]
        if q:
            b = max(q, key=lambda x: x['rs'] / x['app'])
            rec.append(dict(k='season_r', label='Best season rating (10+ apps)', pid=b['pid'], name=nm(b['pid']), v=round(b['rs'] / b['app'], 2), season=b['season']))
    if res:
        w = max(res, key=lambda x: (x['gf'] - x['ga'], x['gf']))
        if w['gf'] > w['ga']:
            rec.append(dict(k='win', label='Biggest win', v='%d-%d' % (w['gf'], w['ga']), opp=w['opp'], date=w['date'], home=w['home']))
        l_ = min(res, key=lambda x: (x['gf'] - x['ga'], -x['ga']))
        if l_['gf'] < l_['ga']:
            rec.append(dict(k='loss', label='Heaviest defeat', v='%d-%d' % (l_['gf'], l_['ga']), opp=l_['opp'], date=l_['date'], home=l_['home']))
        def streak(ok):
            best, cur, start, bs = 0, 0, None, None
            for x in res:
                if ok(x):
                    cur += 1
                    if cur == 1:
                        start = x['date']
                    if cur > best:
                        best, bs = cur, (start, x['date'])
                else:
                    cur = 0
            return best, bs
        n, se = streak(lambda x: x['gf'] > x['ga'])
        if n >= 2:
            rec.append(dict(k='wins', label='Longest winning run', v=n, date=se[0] + ' – ' + se[1]))
        n, se = streak(lambda x: x['gf'] >= x['ga'])
        if n >= 3:
            rec.append(dict(k='unbeaten', label='Longest unbeaten run', v=n, date=se[0] + ' – ' + se[1]))
        n, se = streak(lambda x: x['ga'] == 0)
        if n >= 2:
            rec.append(dict(k='clean', label='Most clean sheets in a row', v=n, date=se[0] + ' – ' + se[1]))
    squad = set(s.my_squad_tags())
    leaders = sorted(P, key=lambda x: (-x['app'], -x['g']))[:30]
    return dict(club=seasonstats.club_name(s.d, my), matches=len(res), records=rec, milestones=miles[-80:],
                leaders=[dict(pid=x['pid'], name=nm(x['pid']), app=x['app'], g=x['g'], a=x['a'], avg=round(x['rs'] / x['app'], 2) if x['app'] else None,
                              here=x['pid'] in squad) for x in leaders])


def career_view(slot, pid):
    """Vremeplov igraca: nastupi po sezoni/klubu iz svih odigranih utakmica u savu, forma po mjesecima, vrhunci, dogadjaji i razvoj."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    ms = sorted([m for m in M['matches'] if m['played']], key=seasonstats.sort_key)
    seas, mon = {}, {}
    best, first_goal, hts, tot = None, None, [], dict(app=0, g=0, a=0)
    for m in ms:
        for r in m['rows']:
            if r[0] != pid:
                continue
            club = r[1]
            opp_i = m['away'] if club == m['home'] else m['home']
            k = (m['season'], club)
            t = seas.setdefault(k, dict(season=m['season'], club=seasonstats.club_name(s.d, club), club_idx=club, app=0, g=0, a=0, rs=0.0))
            t['app'] += 1; t['g'] += r[2]; t['a'] += r[3]; t['rs'] += r[4]
            tot['app'] += 1; tot['g'] += r[2]; tot['a'] += r[3]
            mk = (m['y'], m['m'])
            mo = mon.setdefault(mk, dict(y=m['y'], m=m['m'], app=0, rs=0.0, g=0, a=0))
            mo['app'] += 1; mo['rs'] += r[4]; mo['g'] += r[2]; mo['a'] += r[3]
            e = dict(date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']), opp=seasonstats.club_name(s.d, opp_i), rating=round(r[4], 1), g=r[2], a=r[3])
            if best is None or e['rating'] > best['rating'] or (e['rating'] == best['rating'] and e['g'] > best['g']):
                best = e
            if r[2] and first_goal is None:
                first_goal = e
            if r[2] >= 3:
                hts.append(e)
    seasons = []
    for k in sorted(seas):
        t = seas[k]
        t['avg'] = round(t['rs'] / t['app'], 2) if t['app'] else None
        t.pop('rs')
        seasons.append(t)
    # pc241: sezone koje je igra obrisala (1.7.) iz arhive povijesti; za regena samo sezone u kojima je vec bio regen
    try:
        have = {t['season'] for t in seasons}
        H = _hist_load(_career_id(slot, s))
        for k_, v in H.get('seasons', {}).items():
            se_ = int(k_)
            x = (v.get('players') or {}).get(str(pid))
            if se_ in have or not x:
                continue
            if pid in _REGEN and pid not in set(v.get('regens') or []):
                continue
            seasons.append(dict(season=se_, club=seasonstats.club_name(s.d, x[4]), club_idx=x[4], app=x[0], g=x[1], a=x[2], avg=x[3], archived=True))
            tot['app'] += x[0]; tot['g'] += x[1]; tot['a'] += x[2]
        seasons.sort(key=lambda t: t['season'])
    except Exception as ex:
        print('[career] history:', ex)
    months = [dict(y=v['y'], m=v['m'], app=v['app'], avg=round(v['rs'] / v['app'], 2) if v['app'] else None, g=v['g'], a=v['a']) for k, v in sorted(mon.items())]
    try:
        evs = [e for e in json.load(open(EV_FILE, encoding='utf-8')).get(slot, []) if e.get('pid') == pid]
    except Exception:
        evs = []
    seen, ev2 = set(), []
    for e in evs:
        k = (e.get('kind'), e.get('when'), e.get('to'))
        if k in seen:
            continue
        seen.add(k)
        ev2.append({kk: e.get(kk) for kk in ('kind', 'when', 'to', 'fee', 'wage', 'until', 'years', 'old_wage') if e.get(kk) is not None})
    gs = growth.load_state(HERE).get(slot, {})
    ps = (gs.get('players') or {}).get(str(pid)) or {}
    ups = []
    for h_ in gs.get('history', []):
        for p_ in h_.get('players', []):
            if p_.get('id') == pid:
                for x_ in p_.get('plan', []):
                    if x_.get('d'):
                        ups.append(dict(date=h_.get('date'), f=x_['f'], d=x_['d']))
    r = RAT.get(pid)
    cur = M['cur'].get(pid)
    return dict(id=pid, name=NAMES.get(pid, str(pid)), ovr=(r[0] if r else None), age=(r[1] if r else None),
                club=(seasonstats.club_name(s.d, cur) if cur is not None else None), seasons=seasons, months=months, total=tot,
                best=best, first_goal=first_goal, hattricks=hts, events=ev2, base_ovr=ps.get('base_ovr'), pot=ps.get('pot'), ups=ups, ovr_hist=ps.get('oh') or [])



def _mres(m, my, s):
    home = m['home'] == my
    mine = [r for r in m['rows'] if r[1] == my]
    theirs = [r for r in m['rows'] if r[1] != my]
    gf, ga = seasonstats.match_score_for(m, my)
    opp = m['away'] if home else m['home']
    return dict(n=m['n'], date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']), season=m['season'], tid=m['tid'], home=home, gf=gf, ga=ga,
                res='W' if gf > ga else 'L' if gf < ga else 'D', opp=seasonstats.club_name(s.d, opp), opp_idx=opp, mine=mine, theirs=theirs)


def _table(ms, upto_n=None):
    """tablica iz odigranih utakmica jednog natjecanja (opcionalno bez utakmica sa n >= upto_n)"""
    T = {}
    for m in ms:
        if not m['played'] or (upto_n is not None and m['n'] >= upto_n):
            continue
        gh = seasonstats.match_score(m)[0]
        ga = seasonstats.match_score(m)[1]
        for c, f, g in ((m['home'], gh, ga), (m['away'], ga, gh)):
            t = T.setdefault(c, dict(c=c, pl=0, pts=0, gf=0, ga=0))
            t['pl'] += 1; t['gf'] += f; t['ga'] += g
            t['pts'] += 3 if f > g else 1 if f == g else 0
    return mlsave.game_ranks(list(T.values()), mlsave.results_of([m for m in ms if upto_n is None or m['n'] < upto_n]), 'c')


def debrief_view(slot):
    """Analiza zadnje odigrane utakmice mog kluba: rezultat, strijelci, ocjene, nizovi, promjena mjesta na tablici."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    if not ms:
        return dict(none=True)
    m = ms[-1]
    r = _mres(m, my, s)
    nm = lambda pid: NAMES.get(pid, str(pid))
    mine = sorted(r['mine'], key=lambda x: -x[4])
    pl = [dict(pid=x[0], name=nm(x[0]), pos=POS.get(x[0], 5), g=x[2], a=x[3], rating=round(x[4], 1)) for x in mine]
    opl = [dict(pid=x[0], name=nm(x[0]), g=x[2], a=x[3], rating=round(x[4], 1)) for x in sorted(r['theirs'], key=lambda x: -x[4])]
    # nizovi
    res_all = [_mres(x, my, s)['res'] for x in ms]
    def run(pred):
        n = 0
        for v in reversed(res_all):
            if pred(v):
                n += 1
            else:
                break
        return n
    streak = dict(w=run(lambda v: v == 'W'), u=run(lambda v: v != 'L'), l=run(lambda v: v == 'L'), nw=run(lambda v: v != 'W'))
    # tablica prije/poslije (ako je liga)
    tb = None
    if m['tid'] in COMP_LEAGUES:
        lm = [x for x in M['matches'] if x['tid'] == m['tid'] and x['season'] == m['season']]
        a = {t['c']: t for t in _table(lm, m['n'])}
        b = {t['c']: t for t in _table(lm)}
        if my in b:
            tb = dict(before=(a[my]['pos'] if my in a else None), after=b[my]['pos'], pts=b[my]['pts'], pl=b[my]['pl'], name=COMP_LEAGUES[m['tid']])
    # forma tima: zadnjih 5
    last5 = ''.join(res_all[-5:])
    seasong = [x for x in ms if x['season'] == m['season']]
    scored = sum(_mres(x, my, s)['gf'] for x in seasong)
    conc = sum(_mres(x, my, s)['ga'] for x in seasong)
    comp = COMP_LEAGUES.get(m['tid']) or (COMP_GROUPS.get(m['tid']) or ('', ''))[0] or ''
    try:
        ana = _match_analysis(slot, s, ms, my, pl)
    except Exception as ex:
        print('[debrief] analysis:', ex)
        ana = None
    return dict(id='%s-%s' % (m['n'], r['date']), my=seasonstats.club_name(s.d, my), my_idx=my, opp=r['opp'], opp_idx=r['opp_idx'], home=r['home'], gf=r['gf'], ga=r['ga'], res=r['res'],
                date=r['date'], comp=comp, players=pl, opp_players=opl[:3], streak=streak, table=tb, last5=last5, season_gf=scored, season_ga=conc, n_season=len(seasong),
                analysis=ana)


def _match_analysis(slot, s, ms, my, pl_last):
    """pc321: analiza pomocnika nakon utakmice: umor, ozljede, zuti, forma zadnje 3 utakmice, prijedlog izmjena za sljedecu postavu.
    Kondicija/ozljede/zuti iz savea (mlwrite.read_status), ocjene iz zapisa utakmica. Prijedlog se primjenjuje tek u Squad (Save to career)."""
    ids = s.squad_ids()
    squad = [p for p in ids if p]
    st = s.read_status(squad)
    lu = s.lineup()
    idx2id = {i: p for i, p in enumerate(ids) if p}
    xi = [idx2id.get(i) for i in lu[:11]]
    nm = lambda pid: NAMES.get(pid, str(pid))
    # forma: prosjecna ocjena u zadnje 3 utakmice u kojima je igrao
    recent = {}
    for m in ms[-6:]:
        r = _mres(m, my, s)
        for x in r['mine']:
            recent.setdefault(x[0], []).append(x[4])
    form = {p: sum(v[-3:]) / len(v[-3:]) for p, v in recent.items() if v}
    nx = None
    days = None
    try:
        n_ = next_match(slot).get('next') or {}
        if n_:
            nx = dict(opp=n_.get('opp'), date=n_.get('date'), home=n_.get('home'), opp_idx=n_.get('opp_idx'))
            from datetime import date as _dt
            dd_, mm_, yy_ = [int(x) for x in n_['date'].split('.')]
            gy, gm, gdd = _date_tuple(s.game_date_code())
            days = (_dt(yy_, mm_, dd_) - _dt(gy, gm, gdd)).days
            nx['days'] = days
    except Exception:
        pass
    # kondicija se oporavlja do sljedece utakmice: umor je bitan samo ako je ona za 3 dana ili manje (golmani se ne rotiraju)
    tired = [dict(pid=p, name=nm(p), cond=st[p]['cond']) for p in xi if p and p in st and 0 < st[p]['cond'] < 75
             and days is not None and days <= 3 and POS.get(p, 5) != 0]
    injured = [dict(pid=p, name=nm(p), days=st[p]['inj'], xi=p in xi) for p in squad if p in st and st[p]['inj'] > 0]
    yellow = [dict(pid=p, name=nm(p), n=max(st[p]['yc'].values())) for p in squad if p in st and st[p]['yc'] and max(st[p]['yc'].values()) >= 4]
    _xf = [form[p] for p in xi if p in form]
    _cut = min(6.0, (sum(_xf) / len(_xf) - 0.4) if _xf else 6.0)   # ispod prosjeka momcadi, ne samo ispod 6.0
    poor = [dict(pid=p, name=nm(p), avg=round(form[p], 1)) for p in xi if p in form and len(recent[p]) >= 2 and form[p] < _cut]
    hot = [dict(pid=p, name=nm(p), avg=round(form[p], 1)) for p in squad if p not in xi and p in form and form[p] >= 7.0]
    # prijedlog izmjena: umorni/ozlijedjeni/losa forma u postavi -> najbolji svjezi igrac iste skupine pozicija izvan postave
    used = set(p for p in xi if p)
    swaps = []
    why = {}
    for t in injured:
        if t['xi']:
            why[t['pid']] = 'injured (%d days)' % t['days']
    for t in tired:
        why.setdefault(t['pid'], 'tired (%d%% condition)' % t['cond'])
    for t in poor:
        why.setdefault(t['pid'], 'poor form (average %.1f)' % t['avg'])
    for out, reason in why.items():
        g = growth.pos_group(POS.get(out, 5))
        cands = []
        for p in squad:
            if p in used or p not in st or st[p]['inj'] > 0 or (0 < st[p]['cond'] < 80):
                continue
            if growth.pos_group(POS.get(p, 5)) != g:
                continue
            o = rat(p)[0] or 0
            cands.append((o + (form.get(p, 6.5) - 6.5) * 4, p))
        if not cands:
            continue
        sc, best = max(cands)
        if 'poor form' in reason and sc < (rat(out)[0] or 0):
            continue   # zamjena bi bila slabija od igraca u losoj formi: ostavi ga
        used.add(best)
        swaps.append(dict(out=out, out_name=nm(out), inn=best, in_name=nm(best), why=reason, ovr=rat(best)[0] or None))
    swaps = swaps[:3]
    return dict(tired=tired, injured=injured, yellow=yellow, poor=poor, hot=hot[:4], swaps=swaps, next=nx,
                best=(pl_last[0] if pl_last else None))


# ---------------------------------------------------------------- pc241: povijest sezona (memorija svijeta)
# Igra 1.7. obrise rezultate prosle sezone. App zato pri svakom ucitavanju savea sprema snimku tekuce sezone (tablice svih liga,
# strijelci, statistika svih igraca, moja momcad, uprava, nagrade) u data/history/<karijera>.json. Snimka se nikad ne smanjuje
# (save s manje odigranih utakmica je ne prepise). Kad app vidi novu sezonu, prosla se "zatvori": doda se sto se dogodilo na
# prijelazu (umirovljenja, odlasci/dolasci, promocije/ispadanja, novi cilj) i jednom se prikaze pregled kraja sezone.
HIST_DIR = os.path.join(HERE, 'data', 'history')
HIST_LOCK = threading.Lock()
_HIST_KEY = {}
_NAMES0 = {}


def _orig_name(pid):
    """Ime iz baze (prije regena): regen preuzme ID umirovljenog igraca, a NAMES tada ima novo ime."""
    if not _NAMES0:
        try:
            _NAMES0.update(mlwrite.load_names(_dbf('players.json')))
        except Exception:
            _NAMES0[0] = ''
    return _NAMES0.get(pid) or NAMES.get(pid, str(pid))


def _hist_file(cid):
    return os.path.join(HIST_DIR, re.sub(r'[^A-Za-z0-9_.-]', '_', str(cid)) + '.json')


def _hist_load(cid):
    try:
        H = json.load(open(_hist_file(cid), encoding='utf-8'))
    except Exception:
        H = {}
    H.setdefault('seasons', {})
    return H


def _hist_save(cid, H):
    os.makedirs(HIST_DIR, exist_ok=True)
    tmp = _hist_file(cid) + '.tmp'
    _jdump(H, tmp, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, _hist_file(cid))


def _slabel(se):
    return '%d/%02d' % (se, (se + 1) % 100)


def _hist_snapshot(slot, s, M, se, cv):
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    club = _my_club_name(s)
    leagues = []
    mine = None
    for c in cv.get('comps') or []:
        if c.get('kind') != 'league' or not c.get('rows'):
            continue
        rows = [[r['pos'], r['club'], r.get('idx'), r['pl'], r['w'], r['d'], r['l'], r['gf'], r['ga'], r['pts']] for r in c['rows']]
        n = len(rows)
        tot = 2 * (n - 1)
        top = lambda L, k: [[x['id'], x['name'], x['club'], x.get(k)] for x in (L or [])[:5]]
        e = dict(name=c['name'], tid=c.get('tid'), n=n, rows=rows, done=all(r[3] >= tot for r in rows), played=sum(r[3] for r in rows) // 2,
                 scorers=top(c.get('scorers'), 'g'), assists=top(c.get('assists'), 'a'), rated=[[x['id'], x['name'], x['club'], x.get('rating')] for x in (c.get('rated') or [])[:3]])
        leagues.append(e)
        if any(r[2] == my for r in rows):
            mine = e['name']
    pl = {}
    for pid, x in seasonstats.agg(M, se).items():
        if x['app']:
            pl[str(pid)] = [x['app'], x['g'], x['a'], round(x['rs'] / x['app'], 2), x['clubs'][-1]]
    sq = []
    for pid in s.my_squad_tags():
        o, a = rat(pid)
        sq.append([pid, NAMES.get(pid, str(pid)), a, o, POS.get(pid, 5)])
    me = next((l for l in leagues if l['name'] == mine), None)
    row = next((r for r in me['rows'] if r[2] == my), None) if me else None
    mm = [m for m in M['matches'] if m['played'] and m['season'] == se and my in (m['home'], m['away'])]
    res = []
    for m in sorted(mm, key=seasonstats.sort_key):
        gh = seasonstats.match_score(m)[0]
        ga = seasonstats.match_score(m)[1]
        home = m['home'] == my
        gf, gaa = (gh, ga) if home else (ga, gh)
        res.append([m['dd'], m['m'], m['y'], m['tid'], seasonstats.club_name(s.d, m['away'] if home else m['home']), int(home), gf, gaa])
    out = dict(season=se, label=_slabel(se), club=club, idx=my, manager=s.manager(), league=mine, row=row, leagues=leagues, players=pl,
               squad=sq, results=res, played=sum(l['played'] for l in leagues), date=_fmt_date(s.game_date_code()),
               complete=bool(me and me['done']), regens=sorted(_REGEN))
    try:
        A = json.load(open(BOARD_FILE, encoding='utf-8')).get(_career_id(slot, s)) or {}
        cur = A.get('cur') or {}
        out['board'] = dict(goal=cur.get('goal'), target=cur.get('target'), trust=round(cur.get('trust', 0)), rep=round(A.get('rep', 0)),
                            review=next((x for x in A.get('seasons', []) if x.get('season') == _slabel(se)), None))
    except Exception:
        pass
    if out['complete']:
        try:
            b = ballon_view(slot, se)
            pick = lambda L, k=1: [[x.get('id'), x.get('name'), x.get('club'), x.get('pts') or x.get('score')] for x in (L or [])[:k]]
            out['awards'] = dict(ballon=pick(b.get('ranking'), 3), golden_boy=pick(b.get('golden_boy')), yashin=pick(b.get('yashin')))
        except Exception as ex:
            print('[history] awards:', ex)
    return out


def _hist_aftermath(slot, s, v, cv):
    """Sto se dogodilo izmedju kraja sezone v i ovog savea (nova sezona)."""
    try:
        apply_regens()
    except Exception:
        pass
    M = _season(slot, s)
    cur = M.get('cur') or {}
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    now = set(s.my_squad_tags())
    prev = {r[0]: r for r in v.get('squad') or []}
    cn = lambda ci: seasonstats.club_name(s.d, ci) if ci is not None else ''
    left, arrived, retired = [], [], []
    for pid, r in prev.items():
        if pid in now:
            continue
        if pid in _REGEN:
            retired.append([pid, r[1], r[2], r[3], 1])
        else:
            left.append([pid, r[1], cn(cur.get(pid)) or 'free agent'])
    for pid in now:
        if pid not in prev:
            o, a = rat(pid)
            arrived.append([pid, NAMES.get(pid, str(pid)), a, o, int(pid in _REGEN)])
    # umirovljenja u svijetu: igraci koji su igrali prosle sezone, a sad je na njihovom ID-u regen
    world = []
    for k, x in (v.get('players') or {}).items():
        pid = int(k)
        if pid in _REGEN and pid not in prev and x[0] >= 8:
            o0 = (_RAT0.get(pid) or [0, 0])
            world.append([pid, _orig_name(pid), o0[1], o0[0], cn(x[4]), NAMES.get(pid, '')])
    world.sort(key=lambda r: -(r[3] or 0))
    # promocije/ispadanja: gdje su klubovi sada u odnosu na prosle tablice
    # pc260: usporedba po natjecanju (tid) i indeksu kluba, ne po imenu: preimenovana liga (npr. 'Competition 316' -> ime iz baze) nije promocija
    now_lg, now_ix = {}, {}
    for c in cv.get('comps') or []:
        if c.get('kind') == 'league':
            for r in c.get('rows') or []:
                now_lg.setdefault(r['club'], (c.get('tid'), c['name']))
                if r.get('idx') is not None:
                    now_ix.setdefault(r['idx'], (c.get('tid'), c['name']))
    def _diff(old_tid, old_name, nw):
        if not nw:
            return False
        if old_tid is not None and nw[0] is not None:
            return str(old_tid) != str(nw[0])
        return nw[1] != old_name
    moves = []
    for l in v.get('leagues') or []:
        n = l['n']
        for r in l['rows']:
            nw = now_ix.get(r[2]) if len(r) > 2 and r[2] is not None else None
            nw = nw or now_lg.get(r[1])
            if _diff(l.get('tid'), l['name'], nw):
                moves.append([r[1], l['name'], nw[1], 'up' if r[0] <= n / 2 else 'down', r[0]])
    my_c = next((c for c in cv.get('comps') or [] if c.get('kind') == 'league' and any(r.get('idx') == my for r in c.get('rows') or [])), None)
    my_new = my_c['name'] if my_c else None
    old_me = next((l for l in v.get('leagues') or [] if l['name'] == v.get('league')), None)
    mres = None
    if v.get('league') and my_c and _diff(old_me.get('tid') if old_me else None, v['league'], (my_c.get('tid'), my_c['name'])):
        r = v.get('row') or [99]
        mres = 'promoted' if r[0] <= 6 else 'relegated'
    return dict(left=left, arrived=arrived, retired=retired, world_retired=world[:15], moves=moves, my_league=my_new, my_move=mres,
                new_date=_fmt_date(s.game_date_code()))


def history_tick(slot, s=None):
    """Snimka tekuce sezone + zatvaranje prosle. Brzo izlazi ako se save nije promijenio."""
    if not slot:
        return None
    try:
        s = s or mlwrite.Save(slot_folder(slot), ro=True)
        cid = _career_id(slot, s)
    except Exception:
        return None
    key = (len(s.d), bytes(s.d[0:64]), s.game_date_code(), cid)
    if _HIST_KEY.get(slot) == key:
        return cid
    try:
        apply_regens()
    except Exception:
        pass
    with HIST_LOCK:
        H = _hist_load(cid)
        y, m, _ = _date_tuple(s.game_date_code())
        cur_season = y if m >= 7 else y - 1
        cv = comps_view(slot)
        M = _season(slot, s)
        se = cv.get('season')
        try:
            se = int(se)
        except Exception:
            se = cur_season
        has = any(mm['played'] and mm['season'] == se for mm in M['matches'])
        changed = False
        if has:
            snap = _hist_snapshot(slot, s, M, se, cv)
            old = H['seasons'].get(str(se))
            if not old or snap['played'] >= old.get('played', 0):
                for k_ in ('aftermath', 'closed', 'shown'):
                    if old and k_ in old:
                        snap[k_] = old[k_]
                H['seasons'][str(se)] = snap
                changed = True
        for k_, v in sorted(H['seasons'].items()):
            if int(k_) < cur_season and not v.get('closed'):
                try:
                    v['aftermath'] = _hist_aftermath(slot, s, v, cv)
                except Exception as ex:
                    print('[history] aftermath:', ex)
                    v['aftermath'] = {}
                v['closed'] = _fmt_date(s.game_date_code())
                H['pending'] = k_
                changed = True
                try:
                    _y, _m, _d = _date_tuple(s.game_date_code())
                    world(slot, s).add('season_end', '%04d-%02d-%02d' % (_y, _m, _d), 'season_end:%s' % k_, club=v.get('club'),
                                       pos=(v.get('row') or [None])[0], league=v.get('league'), label=v.get('label'), move=(v.get('aftermath') or {}).get('my_move'))
                except Exception as ex:
                    print('[history] world:', ex)
        if changed:
            _hist_save(cid, H)
    _HIST_KEY[slot] = key
    return cid


def history_view(slot, season=None, full=False):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = history_tick(slot, s) or _career_id(slot, s)
    H = _hist_load(cid)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    if season is not None:
        v = H['seasons'].get(str(season))
        if not v:
            return dict(ok=False, error='no such season')
        v = dict(v)
        pl = v.pop('players', {}) or {}
        # tvoji igraci + najbolji u ligi (za karticu sezone); sve ostalo ostaje u datoteci
        mine = {str(r[0]) for r in v.get('squad') or []}
        mp = []
        for k_, x in pl.items():
            if x[4] == v.get('idx') or k_ in mine:
                mp.append(dict(id=int(k_), name=NAMES.get(int(k_), str(k_)), app=x[0], g=x[1], a=x[2], r=x[3]))
        mp.sort(key=lambda r: (-r['app'], -r['g']))
        v['my_players'] = mp
        if not full:
            v['leagues'] = [l for l in v.get('leagues') or [] if l['name'] == v.get('league')] + [dict(name=l['name'], n=l['n'], done=l['done'], champion=l['rows'][0][1] if l['rows'] else None)
                                                                                                for l in v.get('leagues') or [] if l['name'] != v.get('league')]
        return dict(ok=True, season=v)
    out = []
    for k_, v in sorted(H['seasons'].items(), key=lambda kv: -int(kv[0])):
        r = v.get('row') or []
        champs = [[l['name'], l['rows'][0][1]] for l in v.get('leagues') or [] if l.get('done') and l.get('rows')]
        ts_ = None
        for kk, x in (v.get('players') or {}).items():
            if x[4] == v.get('idx') and x[1] and (ts_ is None or x[1] > ts_[2]):
                ts_ = [int(kk), NAMES.get(int(kk), kk), x[1]]
        out.append(dict(top=ts_, season=int(k_), label=v.get('label'), club=v.get('club'), league=v.get('league'), pos=r[0] if r else None, n=len((next((l for l in v.get('leagues') or [] if l['name'] == v.get('league')), {}) or {}).get('rows') or []),
                        pts=r[9] if len(r) > 9 else None, w=r[4] if r else None, d=r[5] if r else None, l=r[6] if r else None, gf=r[7] if r else None, ga=r[8] if r else None,
                        complete=v.get('complete'), closed=v.get('closed'), champions=champs[:12], awards=v.get('awards'), board=v.get('board'),
                        move=(v.get('aftermath') or {}).get('my_move')))
    return dict(ok=True, career=cid, club=_my_club_name(s), seasons=out, pending=(H.get('pending') if H.get('pending') and not (H['seasons'].get(H.get('pending')) or {}).get('shown') else None))


def history_shown(body):
    s = mlwrite.Save(slot_folder(body['slot']), ro=True)
    cid = _career_id(body['slot'], s)
    with HIST_LOCK:
        H = _hist_load(cid)
        k_ = str(body.get('season') or H.get('pending') or '')
        if k_ in H['seasons']:
            H['seasons'][k_]['shown'] = True
        H.pop('pending', None)
        _hist_save(cid, H)
    return dict(ok=True)


def history_player(slot, pid):
    """Sezone igraca u ovoj karijeri (iz arhive) + tekuca."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = history_tick(slot, s) or _career_id(slot, s)
    H = _hist_load(cid)
    out = []
    for k_, v in sorted(H['seasons'].items(), key=lambda kv: -int(kv[0])):
        x = (v.get('players') or {}).get(str(pid))
        if x:
            out.append(dict(season=v.get('label'), app=x[0], g=x[1], a=x[2], r=x[3], club=seasonstats.club_name(s.d, x[4])))
    return dict(ok=True, seasons=out, regen=pid in _REGEN, orig=_orig_name(pid) if pid in _REGEN else None)


def _hist_eras(H):
    """[(season, v, regens_set)] sortirano; pomoc za razdvajanje starog igraca i regena na istom ID-u."""
    out = []
    for k_, v in sorted(H.get('seasons', {}).items(), key=lambda kv: int(kv[0])):
        out.append((int(k_), v, set(v.get('regens') or [])))
    return out


def _hist_pname(pid, era_new):
    return NAMES.get(pid, str(pid)) if era_new else _orig_name(pid)


def history_club(slot, name):
    """Povijest kluba u ovoj karijeri: plasman po sezonama, naslovi, najbolji strijelci i najvise nastupa svih vremena."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = history_tick(slot, s) or _career_id(slot, s)
    H = _hist_load(cid)
    seasons, P = [], {}
    idx = None
    for se, v, rg in _hist_eras(H):
        for l in v.get('leagues') or []:
            r = next((r for r in l['rows'] if r[1] == name), None)
            if r:
                idx = r[2]
                seasons.append(dict(season=se, label=v.get('label'), league=l['name'], pos=r[0], n=l['n'], pts=r[9], w=r[4], d=r[5], l=r[6], gf=r[7], ga=r[8],
                                    done=bool(l.get('done')), champion=bool(l.get('done') and r[0] == 1)))
                break
    if idx is not None:
        for se, v, rg in _hist_eras(H):
            for k_, x in (v.get('players') or {}).items():
                if x[4] != idx:
                    continue
                pid = int(k_)
                key = (pid, pid in rg)
                p = P.setdefault(key, dict(id=pid, name=_hist_pname(pid, pid in rg), app=0, g=0, a=0, seasons=0, regen_old=(pid in _REGEN and pid not in rg)))
                p['app'] += x[0]; p['g'] += x[1]; p['a'] += x[2]; p['seasons'] += 1
    pl = list(P.values())
    return dict(ok=True, club=name, seasons=list(reversed(seasons)), titles=sum(1 for x in seasons if x['champion']),
                scorers=sorted([p for p in pl if p['g']], key=lambda p: (-p['g'], -p['app']))[:8],
                apps=sorted(pl, key=lambda p: (-p['app'], -p['g']))[:8])


def history_legends(slot):
    """Legende ovog svijeta: strijelci svih vremena, naslovi po klubovima, Hall of Fame umirovljenih, rekordi tvog kluba."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = history_tick(slot, s) or _career_id(slot, s)
    H = _hist_load(cid)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    P, titles, hof = {}, {}, {}
    eras = _hist_eras(H)
    for se, v, rg in eras:
        for k_, x in (v.get('players') or {}).items():
            pid = int(k_)
            key = (pid, pid in rg)
            p = P.setdefault(key, dict(id=pid, name=_hist_pname(pid, pid in rg), app=0, g=0, a=0, seasons=0, club=None, my_app=0, my_g=0, retired=(pid in _REGEN and pid not in rg)))
            p['app'] += x[0]; p['g'] += x[1]; p['a'] += x[2]; p['seasons'] += 1
            p['club'] = seasonstats.club_name(s.d, x[4])
            if x[4] == my:
                p['my_app'] += x[0]; p['my_g'] += x[1]
        for l in v.get('leagues') or []:
            if l.get('done') and l.get('rows'):
                t = titles.setdefault(l['rows'][0][1], dict(club=l['rows'][0][1], n=0, leagues=[], seasons=[], wins=[]))
                t['n'] += 1
                t['seasons'].append(v.get('label'))
                t['wins'].append([v.get('label'), l['name']])
                if l['name'] not in t['leagues']:
                    t['leagues'].append(l['name'])
        A = v.get('aftermath') or {}
        for r in (A.get('world_retired') or []) + [[x[0], x[1], x[2], x[3], v.get('club')] for x in (A.get('retired') or [])]:
            hof[r[0]] = dict(id=r[0], name=r[1], age=r[2], ovr=r[3], club=r[4] if len(r) > 4 else '', season=v.get('label'))
    for h in hof.values():
        p = P.get((h['id'], False)) or {}
        h.update(app=p.get('app', 0), g=p.get('g', 0), a=p.get('a', 0))
    pl = list(P.values())
    fmt = lambda L: [dict(p) for p in L]
    return dict(ok=True, seasons=len(eras),
                scorers=fmt(sorted([p for p in pl if p['g']], key=lambda p: (-p['g'], -p['app']))[:30]),
                assists=fmt(sorted([p for p in pl if p['a']], key=lambda p: (-p['a'], -p['app']))[:30]),
                apps=fmt(sorted(pl, key=lambda p: (-p['app'], -p['g']))[:30]),
                my_scorers=fmt(sorted([p for p in pl if p['my_g']], key=lambda p: (-p['my_g'], -p['my_app']))[:30]),
                my_apps=fmt(sorted([p for p in pl if p['my_app']], key=lambda p: (-p['my_app'], -p['my_g']))[:30]),
                titles=sorted(titles.values(), key=lambda t: (-t['n'], t['club']))[:60], labels=[v.get('label') for se, v, rg in eras],
                hof=sorted(hof.values(), key=lambda h: (-(h.get('ovr') or 0), -(h.get('g') or 0)))[:30], club=_my_club_name(s))


def history_h2h(slot, opp):
    """Medjusobni omjer s klubom kroz sve sezone (arhiva + tekuca sezona iz savea)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = history_tick(slot, s) or _career_id(slot, s)
    H = _hist_load(cid)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    games = {}
    for se, v, rg in _hist_eras(H):
        if v.get('idx') != my:
            continue
        for x in v.get('results') or []:
            if x[4] == opp:
                games[(x[2], x[1], x[0], x[3])] = dict(date='%02d.%02d.%d' % (x[0], x[1], x[2]), season=v.get('label'), home=bool(x[5]), gf=x[6], ga=x[7])
    try:
        M = _season(slot, s)
        for m in M['matches']:
            if not m['played'] or my not in (m['home'], m['away']):
                continue
            oi = m['away'] if m['home'] == my else m['home']
            if seasonstats.club_name(s.d, oi) != opp:
                continue
            r = _mres(m, my, s)
            games[(m['y'], m['m'], m['dd'], m['tid'])] = dict(date=r['date'], season=_slabel(m['season']), home=r['home'], gf=r['gf'], ga=r['ga'])
    except Exception:
        pass
    G = [games[k] for k in sorted(games)]
    w = sum(1 for g in G if g['gf'] > g['ga']); d = sum(1 for g in G if g['gf'] == g['ga'])
    big = max(G, key=lambda g: (g['gf'] - g['ga'], g['gf']), default=None)
    worst = min(G, key=lambda g: (g['gf'] - g['ga'], -g['ga']), default=None)
    return dict(ok=True, opp=opp, n=len(G), w=w, d=d, l=len(G) - w - d, gf=sum(g['gf'] for g in G), ga=sum(g['ga'] for g in G),
                last=list(reversed(G[-6:])), biggest_win=big if big and big['gf'] > big['ga'] else None, worst=worst if worst and worst['gf'] < worst['ga'] else None,
                seasons=len({g['season'] for g in G}))


def history_news(slot):
    """Clanci koji se pozivaju na proslost (za novine i Home)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = history_tick(slot, s) or _career_id(slot, s)
    H = _hist_load(cid)
    eras = _hist_eras(H)
    y, m, _ = _date_tuple(s.game_date_code())
    cur = y if m >= 7 else y - 1
    past = [(se, v, rg) for se, v, rg in eras if se < cur]
    if not past:
        return dict(items=[])
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    club = _my_club_name(s)
    cv = comps_view(slot)
    out = []
    sh = lambda x: re.sub(r'^(ACF|AC|AS|SS|SSC|US|FC|CF) ', '', x or '')
    prev_se, prev, _ = past[-1]
    prev_l = {l['name']: l for l in prev.get('leagues') or []}
    now_l = {c['name']: c for c in cv.get('comps') or [] if c.get('kind') == 'league' and c.get('rows')}

    def champs(lname):
        res = []
        for se, v, rg in eras:
            l = next((l for l in v.get('leagues') or [] if l['name'] == lname and l.get('done') and l.get('rows')), None)
            if l:
                res.append((se, l['rows'][0][1]))
        return res
    mine_now = next((c for c in now_l.values() if any(r.get('idx') == my for r in c['rows'])), None)
    lnames = [mine_now['name']] if mine_now else []
    lnames += [n for n in now_l if n not in lnames][:6]
    for ln in lnames:
        c = now_l[ln]
        ch = champs(ln)
        played = sum(r['pl'] for r in c['rows'])
        lead = c['rows'][0]
        if ch:
            last = ch[-1][1]
            k = 0
            for se_, cl_ in reversed(ch):
                if cl_ != last:
                    break
                k += 1
            if played and lead['club'] == last and k >= 1:
                out.append(dict(tag='Dynasty' if k >= 2 else 'Champions', c='r', club=last, big=sh(last) + (' chase a %s straight title' % {1: 'second', 2: 'third', 3: 'fourth', 4: 'fifth'}.get(k, '%dth' % (k + 1)) if k <= 4 else ' chase title number %d' % (k + 1)),
                                ps=['%s won %s the last %d season%s and lead %s again with %d points.' % (last, ln, k, 's' if k > 1 else '', ln, lead['pts']),
                                    'Can anybody stop them? %s are the closest.' % (c['rows'][1]['club'] if len(c['rows']) > 1 else '')]))
            elif played and last and ln == (mine_now or {}).get('name'):
                r_ = next((r for r in c['rows'] if r['club'] == last), None)
                if r_ and r_['pos'] > len(c['rows']) / 2:
                    out.append(dict(tag='Champions in crisis', c='r', club=last, big='From champions to ' + ordinal_en(r_['pos']),
                                    ps=['Last season %s were crowned champions of %s. Now they sit %s with %d points.' % (last, ln, ordinal_en(r_['pos']), r_['pts']),
                                        'The pressure is growing on the manager.']))
        pl_ = prev_l.get(ln)
        if pl_ and ln == (mine_now or {}).get('name'):
            sc = (pl_.get('scorers') or [None])[0]
            if sc and played:
                gnow = next((x.get('g') for x in c.get('scorers') or [] if x['id'] == sc[0]), 0) or 0
                out.append(dict(tag='Golden Boot', c='b', club=sc[2], big='Last year\'s top scorer: %s' % sc[1],
                                ps=['%s won the scoring race last season with %d goals.' % (sc[1], sc[3] or 0),
                                    'This season he has %d so far.' % gnow if gnow else 'This season he is still waiting for his first goal.']))
    A = prev.get('aftermath') or {}
    if prev.get('idx') == my and A.get('my_move') and mine_now:
        r_ = next((r for r in mine_now['rows'] if r.get('idx') == my), None)
        if r_ and r_['pl']:
            if A['my_move'] == 'relegated':
                out.append(dict(tag='Bounce back', c='r', club=club, big=(sh(club) + ' bounce back' if r_['pos'] <= 3 else sh(club) + ' after the drop'),
                                ps=['Relegated last season, %s now sit %s in %s with %d points.' % (club, ordinal_en(r_['pos']), mine_now['name'], r_['pts']),
                                    'An immediate return is the only goal for the board.' if r_['pos'] > 3 else 'Promotion is in their own hands.']))
            else:
                out.append(dict(tag='New boys', c='b', club=club, big=sh(club) + ' settle in' if r_['pos'] <= len(mine_now['rows']) // 2 else 'Tough first year for ' + sh(club),
                                ps=['Promoted last season, %s sit %s in %s.' % (club, ordinal_en(r_['pos']), mine_now['name']), '']))
    for mv in (A.get('moves') or []):
        if mine_now and mv[2] == mine_now['name'] and mv[3] == 'up' and mv[0] != club:
            r_ = next((r for r in mine_now['rows'] if r['club'] == mv[0]), None)
            if r_ and r_['pl'] >= 5 and r_['pos'] <= 4:
                out.append(dict(tag='Promoted flyers', c='b', club=mv[0], big='Newly promoted %s flying' % sh(mv[0]),
                                ps=['A year ago %s were in %s. Now they are %s in %s.' % (mv[0], mv[1], ordinal_en(r_['pos']), mv[2]), 'Nobody expected this.']))
                break
    wr = (A.get('world_retired') or [])[:1]
    if wr and m in (7, 8, 9):
        x = wr[0]
        out.append(dict(tag='End of an era', c='b', club=x[4] or '', big='End of an era: %s retires' % x[1],
                        ps=['%s has hung up his boots%s.' % (x[1], ' at ' + x[4] if x[4] else ''), 'The game will miss one of its best (OVR %s).' % x[3]]))
    # povratak bivseg igraca: igrac sljedeceg protivnika je prije igrao za tvoj klub
    try:
        nx = next_match(slot)
        opp = (nx.get('next') or {}).get('opp')
        if opp:
            Mx = _season(slot, s)
            oi = (nx.get('next') or {}).get('opp_idx')
            back = []
            for se, v, rg in past:
                for k_, x in (v.get('players') or {}).items():
                    pid = int(k_)
                    if x[4] == my and x[0] >= 8 and Mx['cur'].get(pid) == oi and pid not in rg:
                        back.append((pid, x))
            if back:
                pid, x = max(back, key=lambda b: b[1][0])
                out.append(dict(tag='Return', c='r', club=opp, big='%s returns to face his old club' % NAMES.get(pid, ''),
                                ps=['%s played %d games and scored %d goals for %s.' % (NAMES.get(pid, ''), x[0], x[1], club), 'Now he wears the shirt of %s.' % opp]))
    except Exception:
        pass
    return dict(items=out[:8])


def ordinal_en(n):
    n = int(n or 0)
    return '%d%s' % (n, 'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th'))


def honours_view(slot):
    """Vitrina: naslovi i plasmani po sezonama, klupski rekordi i rekordi igraca (iz svih odigranih utakmica u save-u)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    allm = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    R = [_mres(m, my, s) for m in allm]
    nm = lambda pid: NAMES.get(pid, str(pid))
    seasons = []
    for se in sorted({m['season'] for m in allm}):
        sm = [(m, r) for m, r in zip(allm, R) if m['season'] == se]
        cnt = {}
        for m, _ in sm:
            cnt[m['tid']] = cnt.get(m['tid'], 0) + 1
        lt = max((t for t in cnt if t in COMP_LEAGUES), key=lambda t: cnt[t], default=None)
        e = dict(season=se, n=len(sm), w=sum(1 for _, r in sm if r['res'] == 'W'), d=sum(1 for _, r in sm if r['res'] == 'D'), l=sum(1 for _, r in sm if r['res'] == 'L'),
                 gf=sum(r['gf'] for _, r in sm), ga=sum(r['ga'] for _, r in sm), league=None, pos=None, pts=None, done=False, champion=False)
        if lt:
            lm = [x for x in M['matches'] if x['tid'] == lt and x['season'] == se]
            tb = _table(lm)
            me = next((t for t in tb if t['c'] == my), None)
            e.update(league=COMP_LEAGUES[lt], done=all(x['played'] for x in lm), pos=me['pos'] if me else None, pts=me['pts'] if me else None, teams=len(tb))
            e['champion'] = bool(e['done'] and me and me['pos'] == 1)
        seasons.append(e)
    # pc241: sezone koje je igra obrisala, iz arhive povijesti (samo s istim klubom)
    try:
        have = {e['season'] for e in seasons}
        club_ = seasonstats.club_name(s.d, my)
        for k_, v in _hist_load(_career_id(slot, s)).get('seasons', {}).items():
            se_ = int(k_)
            r_ = v.get('row')
            if se_ in have or v.get('idx') != my or not r_:
                continue
            res_ = v.get('results') or []
            w_ = sum(1 for x in res_ if x[6] > x[7]); d_ = sum(1 for x in res_ if x[6] == x[7])
            lg_ = next((l for l in v.get('leagues') or [] if l['name'] == v.get('league')), {})
            seasons.append(dict(season=se_, n=len(res_), w=w_, d=d_, l=len(res_) - w_ - d_, gf=sum(x[6] for x in res_), ga=sum(x[7] for x in res_),
                                league=v.get('league'), pos=r_[0], pts=r_[9], done=bool(v.get('complete')), champion=bool(v.get('complete') and r_[0] == 1),
                                teams=lg_.get('n'), archived=True))
        seasons.sort(key=lambda e: e['season'])
    except Exception as ex:
        print('[honours] history:', ex)
    rec = {}
    if R:
        bw = max(R, key=lambda r: (r['gf'] - r['ga'], r['gf']))
        bl = min(R, key=lambda r: (r['gf'] - r['ga'], -r['ga']))
        hs = max(R, key=lambda r: (r['gf'] + r['ga'], r['gf']))
        keep = lambda r: dict(date=r['date'], opp=r['opp'], home=r['home'], gf=r['gf'], ga=r['ga'])
        rec['biggest_win'] = keep(bw) if bw['gf'] > bw['ga'] else None
        rec['heaviest_loss'] = keep(bl) if bl['gf'] < bl['ga'] else None
        rec['highest_scoring'] = keep(hs)
        def longest(pred):
            best, cur = 0, 0
            for r in R:
                cur = cur + 1 if pred(r['res']) else 0
                best = max(best, cur)
            return best
        rec['win_streak'] = longest(lambda v: v == 'W')
        rec['unbeaten'] = longest(lambda v: v != 'L')
        rec['loss_streak'] = longest(lambda v: v == 'L')
        rec['clean_sheets'] = sum(1 for r in R if r['ga'] == 0)
        rec['games'] = len(R)
    P = {}
    for m, r in zip(allm, R):
        for x in r['mine']:
            p = P.setdefault(x[0], dict(pid=x[0], name=nm(x[0]), app=0, g=0, a=0, rs=0.0, ht=0, best=None, mg=0))
            p['app'] += 1; p['g'] += x[2]; p['a'] += x[3]; p['rs'] += x[4]
            if x[2] >= 3:
                p['ht'] += 1
            p['mg'] = max(p['mg'], x[2])
            if p['best'] is None or x[4] > p['best']:
                p['best'] = x[4]
    pl = list(P.values())
    for p in pl:
        p['avg'] = round(p['rs'] / p['app'], 2) if p['app'] else 0
        p['best'] = round(p['best'], 1) if p['best'] else None
        p.pop('rs')
    cur_ids = {pid for pid, ci in M['cur'].items() if ci == my}
    top = lambda key, n=5, flt=lambda p: True: [dict(p, here=(p['pid'] in cur_ids)) for p in sorted([p for p in pl if flt(p) and p[key]], key=lambda p: (-p[key], -p['app']))[:n]]
    real, cut, rc = _real_honours(seasonstats.club_name(s.d, my), [e['season'] for e in seasons])
    return dict(club=seasonstats.club_name(s.d, my), seasons=seasons, records=rec, real=real, real_cutoff=cut, real_country=rc,
                scorers=top('g'), assisters=top('a'), apps=top('app'), hattricks=top('ht'), rated=top('avg', 5, lambda p: p['app'] >= 5), mg=top('mg', 5),
                manual=_hn_manual().get(slot, {}), comp_emb=_hn_comp_embs(seasonstats.club_name(s.d, my)))


def _real_cutoff(seasons=()):
    """First season of the game world: real trophies only count before it.
    The FC 27 database is the 2026/27 season (importer --as-of 2026-08-01), so
    the cutoff is 2026. An older career save can start earlier, so the earliest
    season the app knows for that career still wins."""
    base = 2026
    try:
        return min([base] + [int(x) for x in seasons if x])
    except Exception:
        return base


def _real_honours(club, seasons=()):
    try:
        import realhonours
        cut = _real_cutoff(seasons)
        r = realhonours.for_club(club, cut)
        return r, cut, realhonours.home_country(r)
    except Exception as ex:
        print('[honours] real:', ex)
        return {}, None, None


def _hn_comp_embs(club):
    """pc217: logotipi natjecanja iz igre za Vitrinu: domaci kupovi u koje je klub prijavljen (CompetitionEntry.bin,
    sve sto nije liga ni UEFA) i europska natjecanja. r11: samo ID-evi (podaci), bez slika natjecanja."""
    out = dict(cups=[], eu={}, keys={})
    try:
        comps, entry = _comp_db()
        if not comps:
            return out
        tid = _team_id(club)
        eu_kw = ('UEFA', 'CHAMPIONS', 'EUROPA', 'CONFERENCE', 'FIFA', 'CLUB_WORLD')
        for cid in sorted(entry.get(tid, ()) if tid else ()):
            key = comps.get(cid, '')
            out['keys'][cid] = key
            if not key:
                continue
            ku = key.upper()
            if ku.endswith('_LEAGUE') or any(k in ku for k in eu_kw):
                continue
            out['cups'].append(dict(id=cid, key=key))
        for cid, key in comps.items():
            ku = (key or '').upper()
            if 'CHAMPIONS_LEAGUE' in ku and 'ucl' not in out['eu'] and ('UEFA' in ku or 'EUROPE' in ku or ku.startswith('CHAMPIONS')):
                out['eu']['ucl'] = cid
            elif 'EUROPA' in ku and 'uel' not in out['eu']:
                out['eu']['uel'] = cid
            elif 'CONFERENCE' in ku and 'uecl' not in out['eu']:
                out['eu']['uecl'] = cid
        for k, fb in (('ucl', 3), ('uel', 5)):
            if k not in out['eu']:
                out['eu'][k] = fb
    except Exception as e:
        out['error'] = str(e)[:120]
    return out


HN_MANUAL_FILE = os.path.join(HERE, 'data', 'trophies_manual.json')


def _hn_manual():
    try:
        return json.load(open(HN_MANUAL_FILE, encoding='utf-8'))
    except Exception:
        return {}


def honours_manual(body):
    """pc216: kupove i europske trofeje save ne pamti; igrac ih rucno upisuje u Vitrinu (natjecanje -> lista sezona)."""
    slot, comp, op = body['slot'], str(body['comp'])[:60], body.get('op', 'add')
    season = int(body['season'])
    D = _hn_manual()
    m = D.setdefault(slot, {})
    L = m.setdefault(comp, [])
    if op == 'add':
        L.append(season)
    elif season in L:
        L.remove(season)
    if not L:
        m.pop(comp, None)
    os.makedirs(os.path.dirname(HN_MANUAL_FILE), exist_ok=True)
    _jdump(D, HN_MANUAL_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, manual=m)



def _coach_season(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    return s, gd, _sc_season(gd)


def _coach_sev(c, ctr_end, season):
    """Odsteta pri otkazu trenera: pola godisnje place za svaku punu sezonu ugovora iza tekuce."""
    import datetime
    try:
        end_y = datetime.date.fromordinal(ctr_end).year
        end_m = datetime.date.fromordinal(ctr_end).month
        end_season = end_y if end_m >= 7 else end_y - 1
    except Exception:
        end_season = season
    left = max(0, end_season - season)
    return negotiate.rnd100(growth.coach_wage(c) * 0.5 * left, 1000) if left else 0


def growth_staff(body):
    slot = body.get('slot', '')
    gs = growth.load_state(HERE)
    sl = gs.setdefault(slot, {})
    st = sl.setdefault('staff', dict(hired=[], assign={}))
    ctr = st.setdefault('contracts', {})
    pool = {c['id']: c for c in growth.coach_pool()}
    now = _gnow(slot)
    act, cid = body.get('action'), body.get('coach')
    years = max(1, min(3, int(body.get('years') or 2)))
    _m = [r for r in players_data(slot)['players'] if r['mine']]
    bud = st.get('budget') or growth.default_staff_budget(sum(r.get('sal', 0) or 0 for r in _m))
    active = [pool[i] for i in st['hired'] if i in pool and ctr.get(i, now + 730) >= now]
    paid = st.setdefault('paid', {})
    sv_, gd_, season = _coach_season(slot)
    y_, m_, _d = _date_tuple(gd_)
    prorata = max(0.25, ((6 - m_) % 12 + 1) / 12.0)
    if act == 'hire':
        if cid not in pool or cid in st['hired']:
            return dict(ok=False, msg='nema')
        fee = negotiate.rnd100(growth.coach_wage(pool[cid]) * prorata, 1000)
        if fee > sv_.budget():
            return dict(ok=False, msg='tb')

        def fn(sv):
            sv.adjust_budget(-fee)
            return 'Manager %s hired. Wage until the end of the season (%d EUR) paid from the transfer budget.' % (pool[cid].get('name', cid), fee)
        r = _write_slot(slot, 'coach', fn)
        gs = growth.load_state(HERE)
        sl = gs.setdefault(slot, {})
        st = sl.setdefault('staff', dict(hired=[], assign={}))
        ctr = st.setdefault('contracts', {})
        paid = st.setdefault('paid', {})
        st['hired'].append(cid)
        ctr[cid] = now + 365 * years
        paid[cid] = season
        growth.save_state(HERE, gs)
        return dict(ok=True, msg=r.get('message'))
    elif act == 'renew':
        if cid not in st['hired']:
            return dict(ok=False, msg='nije_zaposlen')
        was_active = ctr.get(cid, 0) >= now
        if not was_active:
            fee = negotiate.rnd100(growth.coach_wage(pool[cid]) * prorata, 1000)
            if fee > sv_.budget():
                return dict(ok=False, msg='tb')

            def fn(sv):
                sv.adjust_budget(-fee)
                return 'Manager contract extended, wage until the end of the season (%d EUR) paid from the transfer budget.' % fee
            _write_slot(slot, 'coach', fn)
            gs = growth.load_state(HERE)
            sl = gs.setdefault(slot, {})
            st = sl.setdefault('staff', dict(hired=[], assign={}))
            ctr = st.setdefault('contracts', {})
            paid = st.setdefault('paid', {})
            paid[cid] = season
        ctr[cid] = max(ctr.get(cid, now), now) + 365 * years
    elif act == 'pay':
        due = [i for i in st['hired'] if i in pool and ctr.get(i, 0) >= now and paid.get(i, season) < season]
        tot = sum(growth.coach_wage(pool[i]) for i in due)
        if not tot:
            return dict(ok=True, msg='nema')
        if tot > sv_.budget():
            return dict(ok=False, msg='tb')

        def fn(sv):
            sv.adjust_budget(-tot)
            return 'Godisnje place trenera (%d EUR) placene iz transfer budzeta.' % tot
        r = _write_slot(slot, 'coach', fn)
        gs = growth.load_state(HERE)
        st = gs.setdefault(slot, {}).setdefault('staff', dict(hired=[], assign={}))
        for i in due:
            st.setdefault('paid', {})[i] = season
        growth.save_state(HERE, gs)
        return dict(ok=True, msg=r.get('message'))
    elif act == 'budget':
        st['budget'] = max(0, int(body.get('value') or 0)) or None
    elif act == 'fire':
        sev = _coach_sev(pool[cid], ctr.get(cid, now), season) if cid in pool and ctr.get(cid, 0) >= now else 0
        if sev:
            if sev > sv_.budget():
                return dict(ok=False, msg='tb')

            def fn(sv):
                sv.adjust_budget(-sev)
                return 'Manager dismissed. Compensation for the rest of the contract: %d EUR from the transfer budget.' % sev
            _write_slot(slot, 'coach', fn)
            gs = growth.load_state(HERE)
            sl = gs.setdefault(slot, {})
            st = sl.setdefault('staff', dict(hired=[], assign={}))
            ctr = st.setdefault('contracts', {})
        st['hired'] = [i for i in st['hired'] if i != cid]
        ctr.pop(cid, None)
        st.get('paid', {}).pop(cid, None)
        st['assign'] = {k: v for k, v in st['assign'].items() if v != cid}
    elif act == 'assign':
        if cid not in st['hired'] or ctr.get(cid, now + 1) < now:
            return dict(ok=False, msg='nije_zaposlen')
        st['assign'][str(int(body['pid']))] = cid
    elif act == 'unassign':
        st['assign'].pop(str(int(body['pid'])), None)
    else:
        return dict(ok=False, msg='akcija')
    growth.save_state(HERE, gs)
    return dict(ok=True)


def list_slots():
    out = []
    if DEV:
        return [dict(slot='DEV', size=0, mtime=0, label='razvojni save')]
    _sd = CFG.get('save_dir') or ''
    if not _sd or not os.path.isdir(_sd):
        return []   # r9: no save folder yet; /api/pes17/setup explains how to set it
    try:
        _files = sorted(os.listdir(_sd))
    except OSError:
        return []
    for f in _files:
        if f.startswith('ML0'):
            p = os.path.join(_sd, f)
            out.append(dict(slot=f, size=os.path.getsize(p), mtime=int(os.path.getmtime(p))))
    return out


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) != 11:
        raise ValueError('formacija mora imati 11 igraca')
    out = []
    for r in rows:
        p, x, y = int(r['pos']), int(r['x']), int(r['y'])
        if not (0 <= p <= 12 and 0 <= x <= 99 and 5 <= y <= 99):
            raise ValueError('invalid position or coordinates')
        out.append((p, x, y))
    if out[0][0] != 0 or sum(1 for o in out if o[0] == 0) != 1:
        raise ValueError('the first slot must be a goalkeeper, and only one goalkeeper')
    return out


def apply(body):
    pes17_readonly(body.get('slot'))
    slot = body['slot']
    if game_blocks():
        raise RuntimeError('The game is running. Go to the main menu and confirm it in the app, or close the game (otherwise it overwrites the save).')
    fm = {k: validate_rows(body['formations'][k]) for k in ('kickoff', 'inp', 'out')}
    xi, bench = body['xi'], body.get('bench', [])
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s' % (slot, ts))
            shutil.copy2(src, backup)
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        if body.get('team') == 'nation':   # pc306: sastav reprezentacije
            _nref = _my_nation(s)
            if _nref is None:
                raise ValueError('You do not manage a national team in this career. Nothing was written.')
            s.use_nation(_nref)
        s.set_formation(0, fm['kickoff']); s.set_formation(1, fm['inp']); s.set_formation(2, fm['out'])
        s.set_lineup_by_ids(xi, bench)
        if body.get('tactics') and body['tactics'] != s.my_tactics():   # pc210 (tester): nepromijenjena taktika se ne pise
            s.set_my_tactics(body['tactics'])
        if body.get('numbers'):
            s.set_squad_numbers(body['numbers'])
        fixed = s.fix_points()
        if getattr(s, 'beta_ok', False) and not s.known_format:
            # pc209: na 60 MB je izmjeren samo niz sastava (XI, klupa, pricuva); formacija, taktika i brojevi jos ne
            # pc247: na 60 MB uz "tactics60_beta": true i formacija, upute i brojevi (Save.save provjeri da je sve unutar tih dijelova)
            t60 = bool(s.fmt60 and CFG.get('tactics60_beta', True))
            # pc381: Micheleov 45 MB raspored ('new save layout', jedan pomak): formacija i upute su tocno gdje ih app ocekuje
            # (izmjereno u igri: A/B/C saveovi, Verona 23.9.2025: F0+9.., MY_TAC = F0-4, +146 linija). Brojevi dresova tamo jos nisu izmjereni.
            t45 = bool(not s.fmt60 and s.beta_ok and CFG.get('tactics45_beta', True))
            if t60 and s.changed_outside(s._tac60_ranges()) is not None:
                raise ValueError('This change touches parts of the 60 MB save outside tactics, formation, lineup and shirt numbers. The save was not touched.')
            # pc385: brojevi dresova na 45 MB izmjereni (Michele, Genoa 3.8.2025: Sabelli 20->2 = jedan u16 na club+662+2*12, kao klasicni)
            if t45 and s.changed_outside(s._tac60_ranges()) is not None:
                raise ValueError('On this save layout the app can change the lineup, formation, team instructions and shirt numbers; '
                                 'this change touches other parts of the save. The save was not touched.')
            t60 = t60 or t45
            if not t60 and s.changed_outside([(s.F0 + mlwrite.LINEUP_OFF, s.F0 + mlwrite.LINEUP_OFF + 35)]) is not None:
                raise ValueError('On this save format the app can so far change only the lineup (starting XI, bench and reserves). '
                                 'Formation, tactics and shirt number changes: do them in the game, or switch on the beta in config.json ("tactics60_beta": true). The save was not touched.')
            s._beta_write = True
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        if DEV:
            return dict(ok=True, message='DEV: zapisano u ' + new_dec)
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        note = (' Club points corrected (were %d).' % fixed) if fixed is not None else ''
        return dict(ok=True, message='Spremljeno u %s.%s Backup: %s' % (slot, note, backup), backup=backup)


def set_club_tac(body):
    """Ručno namjesti taktiku AI klubu (test): body {slot, club (ime ili indeks, ili 'next'), tactics:{...}}."""
    pes17_readonly(body.get('slot'))
    slot = body['slot']
    if game_blocks():
        raise RuntimeError('The game is running. Go to the main menu and confirm it in the app, or close the game (otherwise it overwrites the save).')
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
            backup = None
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s_tac' % (slot, ts))
            shutil.copy2(src, backup)
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        c = body['club']
        if c == 'next':
            c = (next_match(slot).get('next') or {}).get('opp_idx')
            if c is None:
                raise RuntimeError('no next opponent')
        elif isinstance(c, str) and not c.isdigit():
            hit = [i for i in range(mlsave.club_layout(s.d)[0]) if seasonstats.club_name(s.d, i).lower() == c.lower()]   # pc258
            if not hit:
                raise RuntimeError('club not found: ' + c)
            c = hit[0]
        c = int(c)
        before = s.club_tactics(c)
        s.set_club_tactics(c, body['tactics'])
        after = s.club_tactics(c)
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        name = seasonstats.club_name(s.d, c)
        if DEV:
            return dict(ok=True, club=name, before=before, after=after)
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        return dict(ok=True, club=name, before=before, after=after, backup=backup)


def opp_squad(slot):
    """Sastav sljedeceg protivnika (indeks u sastavu -> ime) za Tight Marking."""
    nm = next_match(slot)
    oi = (nm.get('next') or {}).get('opp_idx')
    if oi is None:
        return dict(club=None, squad=[])
    s = mlwrite.Save(slot_folder(slot), ro=True)
    sq = [dict(idx=i, id=p, name=NAMES.get(p, str(p)), pos=POS.get(p, 5)) for i, p in enumerate(s.club_squad_ids(oi)) if p]
    return dict(club=seasonstats.club_name(s.d, oi), squad=sq)


def verify_moves(folder, moves, before_folder=None):
    """Cita upisani save i provjerava: igrac je u klubu kupcu, nije vise u izvornom, sastavi/postave/brojevi klubova su konzistentni."""
    import struct
    v = mlwrite.Save(folder)
    before = mlwrite.Save(before_folder) if before_folder else None
    bad = []
    touched = set()
    for m in moves:
        to = int(m['to'])
        o = mlwrite.REC0 + to * mlwrite.STRIDE
        ids = [struct.unpack_from('<I', v.d, o + 332 + 8 * i)[0] for i in range(v._squad_len(o))]
        if int(m['pid']) not in ids:
            bad.append('player %s is not in club %d' % (m['pid'], to))
        touched.add(to)
        if m.get('from') is not None:
            touched.add(int(m['from']))
    for n in touched:
        o = mlwrite.REC0 + n * mlwrite.STRIDE
        L = v._squad_len(o)
        lu = list(v.d[v.TAC0 + 600 * n + 484:v.TAC0 + 600 * n + 484 + L])
        nums = [struct.unpack_from('<H', v.d, o + v.NUM_OFF + 2 * i)[0] for i in range(L)]
        if v.d[o + 1058] != L:
            bad.append('club counter %d' % n)
        # A native club can have a shorter, FF-padded Game Plan list.
        # Accept it only if the source save already used that supported shape.
        shape, _ = v._lineup_shape(lu, L)
        lineup_ok = len(lu) == L and 11 <= L <= 40 and shape is not None
        if shape == 'part':
            old_shape = None
            if before is not None:
                old_n = before._squad_len(o)
                old_lo = before.TAC0 + 600 * n + 484
                old_lu = list(before.d[old_lo:old_lo + old_n])
                old_shape, _ = before._lineup_shape(old_lu, old_n)
            lineup_ok = lineup_ok and old_shape == 'part'
        if not lineup_ok:
            bad.append('club lineup %d' % n)
        nn = [x for x in nums if x]
        if len(nn) != len(set(nn)) or 0 in nums:
            bad.append('club shirt numbers %d' % n)
    return bad


AIL_FILE = os.path.join(HERE, 'data', 'ailists.json')


def _val_of_fn():
    live, _ = read_dump()

    def val_of(pid, ovr, age):
        mv = ((live or {}).get(pid) or {}).get('mv')
        return int(negotiate.value_band(mv, ovr, age) if negotiate.VALUE_BASE else mv) if mv else negotiate.estimate_value(ovr or 50, age or 25)
    return val_of


def _season_key(s):
    y, m, _ = _date_tuple(s.game_date_code())
    return ('S%d' % y) if m >= 7 else ('W%d' % y)


def ai_listings(slot, s=None):
    """Transfer lista i lista posudbi AI klubova (app): generira se jednom po prozoru (ljeto/zima), pa se prune kad igrac promijeni klub."""
    s = s or mlwrite.Save(slot_folder(slot), ro=True)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    key = _season_key(s)
    try:
        allf = json.load(open(AIL_FILE, encoding='utf-8'))
    except Exception:
        allf = {}
    clubs = _tier_clubs(s, my)
    where = {p['pid']: c['idx'] for c in clubs.values() for p in c['players']}
    rec = allf.get(slot)
    if not rec or rec.get('key') != key:
        val_of = _val_of_fn()
        for c in clubs.values():
            for p in c['players']:
                p['val'] = val_of(p['pid'], p['ovr'], p['age'])
        lst = aitransfers.build_listings(clubs, '%s|%s' % (slot, key), val_of)
        rec = dict(key=key, items={str(k): v for k, v in lst.items()})
        allf[slot] = rec
        os.makedirs(os.path.dirname(AIL_FILE), exist_ok=True)
        _jdump(allf, AIL_FILE, ensure_ascii=False)
    try:
        _onl = s.on_loan_pids()
    except Exception:
        _onl = set()
    items = dict(rec['items'])
    try:   # pc161: nezadovoljni (malo minuta) i igraci kojima istice ugovor; racuna se jednom mjesecno
        mk = '%d-%d' % (_date_tuple(s.game_date_code())[0], _date_tuple(s.game_date_code())[1])
        if rec.get('unrest_mk') != mk:
            rec['unrest'] = {str(k): v for k, v in _ai_unrest(slot, s, clubs, key, mk, items).items()}
            rec['unrest_mk'] = mk
            allf[slot] = rec
            _jdump(allf, AIL_FILE, ensure_ascii=False)
        for k_, v_ in (rec.get('unrest') or {}).items():
            items.setdefault(k_, v_)
    except Exception as ex:
        print('[unrest]', ex)
    return {int(k): v for k, v in items.items() if where.get(int(k)) == v['club_idx'] and int(k) not in _onl}


def _ai_unrest(slot, s, clubs, key, mk, have):
    import random
    """pc161: AI klubovi reagiraju na stvarno stanje igraca:
    - igrac koji je po kvaliteti za prvu postavu, a ove sezone igra malo (manje od ~40 % utakmica kluba) postane nezadovoljan;
      sto dulje to traje, to je veca sansa da trazi odlazak i da ga klub stavi na listu (cijena blizu vrijednosti, jer zeli van);
    - igraca kojem istice ugovor (a klub ga nije produzio) klub ponudi prije nego ode besplatno (jeftinije, sto blize kraju).
    Deterministicno po slotu, prozoru i mjesecu."""
    out = {}
    try:
        M = _season(slot, s)
    except Exception:
        M = None
    y, m, _d = _date_tuple(s.game_date_code())
    season_end = y + 1 if m >= 7 else y          # ugovor do ljeta te godine = istice ove sezone
    played = {}
    seas = None
    if M and M.get('matches'):
        pm = [x for x in M['matches'] if x.get('played')]
        if pm:
            seas = max(x['season'] for x in pm)
            for x in pm:
                if x['season'] == seas:
                    for ci in (x.get('home'), x.get('away')):
                        played[ci] = played.get(ci, 0) + 1
    try:
        C = s.all_contracts()
    except Exception:
        C = {}
    val_of = _val_of_fn()
    for c in clubs.values():
        pl = sorted((p for p in c['players'] if p['ovr']), key=lambda q: -q['ovr'])
        if len(pl) < 18:
            continue
        r = random.Random('%s|%s|%s|unrest|%s' % (slot, key, mk, c['idx']))
        n_cl = played.get(c['idx'], 0)
        apps = seasonstats.agg(M, seas, club=c['idx']) if (M and seas is not None and n_cl >= 6) else {}
        _t11 = sorted(((apps.get(q['pid']) or {}).get('app', 0) for q in pl[:11]), reverse=True) if apps else []
        med = _t11[len(_t11) // 2] if _t11 else 0     # tipican broj nastupa igraca prve postave tog kluba (save ne biljezi sve utakmice)
        added = 0
        for rk, q in enumerate(pl):
            if added >= 2:
                break
            pid = q['pid']
            if str(pid) in have or pid in out:
                continue
            reason = None
            if apps and rk <= 12 and 20 <= (q['age'] or 25) <= 31 and q['ovr'] >= c['strength'] - 2:
                a_ = (apps.get(pid) or {}).get('app', 0)
                rel = a_ / float(med) if med else 1.0
                if rel < 0.45 and a_ < 0.3 * n_cl:
                    pr = min(0.6, (0.45 - rel) * 1.1 + max(0, n_cl - 8) * 0.015)
                    if r.random() < pr:
                        reason, f = 'unhappy', r.uniform(0.9, 1.1)
            if not reason:
                ct = C.get(pid)
                # pc284: 'ugovor istjece' tek kad je do kraja ugovora 6 mjeseci ili manje (zimski rok); ljeti s godinom ugovora ima luft
                ml_ = ((ct['y'] - y) * 12 + (ct['m'] - m)) if ct else 99
                if ct and ct['y'] == season_end and 0 <= ml_ <= 6 and rk <= 18 and (q['age'] or 30) <= 31:
                    pr = 0.5 if m in (1, 2) else 0.3
                    if r.random() < pr:
                        reason, f = 'contract', (r.uniform(0.45, 0.7) if m in (1, 2) else r.uniform(0.65, 0.85))
            if reason:
                v = q.get('val') or val_of(pid, q['ovr'], q['age'])
                out[pid] = dict(kind='transfer', reason=reason, club_idx=c['idx'], club=c['name'], ask=aitransfers.rnd100(v * f), val=v, since=_fmt_date(s.game_date_code()))
                added += 1
    try:   # ozlijedjeni ne igraju zbog ozljede, a ne zato sto ih trener ne stavlja: nisu nezadovoljni
        uh = [p_ for p_, v_ in out.items() if v_['reason'] == 'unhappy']
        live_ = growth.read_live(CFG.get('dump') or '', uh) if uh else {}
        for p_ in uh:
            if (live_.get(p_) or {}).get('inj', 0) >= 7:
                out.pop(p_, None)
    except Exception:
        pass
    return out


def tlist_world(slot):
    """Sve transfer liste i liste posudbi na jednom mjestu: AI klubovi (app) + moja (app)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    live, _ = read_dump()
    rows = []
    for pid, v in ai_listings(slot, s).items():
        lv = (live or {}).get(pid) or {}
        o, a = rat(pid)
        rows.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=o, age=lv.get('age') or a, club=v['club'],
                         kind=v['kind'], reason=v['reason'], ask=v.get('ask'), share=v.get('share'), buy=v.get('buy'), mv=v.get('val', 0), src='ai'))
    for e in tlist_view(slot)['items']:
        for kind, on in (('transfer', e['tl']), ('loan', e['loan'])):
            if on:
                rows.append(dict(pid=e['pid'], name=e['name'], pos=e['pos'], ovr=e['ovr'], age=e['age'], club=s.club_name(), kind=kind,
                                 reason=(e['reason'] if kind == 'transfer' else 'minutes'), ask=(e['ask'] if kind == 'transfer' else None),
                                 share=(e['loan_share'] if kind == 'loan' else None), buy=(e['loan_buy'] if kind == 'loan' else None), mv=e['mv'], src='me'))
    return dict(items=rows, key=_season_key(s))


REALMOVES_FILE = os.path.join(HERE, 'data', 'realmoves.json')
_RM = {'busy': False, 'cache': None}


def realmoves_fetch_bg():
    """pc307: jednom (pa svakih 30 dana) skine Wikipedia popise transfera ljeto 2025 / zima 2025-26 u pozadini."""
    if not _wiki_web():
        return   # r8: offline by default; the FL26 Wikipedia transfer cache was cleaned out, never refetch it
    if _RM['busy']:
        return
    try:
        st = json.load(open(REALMOVES_FILE, encoding='utf-8')) if os.path.exists(REALMOVES_FILE) else {}
        pg = st.get('pages') or {}
        if all(p in pg and pg[p].get('ok') is not None and time.time() - pg[p].get('t', 0) < 30 * 86400
               and (pg[p].get('ok') or pg[p].get('pv', 1) >= realmoves.PV) for p in realmoves.PAGES):   # pc379: i stranice koje stari citac nije razumio
            return
    except Exception:
        pass
    _RM['busy'] = True

    def run():
        try:
            realmoves.fetch_all(REALMOVES_FILE)
            _RM['cache'] = None
        except Exception as ex:
            print('[realmoves]', ex)
        finally:
            _RM['busy'] = False
    threading.Thread(target=run, daemon=True).start()


def real_moves_ready():
    """pc379: jesu li stvarni transferi (Wikipedia) ucitani; dok nisu, ne zna se tko je u stvarnosti tek dosao u klub."""
    try:
        if not os.path.exists(REALMOVES_FILE):
            return False
        k = os.path.getmtime(REALMOVES_FILE)
        if _RM.get('ready_k') == k:
            return _RM.get('ready')
        st = json.load(open(REALMOVES_FILE, encoding='utf-8'))
        ok = bool(st.get('rows')) and any((v or {}).get('ok') for v in (st.get('pages') or {}).values())
        _RM['ready_k'], _RM['ready'] = k, ok
        return ok
    except Exception:
        return False


def real_moves(slot):
    """{pid: {date, frm, to}}: igraci koji su u stvarnosti tek dosli u klub u kojem su i u saveu."""
    if not os.path.exists(REALMOVES_FILE):
        realmoves_fetch_bg()
        return {}
    try:
        pd = players_data(slot)
        key = (slot, os.path.getmtime(REALMOVES_FILE), len(pd['players']))
        if _RM['cache'] and _RM['cache'][0] == key:
            return _RM['cache'][1]
        st = json.load(open(REALMOVES_FILE, encoding='utf-8'))
        out = realmoves.match(st.get('rows') or [], [dict(id=p['id'], name=NAMES.get(p['id']) or p.get('name'), club=p.get('club')) for p in pd['players']])
        _RM['cache'] = (key, out)
        return out
    except Exception as ex:
        print('[realmoves] match:', ex)
        return {}


def settled_protect(slot, s, seed=1):
    """pc307: igraci koji su nedavno promijenili klub (u karijeri: datum dolaska iz savea; prije karijere: stvarni transferi)
    ostaju u klubu barem do iduceg ljeta (~400 dana). Rijetke iznimke (~6 %), kao u stvarnosti."""
    import datetime as _dt
    import zlib as _z
    days = {}
    try:
        days.update(s.recent_joins(400))
    except Exception as ex:
        print('[settled] save:', ex)
    try:
        c = s.game_date_code()
        now = _dt.date(c & 0xffff, (c >> 16) & 0xff, c >> 24)
        for pid, v in real_moves(slot).items():
            y, m_, d_ = [int(x) for x in v['date'].split('-')]
            n = (now - _dt.date(y, m_, d_)).days
            if -60 <= n <= 400:
                days.setdefault(int(pid), max(n, 0))
    except Exception as ex:
        print('[settled] real:', ex)
    return {pid for pid in days if _z.crc32(('%s:%s' % (pid, seed)).encode()) % 100 >= 6}


def transfer_past(slot, s):
    """pc352: povijest igraca za AI transfere -> {pid: {block: {klub}, back: {klub}, home: klub}}.
    Izvori: transferi u ovoj karijeri (app), stvarni transferi 2025/26 (Wikipedia popisi) i karijera igraca s Wikipedije
    (samo ono sto je vec u kesu data/wiki; novo se dohvaca samo ako je wiki_web ukljucen).
    block = klub koji je napustio u zadnje 2 sezone (tamo se ne vraca), back = raniji bivsi klubovi, home = prvi mladi klub koji postoji u igri."""
    import realmoves as _rm
    gc = s.game_date_code()
    gy, gm = gc & 0xffff, (gc >> 16) & 0xff
    now = gy if gm >= 7 else gy - 1
    lim = mlsave.club_layout(s.d)[0]
    names = {}
    tok = {}
    for ci in range(lim):
        nm = seasonstats.club_name(s.d, ci)
        if not nm:
            continue
        names[ci] = nm
        for t in _rm.club_tokens(nm):
            if not t.isdigit():
                tok.setdefault(t, set()).add(ci)
    cache = {}

    def idx_of(nm):
        if not nm:
            return None
        k = _rm.norm(nm)
        if k in cache:
            return cache[k]
        if re.search(r'\b(u-?\d\d|b|ii|iii|reserves?|youth|juniors?|primavera|castilla|atletic|academy)\b', k):
            nm = wiki.norm_club(nm)
        tt = [t for t in _rm.club_tokens(nm) if not t.isdigit()]
        cand = set()
        for t in tt:
            cand |= tok.get(t, set())
        hits = [ci for ci in cand if _rm.club_match(nm, names[ci])]
        r = hits[0] if len(hits) == 1 else None   # dvosmisleno ime (npr. 'Sporting') -> nista
        cache[k] = r
        return r
    out = {}

    def add(pid, kind, ci):
        if ci is None:
            return
        h = out.setdefault(int(pid), {'block': set(), 'back': set(), 'home': None})
        if kind == 'home':
            if h['home'] is None:
                h['home'] = ci
        else:
            h[kind].add(ci)
    cur = {}
    try:
        for c_ in aitransfers.load_clubs(s, rat, POS, None).values():
            for p_ in c_['players']:
                cur[p_['pid']] = c_['idx']
    except Exception:
        pass

    def left(pid, ci, season):
        if ci is None or cur.get(int(pid)) == ci:
            return
        add(pid, 'block' if now - season <= 1 else 'back', ci)
    # 1) ova karijera (AI transferi koje je app upisao)
    try:
        e = auto_view().get(slot) or {}
        for wk, w in (e.get('windows') or {}).items():
            m_ = re.match(r'([SW])(\d{4})', wk)
            if not m_:
                continue
            se = int(m_.group(2)) - (1 if m_.group(1) == 'W' else 0)
            for mv in w.get('plan') or []:
                if mv.get('done') and not mv.get('skip') and mv.get('from') is not None:
                    left(mv['pid'], int(mv['from']), se)
    except Exception as ex:
        print('[past] career:', ex)
    # 2) stvarni transferi 2025/26 (prije karijere)
    try:
        for pid, v in real_moves(slot).items():
            y, mo = int(v['date'][:4]), int(v['date'][5:7])
            left(pid, idx_of(v.get('frm')), y if mo >= 7 else y - 1)
    except Exception as ex:
        print('[past] real:', ex)
    # 3) karijera s Wikipedije (kes)
    try:
        for fn in os.listdir(WIKI_DIR):
            if not fn.endswith('.json'):
                continue
            try:
                pid = int(fn[:-5])
                c = json.load(open(os.path.join(WIKI_DIR, fn), encoding='utf-8'))
            except Exception:
                continue
            car = c.get('career') or []
            if not c.get('ok') or not car:
                continue
            for x in car:
                if x.get('youth'):
                    ci = idx_of(x.get('club'))
                    if ci is not None:
                        add(pid, 'home', ci)
                        break
            for x in car:
                if x.get('youth') or x.get('loan'):
                    continue
                m_ = re.match(r'\s*(\d{4})\s*[–-]\s*(\d{4})', x.get('years') or '')
                if m_:
                    left(pid, idx_of(x.get('club')), int(m_.group(2)))
    except Exception as ex:
        print('[past] wiki:', ex)
    for pid, h in out.items():   # maticni klub u kojem igrac upravo igra nije 'povratak'
        if h['home'] is not None and cur.get(pid) == h['home']:
            h['home'] = None
        h['back'] -= h['block']
    return out


def ai_plan(slot, scale=1.0, seed=1, bmod=None, window='S', memory=None, v2=True):
    d = slot_folder(slot)
    s = mlwrite.Save(d)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    live, _ = read_dump()

    def val_of(pid, ovr, age):
        mv = ((live or {}).get(pid) or {}).get('mv')
        return int(mv) if mv else negotiate.estimate_value(ovr or 50, age or 25)
    wages = s.player_wages()

    def wage_of(pid):
        return wages.get(pid, 0)
    try:
        listed = ai_listings(slot, s)
    except Exception:
        listed = None
    _prot = set(s.loaned_pids())
    if CFG.get('settled_rule', True):   # pc307: tek dovedeni igraci ne odlaze odmah
        try:
            _set = settled_protect(slot, s, seed)
            _prot |= _set
            print('[settled] %d players protected' % len(_set))
        except Exception as ex:
            print('[settled]', ex)
    if v2:
        try:
            owners = owner_groups(s)
        except Exception as ex:
            print('[owners]', ex)
            owners = {}
        reg_ = None
        if CFG.get('reg_rules', True) and live:
            try:
                reg_ = dict(tid=club_tids(slot), nat={p_: v_.get('nat') for p_, v_ in live.items()}, new=s.moved_this_window())
            except Exception as ex:
                print('[reg] ai:', ex)
        try:
            inj_, _src = world_injuries()
        except Exception as ex:
            print('[inj] ai:', ex)
            inj_ = {}
        try:
            past_ = transfer_past(slot, s)
        except Exception as ex:
            print('[past] ai:', ex)
            past_ = {}
        moves, stats = aitransfers.plan_v2(s, rat, POS, NAMES, my, seed=seed, scale=scale, protect_pids=_prot, val_of=val_of, wage_of=wage_of, reg=reg_,
                                           listed=listed, bmod=bmod, window=window, memory=memory, owners=owners, inj=inj_, past=past_)
    else:
        moves, stats = aitransfers.plan(s, rat, POS, NAMES, my, seed=seed, scale=scale, protect_pids=_prot, val_of=val_of, wage_of=wage_of, listed=listed, bmod=bmod)
    return dict(moves=moves, stats=stats, my_idx=my)


OWNERS_FILE = os.path.join(HERE, 'data', 'owners.json')
_OWN_CACHE = {}


def _norm_club(n):
    import re
    n = unicodedata_ascii(n or '').lower()
    n = re.sub(r'[^a-z0-9 ]', ' ', n)
    drop = {'fc', 'afc', 'cf', 'sc', 'ac', 'ssc', 'as', 'ss', 'rc', 'cd', 'ca', 'sv', 'vfl', 'vfb', 'tsg', 'fk', 'sk', 'nk', 'hnk', 'club', 'de', 'futbol', 'football', 'calcio', 'the'}
    return ' '.join(w for w in n.split() if w not in drop)


def owner_groups(s):
    """Vlasnicke grupe iz data/owners.json -> {indeks kluba: ime grupe}. Imena se usporedjuju bez FC/AFC/kvacica."""
    try:
        st = os.stat(OWNERS_FILE)
        key = (st.st_mtime, len(s.d))
    except OSError:
        return {}
    if _OWN_CACHE.get('key') == key:
        return dict(_OWN_CACHE['map'])
    cfg = json.load(open(OWNERS_FILE, encoding='utf-8'))
    names = {}
    for i in range(mlsave.club_layout(s.d)[0]):   # pc258: svi klubovi (60 MB)
        try:
            nm = aitransfers._club_name(s.d, i)
        except Exception:
            continue
        if nm:
            names.setdefault(_norm_club(nm), i)
    out = {}
    for g in cfg.get('groups', []):
        for cn in g.get('clubs', []):
            k = _norm_club(cn)
            i = names.get(k)
            if i is None:
                hit = [v for nk, v in names.items() if nk.startswith(k + ' ') or (len(nk.split()) >= 2 and k.startswith(nk + ' '))]
                i = hit[0] if len(hit) == 1 else None
            if i is not None:
                out[i] = g['name']
    _OWN_CACHE.update(key=key, map=out)
    return dict(out)


def ai_moves(body):
    """AI->AI transferi u savu: body {slot, moves:[{pid, to}]} (to = indeks kluba kupca)."""
    slot = body['slot']
    moves = body['moves']
    if game_blocks():
        raise RuntimeError('The game is running. Go to the main menu and confirm it in the app, or close the game (otherwise it overwrites the save).')
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s_ai' % (slot, ts))
            shutil.copy2(src, backup)
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        res = s.ai_apply([(int(m['pid']), int(m['to']), int(m['from'])) if m.get('from') is not None else (int(m['pid']), int(m['to'])) for m in moves], POS, ovr_of=lambda q: rat(q)[0])
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        PCACHE.clear()
        bad = verify_moves(new_dec, moves, src_dec)
        if bad:
            raise RuntimeError('post-write check failed: %s' % bad[:5])
        if len(res) > 6:
            res = ['%d transfera' % len(res)]
        if DEV:
            return dict(ok=True, message='DEV: ' + '; '.join(res))
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        return dict(ok=True, message='; '.join(res) + '. Backup: ' + backup, backup=backup)


AUTO_FILE = os.path.join(HERE, 'autotransfer.json')
AUTO_LOCK = threading.Lock()
LAST_XI = set()   # igraci koje je zadnji upis odmah ubacio u prvih 11 kluba kupca


def auto_load():
    try:
        with _JDUMP_LOCK:
            with open(AUTO_FILE, encoding='utf-8') as fh:
                return json.load(fh)
    except Exception:
        return {}


_AV = {}


def auto_view():
    """pc260: samo za CITANJE (ne mijenjati rezultat!): autotransfer.json zna imati 10+ MB, a pogledi su ga parsirali kod
    svakog poziva (vijesti, povijest, status, price). Kesirano po (mtime, velicina); auto_save/auto_load ostaju isti."""
    try:
        st_ = os.stat(AUTO_FILE)
        key = (st_.st_mtime_ns, st_.st_size)
    except Exception:
        return {}
    if _AV.get('k') == key:
        return _AV['v']
    v = auto_load()
    _AV['k'], _AV['v'] = key, v
    return v


def auto_save(st):
    # One atomic replacement of the final file; readers share the same lock.
    # Keep a complete uncommitted temp on failure so the ledger is recoverable.
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(AUTO_FILE) + '.', suffix='.tmp',
                               dir=os.path.dirname(os.path.abspath(AUTO_FILE)))
    ready = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        ready = True
        with _JDUMP_LOCK:
            for attempt in range(20):
                try:
                    os.replace(tmp, AUTO_FILE)
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.05)
    finally:
        if not ready and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _write_slot_moves(slot, moves, tag='ai'):
    """Zajednicka jezgra: backup, dekriptiraj, primijeni (preskace neispravne), provjeri, enkriptiraj, upisi.
    Vraca (primijenjeni, preskoceni, backup)."""
    pes17_readonly(slot)
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
            backup = None
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s_%s' % (slot, ts, tag))
            shutil.copy2(src, backup)
            if tag == 'auto':
                olds = sorted(f for f in os.listdir(os.path.join(work, 'backup')) if f.startswith(slot + '_') and f.endswith('_auto'))
                for f in olds[:-8]:
                    try:
                        os.remove(os.path.join(work, 'backup', f))
                    except OSError:
                        pass
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        tup = [(int(m['pid']), int(m['to']), int(m['from'])) for m in moves]
        s.ai_apply(tup, POS, skip_errors=True, ovr_of=lambda q: rat(q)[0])
        skipped = dict(s.ai_skipped)
        LAST_XI.clear()
        LAST_XI.update(getattr(s, 'ai_xi', set()))
        done = [m for m in moves if int(m['pid']) not in skipped]
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        PCACHE.clear()
        bad = verify_moves(new_dec, done, src_dec)
        if bad:
            raise RuntimeError('post-write check failed: %s' % bad[:5])
        if not done:
            return done, skipped, backup
        if DEV:
            shutil.copyfile(os.path.join(new_dec, 'data.dat'), os.path.join(DEV, 'data.dat'))
            return done, skipped, backup
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        return done, skipped, backup


WIN_LEN = {'S': 62, 'W': 31}


def _prune_windows(e, wkey):
    """pc260: zatvoreni rokovi se vise nikad ne izvrsavaju (obradjuje se samo tekuci kljuc); svi citatelji proslih rokova
    (vijesti, povijest, sazetak, pre_window, _window_memory) gledaju samo izvrsene poteze. Neizvrseni (~70 %) se brisu,
    inace autotransfer.json raste ~1 MB po roku po karijeri i cijeli se prepisuje kod svakog spremanja."""
    for k, w in list((e.get('windows') or {}).items()):
        if k == wkey or not isinstance(w, dict) or w.get('pruned'):
            continue
        w['total0'] = len(w.get('plan') or [])
        w['plan'] = [m for m in w.get('plan') or [] if m.get('done') and not m.get('skip')]
        w['pruned'] = True


def win_state(code):
    """(kljuc prozora, indeks dana u prozoru, stanje) iz koda datuma igre. stanje: 'in' | 'after' (rujan / veljaca) | None."""
    d, m, y = code >> 24, (code >> 16) & 0xff, code & 0xffff
    if m in (7, 8):
        return 'S%d' % y, (m - 7) * 31 + d - 1, 'in'
    if m == 1:
        return 'W%d' % y, d - 1, 'in'
    if m == 9:
        return 'S%d' % y, WIN_LEN['S'], 'after'
    if m == 2:
        return 'W%d' % y, WIN_LEN['W'], 'after'
    return None, 0, None


def _day_weights(L):
    w = [1 + 2.0 * i / max(1, L - 1) for i in range(L)]
    w[-1] *= 6
    return w


def auto_make_plan(slot, wkey, idx, state, base_scale, seed, bmod=None, out_b0=None, memory=None, out_stats=None):
    """Plan za prozor, rasporedjen po danima; ako je prozor poceo, samo preostali dani (razmjerno manje poteza).
    v2: zamjena dolazi tek nakon prodaje koja ju je pokrenula; zadnja dva dana roka su guzva (preplacivanje)."""
    import random
    L = WIN_LEN[wkey[0]]
    w = _day_weights(L)
    w[-1] /= 2.0   # v2: vise poteza (lanci zamjena) -> zadnji dan i dalje guzva, ali ne trecina roka
    start = 0 if state == 'after' else idx
    frac = sum(w[start:]) / sum(w) if state == 'in' else 1.0
    pl = ai_plan(slot, base_scale * frac, seed, bmod=bmod, window=wkey[0], memory=memory)
    if out_b0 is not None:
        out_b0.update({str(k): v for k, v in (pl['stats'].get('budget0') or {}).items()})
    if out_stats is not None:
        out_stats.update({k: v for k, v in pl['stats'].items() if k != 'budget0'})
    rnd = random.Random(seed * 7919 + 13)
    days = list(range(L))
    ww = w[start:] if state == 'in' else w
    dd = days[start:] if state == 'in' else days
    out = []
    day_of = {}
    dropped = set()
    for m in pl['moves']:
        dep = day_of.get(m.get('after')) if m.get('after') else None
        if m.get('after') and int(m['after']) in dropped:
            dropped.add(int(m['pid']))
            continue
        if dep is not None and dep >= L - 2 and rnd.random() < 0.65:
            dropped.add(int(m['pid']))   # prodan zadnji dan: nema vremena za zamjenu (klub uzme mladog iz skole)
            continue
        if dep is not None:
            # zamjena: nekoliko dana nakon prodaje (ili isti dan ako je prodaja na sam zadnji dan)
            dd2 = [d for d in dd if d >= min(dep + 1, L - 1)]
            ww2 = [(1.0 if d - dep <= 10 else 0.3) * (1.6 if d == L - 1 else 1.0) for d in dd2]
            day = rnd.choices(dd2, ww2)[0]
        else:
            day = rnd.choices(dd, ww)[0]
        day_of[m['pid']] = day
        fee = m.get('fee')
        late = day >= L - 2
        if late and fee:
            fee = int(round(fee * rnd.uniform(1.04, 1.25) / 100000.0) * 100000) or fee
        out.append(dict(pid=m['pid'], to=m['to_idx'], **{'from': m['from_idx']}, day=day, name=m['name'], pos=m['pos'], ovr=m['ovr'],
                        from_name=m['from_name'], to_name=m['to_name'], done=False,
                        age=m.get('age'), tier=m.get('tier'), from_tier=m.get('from_tier'), to_rank=m.get('to_rank'), from_rank=m.get('from_rank'),
                        best_here=m.get('best_here'), second_here=m.get('second_here'), short=m.get('short'),
                        to_str=m.get('to_str'), from_str=m.get('from_str'), fee=fee,
                        why=m.get('why'), repl=m.get('repl'), after=m.get('after'), group=m.get('group'), free=m.get('free'), deadline=late or None, ret=m.get('ret')))
    return out


def _window_memory(wins, wkey):
    """Pamcenje trzista iz proslog roka: zelje klubova koje nisu ostvarene i broj dolazaka (za zimu nakon velikog ljeta)."""
    prev = [k for k in wins if k != wkey]
    if not prev:
        return {}
    last = sorted(prev, key=lambda k: (int(k[1:]), k[0] == 'S'))[-1]
    pw = wins[last]
    mem = dict(wish=pw.get('wish') or {})
    prev_in = {}
    for m in pw.get('plan', []):
        if m.get('done') and not m.get('skip'):
            prev_in[str(m['to'])] = prev_in.get(str(m['to']), 0) + 1
    mem['prev_in'] = prev_in
    return mem


def _market_ctx(slot, s):
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    clubs = _tier_clubs(s, my)
    live, _ = read_dump()

    def val_of(pid, ovr, age):
        mv = ((live or {}).get(pid) or {}).get('mv')
        return int(mv) if mv else negotiate.estimate_value(ovr or 50, age or 25)
    mine = []
    for pid in s.my_squad_tags():
        ov, ag = rat(pid)
        mine.append(dict(pid=pid, pos=POS.get(pid, 5), ovr=ov, age=ag))
    top = sorted((p['ovr'] for p in mine if p['ovr']), reverse=True)[:14]
    myd = dict(idx=my, name=(s.team_name(my) if hasattr(s, 'team_name') else ''), strength=(sum(top) / len(top) if top else 70), players=mine)
    try:
        myd['name'] = aitransfers._club_name(s.d, my)
    except Exception:
        pass
    return my, clubs, val_of, myd


def _new_window(slot, s, wins, wkey, idx, state, base, sd):
    """Novi prijelazni rok: stanje klubova (budzeti iz proslih rokova, preuzimanja, krize) -> plan -> sok transfer -> price."""
    my, clubs, val_of, myd = _market_ctx(slot, s)
    prev = [wins[k] for k in sorted(wins, key=lambda k: (int(k[1:]), k[0] == 'S'))]
    try:
        bmod, evs = market.pre_window(prev, clubs, sd, wkey)
    except Exception as ex:
        print('[market] pre_window:', ex)
        bmod, evs = {}, []
    b0, pst = {}, {}
    try:
        mem = _window_memory(wins, wkey)
        mem['new_coach'] = [int(k) for k in ((auto_view().get(slot) or {}).get('coach') or {}).get('new', {})]
    except Exception as ex:
        print('[market] memory:', ex)
        mem = {}
    plan = auto_make_plan(slot, wkey, idx, state, base, sd, bmod=bmod, out_b0=b0, memory=mem, out_stats=pst)
    w = wins[wkey] = dict(seed=sd, plan=plan, applied=0, skipped=0, b0=b0, events=evs, v=pst.get('v', 1), wish=pst.get('wish') or {},
                          stats=dict(why=pst.get('why'), quota=pst.get('quota_total'), clubs=pst.get('clubs')))
    try:
        nl = aitransfers.national_like(s)
        sh = market.shock_move(clubs, plan, sd, wkey, WIN_LEN[wkey[0]], val_of, NAMES, set(s.loaned_pids()) | set(s.my_squad_tags()))
        if sh and int(sh['from']) not in nl and int(sh['to']) not in nl and (state != 'in' or sh['day'] >= idx):
            plan.append(sh)
        w['sagas'] = market.build(plan, clubs, myd, wkey, WIN_LEN[wkey[0]], sd, evs, val_of, NAMES, start=idx if state == 'in' else 0)
    except Exception as ex:
        print('[market] price:', ex)
        w['sagas'] = []
    return w


def _ensure_sagas(slot, s, w, wkey, start):
    """Rok koji je poceo prije ove verzije appa: price samo za njegove nedovrsene poteze (bez promjene budzeta)."""
    if 'sagas' in w:
        return
    try:
        my, clubs, val_of, myd = _market_ctx(slot, s)
        w['sagas'] = market.build(w['plan'], clubs, myd, wkey, WIN_LEN[wkey[0]], w.get('seed', 1), [], val_of, NAMES, start=start)
    except Exception as ex:
        print('[market] price (stari rok):', ex)
        w['sagas'] = []


def _market_effects(slot, s, w, wkey, upto):
    """Posljedice za tebe kad price dosegnu danasnji dan: interes vecih klubova (moze uznemiriti ambicioznog igraca)."""
    squad = set(s.my_squad_tags())
    for g in w.get('sagas') or []:
        if g.get('kind') != 'interest' or g.get('fx'):
            continue
        st = next((x for x in g['stages'] if x['k'] == 'interest'), None)
        if not st or st['day'] > upto:
            continue
        g['fx'] = True
        pid = int(g['pid'])
        if pid not in squad:
            continue
        tr_ = persona.traits(pid)
        upset = tr_['ambition'] >= 0.55 and tr_['loyalty'] < 0.7
        _ev_add(slot, 'interest', pid, to=g['to'], upset=upset)
        if upset:
            reqs = _req_all().get(slot, {})
            if str(pid) not in reqs:
                reqs[str(pid)] = dict(status='open', reason='interest', club=g['to'], mk='', since=_fmt_date(s.game_date_code()), urgent=False)
                _req_save(slot, reqs)


def _scout_pids(slot):
    try:
        e = _sc_get(slot)
    except Exception:
        return {}
    out = {}
    for r in e.get('reports', []):
        for p in r.get('players', []):
            out[int(p['pid'])] = r.get('scout_name', '')
    return out



# ---------------------------------------------------------------- nova karijera u istom slotu
CAREER_FILE = os.path.join(HERE, 'data', 'careers.json')
CAREER_LOCK = threading.Lock()
SLOT_FILES = ('ailists.json', 'events.json', 'growth_state.json', 'loan_seen.json', 'press.json', 'promises.json',
              'requests.json', 'scouting.json', 'tlist.json', 'youth_hist.json',
              'dramas.json', 'talks.json', 'addons.json',   # pc144: i ovi su po slotu (bonusi/sell-on, razgovori, drame) pa idu u arhivu karijere
              # pc261: i ovi su po slotu, a nova karijera u istom slotu ih je nasljedjivala: sell-on novac od prodaja stare karijere,
              # rucni trofeji u Vitrini, 'vec naplacene' utakmice (gate: nova karijera istog datuma ne bi dobila prihod), posudbe na cekanju
              'sellon_ours.json', 'trophies_manual.json', 'gate.json', 'loan_pending.json', 'loan_refunds.json', 'salary_base.json')
SLOT_STORES = ('negotiations.json', 'loan_negotiations.json')


def _career_fp(s):
    try:
        mgr = s.manager()
    except Exception:
        mgr = ''
    fp = dict(club=int((s.club_offset() - getattr(s, 'REC0', mlwrite.REC0)) //
                       getattr(s, 'STRIDE', mlwrite.STRIDE)), mgr=mgr)
    # pc266: isti slot u dvije igre (FL26 i Football Life 2027) = dvije razlicite karijere, i s istim imenom menadzera i
    # istim indeksom kluba. FL26 zapisi ostaju bez kljuca 'game' (stari id-evi karijera se ne mijenjaju).
    g = _game_of(getattr(s, 'folder', '') or '')
    if g != 'fl26':
        fp['game'] = g
    return fp


def _plan_is_stale(s, e):
    """Stari zapis prije careers.json: AI plan je iz druge karijere ako su njegovi 'obavljeni' transferi
    u ovom saveu i dalje u starim klubovima (u pravoj karijeri bi igraci bili u novim)."""
    done = []
    for w in (e or {}).get('windows', {}).values():
        done += [m for m in w.get('plan', []) if m.get('done') and not m.get('skip')]
    if len(done) < 8:
        return False
    want = {int(m['pid']) for m in done}
    where = {}
    n = 0
    d = s.d
    while mlwrite.REC0 + n * mlwrite.STRIDE + mlwrite.STRIDE <= 6000000 and len(where) < len(want):
        o = mlwrite.REC0 + n * mlwrite.STRIDE
        for i in range(40):
            tag, pid = struct.unpack_from('<II', d, o + s.PAIR_OFF + 8 * i)
            if tag & 0xffff == 0xffff:
                break
            if pid in want:
                where[pid] = n
        n += 1
    to = sum(1 for m in done if where.get(int(m['pid'])) == int(m['to']))
    fr = sum(1 for m in done if where.get(int(m['pid'])) == int(m['from']))
    return to * 4 < len(done) and fr * 2 > len(done)


def _arch_path(slot, arch):
    """pc266: jedinstveno ime arhive (dva prelaska u istoj sekundi su prije pisala u istu datoteku i jedna karijera se gubila).
    Vrijeme ide u arch['ts'] da pripadni <slot>_auto_<ts>.json ima isti zig."""
    ad = os.path.join(HERE, 'data', 'archive')
    os.makedirs(ad, exist_ok=True)
    t0 = time.time()
    for i in range(3600):
        ts = time.strftime('%Y%m%d_%H%M%S', time.localtime(t0 + i))
        p_ = os.path.join(ad, '%s_%s.json' % (slot, ts))
        if not os.path.exists(p_) and not os.path.exists(os.path.join(ad, '%s_auto_%s.json' % (slot, ts))):
            arch['ts'] = ts
            return p_
    arch['ts'] = time.strftime('%Y%m%d_%H%M%S')
    return os.path.join(ad, '%s_%s.json' % (slot, arch['ts']))


def _archive_slot(slot, reason):
    """Podaci appa za slot (iz prijasnje karijere) idu u data/archive/<slot>_<vrijeme>.json i brisu se iz aktivnih datoteka."""
    arch = dict(slot=slot, reason=reason, at=time.strftime('%Y-%m-%d %H:%M:%S'), files={})
    dd = os.path.join(HERE, 'data')
    for f in SLOT_FILES:
        fp_ = os.path.join(dd, f)
        try:
            a = json.load(open(fp_, encoding='utf-8'))
        except Exception:
            continue
        if isinstance(a, dict) and slot in a:
            arch['files'][f] = a.pop(slot)
            _jdump(a, fp_, ensure_ascii=False)
    pre = slot + ':'
    for f, g in (('negotiations.json', 'NEG'), ('loan_negotiations.json', 'LNEG')):
        fp_ = os.path.join(dd, f)
        try:
            a = json.load(open(fp_, encoding='utf-8'))
        except Exception:
            a = {}
        ks = [k for k in a if k.startswith(pre)]
        if ks:
            arch['files'][f] = {k: a.pop(k) for k in ks}
            _jdump(a, fp_, ensure_ascii=False, indent=1)
        st_ = globals().get(g)
        if st_ is not None:
            for k in [k for k in st_.d if k.startswith(pre)]:
                st_.d.pop(k, None)
    # pc261: transferi same igre (snimka klub-po-igracu) su po slotu u data/xfer: nova karijera bi se usporedila sa starom
    xf = os.path.join(dd, 'xfer', re.sub(r'[^A-Za-z0-9_.-]', '_', slot) + '.json')
    if os.path.exists(xf):
        try:
            arch['xfer'] = json.load(open(xf, encoding='utf-8'))
        except Exception:
            pass
        try:
            os.remove(xf)
        except Exception as ex:
            print('[career] xfer:', ex)
    os.makedirs(os.path.join(dd, 'archive'), exist_ok=True)
    _jdump(arch, _arch_path(slot, arch), ensure_ascii=False)
    return arch



def _events_contradict(slot, s):
    """Dogadaji slota iz druge karijere? Jak znak: prodani igrac je i dalje u mojoj momcadi -> sve je staro (True).
    pc169: potpisani kojeg nema u momcadi NIJE dovoljan za brisanje svega (Como: Palestra je bio star, a prodaje
    Mazzitellija i Addaija prave) - takvi se micu pojedinacno (_drop_stale_signed)."""
    try:
        L = json.load(open(EV_FILE, encoding='utf-8')).get(slot) or []
    except Exception:
        return False
    if not L:
        return False
    sq = set(p for p in s.squad_ids() if p)
    if not sq:
        return False
    for i, e in enumerate(L):
        pid = e.get('pid')
        if pid and e.get('kind') == 'sold' and pid in sq and 'signed' not in [x.get('kind') for x in L[i + 1:] if x.get('pid') == pid]:
            return True
    return False


def _drop_stale_signed(slot, s):
    """Potpisani (dolazak bio prije danasnjeg dana) kojeg nema u momcadi, a nije kasnije otisao: zapis iz druge karijere -> u arhivu."""
    try:
        a = json.load(open(EV_FILE, encoding='utf-8'))
    except Exception:
        return 0
    L = a.get(slot) or []
    sq = set(p for p in s.squad_ids() if p)
    if not L or not sq:
        return 0
    y, m, d = _date_tuple(s.game_date_code())
    today = y * 10000 + m * 100 + d
    drop = []
    for i, e in enumerate(L):
        pid = e.get('pid')
        if not pid or e.get('kind') != 'signed' or pid in sq or _when_num(e.get('when')) >= today:
            continue
        later = {x.get('kind') for x in L[i + 1:] if x.get('pid') == pid}
        if later & {'sold', 'loaned', 'loan_failed', 'retired', 'star_left_free', 'req_release'}:
            continue
        drop.append(i)
    if not drop:
        return 0
    old = [L[i] for i in drop]
    a[slot] = [e for i, e in enumerate(L) if i not in set(drop)]
    _jdump(a, EV_FILE, ensure_ascii=False, indent=1)
    dd = os.path.join(HERE, 'data')
    os.makedirs(os.path.join(dd, 'archive'), exist_ok=True)
    _jdump(dict(slot=slot, reason='signed players not in the squad (stale)', at=time.strftime('%Y-%m-%d %H:%M:%S'), files={'events.json': old}), os.path.join(dd, 'archive', '%s_ev_%s.json' % (slot, time.strftime('%Y%m%d_%H%M%S'))), ensure_ascii=False)
    return len(drop)


def _archive_events_only(slot, reason):
    dd = os.path.join(HERE, 'data')
    a = json.load(open(EV_FILE, encoding='utf-8'))
    old = a.get(slot) or []
    a[slot] = []
    _jdump(a, EV_FILE, ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(dd, 'archive'), exist_ok=True)
    _jdump(dict(slot=slot, reason=reason, at=time.strftime('%Y-%m-%d %H:%M:%S'), files={'events.json': old}), os.path.join(dd, 'archive', '%s_ev_%s.json' % (slot, time.strftime('%Y%m%d_%H%M%S'))), ensure_ascii=False)


def _archive_future(slot, s):
    """Stari zapis bez otiska karijere: dogadaji i konferencije s datumom u igri NAKON danasnjeg ne mogu biti iz ove karijere."""
    c = s.game_date_code()
    today = (c & 0xffff, (c >> 16) & 0xff, c >> 24)

    def ymd(w):
        m = re.match(r'\s*(\d{1,2})[./](\d{1,2})[./](\d{4})', str(w or ''))
        return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    arch = dict(slot=slot, reason='legacy: entries dated after %d.%d.%d' % (today[2], today[1], today[0]), at=time.strftime('%Y-%m-%d %H:%M:%S'), files={})
    dd = os.path.join(HERE, 'data')
    fp_ = os.path.join(dd, 'events.json')
    try:
        a = json.load(open(fp_, encoding='utf-8'))
        L = a.get(slot) or []
        old = [x for x in L if (ymd(x.get('when')) or (0,)) > today]
        if old:
            a[slot] = [x for x in L if x not in old]
            arch['files']['events.json'] = old
            _jdump(a, fp_, ensure_ascii=False)
    except Exception:
        pass
    fp_ = os.path.join(dd, 'press.json')
    try:
        a = json.load(open(fp_, encoding='utf-8'))
        P = a.get(slot) or {}
        H = P.get('hist') or []
        old = [x for x in H if (ymd(x.get('when')) or (0,)) > today]
        if old:
            P['hist'] = [x for x in H if x not in old]
            for x in old:
                (P.get('done') or {}).pop(x.get('id'), None)
            arch['files']['press.json'] = old
            _jdump(a, fp_, ensure_ascii=False, indent=1)
    except Exception:
        pass
    os.makedirs(os.path.join(dd, 'archive'), exist_ok=True)
    _jdump(arch, _arch_path(slot, arch), ensure_ascii=False)
    return arch

def _reset_auto_entry(e):
    import copy as _copy
    # duboka kopija: ispod se e['tac'] prazni na istom objektu (prije je arhiva zbog toga ostajala bez AI taktika)
    arch = _copy.deepcopy(dict(windows=e.get('windows'), log=e.get('log'), tac=e.get('tac'), seed=e.get('seed'), coach=e.get('coach'), lu=e.get('lu')))
    e['windows'] = {}
    e['log'] = []
    e.pop('coach', None)
    e.pop('lu', None)
    e.pop('seed', None)
    e.pop('last_mtime', None)
    t = e.get('tac')
    if isinstance(t, dict):
        t['clubs'] = {}
        t['log'] = []
        t.pop('mtime', None)
    e['status'] = 'new career in this slot: the AI transfer plan was reset'
    e['fresh'] = True   # pc413: oznaka ne ovisi o statusu (AI rok ga prepise prije nego sto app ukljuci taktike)
    e.pop('user_set', None)
    return arch


def _time_travel(slot, s, rec, gd):
    """pc354: save iste karijere s ranijim datumom: buduci dogadjaji u arhivu, AI rokovi koji jos nisu poceli se ponistavaju."""
    y, m, d = _date_tuple(gd)
    ds = '%04d-%02d-%02d' % (y, m, d)
    arch = _archive_future(slot, s)
    n_w = 0
    try:
        n_w = world(slot, s).prune_after(ds)
    except Exception as ex:
        print('[career] world prune:', ex)
    season = y if m >= 7 else y - 1
    n_a = 0
    try:
        with AUTO_LOCK:
            st = auto_load()
            e = st.get(slot) or {}
            W = e.get('windows') or {}
            for k in list(W):
                mm = re.match(r'([SW])(\d{4})', k)
                if mm and int(mm.group(2)) - (1 if mm.group(1) == 'W' else 0) > season:
                    W.pop(k)
                    n_a += 1
                    continue
                for mv in (W.get(k) or {}).get('plan') or []:   # potezi iz 'buducnosti' istog roka: opet neodradjeni
                    w_ = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', str(mv.get('when') or ''))
                    if mv.get('done') and w_ and (int(w_.group(3)), int(w_.group(2)), int(w_.group(1))) > (y, m, d):
                        mv['done'] = False
                        mv.pop('when', None)
                        n_a += 1
            lu = e.get('lu') or {}
            lu.pop('emerg', None)
            if n_a:
                auto_save(st)
    except Exception as ex:
        print('[career] auto rewind:', ex)
    # pc407: pregovori i "drame" ugovora (igrac odbija produljenje) iz 'buducnosti' se brisu: nova karijera istog kluba u istom
    # slotu (ili stariji save) inace nosi stari neuspjeli pregovor i igrac se ne moze ponovno nagovoriti (korisnik s Reddita, 2.11.)
    n_n = 0
    try:
        def _later(code_or_str):
            if isinstance(code_or_str, int):
                return _date_tuple(code_or_str) > (y, m, d)
            mm_ = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', str(code_or_str or ''))
            return bool(mm_) and (int(mm_.group(3)), int(mm_.group(2)), int(mm_.group(1))) > (y, m, d)
        A_ = _drama_all()
        D_ = A_.get(slot) or {}
        for k_ in list(D_):
            e_ = D_[k_] or {}
            if _later(e_.get('since')) or (e_.get('season') is not None and int(e_['season']) > season):
                D_.pop(k_)
                n_n += 1
        if n_n:
            _drama_save(A_)
        for st_ in (_neg_store(), _lneg_store()):
            for pid_, r_ in list(st_.for_slot(slot).items()):
                if _later(r_.get('date')) or _later(r_.get('started')):
                    st_.drop(slot, pid_)
                    n_n += 1
    except Exception as ex:
        print('[career] neg rewind:', ex)
    PCACHE.clear()
    _GL.pop('compsv', None)
    if n_n:
        print('[career] %s: %d pregovora/drama iz buducnosti obrisano' % (slot, n_n))
    print('[career] %s: datum unatrag (%s -> %s): arhivirano %d vijesti/konferencija, %d dogadjaja svijeta, %d AI poteza' % (
        slot, _fmt_date(rec['gd']), _fmt_date(gd), sum(len(v) for v in (arch.get('files') or {}).values()), n_w, n_a))


def career_guard(slot, s, st=None):
    """Slot je dobio novu karijeru (drugi klub ili menadzer)? Onda stari AI plan, pregovori, dogadaji, novine... ne vrijede.
    st = vec ucitan autotransfer.json (pozivatelj drzi AUTO_LOCK), inace se ucita ovdje. Vraca True ako je resetirano."""
    if DEV or not slot.startswith('ML0'):
        return False
    with CAREER_LOCK:
        try:
            C = json.load(open(CAREER_FILE, encoding='utf-8'))
        except Exception:
            C = {}
        fp = _career_fp(s)
        rec = C.get(slot)
        gd = s.game_date_code()
        if rec and rec.get('club') == fp['club'] and rec.get('mgr') == fp['mgr'] and rec.get('game') == fp.get('game'):
            if not rec.get('evchk'):
                # pc165: jednokratna provjera za vec postojece zapise (stari 'legacy' put je ostavio dogadaje stare karijere istog datuma)
                rec['evchk'] = 1
                try:
                    if _events_contradict(slot, s):
                        _archive_events_only(slot, 'events contradict save (stale career)')
                        print('[career] %s: dogadaji iz druge karijere arhivirani' % slot)
                    else:
                        _drop_stale_signed(slot, s)
                except Exception as ex:
                    print('[career] evchk:', ex)
                _jdump(C, CAREER_FILE, ensure_ascii=False, indent=1)
            if rec.get('gd') and rec['gd'] != gd and _cmp_date(gd, _add_days(rec['gd'], -2)) < 0:
                # pc354: datum u igri je otisao unatrag (ucitan stariji save ili nova karijera istog kluba i menadzera):
                # sve iz 'buducnosti' (vijesti, konferencije, knjiga svijeta, AI rokovi) se arhivira, da svijet ne ostane iz drugog savea
                try:
                    _time_travel(slot, s, rec, gd)
                except Exception as ex:
                    print('[career] time travel:', ex)
            if rec.get('gd') != gd:
                rec['gd'] = gd
                _jdump(C, CAREER_FILE, ensure_ascii=False, indent=1)
            return False
        if rec and rec.get('mgr') and rec.get('mgr') == fp['mgr'] and rec.get('club') != fp['club'] and rec.get('game') == fp.get('game') and (not rec.get('gd') or _job_change_ok(rec['gd'], gd)):
            # isti menadzer, drugi klub, datum ide dalje: otkaz/novi posao u ISTOJ karijeri (igra te prebaci nakon prihvacene ponude)
            _job_change(slot, s, C, rec, fp, gd)
            return False
        own = st is None
        if own:
            AUTO_LOCK.acquire()
            st = auto_load()
        try:
            e = st.get(slot) or {}
            legacy = not rec
            changed = bool(rec) or _plan_is_stale(s, e)
            if changed:
                # poznat otisak: sve je iz stare karijere. Bez otiska (stari zapis): miče se samo ono sto sigurno nije iz ove
                # karijere (AI plan, dogadaji i konferencije s datumom iza danasnjeg datuma u igri), ostalo ostaje.
                arch = None
                if legacy and _events_contradict(slot, s):
                    legacy = False   # pc165: prodani igrac je i dalje u momcadi / potpisanog nema = dogadaji su iz druge karijere (Palestra)
                    arch = _archive_slot(slot, 'new career (was %s, now %s)' % ({'legacy': 'events contradict save'}, fp))
                if arch is None:
                    arch = _archive_future(slot, s) if legacy else _archive_slot(slot, 'new career (was %s, now %s)' % (rec, fp))
                    if legacy:
                        try:
                            _drop_stale_signed(slot, s)
                        except Exception as ex:
                            print('[career] stale signed:', ex)
                if e:
                    arch['autotransfer'] = _reset_auto_entry(e)
                    _jdump(arch, os.path.join(HERE, 'data', 'archive', '%s_auto_%s.json' % (slot, arch.get('ts') or time.strftime('%Y%m%d_%H%M%S'))), ensure_ascii=False)
                    if own:
                        auto_save(st)
                PCACHE.clear()
                print('[career] %s: nova karijera, stari podaci arhivirani' % slot)
        finally:
            if own:
                AUTO_LOCK.release()
        back = None
        try:
            back = _career_return(slot, fp, st if not own else None)
        except Exception as ex:
            print('[career] povratak:', ex)
        if back:
            C[slot] = dict(back, seen=time.strftime('%Y-%m-%d %H:%M'), gd=gd)
            print('[career] %s: vratila se ranija karijera (%s), podaci vraceni iz arhive' % (slot, back.get('id')))
        else:
            C[slot] = dict(fp, seen=time.strftime('%Y-%m-%d %H:%M'), id=_career_slug(slot, fp))
        _jdump(C, CAREER_FILE, ensure_ascii=False, indent=1)
        return changed


def _career_return(slot, fp, st=None):
    """Isti slot opet ima karijeru koja je ranije arhivirana (npr. promijenjen folder savea: FL26 <-> vanilla, ili drugi save u istom slotu).
    Najnovija arhiva te karijere (isti klub i menadzer) se vraca u aktivne datoteke. -> stari zapis karijere (id, poslovi) ili None."""
    import ast
    ad = os.path.join(HERE, 'data', 'archive')
    if not os.path.isdir(ad):
        return None
    cands = []
    for f in os.listdir(ad):
        m = re.match(r'^(ML[0-9A-F]+)_(\d{8}_\d{6})\.json$', f)
        if not m or m.group(1) != slot:
            continue
        try:
            arch = json.load(open(os.path.join(ad, f), encoding='utf-8'))
            r = re.match(r'new career \(was (\{.*?\}), now (\{.*?\})\)$', arch.get('reason') or '')
            if not r or arch.get('returned'):
                continue
            was = ast.literal_eval(r.group(1))
        except Exception:
            continue
        if was.get('club') == fp.get('club') and (was.get('mgr') or '') == (fp.get('mgr') or '') and was.get('game') == fp.get('game'):
            cands.append((m.group(2), f, arch, was))
    if not cands:
        return None
    ts, f, arch, was = max(cands)
    dd = os.path.join(HERE, 'data')
    for fn, val in (arch.get('files') or {}).items():
        fp_ = os.path.join(dd, fn)
        try:
            a = json.load(open(fp_, encoding='utf-8'))
        except Exception:
            a = {}
        if fn in ('negotiations.json', 'loan_negotiations.json'):
            a.update(val)
            _jdump(a, fp_, ensure_ascii=False, indent=1)
            g = globals().get('NEG' if fn == 'negotiations.json' else 'LNEG')
            if g is not None:
                try:
                    g.d.update(val)
                except Exception:
                    pass
        else:
            a[slot] = val
            _jdump(a, fp_, ensure_ascii=False)
    if isinstance(arch.get('xfer'), dict):   # pc261
        try:
            os.makedirs(os.path.join(dd, 'xfer'), exist_ok=True)
            _jdump(arch['xfer'], os.path.join(dd, 'xfer', re.sub(r'[^A-Za-z0-9_.-]', '_', slot) + '.json'), ensure_ascii=False)
        except Exception as ex:
            print('[career] xfer povratak:', ex)
    af = os.path.join(ad, '%s_auto_%s.json' % (slot, ts))
    if os.path.exists(af):
        aa = json.load(open(af, encoding='utf-8')).get('autotransfer') or {}
        st_ = st if st is not None else auto_load()
        e = st_.setdefault(slot, {})
        for k in ('windows', 'log', 'seed'):
            if aa.get(k) is not None:
                e[k] = aa[k]
        if isinstance(aa.get('tac'), dict) and (aa['tac'].get('clubs') or not isinstance(e.get('tac'), dict)):
            e['tac'] = aa['tac']
        for k in ('coach', 'lu'):
            if isinstance(aa.get(k), dict):
                e[k] = aa[k]
        e.pop('last_mtime', None)
        if st is None:
            auto_save(st_)
    arch['returned'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _jdump(arch, os.path.join(ad, f), ensure_ascii=False)
    PCACHE.clear()
    return was



def _job_change_ok(old_gd, new_gd):
    import datetime
    try:
        a = datetime.date(*_date_tuple(old_gd))
        b = datetime.date(*_date_tuple(new_gd))
        return 0 <= (b - a).days <= 400
    except Exception:
        return True


def _job_change(slot, s, C, rec, fp, gd):
    """Novi posao u istoj karijeri: otisak dobiva novi klub, id karijere (knjiga svijeta, pregovori) ostaje isti."""
    old_club = rec.get('club')
    try:
        old_name = aitransfers._club_name(s.d, int(old_club)) if old_club is not None else ''
    except Exception:
        old_name = ''
    new_name = _my_club_name(s)
    jobs = rec.setdefault('jobs', [])
    jobs.append(dict(club=old_club, name=old_name, until=_fmt_date(gd)))
    rec.update(club=fp['club'], gd=gd, seen=time.strftime('%Y-%m-%d %H:%M'), vacancy=old_club)
    rec.setdefault('id', _career_slug(slot, dict(club=old_club, mgr=fp['mgr'])))
    C[slot] = rec
    _jdump(C, CAREER_FILE, ensure_ascii=False, indent=1)
    try:
        d_ = worldlib.date_str(gd)
        world(slot, s).add('my_job', d_, 'job:%s:%s' % (fp['club'], d_), clubs=[old_name, new_name], frm=old_name, to=new_name, mgr=fp['mgr'])
    except Exception as ex:
        print('[career] ledger:', ex)
    PCACHE.clear()
    print('[career] %s: %s je preuzeo %s (prije %s), ista karijera' % (slot, fp['mgr'], new_name, old_name))


def _career_job_restore():
    """Jednokratno: arhive koje je app napravio jer je otkaz + novi klub (isti menadzer) zamijenio za novu karijeru se vracaju."""
    import ast
    ad = os.path.join(HERE, 'data', 'archive')
    if not os.path.isdir(ad):
        return
    mk = os.path.join(ad, 'restored.json')
    try:
        done = json.load(open(mk, encoding='utf-8'))
    except Exception:
        done = []
    for f in sorted(os.listdir(ad)):
        m = re.match(r'^(ML[0-9A-F]+)_(\d{8}_\d{6})\.json$', f)
        if not m or f in done:
            continue
        slot, ts = m.group(1), m.group(2)
        try:
            arch = json.load(open(os.path.join(ad, f), encoding='utf-8'))
            r = re.match(r'new career \(was (\{.*?\}), now (\{.*?\})\)$', arch.get('reason') or '')
            if not r:
                continue
            was, now = ast.literal_eval(r.group(1)), ast.literal_eval(r.group(2))
            if not (was.get('mgr') and was.get('mgr') == now.get('mgr') and was.get('club') != now.get('club')):
                continue
            dd = os.path.join(HERE, 'data')
            for fn, val in (arch.get('files') or {}).items():
                fp_ = os.path.join(dd, fn)
                try:
                    a = json.load(open(fp_, encoding='utf-8'))
                except Exception:
                    a = {}
                if fn in ('negotiations.json', 'loan_negotiations.json'):
                    for k, v in val.items():
                        a.setdefault(k, v)
                else:
                    cur = a.get(slot)
                    if isinstance(cur, list) and isinstance(val, list):
                        a[slot] = val + [x for x in cur if x not in val]
                    elif isinstance(cur, dict) and isinstance(val, dict):
                        v2 = dict(val)
                        v2.update(cur)
                        a[slot] = v2
                    else:
                        a[slot] = val
                _jdump(a, fp_, ensure_ascii=False)
            af = os.path.join(ad, '%s_auto_%s.json' % (slot, ts))
            if os.path.exists(af):
                aa = json.load(open(af, encoding='utf-8')).get('autotransfer') or {}
                with AUTO_LOCK:
                    st = auto_load()
                    e = st.setdefault(slot, {})
                    if aa.get('windows'):
                        w = e.get('windows') or {}
                        for k, v in aa['windows'].items():
                            w.setdefault(k, v)
                        e['windows'] = w
                    e['log'] = (aa.get('log') or []) + (e.get('log') or [])
                    if aa.get('seed') and not e.get('seed'):
                        e['seed'] = aa['seed']
                    if isinstance(aa.get('tac'), dict) and isinstance(e.get('tac'), dict):
                        e['tac']['clubs'] = dict(aa['tac'].get('clubs') or {}, **(e['tac'].get('clubs') or {}))
                        e['tac']['log'] = (aa['tac'].get('log') or []) + (e['tac'].get('log') or [])
                    auto_save(st)
            # otisak: ista karijera (stari id), novi klub
            try:
                C = json.load(open(CAREER_FILE, encoding='utf-8'))
            except Exception:
                C = {}
            rec = C.get(slot) or {}
            rec.update(club=now.get('club'), mgr=now.get('mgr'))
            rec['id'] = was.get('id') or _career_slug(slot, was)
            rec.setdefault('jobs', []).append(dict(club=was.get('club'), until=rec.get('seen')))
            rec['vacancy'] = was.get('club')   # klub koji si napustio dobiva novog trenera (ne 'parkiranog')
            C[slot] = rec
            _jdump(C, CAREER_FILE, ensure_ascii=False, indent=1)
            done.append(f)
            _jdump(done, mk)
            print('[career] vraceno iz arhive (novi posao, ista karijera):', f)
        except Exception as ex:
            print('[career] restore', f, ex)


# ---------------------------------------------------------------- knjiga svijeta (world ledger)
def _career_slug(slot, fp):
    mg = re.sub(r'[^A-Za-z0-9]+', '', unicodedata_ascii(fp.get('mgr') or ''))[:24] or 'mgr'
    return '%s_%s_%s' % (slot, fp.get('club'), mg) + ('_' + fp['game'] if fp.get('game') else '')


def unicodedata_ascii(t):
    import unicodedata
    return unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode('ascii')


def _career_id(slot, s=None):
    if DEV:
        return 'DEV'
    try:
        C = json.load(open(CAREER_FILE, encoding='utf-8'))
    except Exception:
        C = {}
    rec = C.get(slot)
    if rec and rec.get('id'):
        return rec['id']
    if not rec and s is not None:
        rec = _career_fp(s)
    if not rec:
        return re.sub(r'[^A-Za-z0-9]', '', slot) or 'slot'
    return _career_slug(slot, rec)


def world(slot, s=None):
    L = worldlib.Ledger(os.path.join(HERE, 'data', 'world'), _career_id(slot, s))
    if not L.meta().get('backfill'):
        try:
            _world_backfill(slot, L, s)
        except Exception as ex:
            print('[world] backfill:', ex)
    return L


def _my_club_name(s):
    if getattr(s, 'pes17', False):
        return s.team_name()
    try:
        return seasonstats.club_name(s.d, (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE)
    except Exception:
        return ''


def _world_ev_item(kind, pid, d, kw, myname):
    """Dogadjaj mog kluba (events.json oblik) -> stavka knjige svijeta."""
    kw = dict(kw or {})
    frm, to = None, None
    if kind == 'signed':
        frm, to = kw.get('frm') or None, myname
        if kw.get('loan'):
            kind = 'loan_in'
    elif kind in ('sold', 'loaned', 'loan_offer'):
        frm, to = myname, kw.get('to') or None
    for k in ('kind', 'pid', 'when', 'n', 'frm', 'to'):
        kw.pop(k, None)
    data = dict(kw, frm=frm, to=to, mine=True)
    key = 'ev:%s:%s:%s:%s:%s' % (kind, pid or '', d, frm or to or '', kw.get('fee') or '')
    return (kind, d, key, pid, [myname, frm, to], data)


def _world_ai_item(m, wkey):
    d = worldlib.parse_when(m.get('when')) or ''
    data = dict(name=m.get('name'), ovr=m.get('ovr'), age=m.get('age'), pos=m.get('pos'), fee=int(m.get('fee') or 0),
                frm=m.get('from_name'), to=m.get('to_name'), tier=m.get('tier'), from_tier=m.get('from_tier'), xi=m.get('xi'), win=wkey,
                replacement=m.get('repl'), reason=m.get('why'), group=m.get('group'), deadline=m.get('deadline'), ret=m.get('ret'))
    return ('ai_transfer', d, 'ai:%s:%s' % (wkey, m['pid']), m['pid'], [m.get('from_name'), m.get('to_name')], data)


def _world_backfill(slot, L, s=None):
    """Jednom po karijeri: uvezi ono sto app vec zna (dogadjaji, AI transferi, taktike AI trenera, transferi igre)."""
    if s is None:
        s = mlwrite.Save(slot_folder(slot), ro=True)
    my = _my_club_name(s)
    items = []
    try:
        for e in json.load(open(EV_FILE, encoding='utf-8')).get(slot, []):
            items.append(_world_ev_item(e.get('kind'), e.get('pid'), worldlib.parse_when(e.get('when')), dict(e, name=e.get('name'), ovr=e.get('ovr'), age=e.get('age')), my))
    except Exception:
        pass
    e = auto_view().get(slot) or {}
    for wk, w in (e.get('windows') or {}).items():
        for m in w.get('plan', []):
            if m.get('done') and not m.get('skip'):
                items.append(_world_ai_item(m, wk))
    for t in ((e.get('tac') or {}).get('log') or []):
        d = worldlib.parse_when(t.get('when'))
        items.append(('ai_tactics', d, 'tac:%s:%s:%s:%s' % (t.get('idx'), d, t.get('pf'), t.get('pt')), None, [t.get('name')],
                      dict(club=t.get('name'), change=t.get('kind'), pf=t.get('pf'), pt=t.get('pt'), mood=t.get('mt'), form=t.get('form'))))
    try:
        fp = os.path.join(HERE, 'data', 'xfer', re.sub(r'[^A-Za-z0-9_.-]', '_', slot) + '.json')
        for g in (json.load(open(fp, encoding='utf-8')).get('log') or []):
            d = worldlib.parse_when(g.get('when'))
            items.append(('game_transfer', d, 'gm:%s:%s:%s' % (g.get('pid'), d, g.get('to_name')), g.get('pid'), [g.get('from_name'), g.get('to_name')],
                          dict(name=g.get('name'), ovr=g.get('ovr'), age=g.get('age'), frm=g.get('from_name'), to=g.get('to_name'))))
    except Exception:
        pass
    n = L.add_many(items)
    L.set_meta(backfill=True, backfill_n=n, slot=slot, club=my, at=time.strftime('%Y-%m-%d %H:%M'))
    print('[world] %s: uvezeno %d dogadjaja' % (L.id, n))


def world_add(slot, kind, d, key, pid=None, clubs=None, s=None, **data):
    try:
        return world(slot, s).add(kind, d, key, pid=pid, clubs=clubs, **data)
    except Exception as ex:
        print('[world]', ex)
        return False


def world_feed(slot, limit=200, kind=None, season=None):
    L = world(slot)
    ev = L.query(kind=kind.split(',') if kind else None, season=int(season) if season else None)
    return dict(career=L.id, total=len(ev), events=list(reversed(ev[-int(limit):])))


def world_player(slot, pid):
    return world(slot).player(int(pid))


def world_club(slot, name):
    return world(slot).club(name)


def world_season(slot, season=None):
    L = world(slot)
    ss = sorted({e.get('season') for e in L.events() if e.get('season')})
    if season is None and ss:
        season = ss[-1]
    return dict(seasons=ss, summary=L.season_summary(int(season)) if season else None)


def _win_day_date(wkey, day):
    y = int(wkey[1:])
    if wkey[0] == 'W':
        return '%d.1.%d' % (day + 1, y)
    return ('%d.7.%d' % (day + 1, y)) if day < 31 else ('%d.8.%d' % (day - 30, y))


def _auto_idle_status(e, w, wkey):
    """Nista novo za upis: reci sto je vec napravljeno u ovom roku i kad je sljedeci val (umjesto golog 'no transfers due')."""
    left = [m for m in w['plan'] if not m['done']]
    ap = w.get('applied', 0)
    lg = (e.get('log') or [])
    last = ('; last write %s (game date %s): %d moves' % (lg[-1]['t'], lg[-1]['date'], lg[-1]['n'])) if lg else ''
    if not left:
        return 'up to date: all %d transfers of this window are done%s' % (ap, last)
    nd = min(m['day'] for m in left)
    nn = sum(1 for m in left if m['day'] == nd)
    return 'up to date for %s: %d transfers done this window%s. Next: %d on %s, %d left in the window' % (
        e.get('date', ''), ap, last, nn, _win_day_date(wkey, nd), len(left))


def auto_run_slot(slot, force=False):
    """Jedan prolaz za slot: ako je save promijenjen i igra zatvorena, primijeni transfere koji su dospjeli."""
    with AUTO_LOCK:
        st = auto_load()
        e = st.get(slot)
        if not e or not e.get('enabled'):
            return dict(ok=True, status='switched off')
        if game_blocks():  # igra upaljena: smije samo uz potvrdu "glavni izbornik" (gasi se kad igra spremi)
            return dict(ok=True, status='the game is running: waiting for confirmation that you are on the main menu (outside Master League)')
        p = os.path.join(CFG['save_dir'], slot) if not DEV else os.path.join(DEV, 'data.dat')
        if not os.path.exists(p):
            return dict(ok=False, status='no save')
        mt = os.path.getmtime(p)
        if not force and e.get('last_mtime') == mt and not e.get('topup'):
            return dict(ok=True, status='no change')
        d = slot_folder(slot)
        s = mlwrite.Save(d)
        try:
            career_guard(slot, s, st)
        except Exception as ex:
            print('[career]', ex)
        code = s.game_date_code()
        wkey, idx, state = win_state(code)
        e['last_mtime'] = mt
        e['date'] = '%d.%d.%d' % (code >> 24, (code >> 16) & 0xff, code & 0xffff)
        _prune_windows(e, wkey)
        if not wkey:
            e['status'] = 'outside the transfer window'
            auto_save(st)
            return dict(ok=True, status=e['status'])
        wins = e.setdefault('windows', {})
        w = wins.get(wkey)
        base = 1.0   # v2: zima ima svoju raspodjelu dolazaka (prije: 0.33 ljetnog plana)
        if e.get('level') == 'low':
            base = 0.45   # pc398: "Low" (kao u igri): otprilike pola dolazaka po klubu
        import random as _rnd
        if w is None and e.get('skip_first') and not wins:
            # pc398: prvi rok karijere se preskace (baza je vec azurirana do kraja rujanskog roka); planira se od sljedeceg
            w = wins[wkey] = dict(seed=0, plan=[], applied=0, skipped=0, b0={}, events=[], v=2, wish={}, stats={}, sagas=[], full=True, skipped_first=True)
            print('[auto] %s %s: first window skipped (setting)' % (slot, wkey))
        if w is None:
            # rok se planira cijeli, i kad ga app prvi put vidi usred roka (nova karijera / app nije radio):
            # potezi iz proslih dana se upisu odmah (nadoknada), ostali po danima
            sd = int(e.get('seed', 0) or 0) or _rnd.randint(1, 2 ** 31 - 1)
            if not wins and state == 'in' and idx > 0:
                # pc311: NOVA karijera usred roka (FL26 ML krece 1.8.): baza vec ima stvarne ljetne transfere, pa se ne nadoknadjuju
                # protekli dani (prije: ~700 izmisljenih poteza iz srpnja odjednom + vijesti iz lipnja). Planira se samo ostatak roka.
                w = _new_window(slot, s, wins, wkey, idx, 'in', base, sd)
                w['from'] = idx
            else:
                w = _new_window(slot, s, wins, wkey, idx, 'after', base, sd)
            w['full'] = True
        elif e.pop('topup', None) and not w.get('full'):
            # stari rok planiran samo od dana kad ga je app vidio: dopuni ga do cijelog roka, obavljeni potezi ostaju
            old = wins.pop(wkey)
            w = _new_window(slot, s, wins, wkey, idx, 'after', base, _rnd.randint(1, 2 ** 31 - 1))
            taken = {int(m['pid']) for m in old['plan'] if m.get('done')}
            w['plan'] = [m for m in old['plan'] if m.get('done')] + [m for m in w['plan'] if int(m['pid']) not in taken]
            w['applied'], w['skipped'], w['full'] = old.get('applied', 0), old.get('skipped', 0), True
            print('[auto] %s %s: rok dopunjen, novih poteza %d' % (slot, wkey, sum(1 for m in w['plan'] if not m['done'])))
        else:
            _ensure_sagas(slot, s, w, wkey, idx if state == 'in' else 0)
        try:
            _market_effects(slot, s, w, wkey, idx if state == 'in' else WIN_LEN[wkey[0]])
        except Exception as ex:
            print('[market] efekti:', ex)
        due = [m for m in w['plan'] if not m['done'] and (state == 'after' or m['day'] <= idx)]
        # zastita: potezi koji diraju reprezentacije/posebne momcadi (ostaci starih planova) se ne izvrsavaju
        nl = aitransfers.national_like(s)
        for m in list(due):
            if int(m['from']) in nl or int(m['to']) in nl:
                m['done'] = True
                m['skip'] = 'reprezentacija'
                w['skipped'] = w.get('skipped', 0) + 1
                due.remove(m)
        if not due:
            e['status'] = _auto_idle_status(e, w, wkey)
            auto_save(st)
            return dict(ok=True, status=e['status'])
        try:
            done, skipped, backup = _write_slot_moves(slot, due, 'auto')
        except Exception as ex:
            e['status'] = 'error: %s' % ex
            auto_save(st)
            return dict(ok=False, status=e['status'])
        dp = {int(m['pid']) for m in done}
        try:
            scp = _scout_pids(slot)
            for m in done:
                if int(m['pid']) in scp:
                    _ev_add(slot, 'target_taken', int(m['pid']), to=m.get('to_name', ''), fee=m.get('fee') or 0, scout=scp[int(m['pid'])])
        except Exception as ex:
            print('[market] meta:', ex)
        try:
            sellon_receive(slot, [m for m in w['plan'] if not m['done'] and int(m['pid']) in dp])
        except Exception:
            pass
        for m in w['plan']:
            if not m['done'] and (int(m['pid']) in dp or int(m['pid']) in skipped):
                m['done'] = True
                m['skip'] = skipped.get(int(m['pid']))
                m['when'] = e['date']
                if int(m['pid']) in LAST_XI:
                    m['xi'] = True
                m['win'] = wkey
        w['applied'] += len(done)
        w['skipped'] += len(skipped)
        try:
            L_ = world(slot, s)
            L_.add_many([_world_ai_item(m, wkey) for m in w['plan'] if m.get('done') and not m.get('skip') and int(m['pid']) in dp])
        except Exception as ex:
            print('[world] ai:', ex)
        # novi mtime nakon nasega upisa
        e['last_mtime'] = os.path.getmtime(p)
        e['status'] = 'applied %d, skipped %d (date %s)' % (len(done), len(skipped), e['date'])
        e.setdefault('log', []).append(dict(t=time.strftime('%d.%m.%Y %H:%M'), date=e['date'], n=len(done), skipped=len(skipped), backup=backup))
        e['log'] = e['log'][-30:]
        auto_save(st)
        PCACHE.clear()
        return dict(ok=True, status=e['status'], applied=len(done), skipped=len(skipped))


def auto_status(slot):
    e = auto_view().get(slot) or {}
    wins = e.get('windows', {})
    rows = []
    for k, w in wins.items():
        rows.append(dict(window=k, seed=w.get('seed'), total=w.get('total0') or len(w['plan']), done=sum(1 for m in w['plan'] if m['done']), applied=w.get('applied', 0), skipped=w.get('skipped', 0)))
    return dict(enabled=bool(e.get('enabled')), seed=e.get('seed', 0), level=e.get('level', 'normal'), skip_first=bool(e.get('skip_first')), status=e.get('status', ''), date=e.get('date', ''), windows=rows, log=e.get('log', [])[-8:], game_running=game_running(), menu_ok=menu_ok(),
                coach=dict(on=not ((e.get('coach') or {}).get('off')), sacked=sum((e.get('coach') or {}).get('sacked', {}).values())),
                lu=dict(on=not ((e.get('lu') or {}).get('off')), last=(e.get('lu') or {}).get('last'), stats=(e.get('lu') or {}).get('stats'),
                        log=list(reversed(((e.get('lu') or {}).get('log') or [])[-40:])), checked=list(reversed(((e.get('lu') or {}).get('checked') or [])[-20:]))),
                tac=dict(on=bool((e.get('tac') or {}).get('on')), seed=(e.get('tac') or {}).get('seed', 0), status=(e.get('tac') or {}).get('status', ''), clubs=len((e.get('tac') or {}).get('clubs', {})), changes=len((e.get('tac') or {}).get('log', []))))



TAC_KEYS = ('style', 'build', 'pos', 'area', 'defstyle', 'cont', 'press', 'support', 'line', 'compact')


def _tac_diff(old, new):
    """Popis stvarnih promjena [(polje, staro, novo)] izmedju dvije taktike."""
    out = [(k, old.get(k), new.get(k)) for k in TAC_KEYS if k in new and old.get(k) != new.get(k)]
    oa = sorted(a['id'] for a in old.get('adv', []))
    na = sorted(a['id'] for a in new.get('adv', []))
    if oa != na:
        out.append(('adv', [a.get('name') for a in old.get('adv', [])], [a['id'] for a in new.get('adv', [])]))
    return out


def _tier_clubs(s, my):
    clubs = aitransfers.load_clubs(s, rat, POS, my)
    order = sorted(clubs.values(), key=lambda c: -c['strength'])
    nb = max(1, int(len(order) * 0.09))
    nm_ = int(len(order) * 0.49)
    for i, c in enumerate(order):
        c['tier'] = 'big' if i < nb else 'mid' if i < nm_ else 'small'
    return clubs


def _write_slot_tactics(slot, changes):
    """Backup, dekriptiraj, upisi taktike klubova, provjeri citanjem, enkriptiraj, upisi. Vraca (backup)."""
    pes17_readonly(slot)
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
            backup = None
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s_tacauto' % (slot, ts))
            shutil.copy2(src, backup)
            olds = sorted(f for f in os.listdir(os.path.join(work, 'backup')) if f.startswith(slot + '_') and f.endswith('_tacauto'))
            for f in olds[:-6]:
                try:
                    os.remove(os.path.join(work, 'backup', f))
                except OSError:
                    pass
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        for c in changes:
            s.set_club_tactics(int(c['idx']), c['tactics'])
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        v = mlwrite.Save(new_dec)
        for c in changes:
            a = v.club_tactics(int(c['idx']))
            t = c['tactics']
            if any(a[k] != t[k] for k in TAC_KEYS) or sorted(x['id'] for x in a['adv']) != sorted(x['id'] for x in t['adv']):
                raise RuntimeError('tactics check failed for club %s' % c['idx'])
        if DEV:
            shutil.copyfile(os.path.join(new_dec, 'data.dat'), os.path.join(DEV, 'data.dat'))
            return backup
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        return backup


def _edit_coach_names(s):
    if 'edc' in _GL:
        return _GL['edc']
    out = {}
    try:
        d, _src = _edit_data()
        if d:
            ids = set()
            for i in range(mlsave.club_layout(s.d)[0]):   # pc256
                if 84 + 1680 * (i + 1) > len(s.d):
                    break
                c_ = coaches.club_coach(s, i)
                if c_:
                    ids.add(c_)
            out = coaches.edit_coaches(d, ids)
    except Exception as ex:
        print('[coach] edit:', ex)
    if out:   # pc260: neuspjeh (npr. save bez sidra) se ne pamti zauvijek
        _GL['edc'] = out
    return out


def coach_tick(slot, s, e, t, daynum, code, clubs, forms, my):
    """Uprave AI klubova: pritisak na trenera, otkaz (tijekom sezone ili na kraju), novi trener (slobodan ili doveden iz manjeg kluba).
    Vraca (izmjene za save [(idx, blok, taktika|None)], dogadjaji za vijesti)."""
    import random
    C = e.setdefault('coach', {})
    if C.get('off'):
        return [], []
    y, m, _d = _date_tuple(code)
    season = y if m >= 7 else y - 1
    if C.get('season') != season:
        C.update(season=season, sacked={})
    jobs = C.setdefault('jobs', {})
    rep = C.setdefault('rep', {})
    pool = C.setdefault('pool', {})
    eos = C.setdefault('eos', {})
    newc = C.setdefault('new', {})
    nl = aitransfers.national_like(s)
    cur = {}
    _lim, _nat = mlsave.club_layout(s.d)   # pc256: svi klubovi (60 MB: i iznad 750), bez reprezentacija
    for idx in range(_lim):
        if 84 + 1680 * (idx + 1) > len(s.d):
            break
        if idx in _nat:
            continue
        c_ = coaches.club_coach(s, idx)
        if c_ and idx != my:
            cur[idx] = c_
    nclub = max(1, len(clubs))
    for idx, cid in cur.items():
        j = jobs.get(str(idx))
        if not j or j.get('cid') != cid:
            jobs[str(idx)] = dict(cid=cid, since=(daynum if j else daynum - 400))
        if str(cid) not in rep:
            c = clubs.get(idx)
            rep[str(cid)] = round(1 - c['rank'] / float(nclub), 3) if c and 'rank' in c else coaches.seeded_rep(cid)
    try:
        cv = comps_view(slot)
    except Exception as ex:
        print('[coach] comps:', ex)
        return [], []
    leagues = [c for c in cv.get('comps') or [] if c.get('kind') == 'league' and not str(c.get('name', '')).startswith(('Ostale', 'Other')) and len(c.get('rows') or []) >= 6]
    strength = {i: c['strength'] for i, c in clubs.items()}
    try:
        mo = sorted((rat(q)[0] for q in s.my_squad_tags() if rat(q)[0]), reverse=True)[:14]
        strength[my] = sum(mo) / len(mo) if mo else 70
    except Exception:
        pass
    names = _edit_coach_names(s)
    rnd = random.Random('coach|%s|%s' % (t.get('seed'), daynum))
    changes, events = [], []
    taken = set(cur.values())
    # pc313: i treneri reprezentacija i klubova koje app ne vodi su zauzeti (FL27: Queiroz je dobio i klub i reprezentaciju,
    # 14 trenera u dva kluba odjednom)
    try:
        for idx in range(0, 2400):
            if 84 + 1680 * (idx + 1) > len(s.d):
                break
            c_ = coaches.club_coach(s, idx)
            if c_:
                taken.add(c_)
            try:
                b_ = struct.unpack_from('<I', coaches.read_block(s, idx), 0)[0]
                if 0 < b_ < (1 << 24):
                    taken.add(b_)
            except Exception:
                pass
    except Exception as ex:
        print('[coach] busy:', ex)
    # moj trener: igrac u igri bira trenera iz baze (npr. Fabregas za Como); +652 mog kluba je fffffff5, ali blok drzi odabranog
    try:
        mine_c = struct.unpack_from('<I', coaches.read_block(s, my), 0)[0]
        if 0 < mine_c < (1 << 24):
            taken.add(mine_c)
        mname = (s.manager() or '').strip().lower()
        for cid_, v_ in names.items():
            if mname and v_['name'].strip().lower() == mname:
                taken.add(cid_)
    except Exception:
        pass
    league_of = {}
    for L in leagues:
        for r in L['rows']:
            league_of[r.get('idx')] = (L, r)

    def new_profile(idx):
        st_ = (t.get('clubs') or {}).get(str(idx)) or {}
        c = clubs[idx]
        newp = aimanager.pick_profile(c, random.Random('np|%s|%s' % (idx, daynum)), exclude=st_.get('p'))
        t.setdefault('clubs', {})[str(idx)] = dict(p=newp, mood=None, day=daynum, sw=daynum, eval=daynum)
        return newp

    def candidates(idx, allow_poach=True):
        c = clubs[idx]
        out = []
        for k, v in pool.items():
            cid = int(k)
            if cid not in taken and v.get('avail', 0) <= daynum:
                out.append(dict(cid=cid, name=v.get('name', ''), rep=rep.get(k, 0.4), kind='free', block=bytes.fromhex(v['block'])))
        for cid, v in names.items():
            if cid not in taken and str(cid) not in pool:
                out.append(dict(cid=cid, name=v['name'], rep=rep.get(str(cid), coaches.seeded_rep(cid)), kind='free', block=coaches.make_block(cid, v['name'], v['flag'])))
        if allow_poach:
            for x, cx in clubs.items():
                if x == idx or x == my or x in nl or x not in cur or cx['strength'] > c['strength'] - 3 or cx['strength'] < c['strength'] - 10:
                    continue
                if rep.get(str(cur[x]), 0.4) < coaches.TARGET_REP.get(c['tier'], 0.5) - 0.25:
                    continue
                lr = league_of.get(x)
                if not lr:
                    continue
                L_, r_ = lr
                same_l = bool(league_of.get(idx) and league_of[idx][0] is L_)
                if not same_l:
                    if c['tier'] != 'big':
                        continue   # manji klubovi uzimaju trenere iz svoje lige
                    la = [strength.get(r2.get('idx'), 60) for r2 in L_['rows']]
                    if not la or sum(la) / len(la) < c['strength'] - 5:
                        continue   # veliki klub iz inozemstva uzima samo iz jake lige
                ex = coaches.expected_positions(L_['rows'], strength).get(x)
                over = bool(ex and r_.get('pl', 0) >= 5 and (r_.get('pos') or 99) <= ex - 3)
                if not over and cx['tier'] == c['tier']:
                    continue
                out.append(dict(cid=cur[x], name=coaches.block_name(coaches.read_block(s, x)), rep=rep.get(str(cur[x]), 0.4), kind='poach', from_idx=x, over=over,
                                same_league=bool(league_of.get(idx) and league_of[idx][0] is L_)))
        return out

    def appoint(idx, depth=0):
        cand = candidates(idx, allow_poach=(depth == 0))
        ch = coaches.pick_coach(rnd, clubs[idx], cand)
        if not ch:
            return None
        if ch['kind'] == 'poach':
            x = ch['from_idx']
            blk = coaches.read_block(s, x)
            cur.pop(x, None)   # trener ostaje 'zauzet' (prelazi u novi klub)
            rep_x = appoint(x, depth + 1)
            if not rep_x:
                # pc313: klub x nema zamjenu -> trener bi ostao u oba kluba; nema preuzimanja, uzmi slobodnog
                cur[x] = ch['cid']
                return appoint(idx, depth + 1) if depth == 0 else None
            events.append(dict(coach_ev='poached', idx=x, name=clubs[x]['name'], coach=ch['name'], to=clubs[idx]['name'], newcoach=(rep_x or {}).get('name')))
        else:
            blk = ch['block']
            pool.pop(str(ch['cid']), None)
        cur[idx] = ch['cid']
        taken.add(ch['cid'])
        jobs[str(idx)] = dict(cid=ch['cid'], since=daynum)
        rep[str(ch['cid'])] = round(min(0.95, rep.get(str(ch['cid']), 0.4) + 0.03), 3)
        newc[str(idx)] = daynum
        p_ = new_profile(idx)
        changes.append((idx, blk, aimanager.tactics_for(p_)))
        frm = clubs[ch['from_idx']]['name'] if ch['kind'] == 'poach' else None
        events.append(dict(coach_ev='appointed', idx=idx, name=clubs[idx]['name'], coach=ch['name'], frm=frm, pt=p_, rep=rep[str(ch['cid'])]))
        return ch

    def sack(idx, L, r, ex, reason, p):
        old = cur[idx]
        blk = coaches.read_block(s, idx)
        nm = coaches.block_name(blk)
        pool[str(old)] = dict(block=blk.hex(), avail=daynum + 30, name=nm)
        rep[str(old)] = round(max(0.05, rep.get(str(old), 0.4) - 0.08), 3)
        taken.discard(old)
        cur.pop(idx, None)
        C['sacked'][L['name']] = C['sacked'].get(L['name'], 0) + 1
        events.append(dict(coach_ev='sacked', idx=idx, name=clubs[idx]['name'], coach=nm, pos=r.get('pos'), exp=ex, n=len(L['rows']), pl=r.get('pl'), pts=r.get('pts'),
                           reason=reason, p=p, league=L['name']))
        ch = appoint(idx)
        if not ch:   # nema slobodnog trenera: stari ostaje (ponisti)
            pool.pop(str(old), None)
            cur[idx] = old
            taken.add(old)
            events[-1]['coach_ev'] = 'survived'

    # pc314: popravak starih saveova (FL27 prije pc313): isti trener u dva kluba -> klub koji ne zadrzava trenera uzme slobodnog.
    # Reprezentacije i klubovi koje app ne vodi zadrze svog; izmedju dva kluba ostaje onaj s duljim stazom u appu.
    try:
        own_ = {}
        for idx_ in range(0, 2400):
            if 84 + 1680 * (idx_ + 1) > len(s.d):
                break
            c_ = coaches.club_coach(s, idx_)
            if c_ and idx_ != my:
                own_.setdefault(c_, []).append(idx_)
        nfix_ = 0
        for cid_, L_ in own_.items():
            if len(L_) < 2:
                continue
            mov_ = [x for x in L_ if x in cur and x in clubs and x not in nl]
            if not mov_:
                continue
            keep_ = None
            if len(mov_) == len(L_):
                keep_ = min(mov_, key=lambda x: ((jobs.get(str(x)) or {}).get('since', 0), x))
            for x in mov_:
                if x == keep_ or any(ch_[0] == x for ch_ in changes):
                    continue
                cur.pop(x, None)
                if appoint(x, 1):
                    nfix_ += 1
                else:
                    cur[x] = cid_
        if nfix_:
            print('[coach] %s: %d trenera bilo je u dva kluba, popravljeno' % (slot, nfix_))
    except Exception as ex:
        print('[coach] dupli:', ex)

    # klub koji si napustio trazi novog trenera (igra mu vrati 'parkiranog' trenera, npr. AI Fabregasa)
    try:
        CC = json.load(open(CAREER_FILE, encoding='utf-8'))
        vac = (CC.get(slot) or {}).get('vacancy')
        if vac is not None:
            vac = int(vac)
            if vac in clubs and vac != my:
                old_b = coaches.read_block(s, vac)
                if vac in cur:
                    cur.pop(vac, None)
                ch_ = appoint(vac)
                if ch_:
                    for ev_ in reversed(events):
                        if ev_.get('coach_ev') == 'appointed' and ev_.get('idx') == vac:
                            ev_.update(coach_ev='replaces_you', prev=coaches.block_name(old_b))
                            break
            CC[slot].pop('vacancy', None)
            _jdump(CC, CAREER_FILE, ensure_ascii=False, indent=1)
    except Exception as ex:
        print('[coach] vacancy:', ex)
    for L in leagues:
        rows = L['rows']
        n = len(rows)
        ex_ = coaches.expected_positions(rows, strength)
        cap = max(2, n // 3)
        full = all((r.get('pl') or 0) >= 2 * (n - 1) for r in rows)
        end_now = (full or m == 6) and eos.get(L['name']) != season and all((r.get('pl') or 0) >= n for r in rows)
        for r in rows:
            idx = r.get('idx')
            if idx is None or idx == my or idx in nl or idx not in clubs or idx not in cur or any(ch[0] == idx for ch in changes):
                continue
            c = clubs[idx]
            job = jobs.get(str(idx)) or {}
            ex = ex_.get(idx, n)
            if end_now:
                pr = coaches.end_of_season_sack(r, ex, n, c['tier'], (r.get('pos') or 0) > n - 3)
                if pr and rnd.random() < pr and C['sacked'].get(L['name'], 0) < cap + 2:
                    sack(idx, L, r, ex, 'season', None)
                continue
            f = aimanager.form_of(forms.get(idx, []))
            p = coaches.pressure(r, ex, n, f, c['tier'], daynum - job.get('since', daynum - 400))
            job['p'] = p
            if daynum - job.get('eval', -99) < 7:
                continue
            job['eval'] = daynum
            ch = coaches.sack_chance(p)
            if ch and C['sacked'].get(L['name'], 0) < cap and rnd.random() < ch:
                sack(idx, L, r, ex, 'results', p)
            elif p >= 0.75 and daynum - job.get('warned', -999) >= 30:
                job['warned'] = daynum
                events.append(dict(coach_ev='pressure', idx=idx, name=c['name'], coach=coaches.block_name(coaches.read_block(s, idx)), pos=r.get('pos'), exp=ex, n=n,
                                   pl=r.get('pl'), pts=r.get('pts'), p=p, league=L['name']))
        if end_now:
            eos[L['name']] = season
    for k in [k for k, v in newc.items() if daynum - v > 200]:
        newc.pop(k, None)
    return changes, events


BOARD_FILE = os.path.join(HERE, 'data', 'board.json')
BOARD_LOCK = threading.Lock()


def _board_season_money(s, pos, tp, n, tier):
    """pc316 (odluka korisnika 1.11.): samo bonus, bez kazne (igra ionako sama smanji budzet nove sezone nakon lose sezone).
    Bonus za naslov ili cilj prebacen za 2+ mjesta; jedinica = 2 % godisnjih placa (0,2-3 M)."""
    unit = max(200000, min(3000000, int(s.wage_commitment() * 0.02)))
    unit = int(round(unit / 50000.0)) * 50000
    gap = tp - pos
    if pos == 1:
        return unit * 3, 'League title'
    if gap >= 2:
        return unit * min(3, gap - 1), 'Objective beaten by %d places' % gap
    return 0, ''


# ---------------------------------------------------------------- pc316: ulaganja kluba + dogadjaji s troskom
INV_FILE = os.path.join(HERE, 'data', 'investments.json')
INV_LOCK = threading.Lock()
INV_FAC = {   # kljuc: (naziv, opis ucinka po razini, cijene u % godisnjih placa za razine 1-3, dana do otvaranja)
    'training': ('Training ground', 'Every player grows 5% faster in monthly training per level.', (6, 10, 15), 30),
    'academy': ('Youth academy', 'Players aged 21 or younger grow 8% faster per level.', (4, 7, 10), 30),
    'medical': ('Medical & sports science', 'Injured players keep more of their training, and players over 30 decline 8% slower per level.', (5, 8, 12), 30),
    'stadium': ('Stadium expansion', '6% more seats per level, so more ticket income from every home match.', (18, 26, 35), 120),
}
INV_EV = {
    'camp': ('Warm-weather training camp', 'A week abroad with the whole squad. Every player gets a small form boost for the next three matches.', 1.0),
    'bonding': ('Team-bonding trip', 'Paintball, dinner and a night away together. The whole squad is happier at the club.', 0.5),
    'psych': ('Sports psychologist', 'Sessions for the unhappiest player in the squad. He feels much better about the club.', 0.2),
    'fans': ('Fan day at the training ground', 'Open training, autographs and free food. The supporters love it.', 0.3),
}


def _inv_all():
    try:
        return json.load(open(INV_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _inv_rec(slot, s):
    return _inv_all().get(_career_id(slot, s)) or {}


_CLUB_KEYS = ('fac', 'spon', 'spon_sleeve', 'spon_back', 'spon_off', 'evd', 'ev')


def _club_switch(slot, s):
    """pc339: novi klub u istoj karijeri (otkaz ili odlazak). Sve sto pripada KLUBU ostaje tom klubu: objekti (trening centar,
    akademija...), sponzori i ponude sponzora, neisplacene rate sponzora, predugovori s igracima. Sprema se pod stari klub
    (ako se jednom vratis, sve je opet tu), a novi klub krece od nule. Dresovi starog kluba se vrate na original."""
    try:
        club = _my_club_name(s)
    except Exception:
        return
    if not club:
        return
    cid = _career_id(slot, s)
    old = None
    with INV_LOCK:
        A = _inv_all()
        E = A.setdefault(cid, {})
        if not E.get('club'):
            E['club'] = club
            _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
            return
        if E['club'] == club:
            return
        old = E['club']
        arch = E.setdefault('by_club', {})
        keep = {k: E.pop(k) for k in _CLUB_KEYS if k in E}
        pend = [p_ for p_ in (E.get('spon_pay') or []) if not p_.get('done')]
        if pend:
            keep['spon_pay_open'] = pend
            E['spon_pay'] = [p_ for p_ in E.get('spon_pay') or [] if p_.get('done')]
        arch[old] = keep
        back = arch.pop(club, None) or {}
        for k, v in back.items():
            if k == 'spon_pay_open':
                continue
            E[k] = v
        E['club'] = club
        E.setdefault('hist', []).append(dict(d=_fmt_date(s.game_date_code()), t='New club: %s. Facilities and sponsors of %s stay with that club.' % (club, old), a=0))
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    try:   # predugovori su dogovor sa starim klubom
        with PRECON_LOCK:
            P = _precon_all()
            mine = P.get(cid) or {}
            n = 0
            for k_, e in mine.items():
                if not e.get('done') and not e.get('void'):
                    e['void'] = 'manager_left'
                    e['void_club'] = old
                    n += 1
            if n:
                _jdump(P, PRECON_FILE, ensure_ascii=False, indent=1)
    except Exception as ex:
        print('[club switch] precon:', ex)
    print('[club switch] %s -> %s' % (old, club))


def _inv_level(slot, s, key):
    f = (_inv_rec(slot, s).get('fac') or {}).get(key) or {}
    lv = int(f.get('lvl') or 0)
    if lv and f.get('ready') and _cmp_date(s.game_date_code(), int(f['ready'])) < 0:
        lv -= 1   # zadnja razina se jos gradi
    return max(0, lv)


def _inv_factors(slot):
    try:
        s = mlwrite.Save(slot_folder(slot), ro=True)
        L = {k: _inv_level(slot, s, k) for k in INV_FAC}
    except Exception:
        return None
    return dict(train=1 + 0.05 * L['training'], u21=1 + 0.08 * L['academy'], injt=0.2 + 0.15 * L['medical'], dec=1 - 0.08 * L['medical'])


def _inv_cost(s, pct):
    w = s.wage_commitment() or 20000000
    return max(100000, int(round(w * pct / 100.0 / 50000.0)) * 50000)


def invest_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    R = _inv_rec(slot, s)
    gd = s.game_date_code()
    fac = []
    for k, (nm, eff, costs, days) in INV_FAC.items():
        f = (R.get('fac') or {}).get(k) or {}
        lv = int(f.get('lvl') or 0)
        building = bool(f.get('ready') and _cmp_date(gd, int(f['ready'])) < 0)
        fac.append(dict(key=k, name=nm, effect=eff, level=lv, max=3, building=building, ready=(_fmt_date(int(f['ready'])) if f.get('ready') else None),
                        cost=(_inv_cost(s, costs[lv]) if lv < 3 else None), days=days))
    ev = _inv_event(slot, s, R)
    return dict(ok=True, budget=s.budget(), facilities=fac, event=ev, history=(R.get('hist') or [])[-20:][::-1])


def _inv_event(slot, s, R):
    """Najvise jedna ponuda odjednom; nova najranije 40 dana nakon prosle. Odabir je stalan za karijeru i razdoblje."""
    import random
    e = R.get('ev')
    gd = s.game_date_code()
    if e and not e.get('done'):
        return e
    y, m, d = _date_tuple(gd)
    dn = y * 372 + m * 31 + d
    if e and dn - int(e.get('dn', 0)) < 40:
        return None
    rnd = random.Random('%s|%d' % (_career_id(slot, s), dn // 40))
    keys = list(INV_EV)
    if not growth.enabled(CFG):
        keys = [k for k in keys if k not in ('bonding', 'psych')]   # bez GrowthBridgea nema promjene raspolozenja u igri
    if m in (8, 9, 10, 11, 12, 2, 3, 4, 5):
        keys = [k for k in keys if k != 'camp'] or keys
    k = rnd.choice(keys)
    nm, txt, pct = INV_EV[k]
    e = dict(id='%s-%d' % (k, dn), k=k, name=nm, text=txt, cost=_inv_cost(s, pct), d=_fmt_date(gd), dn=dn, done=False)
    with INV_LOCK:
        A = _inv_all()
        A.setdefault(_career_id(slot, s), {})['ev'] = e
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    return e


def invest_buy(body):
    slot, key = body['slot'], body['key']
    if key not in INV_FAC:
        raise ValueError('unknown investment')
    s0 = mlwrite.Save(slot_folder(slot), ro=True)
    cid = _career_id(slot, s0)
    R = _inv_rec(slot, s0)
    f = (R.get('fac') or {}).get(key) or {}
    lv = int(f.get('lvl') or 0)
    if lv >= 3:
        raise ValueError('Already at the highest level.')
    if f.get('ready') and _cmp_date(s0.game_date_code(), int(f['ready'])) < 0:
        raise ValueError('The previous level is still being built.')
    nm, eff, costs, days = INV_FAC[key]
    cost = _inv_cost(s0, costs[lv])
    if s0.budget() < cost:
        raise ValueError('Not enough transfer budget (%s EUR needed).' % '{:,}'.format(cost))
    r = _write_slot(slot, 'facility', lambda sv: (sv.adjust_budget(-cost), '%s level %d: %s EUR.' % (nm, lv + 1, '{:,}'.format(cost)))[1])
    ready = _add_days(s0.game_date_code(), days)
    with INV_LOCK:
        A = _inv_all()
        E = A.setdefault(cid, {})
        E.setdefault('fac', {})[key] = dict(lvl=lv + 1, d=_fmt_date(s0.game_date_code()), ready=ready)
        E.setdefault('hist', []).append(dict(d=_fmt_date(s0.game_date_code()), t='%s level %d' % (nm, lv + 1), a=-cost))
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    try:
        _board_adjust(slot, s0, 2, 'invest')
    except Exception:
        pass
    return dict(ok=True, message='%s level %d approved: %s EUR. Ready on %s.' % (nm, lv + 1, '{:,}'.format(cost), _fmt_date(ready)), detail=r)


def invest_event(body):
    slot, eid, yes = body['slot'], body['id'], bool(body.get('accept'))
    s0 = mlwrite.Save(slot_folder(slot), ro=True)
    cid = _career_id(slot, s0)
    e = _inv_rec(slot, s0).get('ev')
    if not e or e.get('id') != eid or e.get('done'):
        raise ValueError('This offer is no longer open.')
    msg = 'Declined.'
    if yes:
        if s0.budget() < e['cost']:
            raise ValueError('Not enough transfer budget.')
        squad = [p for p in s0.my_squad_tags() if p]
        k = e['k']
        target = None
        if k == 'psych':
            try:
                live = growth.read_live(CFG.get('dump') or '', squad) or {}
                target = min((p for p in squad if p in live), key=lambda p: live[p].get('aff', 200))
            except Exception:
                target = None
            if not target:
                raise ValueError('No player data from the game yet (press F7 in the game once), so the psychologist does not know who to see.')
        _write_slot(slot, 'invest_ev', lambda sv: (sv.adjust_budget(-e['cost']), '%s: %s EUR.' % (e['name'], '{:,}'.format(e['cost'])))[1])
        if k == 'camp':
            a = _press_load()
            fs0 = a.setdefault(slot, {}).setdefault('form', {})
            c0 = len(_form_targets(slot)[1])
            for p in squad:
                fs0.setdefault('bias', {})[str(p)] = dict(v=1, c0=c0)
            _press_save(a)
            try:
                form_commit(slot)
            except Exception:
                pass
            msg = 'Training camp booked: the squad is sharper for the next three matches.'
        elif k == 'bonding':
            growth.queue(CFG, [(p, 'Affection', 8) for p in squad], 'inv-%s' % eid)
            msg = 'Team-bonding trip done: the whole squad is happier (applied in the game by GrowthBridge).'
        elif k == 'psych':
            growth.queue(CFG, [(target, 'Affection', 24)], 'inv-%s' % eid)
            msg = '%s had sessions with the psychologist and feels much better.' % NAMES.get(target, str(target))
        elif k == 'fans':
            a = _press_load()
            st = a.setdefault(slot, {})
            st['fans'] = max(-20, min(20, st.get('fans', 0) + 4))
            _press_save(a)
            msg = 'Fan day was a hit: supporters\' mood is up.'
    with INV_LOCK:
        A = _inv_all()
        E = A.setdefault(cid, {})
        if E.get('ev') and E['ev'].get('id') == eid:
            E['ev']['done'] = True
            E['ev']['accepted'] = yes
        if yes:
            E.setdefault('hist', []).append(dict(d=_fmt_date(s0.game_date_code()), t=e['name'], a=-e['cost']))
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, message=msg)


# ---------------------------------------------------------------- pc317: sponzor na dresu
SPON_BRANDS = ('Nordwind Energy', 'Halcyon Bank', 'Volta Motors', 'Kestrel Air', 'Brightway Telecom', 'Oro Coffee', 'Meridian Insurance',
               'Apex Logistics', 'Solace Hotels', 'Quartz Tech', 'Riverstone Beer', 'Aurora Mobile', 'Ironleaf Tyres', 'Bluecrest Travel')


def _spon_season(code):
    y, m, _ = _date_tuple(code)
    return y if m >= 7 else y - 1


def _spon_annual(s):
    w = s.wage_commitment() or 20000000
    return max(300000, int(round(w * 0.08 / 50000.0)) * 50000)


# pc323: tri mjesta za sponzora (prsa, rukav bez znacke lige, leda ispod broja); kljuc u zapisu karijere i udio vrijednosti glavnog
SPON_PARTS = {'chest': ('spon', 1.0, 'Shirt sponsor'), 'sleeve': ('spon_sleeve', 0.25, 'Sleeve sponsor'), 'back': ('spon_back', 0.15, 'Back sponsor')}
KS_LOGO_DIR = os.path.join(HERE, 'data', 'kitsp_logos')
_KS_LOGO_LOCK = threading.Lock()


SPON_CUSTOM_FILE = os.path.join(HERE, 'data', 'custom_sponsors.json')


def _spon_custom():
    try:
        L = json.load(open(SPON_CUSTOM_FILE, encoding='utf-8'))
        return [c for c in L if isinstance(c, dict) and c.get('id') and c.get('name')]
    except Exception:
        return []


def spon_custom_add(body):
    """pc324: vlastiti (izmisljeni) sponzor: ime + po zelji logo (PNG iz preglednika, vec smanjen)."""
    import base64
    name = re.sub(r'\s+', ' ', str(body.get('name') or '')).strip()[:40]
    if len(name) < 2:
        raise ValueError('Enter the sponsor name.')
    L = _spon_custom()
    if any(c['name'].lower() == name.lower() for c in L):
        raise ValueError('%s is already on your list.' % name)
    if name.lower() in {b.lower() for b in SPON_BRANDS}:
        raise ValueError('%s is already one of the built-in sponsors.' % name)
    cid = '%x' % (int(time.time() * 1000) & 0xffffffffff)
    has = False
    png = str(body.get('png') or '')
    if png:
        raw = base64.b64decode(png.split(',', 1)[-1])
        if raw[:8] != b'\x89PNG\r\n\x1a\n' or len(raw) > 3 * 1024 * 1024:
            raise ValueError('The logo must be an image (PNG/JPG) up to 3 MB.')
        os.makedirs(KS_LOGO_DIR, exist_ok=True)
        open(os.path.join(KS_LOGO_DIR, 'custom_%s.png' % cid), 'wb').write(raw)
        has = True
    L.append(dict(id=cid, name=name, logo=has))
    _jdump(L, SPON_CUSTOM_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, items=L, message='%s added to your sponsors: it now appears among the sponsor offers (Board and Inbox).' % name)


def spon_custom_del(body):
    cid = str(body.get('id') or '')
    L = [c for c in _spon_custom() if c['id'] != cid]
    _jdump(L, SPON_CUSTOM_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, items=L)


def _ks_donor_logo(tid, part):
    """Sponzor s glavnog dresa kluba tid (Sider kit-server): -> putanja do PNG loga ili None. Rezultat (i 'nema loga') se pamti
    po vremenu izmjene teksture, pa se svaki dres cita samo jednom."""
    import kitsponsor
    import dds
    fp = _kitserver_tex(int(tid), 1)
    if not fp or not os.path.isfile(fp):
        return None
    src = fp + '.orig' if os.path.isfile(fp + '.orig') else fp
    key = '%d_%s' % (int(tid), part)
    png = os.path.join(KS_LOGO_DIR, key + '.png')
    mt = int(os.path.getmtime(src))
    with _KS_LOGO_LOCK:
        idx_p = os.path.join(KS_LOGO_DIR, 'index.json')
        try:
            idx = json.load(open(idx_p, encoding='utf-8'))
        except Exception:
            idx = {}
        e = idx.get(key)
        if e and e.get('mt') == mt and e.get('v') == 5:
            return png if e.get('ok') and os.path.isfile(png) else None
        try:
            L = kitsponsor.logo(src, 'sleeve' if part == 'sleeve' else 'chest')
        except Exception as ex:
            print('[kit sponsor] logo %s: %s' % (key, ex))
            L = None
        os.makedirs(KS_LOGO_DIR, exist_ok=True)
        if L:
            open(png, 'wb').write(dds.to_png(L['w'], L['h'], L['rgba']))
        idx[key] = dict(mt=mt, v=5, ok=bool(L), w=(L or {}).get('w'), h=(L or {}).get('h'))
        _jdump(idx, idx_p)
    return png if L else None


def _ks_donors(s):
    """Klubovi s dresom u kit-serveru (osim mog): [(tid, ime, liga)], prvo moja liga."""
    _kitserver_tex(0, 1)   # ucita map.txt
    M = _GL.get('ksmap') or {}
    try:
        my = int(_team_id(_my_club_name(s)) or 0)
    except Exception:
        my = 0
    lg = (M.get(my) or '').split(os.sep)[0]
    out = []
    for tid, rel in M.items():
        if tid == my:
            continue
        parts = [x for x in rel.split(os.sep) if x]
        out.append((tid, parts[-1] if parts else str(tid), parts[0] if len(parts) > 1 else ''))
    out.sort(key=lambda d: (d[2] != lg, d[0]))
    return out, lg


SPON_DONORS = False   # pc340: sponzori s tudih dresova zasad iskljuceni (logo s teksture ne izgleda dovoljno dobro); ostaju izmisljene i vlastite tvrtke
SPON_DAYS = 30   # pc323: rok za odgovor na ponude sponzora (dana)


def _spon_offers(slot, s, part, season, rnd, used=(), factor=1.0):
    """3 ponude za mjesto 'part'. Sponzori su pravi sponzori s dresova drugih klubova iz kit-servera (logo se prenosi na moj dres);
    bez kit-servera ostaju izmisljene tvrtke."""
    A = _spon_annual(s) * SPON_PARTS[part][1] * factor
    q = lambda x: max(50000, int(round(x / 50000.0)) * 50000)
    # pc324: mjesavina: sponzori s dresova iz igre + izmisljene tvrtke + tvoji vlastiti sponzori (Board -> Your own sponsors)
    cust = [c for c in _spon_custom() if 'c:' + c['id'] not in used]
    n_game = rnd.choice((1, 2, 2, 3)) if not cust else rnd.choice((1, 1, 2))
    picks = []
    try:
        if not SPON_DONORS:
            raise StopIteration
        donors, lg = _ks_donors(s)
        same = [d for d in donors if d[2] == lg]
        other = [d for d in donors if d[2] != lg]
        rnd.shuffle(same)
        rnd.shuffle(other)
        tried = 0
        for d in same[:12] + other:
            if len(picks) >= n_game or tried >= 18:
                break
            if d[0] in used:
                continue
            tried += 1
            if _ks_donor_logo(d[0], part if part == 'sleeve' else 'chest'):
                picks.append(d)
    except StopIteration:
        pass
    except Exception as ex:
        print('[sponsor] donors:', ex)
    B = [dict(brand='%s sponsor' % club, logo=dict(tid=tid, club=club, part=part if part == 'sleeve' else 'chest')) for tid, club, _lg in picks]
    pool = []
    for c in cust:
        pool += [c] * 3   # vlastiti sponzori dolaze cesce
    pool += [dict(name=n) for n in SPON_BRANDS]
    pool = [x for x in pool if 'n:' + x['name'] not in used] or pool
    taken = set()
    while len(B) < 3 and pool:
        c = rnd.choice(pool)
        pool = [x for x in pool if x is not c and x.get('name') != c.get('name')]
        if c.get('name') in taken:
            continue
        taken.add(c.get('name'))
        B.append(dict(brand=c['name'], logo=dict(custom=c['id'], part='chest') if c.get('logo') else None, custom=c.get('id')))
    rnd.shuffle(B)
    def brand(i):
        return B[i] if i < len(B) else dict(brand=SPON_BRANDS[i], logo=None)
    where = {'chest': 'on the front of the shirt', 'sleeve': 'on the sleeve (the one without the league badge)', 'back': 'on the back, under the number'}[part]
    return [
        dict(id='quick', kind='Quick cash', years=1, upfront=q(A * rnd.uniform(1.0, 1.15)), yearly=0, bonus=0, part=part,
             text='One season %s, all the money paid now.' % where, **brand(0)),
        dict(id='long', kind='Long-term partner', years=3, upfront=q(A * 0.3), yearly=q(A * rnd.uniform(0.85, 0.95)), bonus=0, part=part,
             text='Three seasons %s: a signing fee now, then the same amount at the start of every season.' % where, **brand(1)),
        dict(id='perf', kind='Performance deal', years=2, upfront=0, yearly=q(A * rnd.uniform(0.55, 0.65)), bonus=q(A * rnd.uniform(0.6, 0.75)), part=part,
             text='Two seasons %s: a smaller yearly fee, plus a bonus every season you meet the board objective (double for the title).' % where, **brand(2)),
    ]


def sponsor_view(slot, s=None):
    """Sponzori na dresu (pc317 prsa; pc323 i rukav i leda): za svako mjesto bez aktivnog ugovora 3 ponude, stalne za karijeru i
    sezonu. Isplate idu u transfer budzet same, kad je save siguran za upis."""
    import random
    s = s or mlwrite.Save(slot_folder(slot), ro=True)
    R = _inv_rec(slot, s)
    gd = s.game_date_code()
    season = _spon_season(gd)
    cid = _career_id(slot, s)
    parts = {}
    used = set()
    for k_, _f, _t in SPON_PARTS.values():
        a_ = R.get(k_)
        if a_ and a_.get('until', 0) >= season:
            if (a_.get('logo') or {}).get('tid'):
                used.add(int(a_['logo']['tid']))
            if a_.get('custom'):
                used.add('c:' + str(a_['custom']))
            if a_.get('brand'):
                used.add('n:' + a_['brand'])   # pc343: ista tvrtka ne moze biti na dva mjesta dresa
    import datetime
    def _days(a, b):
        ya, ma, da = _date_tuple(a)
        yb, mb, db = _date_tuple(b)
        return (datetime.date(yb, mb, db) - datetime.date(ya, ma, da)).days
    OFF = dict(R.get('spon_off') or {})
    changed = False
    for part, (key, _f, title) in SPON_PARTS.items():
        cur = R.get(key)
        active = cur if cur and cur.get('until', 0) >= season else None
        offers = []
        due = left = None
        rnd_n = 0
        if not active:
            # pc323: ponude imaju rok za odgovor (30 dana od kad su stigle). Propusten rok -> nove ponude, svaki put 10% slabije.
            o_ = OFF.get(part)
            if not o_ or o_.get('season') != season:
                o_ = dict(season=season, since=gd)
                OFF[part] = o_
                changed = True
            try:
                gone = max(0, _days(o_['since'], gd))
            except Exception:
                gone = 0
            rnd_n = gone // SPON_DAYS
            dcode = _add_days(o_['since'], SPON_DAYS * (rnd_n + 1))
            due, left = _fmt_due(dcode), _days(gd, dcode)
            seed = '%s|spon|%d' % (cid, season) if part == 'chest' else '%s|spon-%s|%d' % (cid, part, season)
            if rnd_n:
                seed += '|r%d' % rnd_n
            offers = _spon_offers(slot, s, part, season, random.Random(seed), used, factor=max(0.6, 0.9 ** rnd_n))
            for o in offers:   # isti sponzor ne nudi se za dva mjesta odjednom
                if (o.get('logo') or {}).get('tid'):
                    used.add(int(o['logo']['tid']))
                if o.get('custom'):
                    used.add('c:' + str(o['custom']))
                used.add('n:' + o['brand'])
            for o in offers:
                o['due'], o['days_left'] = due, left
        if active:
            active = dict(active, exit_fee=_spon_exit_fee(active, season))
            active.setdefault('contract', dict(start=active.get('d') or '', end='30 Jun %d' % (active['until'] + 1), place=part, where=SPON_WHERE[part]))
        parts[part] = dict(title=title, active=active, offers=offers, due=due, days_left=left, round=rnd_n)
    if changed:
        try:
            with INV_LOCK:
                A = _inv_all()
                A.setdefault(cid, {})['spon_off'] = OFF
                _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
        except Exception as ex:
            print('[sponsor] offers date:', ex)
    pend = [p_ for p_ in (R.get('spon_pay') or []) if not p_.get('done')]
    return dict(ok=True, kits_on=_kitsp_on(slot, s), places=SPON_WHERE, season='%d/%02d' % (season, (season + 1) % 100), active=parts['chest']['active'], offers=parts['chest']['offers'],
                due=parts['chest']['due'], days_left=parts['chest']['days_left'],
                parts=parts, pending=pend, history=[h for h in (R.get('hist') or []) if h.get('k') == 'sponsor'][-10:][::-1])


def _spon_contract(o, season, place, gd):
    """pc328: ugovor kao u stvarnosti: traje od potpisa do 30. lipnja zadnje sezone; klauzule (ispadanje, raskid)."""
    return dict(start=_fmt_due(gd), end='30 Jun %d' % (season + o['years']), place=place,
                where=SPON_WHERE[place], releg='The yearly fee is halved for every season after a relegation.',
                club_exit='The club may end the deal early by paying 25%% of the money still to come (at least 10%% of one year).',
                exclusive='No other company can be offered this place until the deal ends.')


SPON_WHERE = {'chest': 'front of the shirt (centre of the chest)', 'sleeve': 'sleeve without the league badge', 'back': 'back of the shirt, under the number'}


def _spon_scale(o, part, place):
    """Ista ponuda na drugom mjestu dresa: iznosi se mijenjaju prema vrijednosti mjesta (prsa 100%, rukav 25%, leda 15%)."""
    if place == part:
        return dict(o)
    k = SPON_PARTS[place][1] / SPON_PARTS[part][1]
    q = lambda x: max(50000, int(round(x * k / 50000.0)) * 50000) if x else 0
    return dict(o, upfront=q(o['upfront']), yearly=q(o['yearly']), bonus=q(o['bonus']), part=place)


def sponsor_sign(body):
    slot, oid = body['slot'], body['id']
    part = body.get('part') or 'chest'
    place = body.get('place') or part
    if part not in SPON_PARTS or place not in SPON_PARTS:
        raise ValueError('Unknown sponsor place.')
    key, _f, title = SPON_PARTS[place]
    s = mlwrite.Save(slot_folder(slot), ro=True)
    v = sponsor_view(slot, s)
    if v['parts'][place]['active']:
        raise ValueError('You already have a %s until %s.' % (title.lower(), (v['parts'][place]['active'].get('contract') or {}).get('end') or 'the end of the deal'))
    o = next((x for x in v['parts'][part]['offers'] if x['id'] == oid), None)
    if not o:
        raise ValueError('That offer is no longer available.')
    o = _spon_scale(o, part, place)
    gd = s.game_date_code()
    season = _spon_season(gd)
    cid = _career_id(slot, s)
    pid = '%s-%s' % (place, oid) if (place != 'chest' or part != 'chest') else oid
    with INV_LOCK:
        A = _inv_all()
        E = A.setdefault(cid, {})
        E[key] = dict(o, id=pid, since=season, until=season + o['years'] - 1, d=_fmt_date(gd), paid_seasons=[season],
                      contract=_spon_contract(o, season, place, gd))
        pays = E.setdefault('spon_pay', [])
        first = o['upfront'] + o['yearly']
        if first:
            pays.append(dict(id='%s-%d-0' % (pid, season), amount=first, why='%s (%s): %s (%s)' % (o['brand'], title.lower(), 'signing' if o['upfront'] else 'season fee', v['season']), done=False))
        E.setdefault('hist', []).append(dict(d=_fmt_date(gd), t='%s signed as %s until %s' % (o['brand'], title.lower(), E[key]['contract']['end']), a=0, k='sponsor'))
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    _spon_auto(slot, s)
    try:   # pc330: vijest u novinama
        my = _my_club_name(s)
        val = (o['upfront'] or 0) + (o['yearly'] or 0) * o['years']
        _ev_add(slot, 'sponsor_deal', 0, club=my, brand=o['brand'], place=place, years=o['years'], fee=val, until=E[key]['contract']['end'], _nofan=True,
                head='%s sign %s deal with %s' % (my, {'chest': 'shirt sponsorship', 'sleeve': 'sleeve sponsorship', 'back': 'back-of-shirt sponsorship'}[place], (o['brand'][:-8] + "'s sponsor") if o['brand'].endswith(' sponsor') else o['brand']),
                lead='%s will appear on the %s until %s. The deal is worth about %s EUR to the club.' % (o['brand'], SPON_WHERE[place], E[key]['contract']['end'], '{:,}'.format(val)))
    except Exception as ex:
        print('[sponsor] news:', ex)
    return dict(ok=True, message='%s is your new %s until %s (%s). %s' % (
        o['brand'], title.lower(), E[key]['contract']['end'], o['kind'],
        ('%s EUR goes into the transfer budget as soon as the game is closed or on the main menu.' % '{:,}'.format(first)) if first else ''))


def _spon_exit_fee(sp, season):
    left = max(0, sp['until'] - season)          # sezone koje jos nisu placene
    future = left * (sp.get('yearly') or 0)
    one = (sp.get('yearly') or 0) or (sp.get('upfront') or 0)
    return max(10000, int(round(max(future * 0.25, one * 0.10) / 10000.0)) * 10000)


def sponsor_end(body):
    """pc328: klub raskida ugovor prije isteka: placa odstetu, mjesto je odmah slobodno (nove ponude od danas, 30 dana za odgovor)."""
    slot, place = body['slot'], body.get('part') or 'chest'
    if place not in SPON_PARTS:
        raise ValueError('Unknown sponsor place.')
    key, _f, title = SPON_PARTS[place]
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    season = _spon_season(gd)
    cid = _career_id(slot, s)
    with INV_LOCK:
        A = _inv_all()
        E = A.setdefault(cid, {})
        sp = E.get(key)
        if not sp or sp.get('until', 0) < season:
            raise ValueError('There is no %s to end.' % title.lower())
        fee = _spon_exit_fee(sp, season)
        sp['until'] = season - 1
        sp['ended'] = dict(d=_fmt_date(gd), by='club', fee=fee)
        if fee:
            E.setdefault('spon_pay', []).append(dict(id='%s-exit-%d' % (sp.get('id'), season), amount=-fee, why='%s: early termination fee' % sp['brand'], done=False))
        off = E.setdefault('spon_off', {})
        off[place] = dict(season=season, since=gd)
        E.setdefault('hist', []).append(dict(d=_fmt_date(gd), t='%s deal ended early by the club' % sp['brand'], a=0, k='sponsor'))
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    _spon_auto(slot, s)
    try:
        my = _my_club_name(s)
        _ev_add(slot, 'sponsor_end', 0, club=my, brand=sp['brand'], place=place, fee=fee, _nofan=True,
                head='%s end their deal with %s early' % (my, (sp['brand'][:-8] + "'s sponsor") if sp['brand'].endswith(' sponsor') else sp['brand']),
                lead='The club pays a termination fee of %s EUR. The %s is free for a new partner.' % ('{:,}'.format(fee), SPON_WHERE[place]))
    except Exception as ex:
        print('[sponsor] news:', ex)
    try:
        _kitsp_guard(slot, s, force=True)
    except Exception as ex:
        print('[kit sponsor] guard:', ex)
    return dict(ok=True, message='The %s deal with %s is over. Termination fee: %s EUR (taken from the transfer budget when the game is closed or on the main menu). New offers for this place have arrived.' % (
        title.lower(), sp['brand'], '{:,}'.format(fee)))


def _spon_tick(slot, s):
    """Nova sezona: godisnja rata; kraj sezone (pregled uprave): bonus za plasman. Poziva se iz state()."""
    try:
        R = _inv_rec(slot, s)
        for key in ('spon', 'spon_sleeve', 'spon_back'):
            if R.get(key):
                _spon_tick_one(slot, s, key, R[key])
    except Exception as ex:
        print('[sponsor] tick:', ex)


def _spon_tick_one(slot, s, key, sp):
    try:
        season = _spon_season(s.game_date_code())
        try:
            my_club = _my_club_name(s)
        except Exception:
            my_club = None
        add = []
        if sp.get('yearly') and sp['since'] <= season <= sp['until'] and season not in (sp.get('paid_seasons') or []):
            add.append(('fee', season, sp['yearly'], '%s: season fee (%d/%02d)' % (sp['brand'], season, (season + 1) % 100)))
        if sp.get('bonus'):
            try:
                B = (json.load(open(BOARD_FILE, encoding='utf-8')) or {}).get(_career_id(slot, s)) or {}
                for x in B.get('seasons') or []:
                    if x.get('club') and x['club'] != my_club:   # pc343: sezona u drugom klubu ne vrijedi za ovog sponzora
                        continue
                    sy = int(str(x.get('season', '0/0')).split('/')[0])
                    if sp['since'] <= sy <= sp['until'] and x.get('met') and sy not in (sp.get('bonus_seasons') or []):
                        amt = sp['bonus'] * (2 if x.get('pos') == 1 else 1)
                        add.append(('bonus', sy, amt, '%s: performance bonus (%s%s)' % (sp['brand'], x['season'], ', title' if x.get('pos') == 1 else '')))
            except Exception:
                pass
        rel = []
        try:   # pc328: klauzula o ispadanju: godisnja rata pola za svaku sezonu nakon ispadanja
            B = (json.load(open(BOARD_FILE, encoding='utf-8')) or {}).get(_career_id(slot, s)) or {}
            for x in B.get('seasons') or []:
                if x.get('club') and x['club'] != my_club:
                    continue
                sy = int(str(x.get('season', '0/0')).split('/')[0])
                down = str(x.get('result') or '').startswith('relegated') or (x.get('pos') and x.get('n') and x['n'] >= 16 and x['pos'] > x['n'] - 3)
                if down and sp['since'] <= sy < sp['until'] and sy not in (sp.get('releg_seasons') or []) and sp.get('yearly'):
                    rel.append(sy)
        except Exception:
            pass
        if not add and not rel:
            return
        with INV_LOCK:
            A = _inv_all()
            E = A.setdefault(_career_id(slot, s), {})
            sp2 = E.get(key) or {}
            for sy in rel:
                if sy in (sp2.get('releg_seasons') or []):
                    continue
                sp2.setdefault('releg_seasons', []).append(sy)
                sp2['yearly'] = int(round(sp2.get('yearly', 0) / 2.0 / 50000.0)) * 50000
                E.setdefault('hist', []).append(dict(d=_fmt_date(s.game_date_code()), t='%s: relegation clause, the yearly fee is now %s' % (sp2.get('brand'), '{:,}'.format(sp2['yearly'])), a=0, k='sponsor'))
            for k, sy, amt, why in add:
                fld = 'paid_seasons' if k == 'fee' else 'bonus_seasons'
                if sy in (sp2.get(fld) or []):
                    continue
                if k == 'fee':   # pc343: ako je klauzula o ispadanju upravo smanjila ratu, placa se nova (manja) rata
                    amt = sp2.get('yearly') or 0
                    why = '%s: season fee (%d/%02d)' % (sp2.get('brand'), sy, (sy + 1) % 100)
                    if not amt:
                        continue
                sp2.setdefault(fld, []).append(sy)
                E.setdefault('spon_pay', []).append(dict(id='%s-%s-%d' % (sp2.get('id'), k, sy), amount=int(amt), why=why, done=False))
            _jdump(A, INV_FILE, ensure_ascii=False, indent=1)
    except Exception as ex:
        print('[sponsor] tick:', ex)


def _spon_pay(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = _career_id(slot, s)
    with INV_LOCK:
        pend = [p_ for p_ in (_inv_all().get(cid, {}).get('spon_pay') or []) if not p_.get('done')]
    if not pend:
        return
    tot = sum(p_['amount'] for p_ in pend)
    _write_slot(slot, 'sponsor', lambda sv: (sv.adjust_budget(tot), 'Sponsorship: %s EUR (%s).' % ('{:,}'.format(tot), '; '.join(p_['why'] for p_ in pend)))[1])
    ids = {p_['id'] for p_ in pend}
    with INV_LOCK:
        A = _inv_all()
        E = A.setdefault(cid, {})
        for p_ in E.get('spon_pay') or []:
            if p_['id'] in ids:
                p_['done'] = True
                p_['paid'] = _fmt_date(s.game_date_code())
                E.setdefault('hist', []).append(dict(d=p_['paid'], t=p_['why'], a=p_['amount'], k='sponsor'))
        _jdump(A, INV_FILE, ensure_ascii=False, indent=1)


_SPON_BUSY = threading.Lock()


def _spon_auto(slot, s):
    if DEV or game_blocks():
        return
    R = _inv_rec(slot, s)
    if not any(not p_.get('done') for p_ in (R.get('spon_pay') or [])):
        return
    def go():
        if not _SPON_BUSY.acquire(blocking=False):
            return
        try:
            _spon_pay(slot)
        except Exception as ex:
            print('[sponsor] pay:', ex)
        finally:
            _SPON_BUSY.release()
    threading.Thread(target=go, daemon=True).start()


def inbox_extra(slot):
    """pc317: jedan poziv za sve dodatke Inboxa (prije 4-5 zasebnih zahtjeva jedan za drugim)."""
    out = dict(ok=True)
    for k, fn in (('finance', finance_view), ('board', board_view), ('precon', precon_view), ('invest', invest_view), ('sponsor', sponsor_view)):
        try:
            out[k] = fn(slot)
        except Exception as ex:
            out[k] = dict(ok=False, error=str(ex)[:160])
    return out


# ---------------------------------------------------------------- pc322: sponzor na pravom dresu (Sider kit-server)
def _ks_fl27_root():
    """pc384: content\\kits FL27 kit-servera (modul common\\kits.lua) ili ''."""
    try:
        root = _sider_root()
        d = os.path.join(root, 'content', 'kits') if root else ''
        return d if d and os.path.isfile(os.path.join(d, 'map.txt')) and _is_fl27_setup() else ''
    except Exception:
        return ''


def _ks_fl27_make(tid, club):
    """r11: FL27 kept its kits only inside the game's CPK archives.  Archive reading
    was removed with the logo/CPK importers, so there is no longer a source to copy
    a working kit from.  Loose kit-server files (content\\kits) still work normally.
    -> always None."""
    return None


def _ks_fl27_unmap(tid, name):
    """pc387: red u map.txt se NE dodaje: kit-server za licencirane dresove (realUni) igri podmetne prazan .bin i postavke iz
    config.txt, pa bez punog configa dres dobije krivi kroj (dubok V, vidi se tijelo; Liverpool FL27, 2.11.2026). Moj stari red
    (pc384-386) se brise; dres igra cita iz livecpk (samo tekstura, kroj i ostalo ostaje igrino)."""
    kd = _ks_fl27_root()
    mp = os.path.join(kd, 'map.txt') if kd else ''
    if not mp or not os.path.isfile(mp):
        return
    txt = open(mp, encoding='utf-8', errors='ignore').read()
    new = re.sub(r'(?m)^[ \t]*%d[ \t]*,[ \t]*"%s"[ \t]*\r?\n?' % (tid, re.escape(name)), '', txt)
    if new != txt:
        with open(mp, 'w', encoding='utf-8', newline='') as f_:
            f_.write(new.replace('\r\n', '\n').replace('\n', '\r\n'))
        _GL.pop('ksmap_mt', None)
        print('[kit sponsor] FL27: removed kit-server line %d (kits now go through livecpk)' % tid)


def _ks_fl27_dir(tid, club):
    kd = _ks_fl27_root()
    if not kd:
        return ''
    name = 'TheGaffer_' + (re.sub(r'[^A-Za-z0-9]+', '_', club or '').strip('_') or str(tid))
    return os.path.join(kd, name)


def _ks_fl27_live(p, remove=False):
    """pc387: tekstura iz radne mape (TheGaffer_<klub>\\p<k>\\...) ide u livecpk na isti put kao u igri
    (npr. Asset/model/character/uniform/texture/#windx11/u0103p1.ftex). FL27: prvi livecpk korijen (livecpk\\root);
    pc389 FL26: vlastiti korijen livecpk\\TheGaffer_kits (prvi u sider.ini), pa se korisnikove datoteke nikad ne prepisuju.
    remove: obrisi tu kopiju (igra opet cita svoj dres)."""
    try:
        fn = os.path.basename(p)
        td = os.path.dirname(os.path.dirname(p))
        relp = None
        try:
            relp = json.load(open(os.path.join(td, 'live.json'), encoding='utf-8')).get(fn.lower())
        except Exception:
            pass
        if not relp:
            return None
        if _is_fl27_setup():
            roots = [r_ for r_ in _cpk_roots() if os.path.realpath(r_).startswith(os.path.realpath(os.path.join(_sider_root(), 'livecpk')))] or _cpk_roots()[:1]
            if not roots:
                return None
            dstroot = roots[0]
        else:
            dstroot = _ks_live_root(create=not remove)
            if not dstroot:
                return None
        dst = os.path.join(dstroot, *relp.replace('\\', '/').split('/'))
        if remove:
            if os.path.isfile(dst):
                os.remove(dst)
            return dst
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(p, dst)
        return dst
    except Exception as ex:
        print('[kit sponsor] livecpk:', ex)
        return None


KS_LIVE = 'TheGaffer_kits'


def _ks_live_root(create=False):
    """pc389 FL26 bez kit-servera: livecpk\\TheGaffer_kits, upisan kao PRVI cpk.root u sider.ini (prvi ima prednost),
    da sponzorirani dres nadjaca dres iz kit packa/igre. Prije izmjene sider.ini se spremi kopija. -> putanja ili ''."""
    root = _sider_root()
    if not root:
        return ''
    d = os.path.join(root, 'livecpk', KS_LIVE)
    if not create:
        return d
    os.makedirs(d, exist_ok=True)
    ini_p = os.path.join(root, 'sider.ini')
    try:
        ini = open(ini_p, encoding='utf-8', errors='ignore', newline='').read()
    except Exception:
        return d
    if re.search(r'^\s*cpk\.root\s*=\s*"[^"]*%s"' % re.escape(KS_LIVE), ini, re.M | re.I):
        return d
    nl = '\r\n' if '\r\n' in ini else '\n'
    line = 'cpk.root = ".\\livecpk\\%s"' % KS_LIVE
    m_ = re.search(r'^([ \t]*)cpk\.root\s*=', ini, re.M)
    if m_:
        new = ini[:m_.start()] + m_.group(1) + line + nl + ini[m_.start():]
    else:
        m2 = re.search(r'^\s*\[sider\][^\n]*\n', ini, re.M)
        new = (ini[:m2.end()] + line + nl + ini[m2.end():]) if m2 else (ini.rstrip('\r\n') + nl + line + nl)
    shutil.copy2(ini_p, ini_p + '.bak-gaffer-%s' % time.strftime('%Y%m%d_%H%M%S'))
    open(ini_p, 'w', encoding='utf-8', newline='').write(new)
    _GL.pop('roots', None)
    _GL.pop('kitdirs', None)
    _GL['ks_restart'] = True
    print('[kit sponsor] FL26: added %s as the first cpk.root in sider.ini' % line)
    return d


def _ks_fl26_dir(tid, club):
    return os.path.join(HERE, 'data', 'kitwork', 'TheGaffer_' + (re.sub(r'[^A-Za-z0-9]+', '_', club or '').strip('_') or str(tid)))


def _ks_fl26_make(tid, club, td):
    """pc389: FL26 bez kit-servera: kopije dresova mog kluba (iz livecpk paketa ili arhive igre) u radnu mapu appa
    (data\\kitwork\\TheGaffer_<klub>\\p<k>), uz live.json (put u igri). App crta sponzora na kopije, a rezultat ide u
    livecpk\\TheGaffer_kits. Original u igri/kit packu ostaje netaknut."""
    own = os.path.realpath(_ks_live_root())
    kits, live = [], {}
    for k in range(1, 10):
        fn = 'u%04dp%d.ftex' % (tid, k)
        src = relp = None
        for rt in _cpk_roots():
            if os.path.realpath(rt) == own:
                continue
            for sub in (('Asset',), ('common',), ('common', 'character0'), ('common', 'character1'), ()):
                cand = os.path.join(rt, *(sub + ('model', 'character', 'uniform', 'texture', '#windx11', fn)))
                if os.path.isfile(cand):
                    src, relp = cand, os.path.relpath(cand, rt).replace(os.sep, '/')
                    break
            if src:
                break
        if not src or not os.path.isfile(src):
            continue
        os.makedirs(os.path.join(td, 'p%d' % k), exist_ok=True)
        dst = os.path.join(td, 'p%d' % k, fn)
        if not os.path.isfile(dst):
            shutil.copyfile(src, dst)
        with open(os.path.join(td, 'p%d' % k, 'config.txt'), 'w', encoding='utf-8', newline='\r\n') as f_:
            f_.write('; The Gaffer working copy (not a kit-server entry)\nKitFile=u%04dp%d\n' % (tid, k))
        kits.append('p%d' % k)
        live[fn.lower()] = relp
    if not kits:
        return None
    with open(os.path.join(td, 'order.ini'), 'w', encoding='utf-8', newline='\r\n') as f_:
        f_.write('\n'.join(kits) + '\n')
    json.dump(live, open(os.path.join(td, 'live.json'), 'w', encoding='utf-8'), indent=1)
    print('[kit sponsor] FL26: working copies for %s (%d): %s' % (club, tid, ', '.join(kits)))
    return td


def _ks_fl27_sync(fd):
    """pc387: jednom po pokretanju: teksture sa sponzorom (imaju .orig) iz radne mape u livecpk (prijelaz s pc384-386)."""
    if _GL.get('ks27sync') == fd:
        return
    _GL['ks27sync'] = fd
    for root_, dirs_, files_ in os.walk(fd):
        for f in files_:
            if f.lower().endswith('.ftex') and os.path.isfile(os.path.join(root_, f + '.orig')):
                _ks_fl27_live(os.path.join(root_, f))


def _ks_team_dir(slot):
    """-> (mapa kluba u kit-serveru, team id, ime kluba) za moj klub."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    club = _my_club_name(s)
    tid = _team_id(club)
    if not tid:
        raise ValueError('The game team ID of %s was not found.' % club)
    _kitserver_tex(int(tid), 1)   # ucita map.txt
    rel = (_GL.get('ksmap') or {}).get(int(tid))
    ks = _ks_dir()
    fd = _ks_fl27_dir(int(tid), club)
    if fd and (not rel or os.path.basename(rel.rstrip(os.sep)) == os.path.basename(fd)):
        # pc387: FL27: radna mapa bez reda u map.txt; igra dres cita iz livecpk
        if not os.path.isdir(fd):
            _ks_fl27_make(int(tid), club)
        else:
            _ks_fl27_unmap(int(tid), os.path.basename(fd))
            _ks_fl27_sync(fd)
        if os.path.isdir(fd):
            return fd, int(tid), club
    if (not rel or not ks) and not _is_fl27_setup() and _sider_root():
        # pc389: FL26 bez kit-servera za moj klub: dres iz livecpk paketa/igre preko vlastitog livecpk korijena
        fd = _ks_fl26_dir(int(tid), club)
        if not os.path.isdir(fd) or not os.path.isfile(os.path.join(fd, 'live.json')):
            _ks_fl26_make(int(tid), club, fd)
        else:
            _ks_fl27_sync(fd)
        if os.path.isfile(os.path.join(fd, 'live.json')):
            return fd, int(tid), club
    if (not rel or not ks) and _ks_fl27_root():
        # pc384: FL27 nema dresova u kit-serveru: napravi zapis za moj klub od dresa iz arhive igre (isti dres; postavke ostaju igrine)
        made = _ks_fl27_make(int(tid), club)
        if made:
            _GL.pop('ksdir', None)
            _GL.pop('ksmap_mt', None)
            _kitserver_tex(int(tid), 1)
            rel = (_GL.get('ksmap') or {}).get(int(tid))
            ks = _ks_dir()
    if not rel or not ks:
        if _ks_empty_fl27():
            raise ValueError('Football Life 2027 keeps its kits inside the game files, not in the Sider kit-server (content\\kits\\map.txt is empty), '
                             'so sponsor logos on the kit are not available on FL27 yet. Your sponsor deals, money and everything else work normally.')
        raise ValueError('%s has no kits in the Sider kit-server (%s).' % (club, (os.path.relpath(os.path.join(ks, 'map.txt'), _sider_root()) if ks else 'content\\kit-server or content\\kits')))
    return os.path.join(ks, rel), int(tid), club


def kitsp_files(slot):
    """Glavne teksture igracih dresova mog kluba (p1, p2, p3, varijante i verzije natjecanja), bez golmanskih i brojeva."""
    td, tid, club = _ks_team_dir(slot)
    out = []
    for root_, dirs_, files_ in os.walk(td):
        kd = os.path.basename(root_).lower()
        if not re.match(r'p\d', kd):
            continue
        kf = None
        try:
            for line in open(os.path.join(root_, 'config.txt'), encoding='utf-8', errors='ignore'):
                m_ = re.match(r'\s*KitFile\s*=\s*([^\s;]+)', line)
                if m_:
                    kf = m_.group(1)
                    break
        except Exception:
            pass
        for f in files_:
            fl = f.lower()
            if not fl.endswith('.ftex') or re.search(r'_(back|leg|name)', fl):
                continue
            if kf and f[:-5].lower() != kf.lower() and not re.match(r'u%04dp\d' % tid, fl):
                continue
            p = os.path.join(root_, f)
            out.append(dict(rel=os.path.relpath(p, td).replace(os.sep, '/'), kit=os.path.relpath(root_, td).replace(os.sep, '/'),
                            orig=os.path.isfile(p + '.orig')))
    out.sort(key=lambda x: (x['kit'].count('/'), x['kit']))
    act = {}
    try:
        for part, P in (sponsor_view(slot).get('parts') or {}).items():
            a = P.get('active')
            if a:
                act[part] = dict(brand=a.get('brand'), logo=a.get('logo'))
    except Exception:
        pass
    note = ''
    if os.path.basename(td.rstrip(os.sep)).startswith('TheGaffer_'):
        note = ('Your club has no Sider kit-server entry, so the app swaps only the kit texture through livecpk (the game keeps its own kit settings). '
                'A kit-server setup is still the better option if you have one.')
        if _GL.get('ks_restart'):
            note += ' The app added its own livecpk folder to sider.ini: restart the game once so it is loaded.'
    return dict(ok=True, club=club, tid=tid, files=out, sponsor=(act.get('chest') or {}).get('brand'), parts=act,
                any_orig=any(x['orig'] for x in out), note=note)


def _kitsp_path(slot, rel):
    td, tid, club = _ks_team_dir(slot)
    p = os.path.realpath(os.path.join(td, rel))
    if not p.startswith(os.path.realpath(td) + os.sep) or not p.lower().endswith('.ftex'):
        raise ValueError('bad kit path')
    return p


def kitsp_region(slot, rel, part='chest'):
    import base64
    import kitsponsor
    if part in kitsponsor.PARTS:
        P = kitsponsor.PARTS[part]
        r = kitsponsor.region(_kitsp_path(slot, rel), P['rect'])
        sc = r['w'] / 2048.0
        x0, y0 = P['rect'][:2]
        r['inner'] = [int((v - (x0 if i % 2 == 0 else y0)) * sc) for i, v in enumerate(P['inner'])]
        r['center'] = [int((P['center'][0] - x0) * sc), int((P['center'][1] - y0) * sc)]
        r['box'] = [int(P['box'][0] * sc), int(P['box'][1] * sc)]
        r['rot'] = P['rot']
        r['apply_h'] = r['rh']
    else:
        r = kitsponsor.region(_kitsp_path(slot, rel))
        sc = r['w'] / 2048.0
        r['inner'] = [int(v * sc) - r['x0'] if i % 2 == 0 else int(v * sc) - r['y0'] for i, v in enumerate((840, 1196, 1210, 1430))]
        r['src_dy'] = int(kitsponsor.SRC_DY * sc)
        r['apply_h'] = int((kitsponsor.REGION[3] - kitsponsor.REGION[1]) * sc)
        # pc386: logo ne smije u izrez ovratnika: na V-izrezu (Liverpool FL27, 2.11.2026) unutrasnjost ovratnika uzima teksturu
        # do y ~1260 u sredini prsa; prije je vrh loga (ikona) bio na y 1215 i vidio se u ovratniku. Sad je vrh na 1262.
        r['center'] = [int((1024 - 768) * sc), int((1328 - 1152) * sc)]
        r['box'] = [int(330 * sc), int(132 * sc)]
        r['rot'] = 0
    r['part'] = part
    # pc333: brisanje samo oko starog loga (ili nista ako ga nema)
    r['erase'] = None
    if part in ('chest', 'sleeve'):
        bx = kitsponsor.old_logo_box(_kitsp_path(slot, rel), part)
        if bx:
            sc = r['w'] / 2048.0
            ox, oy = (768, 1152) if part == 'chest' else kitsponsor.PARTS[part]['rect'][:2]
            r['erase'] = [int((bx[0] - ox) * sc), int((bx[1] - oy) * sc), int((bx[2] - ox) * sc), int((bx[3] - oy) * sc)]
    r['rgba'] = base64.b64encode(r['rgba']).decode()
    return dict(ok=True, **r)


def kitsp_apply(body):
    import base64
    import kitsponsor
    p = _kitsp_path(body['slot'], body['rel'])
    part = body.get('part') or 'chest'
    rect = kitsponsor.PARTS[part]['rect'] if part in kitsponsor.PARTS else kitsponsor.REGION
    n = kitsponsor.apply(p, base64.b64decode(body['rgba']), rect=rect)
    if os.path.basename(os.path.dirname(os.path.dirname(p))).startswith('TheGaffer_'):
        _ks_fl27_live(p)   # pc387: FL27 dres ide kroz livecpk; pc389: i FL26 bez kit-servera (livecpk\\TheGaffer_kits)
    try:
        s_ = mlwrite.Save(slot_folder(body['slot']), ro=True)
        _kitsp_mark(_ks_team_dir(body['slot'])[0], _career_id(body['slot'], s_), part)
    except Exception as ex:
        print('[kit sponsor] mark:', ex)
    return dict(ok=True, size=n)


KITSP_APPLIED = os.path.join(HERE, 'data', 'kitsp_applied.json')


def _kitsp_mark(td, cid, part):
    try:
        A = json.load(open(KITSP_APPLIED, encoding='utf-8'))
    except Exception:
        A = {}
    rec = A.get(td)
    if not rec or rec.get('career') != cid:
        rec = dict(career=cid, parts=[])
    if part not in rec['parts']:
        rec['parts'].append(part)
    A[td] = rec
    _jdump(A, KITSP_APPLIED, ensure_ascii=False, indent=1)


def _kitsp_guard(slot, s, force=False):
    """pc328: dresovi nose sponzore samo dok traje ugovor TE karijere. Nova karijera (ili drugi save) -> originalni dresovi;
    istekao ili raskinut ugovor -> taj dio dresa se vraca na original (ostali ostaju)."""
    import kitsponsor
    try:
        A = json.load(open(KITSP_APPLIED, encoding='utf-8'))
    except Exception:
        return
    if not A:
        return
    cid = _career_id(slot, s)
    R = _inv_rec(slot, s)
    season = _spon_season(s.game_date_code())
    act = {p_ for p_, (k_, _f, _t) in SPON_PARTS.items() if R.get(k_) and R[k_].get('until', 0) >= season}
    changed = False
    def each(td):
        for root_, dirs_, files_ in os.walk(td):
            for f in files_:
                if f.lower().endswith('.ftex.orig'):
                    yield os.path.join(root_, f[:-5])
    try:
        my_td = _ks_team_dir(slot)[0]
    except Exception:
        my_td = None
    for td, rec in list(A.items()):
        if not os.path.isdir(td):
            del A[td]
            changed = True
            continue
        if rec.get('career') != cid or (my_td and td != my_td):   # pc339: druga karijera ILI stari klub (otkaz / novi posao)
            n = sum(1 for fp in each(td) if kitsponsor.restore(fp))
            print('[kit sponsor] other career: restored %d original kit textures in %s' % (n, td))
            del A[td]
            changed = True
            continue
        gone = [p_ for p_ in rec.get('parts') or [] if p_ not in act]
        if not gone:
            continue
        if not [p_ for p_ in rec['parts'] if p_ in act]:
            for fp in each(td):
                kitsponsor.restore(fp)
            del A[td]
        else:
            for fp in each(td):
                for p_ in gone:
                    try:
                        kitsponsor.restore_part(fp, p_)
                    except Exception as ex:
                        print('[kit sponsor] restore part:', ex)
            rec['parts'] = [p_ for p_ in rec['parts'] if p_ in act]
        changed = True
    if changed:
        _jdump(A, KITSP_APPLIED, ensure_ascii=False, indent=1)


def _kitsp_on(slot, s):
    """Dijelovi dresa na kojima je sponzor ove karijere vec nacrtan."""
    try:
        A = json.load(open(KITSP_APPLIED, encoding='utf-8'))
        td = _ks_team_dir(slot)[0]
        rec = A.get(td) or {}
        return rec.get('parts') or [] if rec.get('career') == _career_id(slot, s) else []
    except Exception:
        return []


# ---------------------------------------------------------------- pc332: zaustavi igru na odabrani dan (kalendar ML-a)
STOPS_FILE = os.path.join(HERE, 'data', 'stops.json')


def _stops_all():
    try:
        return json.load(open(STOPS_FILE, encoding='utf-8'))
    except Exception:
        return {}


def stops_view(slot):
    """Dani na koje je app stavio zaustavljanje (dogadjaj 0x20/0xffeb "Club ranking update": igra stane taj dan) + prijedlozi."""
    import datetime
    s = mlwrite.Save(slot_folder(slot), ro=True)
    loc = s.calendar_loc()
    gd = s.game_date_code()
    today = datetime.date(gd & 0xffff, (gd >> 16) & 0xff, gd >> 24)
    cid = _career_id(slot, s)
    L = []
    for e in _stops_all().get(cid, []):
        try:
            y, m, d = (int(x) for x in e['d'].split('-'))
            on = any((t_, p_) == s.CAL_STOP for _j, t_, p_ in s.cal_events(y, m, d))
        except Exception:
            on = False
            y = m = d = 0
        try:
            nm = s.cal_matches(y, m, d) if y else 0
        except Exception:
            nm = 0
        L.append(dict(e, past=bool(y) and datetime.date(y, m, d) < today, on=on, matches=nm, label=_fmt_due((d << 24) | (m << 16) | y) if y else e['d']))
    sug = []
    if loc:
        st, rs, yj = loc
        for (y, m, d) in s.cal_window_ends():
            if datetime.date(y, m, d) > today:
                sug.append(dict(d='%d-%02d-%02d' % (y, m, d), label=_fmt_due((d << 24) | (m << 16) | y), why='Transfer deadline day'))
        for (y, m, d, why) in ((yj - 1, 12, 31, 'Last day of the year'), (yj, 6, 30, 'Last day of the season')):
            if datetime.date(y, m, d) > today:
                sug.append(dict(d='%d-%02d-%02d' % (y, m, d), label=_fmt_due((d << 24) | (m << 16) | y), why=why))
    return dict(ok=bool(loc), stops=sorted(L, key=lambda x: x['d']), suggest=sug, today=today.isoformat(),
                season=('%d-07-01' % (loc[2] - 1), '%d-06-30' % loc[2]) if loc else None,
                note=None if loc else 'The season calendar was not found in this save.')


STOPS_ENABLED = False   # pc350: dogadjaj u kalendaru je srusio igru (Liverpool 16./18.8.); iskljuceno dok ne provjerimo s testerom


def _stops_cleanup(slot, s):
    """pc350: sva zaustavljanja koja je app upisao u ovu karijeru se maknu iz savea (kad je save siguran za upis); popis se brise
    tek kad upis uspije. Dogadjaji koje je igra sama stavila se ne diraju (brise se samo tocno nas zapis s tim datumom)."""
    if STOPS_ENABLED or DEV or game_blocks():
        return
    cid = _career_id(slot, s)
    A = _stops_all()
    L = A.get(cid) or []
    if not L:
        return
    days = []
    for e in L:
        try:
            y, m, d = (int(x) for x in e['d'].split('-'))
            days.append((y, m, d))
        except Exception:
            pass
    def fn(sv):
        n = sum(1 for (y, m, d) in days if sv.cal_remove_stop(y, m, d) == 'removed')
        return 'Removed %d game stops added by the app' % n
    if days:
        _write_slot(slot, 'stops-off', fn)
    A.pop(cid, None)
    _jdump(A, STOPS_FILE, ensure_ascii=False, indent=1)
    print('[stops] removed app stops from %s: %s' % (slot, ', '.join(e['d'] for e in L)))


def stop_add(body):
    if not STOPS_ENABLED:
        raise ValueError('Stopping the game on a day is switched off for now (it crashed the game).')
    import datetime
    slot = body['slot']
    try:
        y, m, d = (int(x) for x in str(body.get('d') or '').split('-'))
        dt = datetime.date(y, m, d)
    except Exception:
        raise ValueError('Pick a date.')
    s0 = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s0.game_date_code()
    if dt <= datetime.date(gd & 0xffff, (gd >> 16) & 0xff, gd >> 24):
        raise ValueError('Pick a day after today in the game.')
    loc = s0.calendar_loc()
    if not loc:
        raise ValueError('The season calendar was not found in this save.')
    if not (datetime.date(loc[2] - 1, 7, 1) <= dt <= datetime.date(loc[2], 6, 30)):   # pc343: kalendar ima samo ovu sezonu
        raise ValueError('Pick a day in this season (until 30 Jun %d). The next season calendar is made by the game in the summer.' % loc[2])
    res = {}

    def fn(sv):
        res['r'] = sv.cal_add_stop(y, m, d)
        return 'Stop on %s' % dt.isoformat()
    _write_slot(slot, 'stop', fn)
    cid = _career_id(slot, s0)
    A = _stops_all()
    L = A.setdefault(cid, [])
    if res.get('r') == 'added' and not any(e['d'] == dt.isoformat() for e in L):
        L.append(dict(d=dt.isoformat(), why=str(body.get('why') or '')[:80], added=_fmt_date(gd)))
        _jdump(A, STOPS_FILE, ensure_ascii=False, indent=1)
        try:
            nm = s0.cal_matches(y, m, d)
        except Exception:
            nm = 0
        warn = (' Note: there are already %d matches that day, so the game would stop there anyway; to test it, pick a day without matches.' % nm) if nm else ''
        return dict(ok=True, message='Done: in the game, the calendar now shows "Club ranking update" on %s and the game stops on that day when you continue. Load the career in the game (Load from the main menu).%s' % (_fmt_due((d << 24) | (m << 16) | y), warn))
    return dict(ok=True, message='The game already stops on that day.')


def stop_remove(body):
    slot, ds = body['slot'], str(body.get('d') or '')
    s0 = mlwrite.Save(slot_folder(slot), ro=True)
    cid = _career_id(slot, s0)
    A = _stops_all()
    L = A.get(cid, [])
    if not any(e['d'] == ds for e in L):
        raise ValueError('Only stops added by the app can be removed.')
    y, m, d = (int(x) for x in ds.split('-'))
    _write_slot(slot, 'stop', lambda sv: (sv.cal_remove_stop(y, m, d), 'Stop removed')[1])
    A[cid] = [e for e in L if e['d'] != ds]
    _jdump(A, STOPS_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, message='Removed: the game no longer stops on %s.' % _fmt_due((d << 24) | (m << 16) | y))


def kitsp_logo(tid, part):
    """PNG sponzora s dresa kluba tid (prsa ili rukav) ili None."""
    fp = _ks_donor_logo(int(tid), 'sleeve' if part == 'sleeve' else 'chest')
    return open(fp, 'rb').read() if fp else None


def kitsp_restore(body):
    import kitsponsor
    td, tid, club = _ks_team_dir(body['slot'])
    n = 0
    for root_, dirs_, files_ in os.walk(td):
        for f in files_:
            if f.lower().endswith('.ftex.orig'):
                if kitsponsor.restore(os.path.join(root_, f[:-5])):
                    n += 1
                    if os.path.basename(td.rstrip(os.sep)).startswith('TheGaffer_'):
                        _ks_fl27_live(os.path.join(root_, f[:-5]), remove=True)
    try:
        A = json.load(open(KITSP_APPLIED, encoding='utf-8'))
        if A.pop(td, None) is not None:
            _jdump(A, KITSP_APPLIED, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return dict(ok=True, restored=n, message='Restored %d original kit texture%s for %s.' % (n, '' if n == 1 else 's', club))


def _board_money_auto(slot, s):
    try:
        B = (json.load(open(BOARD_FILE, encoding='utf-8')) or {}).get(_career_id(slot, s)) or {}
    except Exception:
        return
    M = B.get('money')
    if not M or M.get('done') or int(M.get('amount') or 0) <= 0 or DEV or game_blocks():
        return
    threading.Thread(target=lambda: _safe(board_money_collect, slot), daemon=True).start()


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as ex:
        print('[bg]', getattr(fn, '__name__', fn), ex)


def board_money_collect(slot):
    with BOARD_LOCK:
        s0 = mlwrite.Save(slot_folder(slot), ro=True)
        cid = _career_id(slot, s0)
        ALL = json.load(open(BOARD_FILE, encoding='utf-8'))
        B = ALL.get(cid) or {}
        M = B.get('money')
        if not M or M.get('done') or int(M.get('amount') or 0) <= 0:
            return dict(ok=False, message='Nothing to collect.')
        amt = int(M['amount'])

        def fn(s):
            if amt < 0 and s.budget() + amt < 0:
                s.adjust_budget(-s.budget())
            else:
                s.adjust_budget(amt)
            return ('Board %s for %s: %s EUR (%s).' % ('bonus' if amt > 0 else 'fine', M['season'], '{:,}'.format(abs(amt)), M['why']))
        r = _write_slot(slot, 'board', fn)
        M['done'] = True
        _jdump(ALL, BOARD_FILE, ensure_ascii=False, indent=1)
        return dict(ok=True, message=('Added %s EUR to the transfer budget.' if amt > 0 else 'Took %s EUR from the transfer budget.') % '{:,}'.format(abs(amt)), detail=r)


def board_view(slot):
    """Uprava u appu: cilj sezone, povjerenje (tjedno prema tablici i formi), poruke, reputacija i povijest poslova menadzera."""
    with BOARD_LOCK:
        s = mlwrite.Save(slot_folder(slot), ro=True)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        club = _my_club_name(s)
        try:
            cid = _career_id(slot, s)
        except Exception:
            cid = slot
        try:
            ALL = json.load(open(BOARD_FILE, encoding='utf-8'))
        except Exception:
            ALL = {}
        B = ALL.setdefault(cid, {})
        code = s.game_date_code()
        y, m, dd = _date_tuple(code)
        daynum = y * 372 + m * 31 + dd
        today = _fmt_date(code)
        season = y if m >= 7 else y - 1
        clubs = _tier_clubs(s, my)
        strength = {i: c['strength'] for i, c in clubs.items()}
        mo = sorted((rat(q)[0] for q in s.my_squad_tags() if rat(q)[0]), reverse=True)[:14]
        strength[my] = sum(mo) / len(mo) if mo else 70
        allstr = sorted(strength.values(), reverse=True)
        rk = allstr.index(strength[my]) if strength[my] in allstr else len(allstr)
        tier = 'big' if rk < 0.09 * len(allstr) else 'mid' if rk < 0.49 * len(allstr) else 'small'
        cur = B.get('cur')
        msgs = B.setdefault('msgs', [])

        def msg(kind, **kw):
            msgs.append(dict(kind=kind, d=today, club=club, **kw))
            del msgs[:-40]
        if 'rep' not in B:
            B['rep'] = boardlib.start_rep(tier)
            # poslovi prije uprave u appu (careers.json, npr. Como prije Fiorentine): promjena kluba usred sezone = otkaz
            try:
                for j in (json.load(open(CAREER_FILE, encoding='utf-8')).get(slot) or {}).get('jobs') or []:
                    nm = j.get('name') or aitransfers._club_name(s.d, int(j['club']))
                    mid = True
                    mm_ = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', str(j.get('until') or ''))
                    if mm_ and int(mm_.group(2)) in (6, 7):
                        mid = False
                    B.setdefault('jobs', []).append(dict(club=nm, to=j.get('until') if mm_ else None, reason='sacked' if mid else 'left'))
                    if mid:
                        B['rep'] = max(0, B['rep'] - 8)
            except Exception as ex:
                print('[board] jobs:', ex)
        if cur and cur.get('idx') != my and cur.get('club') == club:   # pc346: isti klub, drugi raspored zapisa (npr. drugi format savea) -> isti posao
            cur['idx'] = my
        if not cur or cur.get('idx') != my:
            if cur:
                sacked = cur.get('trust', 50) <= 30 or m not in (6, 7)   # u ML-u se usred sezone klub mijenja samo nakon otkaza
                B.setdefault('jobs', []).append(dict(club=cur.get('club'), frm=cur.get('since'), to=today, reason='sacked' if sacked else 'left',
                                                     trust=round(cur.get('trust', 0)), pos=cur.get('pos'), goal=cur.get('goal')))
                if sacked:
                    B['rep'] = max(0, B['rep'] - 8)
                    msg('sacked_recorded', old=cur.get('club'))
                if {'big': 3, 'mid': 2, 'small': 1}[tier] > {'big': 3, 'mid': 2, 'small': 1}.get(cur.get('tier'), 2):
                    B['rep'] = min(100, B['rep'] + 5)
            cur = B['cur'] = dict(idx=my, club=club, since=today, trust=(60 if not B.get('jobs') else 55), tier=tier, last=daynum)
            msg('welcome', old=(B.get('jobs') or [{}])[-1].get('club'))
        cur['club'], cur['tier'] = club, tier
        prev_league, prev_lstr = cur.get('league'), cur.get('lg_str')
        row, n, rows = None, 0, []
        try:
            for c in comps_view(slot).get('comps') or []:
                if c.get('kind') == 'league':
                    r_ = next((r for r in c.get('rows') or [] if r.get('idx') == my), None)
                    if r_:
                        row, rows, n = r_, c['rows'], len(c['rows'])
                        cur['league'] = c.get('name')
                        break
        except Exception as ex:
            print('[board] comps:', ex)
        if row:
            exp = coaches.expected_positions(rows, strength).get(my, n)
            try:
                _ls = [strength[r_['idx']] for r_ in rows if r_.get('idx') in strength]
                lstr = round(sum(_ls) / len(_ls), 2) if _ls else None
            except Exception:
                lstr = None
            if cur.get('season') is not None and cur.get('season') != season and not cur.get('review'):
                # pc238: kraj prosle sezone app nije vidio (save spremljen tek nakon 1.7., igra tad obrise rezultate).
                # Iz promjene lige se ipak zna ispadanje / promocija; ostalo se ne moze izracunati.
                res = 'unknown'
                if prev_league and prev_league != cur.get('league') and prev_lstr and lstr:
                    res = 'relegated' if lstr < prev_lstr - 1.0 else 'promoted' if lstr > prev_lstr + 1.0 else 'unknown'
                if cur.get('releg_math'):
                    res = 'relegated_seen' if res in ('relegated', 'unknown') else res
                if res == 'relegated':
                    B['rep'] = max(0, B['rep'] - 10)
                    cur['trust'] = max(0.0, cur['trust'] - 20)
                elif res == 'promoted':
                    B['rep'] = min(100, B['rep'] + 6)
                    cur['trust'] = min(100.0, cur['trust'] + 15)
                B.setdefault('seasons', []).append(dict(season='%d/%02d' % (cur['season'], (cur['season'] + 1) % 100), club=club, pos=None, n=cur.get('n'),
                                                        target=cur.get('target'), goal=cur.get('goal'), met=(res == 'promoted') or None, rep_d=None, pts=None,
                                                        missed=True, result=res, league=prev_league))
                msg('season_missed', result=res, old=prev_league, new=cur.get('league'))
            cur['lg_str'] = lstr
            if cur.get('season') != season:
                for _k in ('releg_math', 'champ_math', 'safe_math', 'goal_lost'):
                    cur.pop(_k, None)
                g, tp = boardlib.goal_for(exp, n)
                cur.update(season=season, goal=g, target=tp, exp=exp, n=n, praised=False, review=False)
                msg('objective', goal=g, target=tp)
            cur['pos'], cur['pl'], cur['n'] = row.get('pos'), row.get('pl'), n
            weeks = min(6, (daynum - cur.get('last', daynum)) // 7)
            if weeks >= 1 and (row.get('pl') or 0) >= 5:
                try:
                    forms = aimanager.form_table(seasonstats.compute(s.d), mlsave.club_layout(s.d)[0])
                    f = aimanager.form_of(forms.get(my, []))
                except Exception:
                    f = None
                from datetime import date as _dt
                try:
                    dy, dm, ddd = [int(x) for x in cur['since'].split('/')][::-1]
                    days_in = (_dt(y, m, dd) - _dt(dy, dm, ddd)).days
                except Exception:
                    days_in = 999
                p = coaches.pressure(dict(row, pos=row.get('pos')), cur.get('target', exp), n, f, tier, days_in)
                lv0 = boardlib.level(cur['trust'])
                wd = boardlib.week_delta(p)
                try:
                    if wd > 0 and (row.get('pl') or 0) >= 5 and (row.get('pts') or 0) / float(row.get('pl')) < 1.2:
                        wd = 0.0   # pc398: uz los prosjek bodova (ispod 1,2 po utakmici) povjerenje ne raste
                except Exception:
                    pass
                for _ in range(weeks):
                    cur['trust'] = max(0.0, min(100.0, cur['trust'] + wd))
                cur['p'] = p
                cur.setdefault('hist', []).append(dict(d=today, t=round(cur['trust'], 1), pos=row.get('pos')))
                del cur['hist'][:-60]
                lv1 = boardlib.level(cur['trust'])
                if lv1 != lv0:
                    msg('level', lvl=lv1, pos=row.get('pos'), target=cur.get('target'))
                if lv1 == 'delighted' and not cur.get('praised'):
                    cur['praised'] = True
            if weeks >= 1:
                cur['last'] = daynum
            # pc238: matematicki sigurni ishodi (dvokruzna liga: 2*(n-1) utakmica)
            try:
                tot_g = 2 * (n - 1)
                if n >= 8 and all((r.get('pl') or 0) <= tot_g for r in rows) and (row.get('pl') or 0) >= 5:
                    mx = {r['idx']: (r.get('pts') or 0) + 3 * (tot_g - (r.get('pl') or 0)) for r in rows}
                    mine_pts, mine_max = row.get('pts') or 0, mx[my]
                    others = [r for r in rows if r['idx'] != my]
                    nrel = 3 if n >= 16 else 2 if n >= 10 else 1
                    above = sum(1 for r in others if (r.get('pts') or 0) > mine_max)          # sigurno ispred mene
                    below = sum(1 for r in others if mx[r['idx']] < mine_pts)                # ne mogu me stici
                    tp_ = cur.get('target', n)
                    if above >= n - nrel and not cur.get('releg_math'):
                        cur['releg_math'] = True
                        cur['trust'] = max(0.0, cur['trust'] - 20)
                        B['rep'] = max(0, B['rep'] - 6)
                        msg('relegated_math', pos=row.get('pos'))
                    elif below >= n - 1 and not cur.get('champ_math'):
                        cur['champ_math'] = True
                        cur['trust'] = min(100.0, cur['trust'] + 10)
                        msg('champion_math', pos=1)
                    elif below >= nrel and not cur.get('safe_math') and cur.get('goal') == 'survive':
                        cur['safe_math'] = True
                        cur['trust'] = min(100.0, cur['trust'] + 6)
                        msg('safe_math', pos=row.get('pos'))
                    if above >= tp_ and not cur.get('goal_lost') and not cur.get('releg_math'):
                        cur['goal_lost'] = True
                        cur['trust'] = max(0.0, cur['trust'] - 8)
                        msg('goal_lost', pos=row.get('pos'), target=tp_)
            except Exception as ex:
                print('[board] math:', ex)
            full = rows and all((r.get('pl') or 0) >= 2 * (n - 1) for r in rows)
            if (full or (m in (6, 7) and (row.get('pl') or 0) >= n)) and not cur.get('review'):
                cur['review'] = True
                tp = cur.get('target', n)
                met = (row.get('pos') or n) <= tp
                d_ = boardlib.season_rep(row.get('pos') or n, tp, n, champion=(row.get('pos') == 1))
                B['rep'] = max(0, min(100, B['rep'] + d_))
                cur['trust'] = max(0.0, min(100.0, cur['trust'] + (15 if met else -15)))
                B.setdefault('seasons', []).append(dict(season='%d/%02d' % (season, (season + 1) % 100), club=club, pos=row.get('pos'), n=n, target=tp,
                                                        goal=cur.get('goal'), met=met, rep_d=d_, pts=row.get('pts')))
                msg('season_review', met=met, pos=row.get('pos'), target=tp, rep_d=d_)
                try:   # pc316: nagrada / kazna uprave za kraj sezone (u transfer budzet, igrac je sam naplati)
                    amt, why = _board_season_money(s, row.get('pos') or n, tp, n, tier)
                    if amt:
                        B['money'] = dict(season='%d/%02d' % (season, (season + 1) % 100), amount=amt, why=why, d=today)
                        B['seasons'][-1]['money'] = amt
                except Exception as ex:
                    print('[board] money:', ex)
        ALL[cid] = B
        _jdump(ALL, BOARD_FILE, ensure_ascii=False, indent=1)
        # sto uprava gleda (za stranicu Board)
        factors, pace = [], None
        if row and (row.get('pl') or 0) > 0:
            n_ = n or 20
            tp = cur.get('target', n_)
            gap = (row.get('pos') or n_) - tp
            factors.append(dict(k='table', v='%s of %d (target: top %d)' % (row.get('pos'), n_, tp), s=(1 if gap <= 0 else -1 if gap >= 3 else 0)))
            ppg = row['pts'] / float(row['pl'])
            ppg_need = 2.3 - 1.5 * (tp - 1) / float(max(1, n_ - 1))
            pace = dict(ppg=round(ppg, 2), need=round(ppg_need, 2), proj=int(round(ppg * 2 * (n_ - 1))), proj_need=int(round(ppg_need * 2 * (n_ - 1))))
            factors.append(dict(k='pace', v='%.2f points per game (target pace %.2f)' % (ppg, ppg_need), s=(1 if ppg >= ppg_need else -1 if ppg < ppg_need - 0.3 else 0)))
            fm = row.get('form') or []
            if fm:
                fp_ = sum(3 if x == 'W' else 1 if x == 'D' else 0 for x in fm[-5:])
                factors.append(dict(k='form', v='%d points from the last %d' % (fp_, len(fm[-5:])), s=(1 if fp_ >= 10 else -1 if fp_ <= 4 else 0)))
            try:
                from datetime import date as _dt2
                dy, dm, ddd = [int(x) for x in cur['since'].split('/')][::-1]
                din = (_dt2(y, m, dd) - _dt2(dy, dm, ddd)).days
                if din < 45:
                    factors.append(dict(k='honeymoon', v='New in the job (%d days): the board is patient' % din, s=1))
            except Exception:
                pass
            if tier == 'big':
                factors.append(dict(k='club', v='Big club: high expectations, little patience', s=-1))
            elif tier == 'small':
                factors.append(dict(k='club', v='Small club: the board is more patient', s=1))
        return dict(club=club, career=cid, goal=cur.get('goal'), goal_txt=_goal_txt(slot, s, cur.get('goal')), target=cur.get('target'),
                    pos=cur.get('pos'), pl=cur.get('pl'), n=cur.get('n'), league=cur.get('league'), trust=round(cur.get('trust', 0)),
                    level=boardlib.level(cur.get('trust', 0)), p=cur.get('p'), since=cur.get('since'), rep=round(B['rep']), rep_label=boardlib.rep_label(B['rep']),
                    tier=tier, msgs=list(reversed(msgs[-12:])), jobs=B.get('jobs', []), manager=s.manager(),
                    all_msgs=list(reversed(msgs)), hist=cur.get('hist', []), factors=factors, pace=pace, form=(row or {}).get('form') or [],
                    seasons=B.get('seasons', []), pts=(row or {}).get('pts'), joined=_job_joined(slot, cur.get('since')),
                    money=(B.get('money') if B.get('money') and int(B['money'].get('amount') or 0) > 0 else None))


def _job_joined(slot, since):
    """Datum dolaska u sadasnji klub: kraj zadnjeg posla iz careers.json (prelazak u igri), inace prvi dan uprave u appu."""
    try:
        jobs = (json.load(open(CAREER_FILE, encoding='utf-8')).get(slot) or {}).get('jobs') or []
        if jobs and jobs[-1].get('until'):
            return jobs[-1]['until']
    except Exception:
        pass
    return since


def job_intro(slot, seen=False):
    """Uvod u novi posao (jednom po klubu): velika vijest + prica. seen=True oznaci kao vidjeno."""
    bd = board_view(slot)
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cid = bd.get('career') or slot
    with BOARD_LOCK:
        try:
            ALL = json.load(open(BOARD_FILE, encoding='utf-8'))
        except Exception:
            ALL = {}
        B = ALL.get(cid) or {}
        cur = B.get('cur') or {}
        key = '%s|%s|%s' % (cid, cur.get('club'), cur.get('since'))
        if seen:
            cur['intro_seen'] = key
            B['cur'] = cur
            ALL[cid] = B
            _jdump(ALL, BOARD_FILE, ensure_ascii=False, indent=1)
            return dict(ok=True)
        jobs = bd.get('jobs') or []
        if cur.get('intro_seen') == key or not jobs:
            return dict(show=False)
    old = jobs[-1]
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    prev = None
    try:
        b_ = struct.unpack_from('<I', coaches.read_block(s, my), 0)[0]
        nm = _coach_names().get(b_)
        if nm and nm != s.manager():
            prev = nm
    except Exception:
        pass
    gap_safe = gap_top = None
    try:
        for c in comps_view(slot).get('comps') or []:
            if c.get('kind') == 'league':
                rows = c.get('rows') or []
                me = next((r for r in rows if r.get('idx') == my), None)
                if me:
                    n = len(rows)
                    drop = sorted(rows, key=lambda r: r.get('pos') or 99)[n - 3] if n > 6 else None   # prvo mjesto za ispadanje
                    if drop:
                        gap_safe = -1 if (me.get('pos') or 0) >= drop.get('pos') else (me.get('pts') or 0) - (drop.get('pts') or 0)
                    gap_top = (rows and max(r.get('pts') or 0 for r in rows)) - (me.get('pts') or 0)
                break
    except Exception:
        pass
    it = jobintro.build(key, bd.get('manager'), bd.get('club'), old=old.get('club'), until=old.get('to'), reason=old.get('reason'),
                        old_pos=old.get('pos'), prev=prev, league=bd.get('league'), pos=bd.get('pos') if bd.get('pl') else None, n=bd.get('n'),
                        gap_safe=gap_safe, gap_top=gap_top, goal=bd.get('goal'), target=bd.get('target'))
    it.update(show=True, club=bd.get('club'), old=old.get('club'), reason=old.get('reason'), mgr=bd.get('manager'), league=bd.get('league'),
              joined=bd.get('joined'), prev=prev)
    # jednom i u vijesti (novine)
    try:
        ev = json.load(open(EV_FILE, encoding='utf-8')).get(slot) or []
        if not any(e.get('kind') == 'new_job' and e.get('jkey') == key for e in ev):
            _ev_add(slot, 'new_job', 0, jkey=key, club=bd.get('club'), old=old.get('club'), head=it['head'], lead=it['lead'], body=' '.join(it['paras']), _nofan=True)
    except Exception as ex:
        print('[job intro] ev:', ex)
    return it


def auto_tac_slot(slot, force=False):
    """pc176: AI obrada pise vise puta zaredom (taktike, formacije, fluidna formacija, postave). Potvrda 'glavni meni' vrijedi
    za cijelu obradu; prije se gasila nakon prvog upisa, pa su formacije / fluidna / postave tiho padale dok igra radi."""
    if not _MENU.get('batch'):
        _MENU['batch_wrote'] = False
    _MENU['batch'] = _MENU.get('batch', 0) + 1
    try:
        return _auto_tac_slot(slot, force)
    finally:
        _MENU['batch'] -= 1
        if not _MENU['batch'] and _MENU.get('batch_wrote') and game_running():
            _MENU['on'] = False


def _auto_tac_slot(slot, force=False):
    """AI menadzeri: dodijeli profile taktike klubovima i mijenja ih prema formi. Radi kad je save promijenjen i igra zatvorena."""
    import random as _rnd
    with AUTO_LOCK:
        st = auto_load()
        e = st.get(slot) or {}
        t = e.get('tac')
        if not t or not t.get('on'):
            return dict(ok=True, status='switched off')
        if game_blocks():  # igra upaljena: smije samo uz potvrdu "glavni izbornik" (gasi se kad igra spremi)
            return dict(ok=True, status='the game is running: waiting for confirmation that you are on the main menu (outside Master League)')
        p = os.path.join(CFG['save_dir'], slot) if not DEV else os.path.join(DEV, 'data.dat')
        if not os.path.exists(p):
            return dict(ok=False, status='no save')
        mt = os.path.getmtime(p)
        if not force and t.get('mtime') == mt:
            return dict(ok=True, status='no change')
        s = mlwrite.Save(slot_folder(slot))
        code = s.game_date_code()
        dd, mm, yy = code >> 24, (code >> 16) & 0xff, code & 0xffff
        t['mtime'] = mt
        t['date'] = '%d.%d.%d' % (dd, mm, yy)
        daynum = yy * 372 + mm * 31 + dd
        if not t.get('seed'):
            t['seed'] = _rnd.randint(1, 2 ** 31 - 1)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        try:
            clubs = _tier_clubs(s, my)
            M = seasonstats.compute(s.d)
            forms = aimanager.form_table(M, mlsave.club_layout(s.d)[0])
            cev = []
            try:
                cch, cev = coach_tick(slot, s, e, t, daynum, code, clubs, forms, my)
                if cch:
                    def _cfn(sv):
                        for idx_, blk_, tac_ in cch:
                            coaches.write_coach(sv, idx_, blk_)
                            if tac_:
                                sv.set_club_tactics(idx_, tac_)
                        return 'coaches %d' % len(cch)
                    _write_slot(slot, 'aicoach', _cfn)
                    s = mlwrite.Save(slot_folder(slot))
            except Exception as ex:
                print('[coach]', ex)
                cev = []
            changes, new = aimanager.plan(clubs, forms, t.get('clubs', {}), daynum, int(t['seed']), skip={my})
            # samo stvarne razlike prema trenutnom zapisu
            real = []
            for c in changes:
                cur = s.club_tactics(int(c['idx']))
                if cur is None:
                    continue
                df = _tac_diff(cur, c['tactics'])
                if df:
                    c['diff'] = df
                    c['cur'] = cur
                    real.append(c)
            backup = None
            if real:
                backup = _write_slot_tactics(slot, real)
            try:
                sw = [c for c in real if c['kind'] == 'switch']
                # pc353: novi trener donosi svoj sustav (Alex): klub s novim trenerom vecinom mijenja i formaciju
                appointed = [ev_ for ev_ in (cev or []) if ev_.get('coach_ev') in ('appointed', 'replaces_you') and ev_.get('idx') is not None]
                if sw or appointed:
                    s = mlwrite.Save(slot_folder(slot))
                    lib = _formation_library(s)
                    fch = []
                    for c in sw:
                        rnd_ = _rnd.Random(int(t['seed']) * 13 + int(c['idx']) * 7 + daynum)
                        if rnd_.random() > 0.7:
                            continue
                        fs = _formation_switch(s, int(c['idx']), c['prof_to'], rnd_, lib)
                        if fs:
                            fch.append(fs)
                            c['formation'] = [fs['frm'], fs['to']]
                    done_ = {int(c['idx']) for c in sw if c.get('formation')}
                    for ev_ in appointed:
                        ci_ = int(ev_['idx'])
                        if ci_ in done_ or ci_ == my:
                            continue
                        rnd_ = _rnd.Random(int(t['seed']) * 17 + ci_ * 11 + daynum)
                        if rnd_.random() > 0.75:
                            continue
                        prof_ = ((t.get('clubs') or {}).get(str(ci_)) or {}).get('p') or ev_.get('pt') or 'balanced'
                        fs = _formation_switch(s, ci_, prof_, rnd_, lib)
                        if fs:
                            fch.append(fs)
                            done_.add(ci_)
                            ev_['formation'] = [fs['frm'], fs['to']]
                            t.setdefault('newsys', {})[str(ci_)] = dict(day=daynum, frm=fs['frm'], to=fs['to'])
                    if fch:
                        def _ffn(sv):
                            for fs in fch:
                                sv.d[fs['plan']:fs['plan'] + len(fs['blk'])] = fs['blk']   # pc166: i formacije u posjedu / bez posjeda
                                if fs['blk'][33:66] != fs['blk'][:33] or fs['blk'][66:99] != fs['blk'][:33]:
                                    sv.d[fs['plan'] - 5 + FLUID_FLAG] = 1   # pc173: Fluid Formation On
                                sv.d[fs['blo']:fs['blo'] + len(fs['new'])] = bytes(fs['new'])
                            return 'formations %d' % len(fch)
                        _write_slot(slot, 'aiformation', _ffn)
            except Exception as ex:
                print('[formation]', ex)
            try:
                cid = _career_id(slot)
                if t.get('fluid2' if FLUID_FLAG_OK else 'fluid') != cid:   # pc173: ponovno, sad i s prekidacem
                    s = mlwrite.Save(slot_folder(slot))
                    fp_ = _fluid_plan(s, my)
                    if fp_:
                        def _flfn(sv):
                            for o_, b_ in fp_:
                                sv.d[o_:o_ + len(b_)] = b_
                            return 'fluid formations %d' % len(fp_)
                        _write_slot(slot, 'aifluid', _flfn)
                    t['fluid2' if FLUID_FLAG_OK else 'fluid'] = cid
                    t['fluid_n'] = len(fp_)
                    print('[fluid] %s: fluidna formacija ukljucena za %d klubova' % (slot, len(fp_)))
            except Exception as ex:
                print('[fluid]', ex)
            try:
                lu = e.setdefault('lu', {})
                _lu_verify(lu, M)
                if not lu.get('off'):
                    s = mlwrite.Save(slot_folder(slot))
                    try:   # pc353: odigrana utakmica s hitnom formacijom -> natrag na pravu formaciju
                        rest_ = _emerg_restore(s, lu, M)
                        if rest_:
                            def _rfn(sv):
                                for plan_, blk_, blo_, new_ in rest_:
                                    sv.d[plan_:plan_ + len(blk_)] = blk_
                                    if blo_ is not None:
                                        sv.d[blo_:blo_ + len(new_)] = bytes(new_)
                                return 'formations restored %d' % len(rest_)
                            _write_slot(slot, 'aiformation', _rfn)
                            s = mlwrite.Save(slot_folder(slot))
                    except Exception as ex:
                        print('[emergency formation] restore:', ex)
                    plans = ai_lineups_plan(slot, s, M, my)
                    if plans:
                        def _lfn(sv):
                            for pl_ in plans:
                                if pl_.get('form'):
                                    b_ = bytes.fromhex(pl_['form']['blk'])
                                    sv.d[pl_['form']['plan']:pl_['form']['plan'] + len(b_)] = b_
                                sv.d[pl_['blo']:pl_['blo'] + len(pl_['new'])] = bytes(pl_['new'])
                            return 'lineups %d' % len(plans)
                        _write_slot(slot, 'ailineup', _lfn)
                        for pl_ in plans:
                            if pl_.get('form'):
                                lu.setdefault('emerg', {}).setdefault(str(pl_['idx']), dict(n=pl_['n'], plan=pl_['form']['plan'], orig=pl_['form']['orig'],
                                                                                          frm=pl_['form']['frm'], to=pl_['form']['to'], date=pl_['date']))
                                try:
                                    world(slot, s).add_many([('ai_tactics', worldlib.date_str(code), 'emerg:%s:%s' % (pl_['idx'], pl_['n']), None, [pl_['club']],
                                                              dict(club=pl_['club'], change='emergency', frm=pl_['form']['frm'], to=pl_['form']['to'], opp=pl_['opp']))])
                                except Exception as ex:
                                    print('[world] emergency:', ex)
                        P = lu.setdefault('plans', {})
                        for pl_ in plans:
                            P['%s:%s' % (pl_['n'], pl_['idx'])] = dict(n=pl_['n'], idx=pl_['idx'], club=pl_['club'], date=pl_['date'], level=pl_['level'], xi=pl_['xi'])
                        lg_ = lu.setdefault('log', [])
                        for pl_ in plans:
                            lg_.append(dict(club=pl_['club'], idx=pl_['idx'], opp=pl_['opp'], date=pl_['date'], level=pl_['level'], why=pl_['why'],
                                            out=[NAMES.get(p_, str(p_)) for p_ in pl_['out']], inn=[NAMES.get(p_, str(p_)) for p_ in pl_['inn']],
                                            opp_idx=pl_['opp_idx'], vs_me=pl_['opp_idx'] == my))
                        lu['log'] = lg_[-300:]
                        lu['last'] = dict(date=t.get('date'), n=len(plans), big=sum(1 for p_ in plans if p_['level'] == 'big'), low=sum(1 for p_ in plans if p_['level'] == 'low'))
                        for pl_ in plans:
                            if pl_['opp_idx'] == my:
                                try:
                                    _ev_add(slot, 'opp_lineup', None, club=pl_['club'], level=pl_['level'], date=pl_['date'], why=pl_['why'],
                                            out=[NAMES.get(p_, str(p_)) for p_ in pl_['out']], inn=[NAMES.get(p_, str(p_)) for p_ in pl_['inn']])
                                except Exception:
                                    pass
            except Exception as ex:
                print('[lineup]', ex)
        except Exception as ex:
            t['status'] = 'error: %s' % ex
            auto_save(st)
            return dict(ok=False, status=t['status'])
        t['clubs'] = new
        t['mtime'] = os.path.getmtime(p)
        n_init = sum(1 for c in real if c['kind'] == 'init')
        lg = t.setdefault('log', [])
        for c in real:
            if c['kind'] == 'init':
                continue
            lg.append(dict(idx=c['idx'], name=c['name'], when=t['date'], kind=c['kind'], pf=c['prof_from'], pt=c['prof_to'],
                           mf=c['mood_from'], mt=c['mood_to'], form=c.get('form'), diff=[[k, a, b] for k, a, b in c['diff'] if k != 'adv'],
                           formation=c.get('formation')))
        for ev_ in cev:
            lg.append(dict(ev_, when=t['date'], kind='coach'))
        t['log'] = lg[-500:]
        try:
            d_ = worldlib.date_str(code)
            world(slot, s).add_many([('coach_' + ev_['coach_ev'], d_, 'coach:%s:%s:%s' % (ev_['coach_ev'], ev_['idx'], d_), None, [ev_['name']] + ([ev_['frm']] if ev_.get('frm') else []),
                                      {k: v for k, v in ev_.items() if k not in ('idx',)}) for ev_ in cev])
            world(slot, s).add_many([('ai_tactics', d_, 'tac:%s:%s:%s:%s' % (c['idx'], d_, c['prof_from'], c['prof_to']), None, [c['name']],
                                      dict(club=c['name'], change=c['kind'], pf=c['prof_from'], pt=c['prof_to'], mood=c['mood_to'], form=c.get('form')))
                                     for c in real if c['kind'] != 'init'])
        except Exception as ex:
            print('[world] tac:', ex)
        t['status'] = 'tactics: %d clubs have a style (%d set in this check), %d changes (date %s)' % (len(new), n_init, len(real) - n_init, t['date'])
        auto_save(st)
        PCACHE.clear()
        return dict(ok=True, status=t['status'])



def game_moves(slot):
    """Transferi koje je napravila sama igra: razlika klub-po-igracu izmedju dva save-a (snimka u data/xfer). Prvi poziv samo postavi osnovicu."""
    import json as _j
    try:
        pd = players_data(slot)
    except Exception:
        return dict(moves=[], total=0, base=False)
    dd = os.path.join(HERE, 'data', 'xfer'); os.makedirs(dd, exist_ok=True)
    fp = os.path.join(dd, re.sub(r'[^A-Za-z0-9_.-]', '_', slot) + '.json')
    cur = {str(r['id']): r['club'] for r in pd['players']}
    info = {str(r['id']): r for r in pd['players']}
    st = {}
    if os.path.exists(fp):
        try:
            st = _j.load(open(fp, encoding='utf-8'))
        except Exception:
            st = {}
    log = st.get('log', [])
    snap = st.get('club')
    base = bool(snap)
    if snap and snap != cur:
        ch = [k for k, c in cur.items() if k in snap and snap[k] != c]
        if len(ch) <= 1500:
            e = auto_view().get(slot) or {}
            appmv = {}
            for w in e.get('windows', {}).values():
                for m in w['plan']:
                    if m.get('done') and not m.get('skip'):
                        appmv[str(m['pid'])] = m.get('to_name')
            try:
                when = _gfmt(_gnow(slot))
            except Exception:
                when = ''
            mine = pd.get('mine')
            for k in ch:
                if appmv.get(k) == cur[k] or mine in (cur[k], snap[k]):
                    continue
                r = info[k]
                log.append(dict(pid=int(k), name=r['name'], pos=POSN_ABBR[r['pos']] if isinstance(r['pos'], int) and 0 <= r['pos'] < 13 else '', ovr=r['ovr'], age=r['age'],
                                from_name=snap[k], to_name=cur[k], when=when, n=len(ch)))
                try:
                    d_ = worldlib.parse_when(when)
                    world_add(slot, 'game_transfer', d_, 'gm:%s:%s:%s' % (k, d_, cur[k]), pid=int(k), clubs=[snap[k], cur[k]],
                              name=r['name'], ovr=r['ovr'], age=r['age'], frm=snap[k], to=cur[k])
                except Exception:
                    pass
        st['log'] = log[-600:]
        st['club'] = cur
        _j.dump(st, open(fp, 'w', encoding='utf-8'))
    elif not snap:
        st = dict(club=cur, log=[])
        _j.dump(st, open(fp, 'w', encoding='utf-8'))
    mv = [m for m in reversed(st.get('log', log)) if not m.get('ovr') or m['ovr'] >= 62]
    return dict(moves=mv[:300], total=len(st.get('log', log)), base=base)


POSN_ABBR = ['GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF']


def auto_history(slot):
    """Izvrseni AI transferi (najnoviji prvi) sa cinjenicama za vijesti."""
    e = auto_view().get(slot) or {}
    out = []
    for k, w in e.get('windows', {}).items():
        for m in w['plan']:
            if m.get('done') and not m.get('skip'):
                out.append(dict(m, win=k))
    def key(m):
        w = m.get('when') or '0.0.0'
        try:
            d, mo, y = [int(x) for x in w.split('.')]
        except Exception:
            d = mo = y = 0
        return (y, mo, d, m.get('day', 0))
    out.sort(key=key, reverse=True)
    try:
        gm = game_moves(slot)
    except Exception:
        gm = dict(moves=[], total=0, base=False)
    sg, summ = _market_history(e)
    return dict(moves=out, enabled=bool(e.get('enabled')), tac=list(reversed((e.get('tac') or {}).get('log', []))), game=gm['moves'], game_total=gm['total'], game_base=gm['base'],
                sagas=sg, summaries=summ)


def _market_history(e):
    """Faze prica koje su se vec dogodile (do danasnjeg dana igre) + sazetak svakog roka."""
    cur_key, cur_idx, cur_state = None, 0, None
    try:
        d_, m_, y_ = [int(x) for x in (e.get('date') or '').split('.')]
        cur_key, cur_idx, cur_state = win_state((d_ << 24) | (m_ << 16) | y_)
    except Exception:
        pass
    items, summ = [], []
    for k, w in (e.get('windows') or {}).items():
        current = (k == cur_key and cur_state == 'in')
        upto = cur_idx if current else 10 ** 6
        donep = {int(m['pid']): m for m in w.get('plan', []) if m.get('done')}
        for g in w.get('sagas') or []:
            for i, st in enumerate(g['stages']):
                if st['day'] > upto or st['day'] < w.get('from', -10 ** 6):   # pc311: nista prije pocetka karijere
                    continue
                if g['kind'] in ('real', 'shock') and st['k'] in ('medical', 'deadline', 'war_won') and int(g['pid']) not in donep:
                    continue   # zavrsne faze tek kad je potez stvarno izvrsen
                items.append(dict(st, sid='%s-%s' % (k, g['id']), n=i, last=(i == len(g['stages']) - 1), win=k, when=market.day_date(k, st['day']),
                                  kind=g['kind'], pid=g['pid'], name=g['name'], pos=g.get('pos'), ovr=g.get('ovr'), age=g.get('age'), frm=g['frm'], to=g['to'],
                                  outcome=g['outcome'], rivals=g.get('rivals', []), mine=bool(g.get('mine')), gfee=g.get('fee')))
        try:
            summ.append(market.summary(k, w, not current, upto))
        except Exception:
            pass
    items.sort(key=lambda x: (x['win'][1:], x['win'][0] == 'S', x['day'], x['n']), reverse=True)
    return items, summ


def auto_set(body):
    slot = body['slot']
    with AUTO_LOCK:
        st = auto_load()
        e = st.setdefault(slot, {})
        if any(k in body for k in ('enabled', 'tac_on', 'coach_on', 'lu_on')):
            e['user_set'] = True
            e.pop('fresh', None)
        if 'enabled' in body:
            e['enabled'] = bool(body['enabled'])
            if e['enabled']:
                e.pop('last_mtime', None)
        if 'seed' in body:
            e['seed'] = int(body['seed'])
        if 'level' in body:
            e['level'] = 'low' if body['level'] == 'low' else 'normal'
        if 'skip_first' in body:
            e['skip_first'] = bool(body['skip_first'])
            wins_ = e.get('windows') or {}
            if e['skip_first'] and len(wins_) == 1:
                # vec planiran prvi rok bez ijednog upisa: isprazni ga (preskace se)
                k_, w_ = next(iter(wins_.items()))
                if isinstance(w_, dict) and not w_.get('applied') and not any(m.get('done') for m in w_.get('plan') or []):
                    wins_[k_] = dict(seed=0, plan=[], applied=0, skipped=0, b0={}, events=[], v=2, wish={}, stats={}, sagas=[], full=True, skipped_first=True)
        if 'coach_on' in body:
            e.setdefault('coach', {})['off'] = not bool(body['coach_on'])
        if 'lu_on' in body:
            e.setdefault('lu', {})['off'] = not bool(body['lu_on'])
        if 'tac_on' in body:
            tt = e.setdefault('tac', {})
            tt['on'] = bool(body['tac_on'])
            if tt['on']:
                tt.pop('mtime', None)
        if 'tac_seed' in body:
            e.setdefault('tac', {})['seed'] = int(body['tac_seed'])
        if body.get('tac_reset'):
            tt = e.setdefault('tac', {})
            tt['clubs'] = {}
            tt['log'] = []
            tt.pop('mtime', None)
        if body.get('reset'):
            e['windows'] = {}
            e.pop('last_mtime', None)
        auto_save(st)
    return auto_status(slot)


def _lab_decrypt():
    """Mjerenja: svaki save stavljen u <work>/../loan (i podmape) se jednom dekriptira u <ime>_dec, da se moze usporediti. Samo cita, original ostaje."""
    for base in (os.path.join(os.path.dirname(os.path.abspath(CFG['work'])), 'loan'), os.path.join(CFG['work'], 'loan')):
        if os.path.isdir(base):
            _lab_decrypt_dir(base)


def _lab_decrypt_dir(base):
    log = []
    # dijelovi (ime.p1of2, ime.p2of2 ...) se spoje u jedan file kad stignu svi
    parts = {}
    for f in os.listdir(base):
        m = re.match(r'^(.+)\.p(\d+)of(\d+)$', f)
        if m:
            parts.setdefault((m.group(1), int(m.group(3))), {})[int(m.group(2))] = os.path.join(base, f)
    for (name, n), got in parts.items():
        dst = os.path.join(base, name)
        if len(got) == n and not os.path.exists(dst):
            with open(dst + '.tmp', 'wb') as o:
                for i in range(1, n + 1):
                    with open(got[i], 'rb') as fh:
                        shutil.copyfileobj(fh, o)
            os.replace(dst + '.tmp', dst)
            log.append('SPOJENO %s (%d dijela)' % (dst, n))
    for root, dirs, files in os.walk(base):
        if root.endswith('_dec') or os.path.basename(os.path.dirname(root)).endswith('_dec'):
            continue
        for f in files:
            p = os.path.join(root, f)
            if not f.upper().startswith('ML') or '.' in f or os.path.getsize(p) < 1000000:
                continue
            out = p + '_dec'
            if os.path.exists(os.path.join(out, 'data.dat')):
                continue
            try:
                decrypt(p, out)
                log.append('OK   %s' % p)
            except Exception as ex:
                log.append('GRESKA %s: %s' % (p, ex))
    if log:
        with open(os.path.join(base, '_dekripcija_log.txt'), 'a', encoding='utf-8') as fh:
            fh.write('\n'.join(time.strftime('%d.%m.%Y %H:%M:%S ') + x for x in log) + '\n')


BACKUP_KEEP = 15   # pc299: koliko zadnjih backupova po slotu ostaje (svaki je cijeli save: 20 / 45 / 60 MB)
BACKUP_CHOICES = (0, 1, 3, 15)   # pc356: config 'backup_keep' (Setup): 0 = bez kopija (kopija se napravi za vrijeme upisa i odmah obrise)


def _backup_keep():
    try:
        v = int(CFG.get('backup_keep', 3))
    except Exception:
        v = 3
    return max(0, min(50, v))


def _backup_dir():
    return os.path.join(CFG.get('work') or os.path.join(HERE, 'work'), 'backup')


def backups_info():
    d = _backup_dir()
    fs = [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))] if os.path.isdir(d) else []
    size = sum(os.path.getsize(os.path.join(d, f)) for f in fs)
    return dict(folder=d, count=len(fs), size=size, keep=_backup_keep(), choices=list(BACKUP_CHOICES))


def prune_backups(keep=None):
    """Po slotu (ime prije prvog '_') ostavi zadnjih `keep` backupova, starije obrisi. Backup je cijela kopija savea prije upisa iz appa."""
    keep = _backup_keep() if keep is None else keep
    d = _backup_dir()
    if not os.path.isdir(d):
        return dict(removed=0, freed=0)
    by = {}
    for f in os.listdir(d):
        fp = os.path.join(d, f)
        if os.path.isfile(fp) and re.match(r'^(ML|EDIT)[0-9A-F]{8}', f, re.I):
            by.setdefault(f.split('_')[0], []).append((os.path.getmtime(fp), fp))
    removed = freed = 0
    for k, lst in by.items():
        lst.sort(reverse=True)
        for _mt, fp in lst[keep:]:
            try:
                sz = os.path.getsize(fp)
                os.remove(fp)
                removed += 1
                freed += sz
            except Exception:
                pass
    return dict(removed=removed, freed=freed)


def auto_loop():
    _pb = 0
    while True:
        time.sleep(20)
        if time.time() - _pb > (60 if _backup_keep() <= 1 else 900):   # pc299/pc356: ciscenje (zadnjih N po slotu); s 0-1 kopija svake minute
            _pb = time.time()
            try:
                prune_backups()
            except Exception:
                pass
        try:
            if not DEV:
                _lab_decrypt()
        except Exception:
            pass
        try:
            for slot, e in list(auto_view().items()):
                if e.get('enabled') and not DEV:
                    auto_run_slot(slot)
                if (e.get('tac') or {}).get('on') and not DEV:
                    auto_tac_slot(slot)
        except Exception:
            pass


def list_players(body):
    """Stavlja igrace iz svog kluba na transfer listu u savu (isti zapis kao igra)."""
    slot = body['slot']
    ids = [int(x) for x in body['ids']]
    if game_blocks():
        raise RuntimeError('The game is running. Go to the main menu and confirm it in the app, or close the game (otherwise it overwrites the save).')
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s_list' % (slot, ts))
            shutil.copy2(src, backup)
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        res = []
        if body.get('action', 'list') in ('list', 'loan'):
            _li = s.loaned_in_pids()
            if any(p in _li for p in ids):
                raise ValueError(LOANED_MSG)
        for pid in ids:
            act = body.get('action', 'list')
            if act == 'unlist':
                r = s.unlist_player(pid)
            elif act == 'loan':
                r = s.loan_player(pid, True)
            elif act == 'unloan':
                r = s.loan_player(pid, False)
            else:
                r = s.list_player(pid)
            res.append('%s: %s' % (NAMES.get(pid, pid), r))
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        PCACHE.clear()
        if DEV:
            return dict(ok=True, message='DEV: ' + '; '.join(res))
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        return dict(ok=True, message='%s. Backup: %s' % ('; '.join(res), backup), backup=backup)


MIN_FEE_PCT = 0.80   # najmanja naknada kao dio trzisne vrijednosti (PES)
MIN_SAL_PCT = 1.00   # najmanja placa kao dio sadasnje place igraca


def deals_info(slot):
    """Prihvaceni dogovori koji se mogu prenamijeniti + budzet + podaci za prijedloge."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    live, _ = read_dump()
    rows = []
    for x in s.list_deals():
        lv = (live or {}).get(x['pid']) or {}
        x['name'] = NAMES.get(x['pid'], str(x['pid']))
        x['mv'] = lv.get('mv', 0)
        rows.append(x)
    for x in s.placeholders():
        x['name'] = NAMES.get(x['pid'], str(x['pid']))
        x['mv'] = 0
        rows.append(x)
    try:   # pc413: Salary Budget spremljen na serveru (vidi ga i mobitel; prije samo preglednik u kojem je upisan)
        _sb = _sbase_need(slot, s, {}, required=False)
    except Exception:
        _sb = None
    return dict(deals=rows, squad=len(s.my_squad_tags()), squad_max=40, budget=s.budget(), committed=s.wage_commitment(), live=bool(live), min_fee_pct=MIN_FEE_PCT, min_sal_pct=MIN_SAL_PCT, sbase=_sb)


XFER_LABELS = ('neg', 'sell', 'loan', 'loan_in', 'loan_offer', 'swap')   # upisi koji su dopusteni samo u prijelaznom roku


LEDGER_FILE = os.path.join(HERE, 'data', 'ledger.json')
LEDGER_LOCK = threading.Lock()
FIN_CAT = {'gate': 'Ticket sales', 'sell': 'Player sales', 'sellon': 'Sell-on income', 'loan_refund': 'Refunds', 'refund': 'Refunds',
           'loan_offer': 'Loan fees', 'board': 'Board', 'neg': 'Transfers', 'loan_in': 'Loan fees', 'loan': 'Loan fees', 'fa': 'Free agents',
           'youth': 'Youth signings', 'scout': 'Scouting', 'coach': 'Staff', 'bonus': 'Player bonuses', 'pbonus': 'Player bonuses',
           'contract': 'Contracts', 'facility': 'Facilities', 'invest_ev': 'Club events', 'precon': 'Agent fees', 'sponsor': 'Sponsorship'}


def _ledger_add(slot, s, label, amount, msg='', pid=None, b0=None):
    c = s.game_date_code()
    d_, m_, y_ = c >> 24, (c >> 16) & 0xff, c & 0xffff
    try:
        cid = _career_id(slot, s)
    except Exception:
        cid = slot
    with LEDGER_LOCK:
        try:
            L = json.load(open(LEDGER_FILE, encoding='utf-8'))
        except Exception:
            L = {}
        e = L.setdefault(cid, {'rows': [], 'bud': {}})
        e['rows'].append(dict(d='%d.%d.%d' % (d_, m_, y_), ym='%04d-%02d' % (y_, m_), k=label, a=int(amount), pid=pid,
                              t=re.sub(r'\s*Backup:.*$', '', str(msg or ''))[:120]))
        del e['rows'][:-1500]
        if b0 is not None:   # stanje budzeta poslije upisa, a prije prvog upisa i pocetno stanje
            if not e['bud'] and 'first' not in e:
                e['first'] = int(b0)
            e['bud']['%04d-%02d-%02d' % (y_, m_, d_)] = int(b0 + amount)
        _jdump(L, LEDGER_FILE, ensure_ascii=False)


def _ledger_snap(slot, s):
    """Stanje transfer budzeta po danu igre (za krivulju i za promjene koje napravi sama igra)."""
    try:
        c = s.game_date_code()
        key = '%04d-%02d-%02d' % (c & 0xffff, (c >> 16) & 0xff, c >> 24)
        b = s.budget()
        cid = _career_id(slot, s)
        with LEDGER_LOCK:
            try:
                L = json.load(open(LEDGER_FILE, encoding='utf-8'))
            except Exception:
                L = {}
            e = L.setdefault(cid, {'rows': [], 'bud': {}})
            if e['bud'].get(key) == b:
                return
            e['bud'][key] = b
            if len(e['bud']) > 800:
                for k_ in sorted(e['bud'])[:-800]:
                    e['bud'].pop(k_, None)
            _jdump(L, LEDGER_FILE, ensure_ascii=False)
    except Exception as ex:
        print('[ledger] snap:', ex)


def finance_view(slot):
    """pc316: financije kluba po mjesecima: prihodi i rashodi iz upisa appa, promjene koje napravi igra (nagrade, sezonski
    budzet, transferi u igri), godisnje place, upozorenja uprave."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    _ledger_snap(slot, s)
    cid = _career_id(slot, s)
    try:
        L = (json.load(open(LEDGER_FILE, encoding='utf-8')) or {}).get(cid) or {}
    except Exception:
        L = {}
    rows = L.get('rows') or []
    bud = sorted((L.get('bud') or {}).items())
    c = s.game_date_code()
    y, m, _ = _date_tuple(c)
    season = y if m >= 7 else y - 1
    wages = s.wage_commitment()
    months = {}
    for r in rows:
        e = months.setdefault(r['ym'], dict(ym=r['ym'], inc={}, exp={}, items=[]))
        cat = FIN_CAT.get(r['k'], r['k'].capitalize())
        tgt = e['inc'] if r['a'] > 0 else e['exp']
        tgt[cat] = tgt.get(cat, 0) + abs(r['a'])
        e['items'].append(r)
    # promjene koje je napravila igra: razlika budzeta mjeseca minus upisi appa u tom mjesecu
    by_m = {}
    for k, b in bud:
        by_m.setdefault(k[:7], []).append(b)
    prev_end = L.get('first')
    for ym in sorted(by_m):
        vals = by_m[ym]
        start = prev_end if prev_end is not None else vals[0]
        app_sum = sum(r['a'] for r in rows if r['ym'] == ym)
        game = vals[-1] - start - app_sum
        e = months.setdefault(ym, dict(ym=ym, inc={}, exp={}, items=[]))
        e['start'], e['end'] = start, vals[-1]
        if abs(game) >= 1000:
            (e['inc'] if game > 0 else e['exp'])['In-game (prizes, season budget, game deals)'] = abs(game)
            e['sparse'] = len(vals) < 3   # pc317: malo snimaka (app dugo zatvoren): iznos igre je zbirni za cijeli period
        prev_end = vals[-1]
    out = []
    for ym in sorted(months, reverse=True):
        e = months[ym]
        e['income'] = sum(e['inc'].values())
        e['expense'] = sum(e['exp'].values())
        e['net'] = e['income'] - e['expense']
        e['items'] = e['items'][-30:]
        out.append(e)
    # sezona
    s_from = '%04d-07' % season
    srows = [r for r in rows if r['ym'] >= s_from]
    s_inc = sum(r['a'] for r in srows if r['a'] > 0)
    s_exp = -sum(r['a'] for r in srows if r['a'] < 0)
    warn = []
    try:
        e_sb = _sb_store().get(cid) or {}
        if e_sb.get('base') and e_sb.get('season') == season and wages > e_sb['base']:
            warn.append(dict(k='wages', t='Wages are above the salary budget by %s EUR. The board wants the wage bill cut.' % '{:,}'.format(wages - e_sb['base'])))
    except Exception:
        pass
    try:
        b_start = next((b for k_, b in bud if k_ >= '%04d-07-01' % season), None)
        if b_start and s_exp > 0.85 * b_start and s_exp > s_inc:
            warn.append(dict(k='spend', t='You have spent %d%% of the budget you started the season with. The board is watching spending.' % round(100.0 * s_exp / b_start)))
    except Exception:
        pass
    if s.budget() < 0:
        warn.append(dict(k='debt', t='The transfer budget is negative. The board expects sales before any new signing.'))
    return dict(ok=True, months=out, budget=s.budget(), wages=wages, wages_month=int(wages / 12), season='%d/%02d' % (season, (season + 1) % 100),
                season_income=s_inc, season_expense=s_exp, series=[dict(d=k, b=b) for k, b in bud[-120:]], warnings=warn, game_account=_game_acct(s), budget_settings=_bset(s))


def _bset(s):
    try:
        return s.budget_settings()
    except Exception:
        return None


def budget_settings_set(body):
    slot = body['slot']
    vals = {k: v for k, v in (body.get('vals') or {}).items() if k in mlwrite.Save.BUDGET_SETTINGS and v in ('salary', 'transfer')}
    if not vals:
        raise ValueError('Nothing to change.')
    r = _write_slot(slot, 'budgetset', lambda sv: (sv.set_budget_settings(vals), 'Budget settings changed')[1])
    return dict(ok=True, message='Budget settings saved into the career. Load the career in the game to see them.', backup=r.get('backup') if isinstance(r, dict) else None)


def _game_acct(s):
    try:
        a = s.club_account()
        return a if all(0 <= v < 5 * 10 ** 9 for v in a.values()) else None
    except Exception:
        return None


def _write_slot(slot, label, fn, pid=None):
    """Dekriptira slot, primjeni fn(Save), spremi s TOCNOM duljinom, enkriptira i upise natrag (uz backup)."""
    pes17_readonly(slot)
    if game_blocks():
        raise RuntimeError('The game is running. Go to the main menu and confirm it in the app, or close the game (otherwise it overwrites the save).')
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        if DEV:
            src_dec = DEV
            new_dec = os.path.join(work, 'dev_out')
        else:
            src = os.path.join(CFG['save_dir'], slot)
            os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
            backup = os.path.join(work, 'backup', '%s_%s_%s' % (slot, ts, label))
            shutil.copy2(src, backup)
            src_dec = os.path.join(work, 'apply_dec')
            decrypt(src, src_dec)
            new_dec = os.path.join(work, 'apply_new')
        s = mlwrite.Save(src_dec)
        if label in XFER_LABELS and win_state(s.game_date_code())[2] != 'in':
            c = s.game_date_code()
            raise ValueError('The transfer window is closed (in game it is %d.%d.%d.). Transfers, sales and loans only work when the window opens ' '(summer 1.7.-31.8., winter 1.1.-31.1.).' % (c >> 24, (c >> 16) & 0xff, c & 0xffff))
        size0 = len(s.d)
        try:
            _b0 = s.budget()
        except Exception:
            _b0 = None
        msg = fn(s)
        if len(s.d) != size0:
            raise RuntimeError('interna greska: velicina save-a se promijenila')
        try:   # pc316: knjiga prihoda i rashoda (svaki upis appa koji mijenja transfer budzet)
            _b1 = s.budget()
            if _b0 is not None and _b1 is not None and _b1 != _b0 and not DEV:
                _ledger_add(slot, s, label, _b1 - _b0, msg, pid, b0=_b0)
        except Exception as ex:
            print('[ledger]', ex)
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        s.save(new_dec)
        PCACHE.clear()
        if DEV:
            return dict(ok=True, message='DEV: ' + msg)
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        _enc_check(encrypt(new_dec, newfile))
        if not os.path.exists(newfile):
            raise RuntimeError('encryption failed')
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa (OneDrive?). Backup: ' + backup)
        hint = ''
        if _MENU.get('batch'):
            _MENU['batch_wrote'] = True
        elif game_running():
            _MENU['on'] = False   # potvrda 'glavni meni' vrijedi za jedan upis (pc176: ili za jednu AI obradu, vidi auto_tac_slot)
            hint = ' IMPORTANT: the game is running. Load the save from the main menu now (Load). If you were in Master League, quit WITHOUT saving and load it again, otherwise the game overwrites this change.'
        if pid:
            WRITES.append(dict(slot=slot, kind=label, pid=int(pid), t=os.path.getmtime(src)))
        try:   # pc203: ime igraca umjesto id-a u poruci ("sold 132155 to ...")
            msg = re.sub(r'\b(sold|loaned|signed) (\d{3,7})\b', lambda m_: '%s %s' % (m_.group(1), NAMES.get(int(m_.group(2))) or m_.group(2)), str(msg))
        except Exception:
            pass
        return dict(ok=True, message='%s Backup: %s%s' % (msg, backup, hint), backup=backup)


def lab_restore(body):
    """LAB: vrati dekriptirani save iz mape (data.dat + description.dat) u slot (uz backup). Samo za testove."""
    pes17_readonly(body.get('slot'))
    if game_running():
        raise RuntimeError('The game is running. Close it, then restore the save.')
    slot = body['slot']
    srcdir = body['src']
    if not slot.startswith('ML0') or not os.path.isfile(os.path.join(srcdir, 'data.dat')) or not os.path.isfile(os.path.join(srcdir, 'description.dat')):
        raise ValueError('invalid slot or folder (needs data.dat + description.dat)')
    work = CFG['work']
    ts = time.strftime('%Y%m%d_%H%M%S')
    with LOCK:
        src = os.path.join(CFG['save_dir'], slot)
        os.makedirs(os.path.join(work, 'backup'), exist_ok=True)
        backup = os.path.join(work, 'backup', '%s_%s_prije_lab_restore' % (slot, ts))
        shutil.copy2(src, backup)
        new_dec = os.path.join(work, 'apply_new')
        if os.path.exists(new_dec):
            shutil.rmtree(new_dec)
        os.makedirs(new_dec)
        for fn_ in os.listdir(srcdir):
            if os.path.isfile(os.path.join(srcdir, fn_)):
                shutil.copyfile(os.path.join(srcdir, fn_), os.path.join(new_dec, fn_))
        PCACHE.clear()
        newfile = os.path.join(work, 'ML_new')
        if os.path.exists(newfile):
            os.remove(newfile)
        rr = encrypt(new_dec, newfile)
        if rr.returncode != 0 or not os.path.exists(newfile):
            raise RuntimeError('enkripcija: rc=%s stdout=%r stderr=%r sizes=%s' % (rr.returncode, rr.stdout[-400:], rr.stderr[-400:], [(f, os.path.getsize(os.path.join(new_dec, f))) for f in os.listdir(new_dec)]))
        shutil.copyfile(newfile, src)
        if sha(newfile) != sha(src):
            raise RuntimeError('hash save-a se ne poklapa. Backup: ' + backup)
    return dict(ok=True, message='Vraceno iz %s. Backup: %s' % (srcdir, backup))


def swap_deal(body):
    slot = body['slot']
    old, new = int(body['old']), int(body['new'])
    fee, sal = int(body['fee']), int(body['salary'])
    rel = int(body['release']) if body.get('release') not in (None, '') else fee
    yr = int(body.get('end_year', 2027))
    live, _ = read_dump()
    lv = (live or {}).get(new)
    if lv:
        if lv['mv'] and fee < lv['mv'] * MIN_FEE_PCT:
            raise ValueError('fee is too low: the game requires at least %d EUR (%d%% of market value)' % (lv['mv'] * MIN_FEE_PCT, MIN_FEE_PCT * 100))
        if lv['sal'] and sal < lv['sal'] * MIN_SAL_PCT:
            raise ValueError('wage is too low: the player currently earns %d EUR a year' % lv['sal'])

    def fn(s):
        r = s.swap_deal(old, new, fee, sal, rel, yr)
        return '%s u dogovoru: naknada %d EUR, placa %d EUR/god.' % (NAMES.get(new, new), fee, sal)
    return _write_slot(slot, 'swap', fn)


# ------------------------------------------------------------------ pregovori
NEG = None


TL_FILE = os.path.join(HERE, 'data', 'tlist.json')
TL_REASONS = ('surplus', 'cash', 'unhappy', 'prospect', 'other')


def _tl_all():
    try:
        return json.load(open(TL_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _tl_slot(slot):
    return _tl_all().get(slot, {})


def _tl_save(slot, d):
    a = _tl_all()
    a[slot] = d
    os.makedirs(os.path.dirname(TL_FILE), exist_ok=True)
    _jdump(a, TL_FILE, ensure_ascii=False, indent=1)


def _tl_norm(e):
    """Stari zapisi (bez 'tl') su transfer lista."""
    e = dict(e)
    e.setdefault('tl', not e.get('loan_only', False))
    e.setdefault('loan', False)
    return e


def tlist_view(slot):
    """Appova transfer lista i lista posudbi za tvoj klub: radi odmah, neovisno o igri."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    squad = s.my_squad_tags()
    live, _ = read_dump()
    cur = _tl_slot(slot)
    out = []
    for k, e0 in cur.items():
        pid = int(k)
        if pid not in squad:
            continue
        e = _tl_norm(e0)
        lv = (live or {}).get(pid) or {}
        o, a = rat(pid)
        out.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=o, age=lv.get('age') or a, mv=lv.get('mv', 0),
                        tl=e['tl'], loan=e['loan'], ask=e.get('ask'), reason=e.get('reason', 'other'), added=e.get('added'),
                        loan_share=e.get('loan_share'), loan_buy=e.get('loan_buy'), loan_added=e.get('loan_added')))
    return dict(items=out, reasons=list(TL_REASONS))


LOANED_MSG = 'The player is on loan with you (another club owns him): you cannot list him for transfer/loan, sell him or extend his contract.'


def tlist_set(body):
    slot, pid, on = body['slot'], int(body['pid']), bool(body.get('on', True))
    kind = body.get('kind', 'transfer')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if pid not in s.my_squad_tags():
        raise ValueError('player is not in your club')
    if on and pid in s.loaned_in_pids():
        raise ValueError(LOANED_MSG)
    cur = _tl_slot(slot)
    key = str(pid)
    e = _tl_norm(cur.get(key, dict(tl=False, loan=False)))
    today = _fmt_date(s.game_date_code())

    def num(x):
        if x in (None, '', 0, '0'):
            return None
        x = int(x)
        if x < 0:
            raise ValueError('neispravan iznos')
        return x
    if kind == 'loan':
        e['loan'] = on
        if on:
            sh = body.get('share')
            e['loan_share'] = max(0, min(100, int(sh))) if sh not in (None, '') else e.get('loan_share', 100)
            e['loan_buy'] = num(body.get('buy'))
            e['loan_added'] = e.get('loan_added') or today
        else:
            e.pop('loan_share', None); e.pop('loan_buy', None); e.pop('loan_added', None)
    else:
        if on and not e.get('tl') and not body.get('confirm_fav'):
            try:
                fav, why = fan_favourite(slot, s, pid)
                if fav >= 25:
                    return dict(ok=False, fav=fav, why=why, fav_warn=('%s is %s (%s). If you sell him, the fans will not be happy%s. Put him on the transfer list anyway?'
                                                                   % (NAMES.get(pid, ''), "a fans' favourite" if fav >= 50 else 'popular with the fans', ', '.join(why),
                                                                      ', especially if he goes to a rival' if fav >= 50 else '')))
            except Exception as ex:
                print('[fans] tl:', ex)
        e['tl'] = on
        if on:
            reason = body.get('reason') or e.get('reason') or 'other'
            e['reason'] = reason if reason in TL_REASONS else 'other'
            e['ask'] = num(body.get('ask'))
            e['added'] = e.get('added') or today
        else:
            e.pop('ask', None); e.pop('reason', None); e.pop('added', None)
    if e['tl'] or e['loan']:
        cur[key] = e
    else:
        cur.pop(key, None)
    _tl_save(slot, cur)
    return tlist_view(slot)


def _tl_remove(slot, pid):
    cur = _tl_slot(slot)
    if cur.pop(str(pid), None) is not None:
        _tl_save(slot, cur)


def _neg_store():
    global NEG
    if NEG is None:
        NEG = negotiate.Store(os.path.join(HERE, 'data', 'negotiations.json'))
    return NEG


def _date_tuple(code):
    return (code & 0xffff, (code >> 16) & 0xff, (code >> 24) & 0xff)   # (godina, mjesec, dan)


def _add_days(code, days):
    import datetime
    y, m, d = _date_tuple(code)
    t = datetime.date(y, m, d) + datetime.timedelta(days=days)
    return (t.day << 24) | (t.month << 16) | t.year


def _cmp_date(a, b):
    return (_date_tuple(a) > _date_tuple(b)) - (_date_tuple(a) < _date_tuple(b))


def _fmt_date(code):
    y, m, d = _date_tuple(code)
    return '%d/%d/%d' % (d, m, y)


def _fmt_due(code):
    """pc236: rok odgovora bez dvoznacnosti dan/mjesec (npr. '6 Oct 2025')."""
    y, m, d = _date_tuple(code)
    return '%d %s %d' % (d, 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()[m - 1], y)


_SLOTS = {0: 1, 1: 2, 2: 1, 3: 1, 4: 1, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1, 11: 1, 12: 1}


def _crowd_count(s, pid, ovr):
    """Koliko je mojih igraca na njegovoj poziciji jednako dobro ili bolje, minus mjesta u prvoj postavi (0 = ima mjesta). Dugotrajno ozlijedjeni ne racunaju."""
    ppos = POS.get(pid)
    if ppos not in _SLOTS or not ovr:
        return 0
    out_ = _long_injured(s)
    ahead = [q for q in s.squad_ids() if q and q not in out_ and POS.get(q) == ppos and rat(q)[0] >= ovr - 1]
    return max(0, len(ahead) - _SLOTS[ppos] + 1)


def neg_context(slot, pid):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    live, _ = read_dump()
    lv = (live or {}).get(pid) or {}
    ovr, age = rat(pid)
    ml = None
    if lv.get('cy'):
        ml = (lv['cy'] - y) * 12 + (lv['cm'] - m)
    if not lv:
        # pc165: nema svjezeg dumpa (npr. nova karijera prije F7): placa i ugovor iz savea, vrijednost iz starog dumpa.
        # Prije se sve procjenjivalo iz OVR-a (Zirkzee: 13 M umjesto 25 M, placa 3,75 M umjesto ~2,9 M).
        lv = {}
        try:
            k_ = s.read_contracts([pid]).get(pid) or {}
            if k_.get('sal'):
                lv['sal'] = k_['sal']
            if k_.get('y'):
                lv['cy'], lv['cm'] = k_['y'], k_.get('m') or 6
                ml = (lv['cy'] - y) * 12 + (lv['cm'] - m)
        except Exception as ex:
            print('[neg] ugovor iz savea:', ex)
        try:
            mv_ = (read_dump_any().get(pid) or {}).get('mv') or 0
        except Exception:
            mv_ = 0
        if not mv_ and lv.get('sal'):
            mv_ = negotiate.rnd100(lv['sal'] * 8.5, 1000)
        if mv_:
            lv['mv'] = mv_
    f = negotiate.facts(ovr, lv.get('age') or age or 25, lv.get('mv', 0), lv.get('sal', 0), ml, lv.get('tl'))
    my = [rat(p)[0] for p in s.squad_ids() if p]
    pd = players_data(slot)
    club = next((r['club'] for r in pd['players'] if r['id'] == pid), '')
    cs = {}
    for r in pd['players']:
        if r['club'] and r['ovr']:
            cs.setdefault(r['club'], []).append(r['ovr'])
    top = lambda L: (sum(sorted(L, reverse=True)[:14]) / min(14, len(L))) if L else None
    cur_str = top(cs.get(club, []))
    my_ovrs = [o for o in my if o]
    my_str = top(my_ovrs)
    free = False
    try:
        # pc235: na 60 MB isti PID moze imati i igrac u klubu; slobodan je ako postoji jedinstven slobodni zapis s tim PID-om
        free = bool(s.fmt60 and pid in s.free_agents())
    except Exception:
        free = False
    if free:
        club = ''
        cur_str = None
    if not club and not free:
        try:
            free = any(r['id'] == pid for r in _fa_pool(slot)[0])
        except Exception:
            free = False
    if free:   # nema ugovora ni place: podaci iz dumpa (stari klub) ne vrijede
        f = negotiate.facts(ovr, age or 25, 0, 0, None, False)
        lv = {}
    return dict(save=s, gd=gd, f=f, my=my_ovrs, club=club, month_key='%d-%d' % (y, m), until=(lv.get('cm'), lv.get('cy')), cur_str=cur_str, my_str=my_str, crowd=_crowd_count(s, pid, f['ovr']), free=free)


def _moved(slot, save):
    """Igraci koji su u ovom prijelaznom roku promijenili klub: iz savea (datum ugovora) + zapisi appa."""
    wk = save.window_key(save.game_date_code())
    out = set(save.moved_this_window())
    if wk is not None:
        for k, rec in _neg_store().for_slot(slot).items():
            if k <= -10 ** 9 and rec.get('wk') == list(wk):
                out.add(-k - 10 ** 9)
    return out


def _mark_moved(slot, save, pid):
    wk = save.window_key(save.game_date_code())
    if wk is not None:
        _neg_store().put(slot, -10 ** 9 - pid, dict(wk=list(wk)))


def _slots(save):
    d = {x['pid']: x for x in save.list_deals()}
    for x in save.placeholders():
        d.setdefault(x['pid'], x)
    return d


DIRECT = dict(pid=0, fee=0, salary=0)     # "slot" 0 = dolazak bez zamjene (eksperiment)


def _old_deal(deals, old):
    return DIRECT if old == 0 else deals.get(old)


def _neg_view(slot, pid, rec, ctx=None):
    ctx = ctx or neg_context(slot, pid)
    f = ctx['f']
    deals = _slots(ctx['save'])
    old = _old_deal(deals, rec['old'])
    budget = ctx['save'].budget()
    return dict(
        pid=pid, name=NAMES.get(pid, str(pid)), club=ctx['club'], stage=rec['stage'], round=rec['round'],
        p_round=rec.get('p_round', 0), club_rounds=negotiate.CLUB_ROUNDS, player_rounds=negotiate.PLAYER_ROUNDS,
        p_last_role=rec.get('p_last_role'), p_last_years=rec.get('p_last_years'),
        log=rec['log'], fee=rec.get('fee'), salary=rec.get('salary'), years=rec.get('years'), role=rec.get('role'),
        old=rec['old'], old_name=(NAMES.get(rec['old'], str(rec['old'])) if rec['old'] else ''), old_fee=(old or {}).get('fee', 0), old_salary=(old or {}).get('salary', 0),
        committed=ctx['save'].wage_commitment(), budget=budget,
        mv=f['mv'], mv_est=f['est'], cur_sal=f['sal'], ovr=f['ovr'], age=f['age'], listed=f['listed'],
        until=('%s/%s' % ctx['until']) if ctx['until'][1] else '', last_counter=rec.get('last_counter'),
        p_last_counter=rec.get('p_last_counter'), tone=rec.get('tone'), ptone=rec.get('ptone'),
        rival=(dict(club=rec['rival']['club'], deadline=rec['rival']['deadline'], bid=(rec['rival']['bid'] if rec.get('rival_known') else None),
                    **(lambda pv: dict(wage=pv['riv_wage'], role=pv['riv_role']))(_rival_info(slot, ctx, pid, persona.traits(pid), rec['rival'], rec.get('p_last_counter') or f['sal'], 'starter')) if rec['stage'] in ('player', 'ready') else {}) if rec.get('rival') else None),
        interested=rec.get('interested') or ([rec['rival']['club']] if rec.get('rival') else []),
        app_bonus=rec.get('app_bonus', 0), sellon=rec.get('sellon', 0), add_apps=ADD_APPS, add_p_app=ADD_P_APP, add_p_sell=ADD_P_SELL,
        interest=rec.get('interest') or (persona.interest(persona.appeal(f, persona.traits(pid), ctx['my'], ctx['cur_str'], ctx['my_str'], 'starter', ctx.get('crowd', 0))['score']) if rec['stage'] == 'player' else None), clause=rec.get('clause'),
        locked_until=rec.get('lock_until') and _fmt_date(rec['lock_until']), roles=list(negotiate.ROLES), free=bool(rec.get('free')), pre=bool(rec.get('pre')),
        waiting=(dict(kind=rec['pending']['kind'], until=_fmt_due(rec['pending']['due'])) if rec.get('pending') else None),
        agent=rec.get('agent'), agent_fee=rec.get('agent_fee'), med=rec.get('med'), today=_fmt_due(ctx['gd']), grudge=bool(rec.get('grudge')),
        quiet_used=('quiet' in (rec.get('ev_used') or [])),
        reason=((ai_listings(slot, ctx['save']).get(pid) or {}).get('reason') if (ai_listings(slot, ctx['save']).get(pid) or {}).get('kind') == 'transfer' else None))


def _win_ord(code):
    """Redni broj prijelaznog roka kojem pripada datum: rok u kojem je, ili prvi sljedeci (pregovor izvan roka vrijedi za sljedeci rok)."""
    if not code:
        return -1
    y, m, _ = _date_tuple(code)
    if m in (7, 8):
        return y * 2 + 1
    if m == 1:
        return y * 2
    if 2 <= m <= 6:
        return y * 2 + 1
    return (y + 1) * 2


def _neg_expired(rec, gd, career):
    """Pregovor iz proslog prijelaznog roka ili druge karijere vise ne vrijedi."""
    if rec.get('career') and career and rec['career'] != career:
        return True
    if not rec.get('date'):
        return True
    if _cmp_date(rec['date'], gd) > 0:
        return True   # zapoceto 'u buducnosti' = druga karijera u istom slotu
    return _win_ord(rec['date']) < _win_ord(gd)


def neg_list(slot):
    """Svi otvoreni pregovori ove karijere i ovog roka: dovodjenja, posudbe k meni, prodaje."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    try:
        career = _career_id(slot, s)
    except Exception:
        career = None
    mine = set(s.my_squad_tags())
    deals = {x['pid'] for x in s.list_deals()}
    try:
        pd = players_data(slot)
        pinfo = {r['id']: r for r in pd['players']}
    except Exception:
        pinfo = {}
    out = []
    for pid, rec in _neg_store().for_slot(slot).items():
        if pid > 0 and 'old' in rec and rec.get('stage') in ('club', 'player', 'agent', 'medical', 'ready'):
            if _neg_expired(rec, gd, career) or pid in mine or (rec['old'] == 0 and pid in deals):
                continue
            if not any(e.get('who') == 'you' for e in rec.get('log') or []):
                continue        # samo otvoren prozor pregovora, ponuda jos nije poslana
            pe = rec.get('pending')
            r = pinfo.get(pid) or {}
            lo = next((e for e in reversed(rec['log']) if e.get('who') == 'you' and e.get('stage') == 'club'), {})
            out.append(dict(kind='buy', pid=pid, name=NAMES.get(pid, str(pid)), stage=rec['stage'], old=rec['old'], waiting=(_fmt_due(pe['due']) if pe else None),
                            club=r.get('club') or '', ovr=r.get('ovr'), pos=r.get('pos'), fee=rec.get('fee') or lo.get('amount'), counter=rec.get('last_counter'),
                            started=_fmt_date(rec['date']) if rec.get('date') else ''))
    for pid, rec in _lneg_store().for_slot(slot).items():
        if rec.get('stage') not in ('club', 'player', 'ready'):
            continue
        if _neg_expired(rec, gd, career) or pid in mine or pid in deals:
            continue
        if 'log' in rec and not any(e.get('who') == 'you' for e in rec.get('log') or []):
            continue
        r = pinfo.get(pid) or {}
        pe = rec.get('pending')
        out.append(dict(kind='loan', pid=pid, name=NAMES.get(pid, str(pid)), stage=rec['stage'], loan_kind=rec.get('kind'), waiting=(_fmt_due(pe['due']) if pe else None),
                        club=r.get('club') or '', ovr=r.get('ovr'), pos=r.get('pos'), fee=rec.get('fee'), started=_fmt_date(rec['date']) if rec.get('date') else ''))
    y, m, _ = _date_tuple(gd)
    mk = _sell_mk(gd)
    for k, w in _neg_store().for_slot(slot).items():
        if k >= 0 or 'off' not in w or w.get('mk') != mk or w.get('gone') or w.get('stage') not in ('club', 'player', 'ready') or not w.get('log'):
            continue
        pid = w['pid']
        if pid not in mine:
            continue
        r = pinfo.get(pid) or {}
        pe = w.get('pending')
        out.append(dict(kind='sale', pid=pid, off=w['off'], name=NAMES.get(pid, str(pid)), stage=w['stage'], club=w.get('club') or '', ovr=r.get('ovr'), pos=r.get('pos'),
                        fee=w.get('fee'), waiting=(_fmt_due(pe['due']) if pe else None)))
    return out


NFS_FILE = os.path.join(HERE, 'data', 'not_for_sale.json')


def _nfs(slot, s):
    """pc398: igraci koje sam proglasio 'nije na prodaju' u ovoj karijeri: {pid}."""
    try:
        return set(int(x) for x in (json.load(open(NFS_FILE, encoding='utf-8')) or {}).get(_career_id(slot, s), []))
    except Exception:
        return set()


def sell_nfs(body):
    slot, pid, on = body['slot'], int(body['pid']), bool(body.get('on', True))
    s = mlwrite.Save(slot_folder(slot), ro=True)
    try:
        A = json.load(open(NFS_FILE, encoding='utf-8')) or {}
    except Exception:
        A = {}
    cid = _career_id(slot, s)
    cur = set(int(x) for x in A.get(cid, []))
    (cur.add if on else cur.discard)(pid)
    A[cid] = sorted(cur)
    _jdump(A, NFS_FILE, ensure_ascii=False, indent=1)
    PCACHE.clear()
    return dict(ok=True, nfs=sorted(cur))


def sell_dismiss(body):
    """pc215: odbaci ponudu za prodaju (npr. igrac ne zeli u taj klub) prije isteka mjeseca igre; ne prikazuje se vise."""
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    w.pop('pending', None)
    w.update(gone=True, stage='dead', why_gone='you')
    w['log'].append(dict(who='you', stage='club', ev='dismissed'))
    _sell_put(slot, pid, off, w)
    return dict(ok=True)


def neg_end(body):
    """Prekini pregovor sam (bez zakljucavanja): kind buy | loan | sale."""
    slot, pid, kind = body['slot'], int(body['pid']), body.get('kind', 'buy')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    d = _fmt_date(s.game_date_code())
    if kind == 'buy':
        st = _neg_store()
        rec = st.get(slot, pid)
        if rec:
            rec.pop('pending', None)
            rec['stage'] = 'ended'
            rec['log'].append(dict(who='you', ev='ended', d=d))
            st.put(slot, pid, rec)
    elif kind == 'loan':
        st = _lneg_store()
        rec = st.get(slot, pid)
        if rec:
            rec.pop('pending', None)
            rec['stage'] = 'ended'
            st.put(slot, pid, rec)
    elif kind == 'sale':
        off = int(body['off'])
        w = _neg_store().get(slot, _sell_key(pid, off))
        if w:
            w.pop('pending', None)
            w.update(gone=True, stage='dead', why_gone='you')
            w['log'].append(dict(who='you', stage='club', ev='ended'))
            _sell_put(slot, pid, off, w)
    else:
        raise ValueError('unknown negotiation type')
    return dict(ok=True, items=neg_list(slot))


ADD_FILE = os.path.join(HERE, 'data', 'addons.json')
ADD_APPS = 20          # nastupa nakon potpisa za isplatu bonusa
ADD_P_APP = 0.6        # klub vrednuje bonus na 60%
ADD_P_SELL = 0.4       # vjerojatnost buduce prodaje za sell-on


def _addons(slot):
    try:
        return json.load(open(ADD_FILE, encoding='utf-8')).get(slot, {})
    except Exception:
        return {}


def _addons_save(slot, d):
    try:
        a = json.load(open(ADD_FILE, encoding='utf-8'))
    except Exception:
        a = {}
    a[slot] = d
    os.makedirs(os.path.dirname(ADD_FILE), exist_ok=True)
    _jdump(a, ADD_FILE, ensure_ascii=False, indent=1)


def _addon_value(f, bonus, sellon):
    mv = f.get('mv') or 0
    v = bonus * ADD_P_APP + (sellon / 100.0) * mv * 0.9 * ADD_P_SELL
    return min(v, 0.3 * mv) if mv else v


SO_FILE = os.path.join(HERE, 'data', 'sellon_ours.json')
SELLON_DISC = 0.0036      # snizenje gotove naknade po 1% sell-ona (20% sell-on = -7.2%)


def _so_all():
    try:
        return json.load(open(SO_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _so_save(a):
    os.makedirs(os.path.dirname(SO_FILE), exist_ok=True)
    _jdump(a, SO_FILE, ensure_ascii=False, indent=1)


def sellon_receive(slot, moves):
    """AI klub koji je od mene kupio igraca sa sell-on klauzulom ga je preprodao (potez iz app-simulacije): isplati moj postotak."""
    cl = _so_all().get(slot) or {}
    pay = []
    for m in moves:
        e = cl.get(str(int(m['pid'])))
        fee = m.get('fee') or 0
        if e and fee:
            pay.append((int(m['pid']), int(round(fee * e['pct'] / 100.0 / 100.0)) * 100, m.get('to_name') or m.get('to_club') or ''))
    pay = [x for x in pay if x[1] > 0]
    if not pay:
        return
    tot = sum(x[1] for x in pay)

    def fn(sv):
        sv.adjust_budget(tot)
        return 'Sell-on primljen: %d EUR.' % tot
    _write_slot(slot, 'sellon', fn)
    for pid, amt, to in pay:
        _ev_add(slot, 'sellon_received', pid, fee=amt, to=to)


def addon_add(slot, s, pid, bonus, sellon, club, pbonus=None, release=None):
    pb = {k: int(v) for k, v in (pbonus or {}).items() if v}
    if not bonus and not sellon and not pb and not release:
        return
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    n = len([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])])
    d = _addons(slot)
    d[str(pid)] = dict(bonus=int(bonus), sellon=int(sellon), club=club or '', base=n, paid=not bonus, apps=ADD_APPS,
                       pbonus=pb, release=int(release or 0), pdone=dict(app=0, goal=0, win=0))
    _addons_save(slot, d)


LP_FILE = os.path.join(HERE, 'data', 'loan_pending.json')


def _lp_all():
    try:
        return json.load(open(LP_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _lp_save(a):
    os.makedirs(os.path.dirname(LP_FILE), exist_ok=True)
    _jdump(a, LP_FILE, indent=1)


def _lp_add(slot, s, pid, fee, extra=0, club='', backup=None):
    """Posudba koju je app upisao i koja ceka da je igra izvrsi (sljedeci dan)."""
    a = _lp_all()
    try:
        cid = _career_id(slot, s)
    except Exception:
        cid = None
    a.setdefault(slot, {})[str(pid)] = dict(fee=int(fee), extra=int(extra or 0), date=s.game_date_code(), career=cid, club=club or '', backup=backup or '',
                                            ext=bool(s.ext), wrote=time.strftime('%Y-%m-%d %H:%M:%S'))
    _lp_save(a)


def _lp_deal_row(s, pid, fee):
    """Red u dnevniku dogovora koji je app upisao za posudbu (tag, pid, -naknada, 2) -> dokaz da je upis stvarno u saveu."""
    d = s.d
    f = struct.unpack('<I', struct.pack('<i', -(int(fee) // 100)))[0]
    for k in range(-30, 400):
        o = s.D0 + 52 * k
        if o < 0 or o + 52 > len(d):
            continue
        if struct.unpack_from('<I', d, o + 16)[0] == pid and struct.unpack_from('<I', d, o + 44)[0] == f and struct.unpack_from('<I', d, o + 48)[0] == 2:
            return o
    return None



DR_DIR = os.path.join(HERE, 'data', 'deal_reports')


def deal_report(slot, s, pid, e):
    """Izvjestaj kad igra potrosi app-ov dogovor bez dolaska igraca: sto je app upisao, sto je ostalo u saveu nakon dana u igri,
    pretpostavljeni uzrok. Ide u datoteku podrske zajedno sa saveom prije upisa (backup) i sadasnjim saveom."""
    import struct as _st
    d = s.d
    _ch, e2 = s._chunks()
    big = b''.join(_ch)
    pat = _st.pack('<I', pid)
    rec = None
    i = big.find(pat)
    while i >= 0:
        if i >= 192 and (i - 192) % 156 == 0:
            rec = big[i - 48:i + 108]
            break
        i = big.find(pat, i + 1)
    R = dict(slot=slot, pid=pid, name=NAMES.get(pid, str(pid)), club=e.get('club'), fee=e.get('fee'), written=e.get('wrote'), deal_date='%x' % e.get('date', 0),
             now='%x' % s.game_date_code(), format='45MB' if s.ext else '19.9MB', backup_before=e.get('backup'), checks={}, guess=[])
    C = R['checks']
    C['tail_has_player'] = pat in bytes(d[e2:])
    C['deal_log_row'] = _lp_deal_row(s, pid, e['fee']) is not None
    try:
        B, CNT, k = s._s16_slot()
        rows = []
        for kk in range(-16, 112):
            o = B + 80 * kk
            if _st.unpack_from('<I', d, o + 44)[0] == pid:
                rows.append(dict(k=kk, type=hex(_st.unpack_from('<I', d, o + 4)[0]), date=hex(_st.unpack_from('<I', d, o + 8)[0]), pending=_st.unpack_from('<I', d, o + 20)[0]))
        C['s16_rows'] = rows
        C['s16_counter'] = hex(_st.unpack_from('<I', d, CNT)[0])
        C['s16_arrival_row'] = any(r_['type'] == '0x23' for r_ in rows)
    except Exception as ex:
        C['s16_error'] = str(ex)
    if rec:
        C['player_owner'] = hex(_st.unpack_from('<I', rec, 140)[0])
        C['player_loan_marker'] = hex(_st.unpack_from('<I', rec, 136)[0])
        C['player_loan_end'] = hex(_st.unpack_from('<I', rec, 152)[0])
    try:
        sq = s.my_squad_tags()
        C['my_squad_size'] = len(sq)
    except Exception:
        pass
    try:
        R['tables'] = loanscan.scan(s)['summary']
    except Exception as ex:
        R['tables'] = 'scan failed: %s' % ex
    # pretpostavke
    if not C.get('tail_has_player') and not C.get('s16_arrival_row'):
        R['guess'].append('The game removed the agreed deal on the move day without executing it (same pattern as Spinazzola, 27.10.2026).')
    if 'not' in str(R['tables']) or 'moved' in str(R['tables']):
        R['guess'].append('Transfer tables are not where the app expects them: likely a new game version. See "tables".')
    if C.get('my_squad_size', 0) >= 40:
        R['guess'].append('Squad was full (40).')
    os.makedirs(DR_DIR, exist_ok=True)
    fn = os.path.join(DR_DIR, '%s_%d_%s.json' % (re.sub(r'[^A-Za-z0-9]', '', slot), pid, time.strftime('%Y%m%d_%H%M%S')))
    _jdump(R, fn, ensure_ascii=False, indent=1)
    print('[dealrep] %s' % fn)
    return R


_LP_LOCK = threading.Lock()


def loan_pending_check(slot, s):
    # dva istovremena zahtjeva su 28.10. dvaput vratila istu naknadu (Caicedo, 2 x 6.5 M): provjera smije raditi samo jednom u isto vrijeme
    if not _LP_LOCK.acquire(blocking=False):
        return
    try:
        return _loan_pending_check0(slot, s)
    finally:
        _LP_LOCK.release()


def _loan_pending_check0(slot, s):
    """Igra ponekad potrosi app-ov dogovor o posudbi bez dolaska igraca (uzrok nije poznat; tester 27.10., Spinazzola).
    Kad je dan dolaska prosao, igrac nije kod mene, a dogovora vise nema u repu savea: naknada se vraca u budzet i javlja se vijest."""
    a = _lp_all()
    L = a.get(slot) or {}
    if not L:
        return
    gd = s.game_date_code()
    try:
        cid = _career_id(slot, s)
    except Exception:
        cid = None
    squad = set(s.my_squad_tags())
    try:   # pc152: posudba koju je korisnik vec rucno vratio (Refund) se ne vraca jos jednom (Saibari 2x 28.10.)
        _done = {(int(x['pid']), int(x['fee'])) for x in _refunds().get(slot, [])}
    except Exception:
        _done = set()
    for _k in [k_ for k_, e_ in L.items() if (int(k_), int(e_.get('fee', 0))) in _done]:
        del L[_k]
        a[slot] = L
        _lp_save(a)
    try:
        li = set(s.loaned_in_pids())
    except Exception:
        li = set()
    _ch, e2 = s._chunks()
    tail = bytes(s.d[e2:])
    failed, ch = [], False
    for k, e in list(L.items()):
        pid = int(k)
        if e.get('career') and cid and e['career'] != cid:
            del L[k]; ch = True; continue
        if pid in squad or pid in li:
            del L[k]; ch = True; continue          # stigao
        if _cmp_date(gd, e['date']) < 0:
            del L[k]; ch = True; continue          # ucitan stariji save: posudba se u ovom tijeku nije dogodila
        if _cmp_date(gd, _add_days(e['date'], 1)) <= 0:
            continue                               # dan dolaska jos nije prosao
        done5 = False
        try:
            mb = e2 + s.META0
            for j_ in range(-60, 60):
                o_ = mb + 60 * j_
                if 0 <= o_ < len(s.d) - 60 and struct.unpack_from('<I', s.d, o_ + 36)[0] == pid and s.d[o_ + 8] == 5:
                    done5 = True
                    break
        except Exception:
            pass
        if done5:
            failed.append((pid, e))                # igra je dogovor oznacila kao izvrsen (status 5), a igrac nije stigao (vanilla 28.10., Caicedo)
            continue
        if struct.pack('<I', pid) in tail:
            if _cmp_date(gd, _add_days(e['date'], 10)) > 0:
                del L[k]; ch = True                # predugo ceka: ne diramo nista
            continue
        if _lp_deal_row(s, pid, e['fee']) is None:
            del L[k]; ch = True; continue          # upis nije u ovom saveu (igra ga je prepisala): nista nije placeno
        failed.append((pid, e))
    for pid, e in failed:
        try:
            deal_report(slot, s, pid, e)
        except Exception as ex:
            print('[dealrep]', ex)
    if failed:
        tot = sum(e['fee'] + e.get('extra', 0) for _, e in failed)

        def fn(sv):
            sv.adjust_budget(tot)   # samo budzet; strukture igre (dnevnik dogovora) se ne diraju
            return 'Loan fee refunded: %d EUR.' % tot
        _write_slot(slot, 'loan_refund', fn)
        try:   # zapisano i u popis povrata, da ga rucni Refund ne vrati jos jednom
            ra = _refunds()
            ra.setdefault(slot, []).extend(dict(pid=pid, fee=int(e['fee']), when=time.strftime('%Y-%m-%d %H:%M'), auto=True) for pid, e in failed)
            _jdump(ra, REFUND_FILE, ensure_ascii=False, indent=1)
        except Exception:
            pass
        for pid, e in failed:
            del L[str(pid)]
            try:
                ev = json.load(open(EV_FILE, encoding='utf-8'))
                EL = ev.get(slot, [])
                for i in range(len(EL) - 1, -1, -1):
                    if EL[i].get('kind') == 'signed' and EL[i].get('pid') == pid and EL[i].get('loan'):
                        del EL[i]
                        break
                _jdump(ev, EV_FILE, ensure_ascii=False, indent=1)
            except Exception:
                pass
            try:
                _neg_store().drop(slot, -10 ** 9 - pid)
            except Exception:
                pass
            _ev_add(slot, 'loan_failed', pid, fee=e['fee'] + e.get('extra', 0), frm=e.get('club', ''))
        ch = True
    if ch:
        a[slot] = L
        _lp_save(a)


def _code_of(ds):
    d_, m_, y_ = (int(x) for x in str(ds).split('/'))
    return (d_ << 24) | (m_ << 16) | y_


def option_loan_check(slot, s):
    """Posudba s opcijom otkupa iz appa (45 MB): igra je zna izvesti, ali obrisati zapis dogovora (Cubarsi, 28.10.),
    pa igrac nije u Other Teams i opcije nema. Kad je igrac stigao, a zapisa nema, app ga vrati (jednom po igracu)."""
    if not s.ext:
        return
    try:
        ev = json.load(open(EV_FILE, encoding='utf-8'))
    except Exception:
        return
    L = ev.get(slot) or []
    todo = [e for e in L if e.get('kind') == 'signed' and e.get('loan') and e.get('option') and e.get('opt') and not e.get('opt_fixed')]
    if not todo:
        return
    li = set(s.loaned_in_pids())
    fix = []
    for e in todo:
        pid = e.get('pid')
        if pid not in li or s.option_record(pid):
            continue
        try:
            fix.append((e, dict(pid=pid, fee=int(e.get('fee') or 0), buy=int(e['option']), wage=int(e['opt']['wage']), release=int(e['opt']['release']),
                                opt_end=_code_of(e['opt']['end_s']), loan_end=_code_of(e['until']), arrived=_add_days(_code_of(e['when']), 1))))
        except Exception as ex:
            print('[optfix]', ex)
    if not fix:
        return

    def fn(sv):
        out = []
        for _e, a in fix:
            out.append(sv.restore_option_loan(a['pid'], a['fee'], a['buy'], a['wage'], a['release'], a['opt_end'], a['loan_end'], a['arrived']))
        return '; '.join(out)
    _write_slot(slot, 'opt_fix', fn)
    ev = json.load(open(EV_FILE, encoding='utf-8'))
    for e in ev.get(slot) or []:
        if any(e.get('pid') == a['pid'] and e.get('kind') == 'signed' and e.get('loan') for _e, a in fix):
            e['opt_fixed'] = True
    _jdump(ev, EV_FILE, ensure_ascii=False, indent=1)


def addon_check(slot, s):
    """Bonus za nastupe: kad igrac skupi ADD_APPS nastupa nakon potpisa, bonus se odbija od transfer budzeta."""
    try:
        loan_pending_check(slot, s)
    except Exception as ex:
        print('[loanpend]', ex)
    try:
        option_loan_check(slot, s)
    except Exception as ex:
        print('[optfix]', ex)
    try:
        _pbonus_check(slot, s)
    except Exception as ex:
        print('[pbonus]', ex)
    d = _addons(slot)
    due = [k for k, e in d.items() if e.get('bonus') and not e.get('paid')]
    if not due:
        return
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    squad = set(s.my_squad_tags())
    pay = []
    for k in due:
        pid, e = int(k), d[k]
        since = ms[min(e.get('base', 0), len(ms)):]
        apps = sum(1 for m in since if any(r[0] == pid and r[1] == my for r in m['rows']))
        if apps >= e.get('apps', ADD_APPS):
            pay.append((k, pid, e))
    if not pay:
        return
    tot = sum(e['bonus'] for _, _, e in pay)

    def fn(sv):
        sv.adjust_budget(-tot)
        return 'Appearance bonuses paid: %d EUR.' % tot
    _write_slot(slot, 'bonus', fn)
    for k, pid, e in pay:
        e['paid'] = True
        _ev_add(slot, 'bonus_paid', pid, fee=e['bonus'], to=e.get('club', ''))
    _addons_save(slot, d)


def _pbonus_check(slot, s):
    """Bonusi iz ugovora (nastup, gol, pobjeda) za igrace koje je app doveo: placa ih klub iz transfer budzeta
    za utakmice odigrane od potpisa (igra ih ne zna jer se jos ne upisuju u njen ugovor)."""
    d = _addons(slot)
    act = {k: e for k, e in d.items() if e.get('pbonus')}
    if not act:
        return
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    squad = set(s.my_squad_tags())
    tot, pays = 0, []
    for k, e in act.items():
        pid = int(k)
        if pid not in squad:
            continue
        since = ms[min(e.get('base', 0), len(ms)):]
        apps = goals = wins = 0
        for m in since:
            row = next((r for r in m['rows'] if r[0] == pid and r[1] == my), None)
            if not row:
                continue
            apps += 1
            goals += row[2] or 0
            gf = seasonstats.match_score_for(m, my)[0]
            ga = seasonstats.match_score_for(m, my)[1]
            wins += 1 if gf > ga else 0
        done = e.setdefault('pdone', dict(app=0, goal=0, win=0))
        pb = e['pbonus']
        amt = (apps - done.get('app', 0)) * pb.get('app', 0) + (goals - done.get('goal', 0)) * pb.get('goal', 0) + (wins - done.get('win', 0)) * pb.get('win', 0)
        if amt > 0:
            pays.append((pid, amt, apps - done.get('app', 0), goals - done.get('goal', 0), wins - done.get('win', 0)))
            tot += amt
        e['pdone'] = dict(app=apps, goal=goals, win=wins)
    if tot <= 0:
        _addons_save(slot, d)
        return

    def fn(sv):
        sv.adjust_budget(-tot)
        return 'Player bonuses paid: %d EUR.' % tot
    _write_slot(slot, 'pbonus', fn)
    _addons_save(slot, d)
    for pid, amt, a_, g_, w_ in pays:
        _ev_add(slot, 'pbonus_paid', pid, fee=amt, apps=a_, goals=g_, wins=w_)


def _interest(slot, ctx, pid):
    """Klubovi zainteresirani za igraca (random ali logicno, deterministicno po (slot, igrac, mjesec)).
    Broj ovisi o OVR-u, dobi (mladi talenti privlace vise, stariji manje) i ugovoru (istjece = vise). -> lista dict(club, bid, deadline), najjaca ponuda prva."""
    f = ctx['f']
    ovr = f['ovr'] or 0
    age = f['age'] or 25
    if ovr < 55:
        return []
    r = negotiate._rng('interest', slot, pid, ctx['month_key'])
    w = [0.15, 0.35, 0.5] if ovr >= 80 else [0.3, 0.4, 0.3] if ovr >= 72 else [0.55, 0.35, 0.1] if ovr >= 62 else [0.78, 0.19, 0.03]
    # 0 / 1 / 2+ zainteresiranih
    x, n = r.random(), 0
    acc = 0.0
    for i, pw in enumerate(w):
        acc += pw
        if x < acc:
            n = i
            break
    else:
        n = 2
    if n == 2 and r.random() < 0.3:
        n = 3
    ml = f.get('months_left')
    if age <= 22 and ovr >= 62 and n < 3 and r.random() < 0.5:
        n += 1
    if ml is not None and ml <= 6 and n < 3 and r.random() < 0.5:
        n += 1
    if f['listed'] and n < 3 and r.random() < 0.3:
        n += 1
    if age >= 32 and n > 1:
        n -= 1
    if not n:
        return []
    s = ctx['save']
    tiers = _club_tiers(slot, s)
    lo, hi = ovr - 7, ovr + (12 if age <= 22 else 3 if age >= 31 else 8)
    pool = []
    _ac = s.ai_clubs()
    _dupn = {k for k, v in __import__('collections').Counter(c[1] for c in _ac).items() if v > 1}   # pc260: rival se kasnije trazi po imenu
    for c in _ac:
        t = tiers.get((c[0] - mlwrite.REC0) // mlwrite.STRIDE)
        if t is None or c[1] == ctx['club'] or c[1] in _dupn:
            continue
        if lo <= t[1] <= hi:
            pool.append(c[1])
    r.shuffle(pool)
    ask = negotiate.club_ask(f, 'balanced')
    out = []
    for club in pool[:n]:
        bid = negotiate.rnd100(ask * r.uniform(0.96, 1.12), 1000 if ask > 20000 else 100)
        out.append(dict(club=club, bid=bid, deadline=r.choice([2, 3, 3])))
    out.sort(key=lambda z: -z['bid'])
    return out


def _rival_info(slot, ctx, pid, ptr, rv, my_sal, my_role):
    """Igrac bira izmedju mene i rivala: minute (uloga), klub (korak naprijed/nazad), placa. -> dict(riv_wage, riv_role, riv_wins, need_wage)"""
    f = ctx['f']
    pd = players_data(slot)
    ro = [r['ovr'] for r in pd['players'] if r['club'] == rv['club'] and r['ovr']]
    rstr = (sum(sorted(ro, reverse=True)[:14]) / min(14, len(ro))) if ro else None
    riv_role = negotiate.role_demand(ro, f) if ro else 'starter'
    ap_r = persona.appeal(f, ptr, ro, ctx['cur_str'], rstr, riv_role, 0)
    riv_wage = negotiate.rnd100(max(f['sal'] * 1.2, negotiate.wage_ask(f, 'normal', ro or ctx['my'], riv_role, 3)), 1000)
    ap_me = persona.appeal(f, ptr, ctx['my'], ctx['cur_str'], ctx['my_str'], my_role, ctx['crowd'])

    def tot(w):
        return ap_me['score'] + max(-0.4, min(0.4, (w / float(riv_wage) - 1.0) * 1.5))
    riv_t = ap_r['score'] + 0.02
    wins = riv_t > tot(my_sal)
    need = None
    if wins:
        w = my_sal
        while w <= riv_wage * 1.6:
            w *= 1.04
            if tot(w) >= riv_t:
                need = negotiate.rnd100(w, 1000)
                break
    return dict(riv_wage=riv_wage, riv_role=riv_role, riv_wins=wins, need_wage=need)


def _rival_move(slot, ctx, pid, rv):
    """Igrac stvarno prelazi u rivala (zapis u save). Vraca True ako je upisano."""
    try:
        if game_running():
            return False
        s = ctx['save']
        names = {c[1]: c[0] for c in s.ai_clubs()}
        to, frm = names.get(rv['club']), names.get(ctx['club'])
        if to is None or frm is None:
            return False
        idx = lambda o: (o - mlwrite.REC0) // mlwrite.STRIDE
        done, skipped, _b = _write_slot_moves(slot, [{'pid': pid, 'to': idx(to), 'from': idx(frm)}], 'rival')
        if pid in skipped or not done:
            return False
        try:
            _mark_moved(slot, s, pid)
        except Exception:
            pass
        _ev_add(slot, 'rival_signed', pid, to=rv['club'], frm=ctx['club'], fee=rv.get('bid') or 0)
        return True
    except Exception:
        return False


def interest_view(slot, pid):
    ctx = neg_context(slot, pid)
    return dict(pid=pid, clubs=[z['club'] for z in _interest(slot, ctx, pid)])


_CTID = {}


def club_tids(slot):
    """{indeks kluba: id lige} iz utakmica sezone u saveu (comps_view); kesirano po slotu i saveu."""
    try:
        key = (slot, os.path.getmtime(os.path.join(slot_folder(slot), 'data.dat')))
    except Exception:
        key = (slot, None)
    if _CTID.get('k') == key:
        return _CTID['v']
    out = {}
    try:
        for c in comps_view(slot).get('comps', []):
            if c.get('kind') == 'league':
                for r in c.get('rows') or []:
                    if r.get('idx') is not None:
                        out.setdefault(r['idx'], c['tid'])
    except Exception as ex:
        print('[reg] leagues:', ex)
    _CTID.update(k=key, v=out)
    return out


def reg_check(slot, s, pid, src_idx=None):
    """pc195: pravila registracije (Michele & Claude) za dolazak igraca u moj klub; ValueError s razlogom ako nije dopusteno.
    Iskljucivo: Setup -> reg_rules = false."""
    if not CFG.get('reg_rules', True):
        return
    try:
        tids = club_tids(slot)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        tid = tids.get(my)
        if tid not in regrules.RULES:
            return
        live = read_dump_any() or {}
        new = s.moved_this_window()
        squad = []
        for q in s.my_squad_tags():
            o, a = rat(q)
            squad.append(dict(pid=q, age=(live.get(q) or {}).get('age') or a, nat=(live.get(q) or {}).get('nat'), new=q in new))
        o, a = rat(pid)
        inc = dict(pid=pid, age=(live.get(pid) or {}).get('age') or a, nat=(live.get(pid) or {}).get('nat'))
        if src_idx is None:
            fc = s.find_club_of(pid)
            src_idx = ((fc[0] - mlwrite.REC0) // mlwrite.STRIDE) if fc else None
        why = regrules.check(tid, squad, inc, tids.get(src_idx) if src_idx is not None else None)
    except Exception as ex:
        print('[reg] check:', ex)
        return
    if why:
        raise ValueError(why)


def neg_start(body):
    slot, pid, old = body['slot'], int(body['pid']), int(body['old'])
    st = _neg_store()
    ctx = neg_context(slot, pid)
    reg_check(slot, mlwrite.Save(slot_folder(slot), ro=True), pid)
    s = ctx['save']
    deals = _slots(s)
    if old != 0 and old not in deals:
        raise ValueError('that deal does not exist')
    if old == 0 and s._squad_len(s.club_offset()) >= 40:
        raise ValueError('squad is full (40)')
    if pid in deals or pid in s.my_squad_tags():
        raise ValueError('player is already in your club or has a deal')
    if pid in _moved(slot, s):
        raise ValueError('player has already changed clubs in this transfer window')
    rec = st.get(slot, pid)
    try:
        _cid = _career_id(slot, s)
    except Exception:
        _cid = None
    if rec and 'old' in rec and _neg_expired(rec, ctx['gd'], _cid) and rec['stage'] != 'dead':
        rec = None   # pregovor iz proslog roka / druge karijere: krece ispocetka
    if rec and rec['stage'] == 'dead' and _cmp_date(ctx['gd'], rec.get('lock_until', 0)) < 0:
        return _neg_view(slot, pid, rec, ctx)
    if rec and bool(rec.get('pre')) != bool(body.get('pre')) and rec['stage'] != 'dead':
        rec = None   # pc316: obican pregovor i predugovor se ne mijesaju
    if rec and rec['stage'] in ('club', 'player', 'agent', 'medical', 'ready') and rec['old'] == old:
        if _neg_tick(slot, pid, rec, ctx):
            st.put(slot, pid, rec)
        return _neg_view(slot, pid, rec, ctx)
    rec = dict(stage='club', round=0, p_round=0, old=old, log=[], mood=negotiate.club_mood(slot, pid, ctx['month_key']),
               pmood=negotiate.player_mood(slot, pid, ctx['month_key']), date=ctx['gd'], career=_cid)
    if body.get('pre'):
        # pc316: predugovor (Bosman): igrac kojem istjece ugovor za najvise 6 mjeseci, dogovor samo s igracem, bez odstete
        if old != 0 or ctx.get('free') or not ctx.get('club'):
            raise ValueError('A pre-contract is only for a player at another club whose contract is running out.')
        ml_ = _precon_months(ctx['save'], pid)
        if ml_ is None or not (0 < ml_ <= 6):
            raise ValueError('A pre-contract is only possible in the last 6 months of the player\'s contract.')
        if pid in _precon_load(slot, s) and not _precon_load(slot, s)[pid].get('void'):
            raise ValueError('You already have a pre-contract with this player.')
        rec.update(stage='player', fee=0, free=True, pre=True, club0=ctx['club'], app_bonus=0, sellon=0,
                   dem0=persona.demanded_role(persona.squad_rank(ctx['my'], ctx['f']['ovr']), ctx['f']['age']))
        st.put(slot, pid, rec)
        return _neg_view(slot, pid, rec, ctx)
    if ctx.get('club') and _club_grudge(slot, ctx['club'], ctx['gd']):
        rec['mood'] = 'hard'
        rec['grudge'] = True
        _neg_log(rec, ctx, who='event', ev='grudge', club=ctx['club'])
    if ctx.get('free'):
        # slobodan igrac: nema kluba ni odstete, odmah razgovor s igracem (isti sustav kao kod igraca iz kluba)
        if not _fa_sign_ok(slot):
            raise ValueError(FA_CLASSIC_MSG)
        if old != 0:
            raise ValueError('slobodan igrac dolazi bez zamjene dogovora')
        rec.update(stage='player', fee=0, free=True, app_bonus=0, sellon=0,
                   dem0=persona.demanded_role(persona.squad_rank(ctx['my'], ctx['f']['ovr']), ctx['f']['age']))
    try:
        _il = _interest(slot, ctx, pid)
        rec['rival'] = _il[0] if _il else None
        rec['interested'] = [z['club'] for z in _il]
    except Exception:
        rec['rival'] = None
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)


def _lock(rec, ctx):
    rec['stage'] = 'dead'
    rec['lock_until'] = _add_days(ctx['gd'], negotiate.LOCK_DAYS)


def _win_last(gd):
    """Zadnji dan prijelaznog roka (kod datuma) ako je rok otvoren, inace None."""
    k, idx, state = win_state(gd)
    if state != 'in':
        return None
    y = gd & 0xffff
    return ((31 << 24) | (8 << 16) | y) if k[0] == 'S' else ((31 << 24) | (1 << 16) | y)


def _due(gd, days):
    """Datum kad stize odgovor; nikad nakon zadnjeg dana roka (zadnji dan je guzva, sve se rjesava isti dan)."""
    d = _add_days(gd, max(0, int(days)))
    last = _win_last(gd)
    if last is not None and _cmp_date(d, last) > 0:
        d = last
    return d


def _seller_rank(slot, ctx, pid):
    try:
        pd = players_data(slot)
        rows = sorted((r for r in pd['players'] if r['club'] == ctx['club'] and r['ovr']), key=lambda r: -r['ovr'])
        return next((i for i, r in enumerate(rows) if r['id'] == pid), None)
    except Exception:
        return None


def _neg_world(slot, kind, pid, club, **kw):
    try:
        s = mlwrite.Save(slot_folder(slot), ro=True)
        d = worldlib.date_str(s.game_date_code())
        world(slot, s).add(kind, d, 'neg:%s:%s:%s:%s' % (kind, pid, club, d), pid=pid, clubs=[club], club=club, name=NAMES.get(pid), **kw)
    except Exception as ex:
        print('[world] neg:', ex)


def _club_grudge(slot, club, gd):
    """Klub pamti uvredljivu ponudu (godinu dana): tvrd u pregovorima."""
    try:
        since = worldlib.date_str(_add_days(gd, -365))
        return bool(world(slot).query(kind='neg_insult', club=club, since=since))
    except Exception:
        return False


def _neg_log(rec, ctx, **e):
    e.setdefault('d', _fmt_date(ctx['gd']))
    rec['log'].append(e)


def neg_offer(body):
    slot, pid, fee = body['slot'], int(body['pid']), int(body['fee'])
    bonus = max(0, int(body.get('bonus') or 0))
    sellon = max(0, min(30, int(body.get('sellon') or 0)))
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'club':
        raise ValueError('negotiation is not at the club stage')
    ctx = neg_context(slot, pid)
    _neg_tick(slot, pid, rec, ctx)
    if rec.get('pending'):
        raise ValueError('%s have not answered your last offer yet (reply by %s).' % (ctx['club'] or 'The club', _fmt_due(rec['pending']['due'])))
    if rec['stage'] != 'club':
        st.put(slot, pid, rec)
        return _neg_view(slot, pid, rec, ctx)
    deals = _slots(ctx['save'])
    if rec['old'] != 0 and rec['old'] not in deals:
        raise ValueError('swap deal no longer exists')
    if fee <= 0:
        raise ValueError('invalid offer')
    if fee > ctx['save'].budget() + _old_deal(deals, rec['old'])['fee']:
        raise ValueError('Not enough transfer budget for this offer.')
    rec['round'] += 1
    _neg_log(rec, ctx, who='you', stage='club', amount=fee, bonus=bonus, sellon=sellon)
    delay = nego2.club_delay(slot, pid, rec['round'], rec['mood'])
    rec['pending'] = dict(kind='club', due=_due(ctx['gd'], delay), fee=fee, bonus=bonus, sellon=sellon)
    _neg_tick(slot, pid, rec, ctx)
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)


def _neg_tick(slot, pid, rec, ctx):
    """Odgovor koji je dospio (datum igre >= rok odgovora) se izvrsi. Vraca True ako se nesto promijenilo."""
    pe = rec.get('pending')
    if not pe or _cmp_date(ctx['gd'], pe['due']) < 0:
        return False
    if pe.get('hurry'):
        pe.pop('hurry')
    kind = pe['kind']
    if kind == 'club':
        if not _club_events(slot, pid, rec, ctx):
            return True   # klub odugovlaci: novi rok
        rec.pop('pending', None)
        _club_resolve(slot, pid, rec, ctx, pe['fee'], pe['bonus'], pe['sellon'])
    elif kind == 'player':
        rec.pop('pending', None)
        _terms_resolve(slot, pid, rec, ctx, pe['salary'], pe['years'], pe['role'])
    elif kind == 'medical':
        rec.pop('pending', None)
        _medical_resolve(slot, pid, rec, ctx)
    elif kind == 'quiet':
        rec.pop('pending', None)
        _quiet_resolve(slot, pid, rec, ctx)
    else:
        rec.pop('pending', None)
    return True


def _club_events(slot, pid, rec, ctx):
    """Neocekivani dogadjaji prije odgovora kluba. False = klub jos ne odgovara (rok pomaknut)."""
    used = set(rec.get('ev_used') or [])
    ev = nego2.club_event(slot, pid, rec['round'], ctx['f'], used, bool(rec.get('rival')), _seller_rank(slot, ctx, pid))
    if not ev:
        return True
    used.add(ev)
    rec['ev_used'] = sorted(used)
    c = ctx['club'] or 'The club'
    if ev == 'stall':
        n = nego2.stall_days(slot, pid, rec['round'])
        nd = _due(ctx['gd'], n)
        if _cmp_date(nd, ctx['gd']) <= 0:
            return True   # zadnji dan roka: nema vremena za odugovlacenje
        rec['pending']['due'] = nd
        why = nego2.rng('stallwhy', slot, pid, rec['round']).choice(nego2.STALL_WHY)
        _neg_log(rec, ctx, who='event', ev='stall', club=c, until=_fmt_due(nd), why=why)
        return False
    if ev == 'coach_block':
        if rec['mood'] == 'hard':
            _neg_log(rec, ctx, who='event', ev='coach_block_walk', club=c)
            rec.pop('pending', None)
            _lock(rec, ctx)
            _neg_world(slot, 'neg_collapse', pid, ctx['club'], reason='coach_block')
            return False
        rec['mood'] = 'hard'
        why = nego2.rng('blockwhy', slot, pid, rec['round']).choice(nego2.BLOCK_WHY)
        _neg_log(rec, ctx, who='event', ev='coach_block', club=c, why=why)
        return True
    if ev == 'soften':
        rec['mood'] = 'eager'
        why = nego2.rng('softwhy', slot, pid, rec['round']).choice(nego2.SOFT_WHY)
        _neg_log(rec, ctx, who='event', ev='soften', club=c, why=why)
        return True
    if ev == 'rival':
        try:
            il = _interest(slot, ctx, pid)
        except Exception:
            il = []
        if il:
            rv = dict(il[0])
            rv['deadline'] = rec['round'] + 2
            rec['rival'] = rv
            rec['interested'] = sorted(set((rec.get('interested') or []) + [z['club'] for z in il]))
            _neg_log(rec, ctx, who='event', ev='rival', club=c, rival=rv['club'])
        return True
    return True


def _club_resolve(slot, pid, rec, ctx, fee, bonus, sellon):
    av = _addon_value(ctx['f'], bonus, sellon)
    value = fee + av
    lcv = rec.get('lc_val')
    rv = rec.get('rival')
    if lcv and value >= lcv:
        r = dict(decision='accept', counter=fee, hint='hot')
    elif rv and value < rv['bid']:
        rec['lc_val'] = rv['bid']
        rec['rival_known'] = True
        r = dict(decision='counter', counter=max(fee + 100, negotiate.rnd100(rv['bid'] - av, 100)), hint='warm', rival=True)
    else:
        r = negotiate.club_reply(ctx['f'], rec['mood'], value, rec['round'])
        if r['decision'] == 'counter':
            rec['lc_val'] = r['counter']
            r['counter'] = max(fee, negotiate.rnd100(r['counter'] - av, 100))
    if rv and r['decision'] != 'accept' and rec['round'] >= rv['deadline']:
        r = dict(decision='walk', hint='cold', rival_won=True)
    rec['tone'] = rec['mood']
    ent = dict(who='club', stage='club', decision=r['decision'], hint=r.get('hint'), counter=r.get('counter'), d=_fmt_date(ctx['gd']))
    if r.get('rival'):
        ent['rival'] = True
    if r.get('rival_won'):
        ent['rival_won'] = True
        ent['moved'] = _rival_move(slot, ctx, pid, rv)
    rec['log'].append(ent)
    if r['decision'] == 'accept':
        rec['stage'] = 'player'
        rec['fee'] = fee
        rec['app_bonus'] = bonus
        rec['sellon'] = sellon
        _rk = persona.squad_rank(ctx['my'], ctx['f']['ovr'])
        rec['dem0'] = persona.demanded_role(_rk, ctx['f']['age'])
    elif r['decision'] == 'counter':
        rec['last_counter'] = r['counter']
    elif r['decision'] == 'walk':
        _lock(rec, ctx)
        ask = negotiate.club_ask(ctx['f'], rec['mood'], negotiate.BUY_K)
        if ask and value / float(ask) < 0.65:
            _neg_world(slot, 'neg_insult', pid, ctx['club'], offer=fee)
            rec['insult'] = True


def neg_quiet(body):
    """Kupujes: ne javljas se klubu nekoliko dana, da vidis hoce li popustiti (ili ce ga netko drugi uzeti)."""
    slot, pid = body['slot'], int(body['pid'])
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'club' or rec.get('pending'):
        raise ValueError('You can only go quiet during club talks, when they are not already deciding.')
    if 'quiet' in (rec.get('ev_used') or []):
        raise ValueError('You already went quiet once: they will not fall for it again.')
    ctx = neg_context(slot, pid)
    n = nego2.rng('quiet', slot, pid, rec['round']).randint(2, 4)
    due = _due(ctx['gd'], n)
    if _cmp_date(due, ctx['gd']) <= 0:
        raise ValueError('It is the last day of the window: no time to play games.')
    rec.setdefault('ev_used', []).append('quiet')
    rec['pending'] = dict(kind='quiet', due=due)
    _neg_log(rec, ctx, who='you', stage='club', ev='quiet', until=_fmt_due(due))
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)


def _quiet_resolve(slot, pid, rec, ctx):
    f = ctx['f']
    r = nego2.rng('quietres', slot, pid, rec['round'])
    last = _win_last(ctx['gd'])
    late = last is not None and _cmp_date(_add_days(ctx['gd'], 5), last) >= 0
    soft = (f.get('months_left') is not None and f['months_left'] <= 12) or f.get('listed') or late
    p_soft = 0.55 if soft else 0.25
    rv = rec.get('rival')
    x = r.random()
    c = ctx['club'] or 'The club'
    if rv and x < 0.35:
        _neg_log(rec, ctx, who='event', ev='quiet_rival', club=c, rival=rv['club'])
        ent = dict(who='club', stage='club', decision='walk', hint='cold', rival_won=True, d=_fmt_date(ctx['gd']))
        ent['moved'] = _rival_move(slot, ctx, pid, rv)
        rec['log'].append(ent)
        _lock(rec, ctx)
        return
    if r.random() < p_soft:
        rec['mood'] = 'eager'
        if rec.get('last_counter'):
            k = r.uniform(0.9, 0.96)
            rec['last_counter'] = negotiate.rnd100(rec['last_counter'] * k, 1000)
            if rec.get('lc_val'):
                rec['lc_val'] = negotiate.rnd100(rec['lc_val'] * k, 1000)
        _neg_log(rec, ctx, who='event', ev='quiet_soften', club=c, amount=rec.get('last_counter'))
    else:
        _neg_log(rec, ctx, who='event', ev='quiet_nothing', club=c)


def neg_hurry(body):
    """Trazis odgovor odmah: klub/agent odgovori danas, ali se moze naljutiti (tvrdji stav)."""
    slot, pid = body['slot'], int(body['pid'])
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or not rec.get('pending'):
        raise ValueError('nothing to wait for')
    if rec['pending']['kind'] in ('medical', 'quiet'):
        raise ValueError('This cannot be rushed. Advance days in the game.')
    ctx = neg_context(slot, pid)
    pe = rec['pending']
    r = nego2.rng('hurry', slot, pid, rec['round'], rec.get('p_round', 0), pe['kind'])
    annoyed = r.random() < 0.4
    if pe['kind'] == 'club' and annoyed:
        rec['mood'] = {'eager': 'balanced', 'balanced': 'hard'}.get(rec['mood'], 'hard')
    if pe['kind'] == 'player' and annoyed:
        rec['pmood'] = {'modest': 'normal', 'normal': 'greedy'}.get(rec['pmood'], 'greedy')
    _neg_log(rec, ctx, who='event', ev='hurry_annoyed' if annoyed else 'hurry', club=ctx['club'], target=pe['kind'])
    pe['due'] = ctx['gd']
    pe['hurry'] = True
    rec.setdefault('ev_used', [])
    if 'stall' not in rec['ev_used']:
        rec['ev_used'].append('stall')   # pod pritiskom vise ne odugovlace
    _neg_tick(slot, pid, rec, ctx)
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)



SB_FILE = os.path.join(HERE, 'data', 'salary_base.json')


def _sb_store():
    try:
        return json.load(open(SB_FILE, encoding='utf-8'))
    except Exception:
        return {}


def sbase_set(body):
    """Korisnik upise Salary Budget kako ga igra prikazuje (preostalo). Osnovica sezone = prikazano + trenutne place
    (provjereno 27.10. na Arsenalu: 9.002.600 → 7.711.500 → 6.415.800 uz dva potpisa, osnovica ista 157.918.200)."""
    slot = body['slot']
    shown = int(str(body.get('shown') or '0').replace('.', '').replace(',', '').strip() or 0)
    s = mlwrite.Save(slot_folder(slot), ro=True)
    y, m, _ = _date_tuple(s.game_date_code())
    base = shown + s.wage_commitment()
    a = _sb_store()
    a.pop(slot, None)
    a[_career_id(slot, s)] = dict(base=base, season=y if m >= 7 else y - 1, shown=shown, when=_fmt_date(s.game_date_code()))   # pc147: po karijeri
    _jdump(a, SB_FILE, indent=1)
    return dict(ok=True, base=base, room=shown)


def _sbase_need(slot, s, body, required=True):
    """Osnovica salary budgeta: iz zahtjeva, inace spremljena za ovu sezonu. Bez nje igra zna potiho otkazati posudbu ili transfer
    na dan dolaska (place iznad budzeta), pa je app trazi jednom po sezoni."""
    v = body.get('sbase')
    if v not in (None, ''):
        return int(v)
    e = _sb_store().get(_career_id(slot, s)) or {}
    y, m, _ = _date_tuple(s.game_date_code())
    if e.get('base') and e.get('season') == (y if m >= 7 else y - 1):
        return int(e['base'])
    if not required:
        return None    # posudbe: utjecaj na salary budget jos nije potvrden u igri, ne blokiramo
    raise ValueError('[salary-budget] Enter your Salary Budget first: the game cancels a deal on the arrival day if his wage does not fit, without telling you.')

def neg_terms(body):
    slot, pid = body['slot'], int(body['pid'])
    sal, years, role = int(body['salary']), int(body['years']), body['role']
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'player':
        raise ValueError('negotiation is not at the player stage')
    if rec.get('pending'):
        raise ValueError("The player's agent has not answered yet (reply by %s)." % _fmt_due(rec['pending']['due']))
    if not (1 <= years <= 5) or role not in negotiate.ROLES or sal <= 0:
        raise ValueError('invalid terms')
    ctx = neg_context(slot, pid)
    sbase = _sbase_need(slot, ctx['save'], body)
    if sbase not in (None, ''):
        deals = _slots(ctx['save'])
        after = int(sbase) - (ctx['save'].wage_commitment() - _old_deal(deals, rec['old'])['salary'] + sal)
        if after < 0:
            raise ValueError('Over the salary budget (%d EUR short).' % -after)
    rel = max(0, int(body.get('release') or 0))
    b_app, b_goal, b_win = (max(0, min(200000, int(body.get(k) or 0))) for k in ('b_app', 'b_goal', 'b_win'))
    rec['terms_x'] = _terms_extra(pid, ctx, role, rel, b_app, b_goal, b_win)
    rec['p_round'] = rec.get('p_round', 0) + 1
    _neg_log(rec, ctx, who='you', stage='player', amount=sal, years=years, role=role, release=rel, b_app=b_app, b_goal=b_goal, b_win=b_win)
    delay = nego2.agent_delay(slot, pid, rec['p_round'], rec['pmood'])
    rec['pending'] = dict(kind='player', due=_due(ctx['gd'], delay), salary=sal, years=years, role=role)
    _neg_tick(slot, pid, rec, ctx)
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)



BONUS_APPS = {'key': 34, 'starter': 30, 'rotation': 20, 'prospect': 10}


def _terms_extra(pid, ctx, role, rel, b_app, b_goal, b_win):
    """Koliko igrac vrijedi bonuse i odstetnu klauzulu (kao dodatak placi): ocekivani nastupi po ulozi,
    golovi po poziciji, pobjede ~45 %. Igrac racuna bonuse s 70 % (nisu sigurni). Niska klauzula vrijedi onima koji je zele."""
    apps = BONUS_APPS.get(role, 20)
    pos = POS.get(pid, 5)
    gpa = 0.42 if pos >= 9 else 0.2 if pos == 8 else 0.1 if pos >= 4 else 0.04 if pos >= 1 else 0.0
    val = apps * b_app + apps * gpa * b_goal + apps * 0.45 * b_win
    add = 0.7 * val
    mv = (ctx.get('f') or {}).get('mv') or 0
    try:
        wants = persona.wants_clause(persona.traits(pid))
    except Exception:
        wants = False
    sal0 = (ctx.get('f') or {}).get('sal') or 0
    if rel and mv:
        if rel <= mv * 1.1:
            add += sal0 * (0.06 if wants else 0.02)
        elif rel <= mv * 1.6:
            add += sal0 * (0.03 if wants else 0.0)
    return dict(release=rel, b_app=b_app, b_goal=b_goal, b_win=b_win, add=int(add), bonus_value=int(val))

def _terms_resolve(slot, pid, rec, ctx, sal, years, role):
    ptr = persona.traits(pid)
    ap = persona.appeal(ctx['f'], ptr, ctx['my'], ctx['cur_str'], ctx['my_str'], role, ctx['crowd'])
    rec['interest'] = persona.interest(ap['score'])
    extra = {}
    if persona.changed_mind(rec.get('dem0'), ap['dem'], ptr):
        r = dict(decision='withdraw', hint='cold')
        extra = dict(why=['competition'])
    elif ap['score'] < persona.REFUSE:
        r = dict(decision='refuse', hint='cold')
        extra = dict(why=ap['neg'][:2] or ['step_down'])
    else:
        lc = rec.get('p_last_counter')
        tx = rec.get('terms_x') or {}
        eff = sal + int(tx.get('add') or 0)          # bonusi i klauzula kao dodatak placi
        if lc and sal >= lc and rec.get('p_last_role') == role and rec.get('p_last_years') == years:
            r = dict(decision='accept', counter=sal, hint='hot')
        else:
            r = negotiate.player_reply(ctx['f'], rec['pmood'], ctx['my'], eff, years, role, rec['p_round'], persona.premium(ap['score']))
            if r.get('counter') and r['decision'] == 'counter':
                r['counter'] = max(sal + 100, negotiate.rnd100(r['counter'] - int(tx.get('add') or 0), 100))
            elif r['decision'] == 'accept':
                r['counter'] = sal
        if persona.premium(ap['score']) > 1.0 and r['decision'] in ('counter', 'reject'):
            extra = dict(why=ap['neg'][:2], premium=True)
        if r['decision'] == 'accept' and persona.wants_clause(ptr):
            cap = max(rec['fee'], negotiate.rnd100(ctx['f']['mv'] * 0.7, 1000))
            rec['clause'] = cap
            extra = dict(clause=cap)
    rv = rec.get('rival')
    if rv and r['decision'] == 'accept':
        pv = _rival_info(slot, ctx, pid, ptr, rv, sal, role)
        if pv['riv_wins']:
            extra = dict(rival=True, rwage=pv['riv_wage'], rrole=pv['riv_role'])
            if pv['need_wage']:
                r = dict(decision='counter', counter=pv['need_wage'], hint='warm')
            else:
                r = dict(decision='rival_pick', hint='cold')
                extra['moved'] = _rival_move(slot, ctx, pid, rv)
    rec['ptone'] = rec['pmood']
    rec['log'].append(dict(who='player', stage='player', decision=r['decision'], hint=r.get('hint'), counter=r.get('counter'), d=_fmt_date(ctx['gd']), **extra))
    if r['decision'] == 'accept':
        rec.update(salary=sal, years=years, role=role)
        tx = rec.get('terms_x') or {}
        if tx.get('release'):
            rec['clause'] = tx['release']
        rec['pbonus'] = dict(app=tx.get('b_app', 0), goal=tx.get('b_goal', 0), win=tx.get('b_win', 0))
        ask = nego2.agent_ask(slot, pid, ctx['f'], rec.get('fee') or 0, bool(rec.get('free')), ptr['money'], sal)
        rec.update(stage='agent', agent=dict(ask=ask, haggled=False))
        _neg_log(rec, ctx, who='agent', stage='agent', ev='agent_ask', amount=ask, free=bool(rec.get('free')))
    elif r['decision'] == 'counter':
        rec.update(p_last_counter=r['counter'], p_last_role=role, p_last_years=years)
    elif r['decision'] in ('walk', 'refuse', 'withdraw', 'rival_pick'):
        _lock(rec, ctx)


def neg_agent(body):
    """Naknada agentu: pay | haggle | refuse."""
    slot, pid, ch = body['slot'], int(body['pid']), body.get('choice')
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'agent':
        raise ValueError('negotiation is not at the agent stage')
    ctx = neg_context(slot, pid)
    ag = rec['agent']
    ptr = persona.traits(pid)
    deals = _slots(ctx['save'])
    room = ctx['save'].budget() + _old_deal(deals, rec['old'])['fee'] - (rec.get('fee') or 0)
    if ch == 'pay':
        if ag['ask'] > room:
            raise ValueError('Not enough transfer budget for the agent fee (%s short).' % money_s(ag['ask'] - room))
        _neg_log(rec, ctx, who='you', stage='agent', ev='agent_pay', amount=ag['ask'])
        rec['agent_fee'] = ag['ask']
        _start_medical(slot, pid, rec, ctx)
    elif ch == 'haggle':
        if ag.get('haggled'):
            raise ValueError('The agent will not discuss the fee again.')
        ag['haggled'] = True
        _neg_log(rec, ctx, who='you', stage='agent', ev='agent_haggle')
        res, x = nego2.agent_haggle(slot, pid, ptr['loyalty'])
        if res == 'cut':
            ag['ask'] = negotiate.rnd100(ag['ask'] * x, 1000)
            _neg_log(rec, ctx, who='agent', stage='agent', ev='agent_cut', amount=ag['ask'])
        elif res == 'firm':
            _neg_log(rec, ctx, who='agent', stage='agent', ev='agent_firm', amount=ag['ask'])
        else:
            if x:
                _neg_log(rec, ctx, who='agent', stage='agent', ev='agent_walk')
                _lock(rec, ctx)
                _neg_world(slot, 'neg_collapse', pid, ctx['club'], reason='agent')
            else:
                _neg_log(rec, ctx, who='agent', stage='agent', ev='agent_offended', amount=ag['ask'])
    elif ch == 'refuse':
        _neg_log(rec, ctx, who='you', stage='agent', ev='agent_refuse')
        if nego2.agent_refused(slot, pid, ptr['loyalty'], ptr['ambition']):
            _neg_log(rec, ctx, who='player', stage='agent', ev='agent_overruled')
            rec['agent_fee'] = 0
            _start_medical(slot, pid, rec, ctx)
        else:
            _neg_log(rec, ctx, who='agent', stage='agent', ev='agent_takes_away')
            _lock(rec, ctx)
            _neg_world(slot, 'neg_collapse', pid, ctx['club'], reason='agent_refused')
    else:
        raise ValueError('unknown choice')
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)


def money_s(x):
    return '%.1fM EUR' % (x / 1e6) if x >= 1e6 else '%dK EUR' % (x // 1000)


def _start_medical(slot, pid, rec, ctx):
    rec['stage'] = 'medical'
    rec['pending'] = dict(kind='medical', due=_due(ctx['gd'], 1))
    _neg_log(rec, ctx, who='event', ev='medical_booked', until=_fmt_due(rec['pending']['due']))
    _neg_tick(slot, pid, rec, ctx)


def _medical_resolve(slot, pid, rec, ctx):
    lv = {}
    try:
        lv = (read_dump()[0] or {}).get(pid) or {}
    except Exception:
        pass
    res = nego2.medical(slot, pid, ctx['f']['age'] or 25, inj_low=(lv.get('inj') == 1))
    rec['med'] = res
    if res == 'pass':
        _neg_log(rec, ctx, who='event', ev='medical_pass')
        rec['stage'] = 'ready'
    elif res == 'concern':
        _neg_log(rec, ctx, who='event', ev='medical_concern')
    else:
        _neg_log(rec, ctx, who='event', ev='medical_fail')
        _lock(rec, ctx)
        _neg_world(slot, 'neg_collapse', pid, ctx['club'], reason='medical')


def neg_medical(body):
    """Nalaz na lijecnickom: sign | discount | walk."""
    slot, pid, ch = body['slot'], int(body['pid']), body.get('choice')
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'medical' or rec.get('med') not in ('concern', 'concern_no'):
        raise ValueError('no medical decision is needed')
    ctx = neg_context(slot, pid)
    if ch == 'sign':
        _neg_log(rec, ctx, who='you', stage='medical', ev='medical_accept')
        rec['stage'] = 'ready'
    elif ch == 'discount':
        if rec['med'] == 'concern_no' or rec.get('free'):
            raise ValueError('The club has already refused to lower the fee.')
        _neg_log(rec, ctx, who='you', stage='medical', ev='medical_ask_discount')
        f = nego2.medical_discount(slot, pid)
        if f:
            rec['fee'] = negotiate.rnd100(rec['fee'] * f, 1000)
            _neg_log(rec, ctx, who='club', stage='medical', ev='medical_discount', amount=rec['fee'])
            rec['stage'] = 'ready'
        else:
            rec['med'] = 'concern_no'
            _neg_log(rec, ctx, who='club', stage='medical', ev='medical_no_discount')
    elif ch == 'walk':
        _neg_log(rec, ctx, who='you', stage='medical', ev='medical_walk')
        rec['stage'] = 'dead'
        _neg_world(slot, 'neg_collapse', pid, ctx['club'], reason='medical_walk')
    else:
        raise ValueError('unknown choice')
    st.put(slot, pid, rec)
    return _neg_view(slot, pid, rec, ctx)


PRECON_FILE = os.path.join(HERE, 'data', 'precontracts.json')
PRECON_LOCK = threading.Lock()


def _precon_months(s, pid):
    """Mjeseci do isteka ugovora (iz savea); None ako nije poznato."""
    k = s.read_contracts([pid]).get(pid) or {}
    if not k.get('y'):
        return None
    y, m, _ = _date_tuple(s.game_date_code())
    return (k['y'] - y) * 12 + ((k.get('m') or 6) - m)


def _precon_all():
    try:
        return json.load(open(PRECON_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _precon_load(slot, s):
    return {int(k): v for k, v in (_precon_all().get(_career_id(slot, s)) or {}).items()}


def _precon_store(slot, pid, rec, ctx):
    s = ctx['save']
    y, m, _ = _date_tuple(ctx['gd'])
    k = s.read_contracts([pid]).get(pid) or {}
    ey = k.get('y') or y
    yr = ey + rec['years']   # novi ugovor krece kad stari istekne
    e = dict(pid=pid, name=NAMES.get(pid, str(pid)), club=rec.get('club0') or ctx.get('club') or '', sal=int(rec['salary']), years=rec['years'],
             until=yr, agent_fee=int(rec.get('agent_fee') or 0), role=rec.get('role'), d=_fmt_date(ctx['gd']),
             ends='%d.%d.%d' % (k.get('d') or 31, k.get('m') or 8, ey), clause=rec.get('clause'), pbonus=rec.get('pbonus'))
    with PRECON_LOCK:
        A = _precon_all()
        A.setdefault(_career_id(slot, s), {})[str(pid)] = e
        _jdump(A, PRECON_FILE, ensure_ascii=False, indent=1)
    rec['stage'] = 'done'
    _neg_store().put(slot, pid, rec)
    try:
        _ev_add(slot, 'precontract', pid, frm=e['club'], wage=e['sal'], years=e['years'], until=yr)
    except Exception:
        pass
    return dict(ok=True, precontract=e, message='Pre-contract agreed with %s: he joins on a free when his contract at %s ends (%s). '
                'Complete the move from the Inbox once the transfer window is open.' % (e['name'], e['club'], e['ends']))


def precon_view(slot):
    """Predugovori (moji dogovori) + kandidati (igraci drugih klubova kojima istjece ugovor za <= 6 mj.) + moji igraci pred Bosmanom."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    inwin = win_state(gd)[2] == 'in'
    mine = _precon_load(slot, s)
    pd = players_data(slot)
    byid = {r['id']: r for r in pd['players']}
    out = []
    for pid, e in mine.items():
        if e.get('done') or e.get('void'):
            continue
        r = byid.get(pid) or {}
        ml = _precon_months(s, pid)
        e = dict(e, now_club=r.get('club') or '', ovr=r.get('ovr'), age=r.get('age'), months_left=ml)
        e['status'] = ('void' if r.get('club') and r.get('club') != e['club'] and not r.get('mine') else
                       'ready' if inwin and (ml is None or ml <= 2) else 'waiting')
        out.append(e)
    my = set(s.my_squad_tags())
    ids = [r['id'] for r in pd['players'] if r.get('club') and r['id'] not in my and (r.get('ovr') or 0) >= 70]
    K = s.read_contracts(ids)
    cands = []
    for pid in ids:
        k = K.get(pid) or {}
        if not k.get('y'):
            continue
        ml = (k['y'] - y) * 12 + ((k.get('m') or 6) - m)
        if 0 < ml <= 6 and pid not in mine:
            r = byid[pid]
            cands.append(dict(pid=pid, name=r['name'], club=r['club'], ovr=r['ovr'], age=r['age'], pos=r.get('pos'), sal=k.get('sal'),
                              ends='%d.%d.%d' % (k.get('d') or 31, k.get('m') or 8, k['y']), months_left=ml))
    cands.sort(key=lambda c: (-(c['ovr'] or 0), c['age'] or 99))
    cs = {}
    for r in pd['players']:
        if r.get('club') and not r.get('mine') and r.get('ovr'):
            cs.setdefault(r['club'], []).append(r['ovr'])
    cstr = {c: sum(sorted(v, reverse=True)[:14]) / float(min(14, len(v))) for c, v in cs.items() if len(v) >= 14}
    Km = s.read_contracts(list(my))
    risk = []
    for pid in my:
        k = Km.get(pid) or {}
        if not k.get('y'):
            continue
        ml = (k['y'] - y) * 12 + ((k.get('m') or 6) - m)
        if 0 < ml <= 6:
            r = byid.get(pid) or {}
            risk.append(dict(pid=pid, name=r.get('name') or NAMES.get(pid, str(pid)), ovr=r.get('ovr'), age=r.get('age'), months_left=ml,
                             ends='%d.%d.%d' % (k.get('d') or 31, k.get('m') or 8, k['y']), suitors=_bosman_suitors(slot, s, pid, r, cstr)))
    risk.sort(key=lambda x: -(x['ovr'] or 0))
    return dict(ok=True, mine=out, cands=cands[:120], risk=risk, window=inwin, date=_fmt_date(gd))


def _bosman_suitors(slot, s, pid, r, cstr):
    """Koji AI klubovi 'nude predugovor' mom igracu (stabilno po mjesecu): jaci igrac = vise klubova. Samo najava; igra sama
    pusta igraca kad ugovor istekne ako ga ne produljis."""
    import random
    try:
        ovr = r.get('ovr') or 65
        if ovr < 72:
            return []
        y, m, _ = _date_tuple(s.game_date_code())
        rnd = random.Random('%s-%d-%d-%d' % (_career_id(slot, s), pid, y, m))
        clubs = sorted(c for c, v in cstr.items() if v >= ovr - 5)
        n = 1 + (ovr >= 78) + (ovr >= 83)
        return rnd.sample(clubs, min(n, len(clubs))) if clubs and rnd.random() < 0.35 + 0.08 * (ovr - 72) else []
    except Exception:
        return []


def precon_complete(body):
    slot, pid = body['slot'], int(body['pid'])
    s0 = mlwrite.Save(slot_folder(slot), ro=True)
    mine = _precon_load(slot, s0)
    e = mine.get(pid)
    if e and e.get('void') == 'manager_left':
        raise ValueError('This pre-contract was agreed for %s; it does not move with you to your new club.' % (e.get('void_club') or 'your old club'))
    if not e or e.get('done'):
        raise ValueError('No open pre-contract with this player.')
    if win_state(s0.game_date_code())[2] != 'in':
        raise ValueError('The transfer window is closed. The player joins when the window opens.')
    if s0._squad_len(s0.club_offset()) >= 40:
        raise ValueError('squad is full (40)')
    reg_check(slot, s0, pid)
    cur = next((r for r in players_data(slot)['players'] if r['id'] == pid), {}) or {}
    free_now = not cur.get('club')
    if cur.get('club') and cur['club'] != e['club']:
        raise ValueError('%s has moved to %s in the game: the pre-contract is void.' % (e['name'], cur['club']))
    end = (31 << 24) | (8 << 16) | int(e['until'])

    def fn(s):
        if free_now:
            s.sign_outside_x(pid, 0, e['sal'], int(e['until']), pos=POS, free=True, release=e.get('clause') or 0)
        elif s.ext and getattr(s, 'game27', False):
            s.add_deal(pid, 0, e['sal'], release=e.get('clause') or negotiate.rnd100(e['sal'] * 10, 100), end=end, level=2)
        else:
            s.direct_sign(pid, 0, e['sal'], end, pos=POS)
        if e.get('agent_fee'):
            s.adjust_budget(-e['agent_fee'])
        return '%s joins on a free (pre-contract): wage %d EUR/yr, contract until 31/8/%d.' % (e['name'], e['sal'], e['until'])
    r = _write_slot(slot, 'precon', fn, pid=pid)
    with PRECON_LOCK:
        A = _precon_all()
        A.setdefault(_career_id(slot, s0), {}).setdefault(str(pid), e)['done'] = True
        _jdump(A, PRECON_FILE, ensure_ascii=False, indent=1)
    PCACHE.clear()
    FA_CACHE.clear()
    _mark_moved(slot, s0, pid)
    try:
        _ev_add(slot, 'signed', pid, frm=e['club'], fee=0, wage=e['sal'], years=e['years'], until=e['until'])
    except Exception:
        pass
    return r


def precon_cancel(body):
    slot, pid = body['slot'], int(body['pid'])
    s0 = mlwrite.Save(slot_folder(slot), ro=True)
    with PRECON_LOCK:
        A = _precon_all()
        A.get(_career_id(slot, s0), {}).pop(str(pid), None)
        _jdump(A, PRECON_FILE, ensure_ascii=False, indent=1)
    return dict(ok=True, message='Pre-contract cancelled.')


def neg_finish(body):
    slot, pid = body['slot'], int(body['pid'])
    st = _neg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'ready':
        raise ValueError('negotiation is not finished')
    reg_check(slot, mlwrite.Save(slot_folder(slot)), pid)
    ctx = neg_context(slot, pid)
    _ptr = persona.traits(pid)
    _ap = persona.appeal(ctx['f'], _ptr, ctx['my'], ctx['cur_str'], ctx['my_str'], rec.get('role'), ctx['crowd'])
    if persona.changed_mind(rec.get('dem0'), _ap['dem'], _ptr):
        rec['log'].append(dict(who='player', stage='player', decision='withdraw', hint='cold', why=['competition']))
        _lock(rec, ctx)
        st.put(slot, pid, rec)
        raise ValueError('The player changed his mind: there is less room for him in the squad now.')
    fee, sal = rec['fee'], rec['salary']
    _gy, _gm, _gd_ = _date_tuple(ctx['gd'])
    if rec.get('pre'):
        return _precon_store(slot, pid, rec, ctx)
    yr = (_gy + rec['years']) if _gm >= 7 else (_gy + rec['years'] - 1)   # ugovor do 31.8.: ljeti +godine, zimi jedna manje
    afee = int(rec.get('agent_fee') or 0)
    rel = max(fee, negotiate.rnd100(ctx['f']['mv'] * 0.95, 100))
    if rec.get('clause'):
        # pc235 (izvjestaj testera 03): slobodni igrac zadrzava tocno dogovorenu klauzulu (prije se rezala na 95 % vrijednosti)
        rel = rec['clause'] if rec.get('free') else min(rel, rec['clause'])
    old = rec['old']

    def fn(s):
        if afee and not rec.get('free'):
            s.adjust_budget(-afee)   # naknada agentu (iz transfer budzeta)
        if rec.get('free'):
            # pc235: prvo upis i provjera dogovora, tek onda agentova naknada (inace 60 MB provjera odbije upis)
            s.sign_outside_x(pid, 0, sal, yr, pos=POS, free=True, release=rel)
            if afee:
                s.adjust_budget(-afee)
            return '%s (free agent): wage %d EUR/yr, contract until 31/8/%d.' % (NAMES.get(pid, pid), sal, yr)
        if s.ext and getattr(s, 'game27', False):
            # pc273: FL27 kupnja = dogovor kao u igri (novac odmah, igrac dolazi nakon ~3 dana simulacije); provjereno u igri (Kluivert)
            if rec.get('free') or old != 0:
                raise ValueError('On Football Life 2027 saves the app can so far only buy a player outright (no swaps, no free agents yet). The save was not touched.')
            s.add_deal(pid, fee, sal, release=rel, end=(31 << 24) | (8 << 16) | yr, level=2)
            return '%s: fee %d EUR, wage %d EUR/yr, contract until 31/8/%d. In the game, advance about 3 days and he arrives.' % (NAMES.get(pid, pid), fee, sal, yr)
        if old == 0:
            s.direct_sign(pid, fee, sal, (31 << 24) | (8 << 16) | yr, pos=POS)
        elif old in {x['pid'] for x in s.list_deals()}:
            s.swap_deal(old, pid, fee, sal, rel, yr)
        else:
            s.squad_swap(old, pid, fee, sal, yr)
        return '%s: fee %d EUR, wage %d EUR/yr, contract until 31/8/%d.' % (NAMES.get(pid, pid), fee, sal, yr)
    r = _write_slot(slot, 'neg', fn, pid=pid)
    if rec.get('free'):
        FA_CACHE.clear()
        PCACHE.clear()
    _mark_moved(slot, ctx['save'], pid)
    try:
        if rec.get('role') in ('key', 'starter') or ctx.get('crowd'):
            promise_add(slot, ctx['save'], pid, rec.get('role'))
    except Exception:
        pass
    try:
        addon_add(slot, ctx['save'], pid, rec.get('app_bonus', 0), rec.get('sellon', 0), ctx.get('club'), pbonus=rec.get('pbonus'), release=rec.get('clause'))
    except Exception:
        pass
    try:
        _ev_add(slot, 'signed', pid, frm=ctx.get('club') or '', fee=fee, wage=sal, years=rec['years'], until=yr, bonus=rec.get('app_bonus', 0), sellon=rec.get('sellon', 0))
    except Exception:
        pass
    rec['stage'] = 'done'
    st.put(slot, pid, rec)
    return r



# ---------------------------------------------------------------- slobodni igraci (free agents)
FA_CACHE = {}
FA_NEG = {}   # (slot, pid) -> dict(rounds, mood, ask, agreed)
_FA_SKIP_TEAMS = ('The Old Boys', 'World Selection')


def _national_teams(data):
    """pc260: [(indeks, ime)] reprezentacija. Klasicni/45 MB: od 'Albania' (580) do 693. 60 MB: na 580-692 su KLUBOVI
    (skauti su nudili 'Celtic FC' kao reprezentaciju), a reprezentacije su skup iz club_layout."""
    lim, natset = mlsave.club_layout(data)
    if natset:
        ks = sorted(natset)
        names = mlsave.team_names(data, ks[-1] + 1)
    else:
        names = mlsave.team_names(data)
        ks = range(mlsave.FIRST_NATIONAL, len(names))
    return [(k, names[k]) for k in ks if k < len(names) and names[k]]


def _fa_pool(slot):
    """Svi slobodni igraci u saveu: zapis bez kluba (+140 = ffffffff) i nisu ni u jednom klupskom sastavu.
    Drzava = reprezentacija u cijem su sastavu (ako jesu). Kes po saveu."""
    d = slot_folder(slot)
    key = (d, os.path.getmtime(os.path.join(d, 'data.dat')))
    if FA_CACHE.get('k') == key:
        return FA_CACHE['v']
    s = mlwrite.Save(d)
    data = bytes(s.d)
    clubs = mlsave.all_players(data)
    nat, skip = {}, set()
    for k, nk in _national_teams(data):
        o = mlsave.REC0 + k * mlsave.STRIDE + mlsave.SQUAD_OFF
        for i in range(mlsave.SQUAD_SLOTS):
            pid, _t = struct.unpack_from('<II', data, o + i * 8)
            if 0 < pid < 400000:
                if nk in _FA_SKIP_TEAMS:
                    skip.add(pid)
                else:
                    nat.setdefault(pid, nk)
    # omladina tvog kluba (tablica registracija 368 B) takodjer nema klub u zapisu: to nisu slobodni igraci
    reg = set()
    try:
        sq = list(s.my_squad_tags())
        o = data.find(struct.pack('<I', sq[0]))
        while o != -1:
            if all(1000 <= struct.unpack_from('<I', data, o + 368 * j)[0] < 400000 for j in (1, 2, 3)):
                break
            o = data.find(struct.pack('<I', sq[0]), o + 1)
        if o != -1:
            st = o
            while st - 368 > 0 and 1000 <= struct.unpack_from('<I', data, st - 368)[0] < 400000:
                st -= 368
            while 1000 <= struct.unpack_from('<I', data, st)[0] < 400000:
                reg.add(struct.unpack_from('<I', data, st)[0])
                st += 368
    except Exception:
        pass
    out = []
    for pid, end in s.free_agents().items():
        if (pid in clubs and not s.fmt60) or pid in skip or pid in reg or pid not in NAMES:   # pc235: 60 MB popis vec iskljucuje sastave po punom kljucu
            continue
        o, a = rat(pid)
        if not o or not a or a > 38 or a < 18:
            continue
        out.append(dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=o, age=a, nat=nat.get(pid, '')))
    out.sort(key=lambda r: (-r['ovr'], r['age']))
    FA_CACHE.update(k=key, v=(out, s))
    return out, s


def _fa_my_ovrs(s):
    return [rat(p)[0] for p in s.my_squad_tags() if rat(p)[0]]


def _fa_terms(slot, s, r, gd, my_ovrs):
    f = negotiate.facts(r['ovr'], r['age'], 0, 0, None, False)
    y, m, _ = _date_tuple(gd)
    mood = negotiate.player_mood(slot, r['id'], '%d-%d' % (y, m))
    role = negotiate.role_demand(my_ovrs, f)
    # slobodan igrac nema klub: trazi nesto manje od igraca pod ugovorom, ali dobiva i bonus za potpis (ne placa se iz appa)
    return f, mood, role, _fa_ask(f, mood, my_ovrs, role, 2)


def _fa_ask(f, mood, my_ovrs, role, years):
    import math
    return int(math.ceil(negotiate.wage_ask(f, mood, my_ovrs, role, years) / 100.0) * 100)


def freeagents_view(slot, q='', pos='', mn=0, maxage=0, nat='', lim=120):
    pool, s = _fa_pool(slot)
    gd = s.game_date_code()
    my_ovrs = _fa_my_ovrs(s)
    q = (q or '').strip().lower()
    rows = []
    for r in pool:
        if mn and r['ovr'] < mn:
            continue
        if maxage and r['age'] > maxage:
            continue
        if pos != '' and pos is not None and str(r['pos']) not in str(pos).split(','):
            continue
        if nat and r['nat'] != nat:
            continue
        if q and q not in r['name'].lower():
            continue
        rows.append(r)
        if len(rows) >= lim:
            break
    out = []
    for r in rows:
        f, mood, role, ask = _fa_terms(slot, s, r, gd, my_ovrs)
        n = FA_NEG.get((slot, r['id'])) or {}
        out.append(dict(r, ask=ask, role=role, mv_e=f['mv'], agreed=n.get('agreed'), locked=n.get('locked', False)))
    nats = sorted({r['nat'] for r in pool if r['nat']})
    return dict(items=out, total=len(pool), nations=nats, squad=len(s.my_squad_tags()), date=_fmt_date(gd), sign_ok=True, sign_msg=None)


FA_CLASSIC_MSG = 'Signing free agents from the app does not work on the classic (19.9 MB) save yet. Sign him in the game (Transfers > Free Agents); everything else in the app works.'


def _fa_sign_ok(slot):
    """pc201: potpis slobodnog igraca radi na svim formatima (klasicni 19,9 MB preko classic_join, izmjereno na pravom potpisu u igri)."""
    return True


def freeagent_offer(body):
    """Ponuda slobodnom igracu (placa, godine, uloga). Do 3 runde; nakon dogovora potpis ide kroz freeagent_sign."""
    slot, pid = body['slot'], int(body['pid'])
    if not _fa_sign_ok(slot):
        raise ValueError(FA_CLASSIC_MSG)
    reg_check(slot, mlwrite.Save(slot_folder(slot), ro=True), pid, src_idx=-1)
    wage, years = int(body['wage']), max(1, min(5, int(body.get('years', 2))))
    pool, s = _fa_pool(slot)
    r = next((x for x in pool if x['id'] == pid), None)
    if not r:
        raise ValueError('player is not a free agent')
    gd = s.game_date_code()
    my_ovrs = _fa_my_ovrs(s)
    f, mood, dem, ask0 = _fa_terms(slot, s, r, gd, my_ovrs)
    role = body.get('role') or dem
    if role not in negotiate.ROLES:
        role = dem
    n = FA_NEG.setdefault((slot, pid), dict(rounds=0))
    if n.get('locked'):
        return dict(decision='walk', msg='Igrac vise ne zeli razgovarati.')
    n['rounds'] += 1
    ask = _fa_ask(f, mood, my_ovrs, role, years)
    ratio = wage / float(ask) if ask else 9
    rep = {}
    if wage >= ask:
        dec = 'accept'
    elif ratio >= 0.9:
        dec, rep['counter'] = 'counter', min(ask, negotiate.rnd100((wage + ask) / 2.0, 100))
    elif n['rounds'] >= 3 or ratio < 0.6:
        dec = 'walk'
    else:
        dec = 'reject'
    if dec == 'accept':
        n['agreed'] = dict(wage=wage, years=years, role=role)
    elif dec in ('walk', 'refuse', 'withdraw'):
        n['locked'] = True
    out = dict(decision=dec, round=n['rounds'], agreed=n.get('agreed'))
    if rep.get('counter'):
        out['counter'] = rep['counter']
    return out


def freeagent_sign(body):
    slot, pid = body['slot'], int(body['pid'])
    n = FA_NEG.get((slot, pid)) or {}
    a = n.get('agreed')
    if not a:
        raise ValueError('no agreement with the player')
    s0 = mlwrite.Save(slot_folder(slot))
    reg_check(slot, s0, pid, src_idx=-1)
    if len(s0.my_squad_tags()) >= 40:
        raise ValueError('squad is full (40)')
    y, m, _ = _date_tuple(s0.game_date_code())
    yr = y + a['years'] if m >= 7 else y + a['years'] - 1

    def fn(s):
        return s.sign_outside_x(pid, 0, a['wage'], yr, pos=POS, free=True)
    r = _write_slot(slot, 'fa', fn, pid=pid)
    FA_CACHE.clear()
    PCACHE.clear()
    try:
        _ev_add(slot, 'signed', pid, frm='', fee=0, wage=a['wage'], years=a['years'], until=yr, bonus=0, sellon=0)
    except Exception:
        pass
    FA_NEG.pop((slot, pid), None)
    return r


# ---------------------------------------------------------------- skautska mreza (deep scouting)
SC_FILE = os.path.join(HERE, 'data', 'scouting.json')
SC_TIERS = {   # godisnja placa (iz transfer budzeta), trajanje misije (dana), broj igraca u izvjescu, tocnost OVR (+-), tocnost potencijala (+-)
    'local': dict(fee=120000, days=21, n=5, acc=4, pacc=6),
    'regional': dict(fee=350000, days=14, n=8, acc=2, pacc=4),
    'elite': dict(fee=900000, days=10, n=12, acc=1, pacc=2),
}
SC_MAX = 3
SC_POOL = {   # drzava: (imena, prezimena) - nasumicni skauti na trzistu
    'Spain': (('Javier', 'Pablo', 'Álvaro', 'Sergio', 'Iñaki', 'Rubén', 'Óscar'), ('Herrera', 'Navarro', 'Ortega', 'Salinas', 'Etxeberria', 'Calvo', 'Prieto')),
    'Italy': (('Luca', 'Marco', 'Giovanni', 'Davide', 'Stefano', 'Matteo'), ('Bianchi', 'Ferretti', 'Galli', 'Moretti', 'Lombardi', 'Rinaldi')),
    'France': (('Julien', 'Antoine', 'Pierre', 'Mathieu', 'Olivier', 'Bastien'), ('Lefèvre', 'Garnier', 'Moreau', 'Dubois', 'Roussel', 'Chevalier')),
    'Germany': (('Lukas', 'Jonas', 'Felix', 'Tobias', 'Matthias', 'Florian'), ('Brandt', 'Hoffmann', 'Krüger', 'Lehmann', 'Vogel', 'Schäfer')),
    'England': (('James', 'Oliver', 'Harry', 'Daniel', 'Tom', 'Ben'), ('Whitaker', 'Hughes', 'Fletcher', 'Turner', 'Barker', 'Collins')),
    'Netherlands': (('Ruud', 'Arjen', 'Sander', 'Jesper', 'Bram', 'Niels'), ('de Vries', 'Bakker', 'Visser', 'van Dijk', 'Smit', 'Mulder')),
    'Portugal': (('João', 'Tiago', 'Rui', 'Nuno', 'Pedro', 'Hugo'), ('Ferreira', 'Carvalho', 'Pinto', 'Mendes', 'Almeida', 'Teixeira')),
    'Brazil': (('Rafael', 'Bruno', 'Gustavo', 'Felipe', 'Thiago', 'Caio'), ('Oliveira', 'Santos', 'Ribeiro', 'Barbosa', 'Moura', 'Lacerda')),
    'Argentina': (('Mateo', 'Santiago', 'Joaquín', 'Matías', 'Facundo', 'Nicolás'), ('Gómez', 'Fernández', 'Acosta', 'Sosa', 'Benítez', 'Medina')),
    'Denmark': (('Søren', 'Mads', 'Kasper', 'Rasmus', 'Anders', 'Jonas'), ('Nielsen', 'Jensen', 'Kjær', 'Lund', 'Madsen', 'Holm')),
    'Sweden': (('Erik', 'Lars', 'Nils', 'Oskar', 'Henrik', 'Viktor'), ('Lindqvist', 'Berg', 'Forsberg', 'Holmberg', 'Nyström', 'Sjöberg')),
    'Poland': (('Tomasz', 'Kacper', 'Bartosz', 'Paweł', 'Michał', 'Jakub'), ('Kowalski', 'Nowak', 'Wiśniewski', 'Zieliński', 'Mazur', 'Krawczyk')),
    'Turkey': (('Mehmet', 'Emre', 'Burak', 'Can', 'Kerem', 'Arda'), ('Yılmaz', 'Demir', 'Kaya', 'Aydın', 'Öztürk', 'Arslan')),
    'Morocco': (('Youssef', 'Karim', 'Hakim', 'Anas', 'Mehdi', 'Omar'), ('El Amrani', 'Benali', 'Tazi', 'Idrissi', 'Bennani', 'Alaoui')),
    'Ghana': (('Kwame', 'Kofi', 'Yaw', 'Kojo', 'Emmanuel', 'Isaac'), ('Mensah', 'Owusu', 'Boateng', 'Asante', 'Darko', 'Appiah')),
    'Japan': (('Kenji', 'Hiroshi', 'Takumi', 'Daisuke', 'Ryo', 'Yuki'), ('Tanaka', 'Suzuki', 'Watanabe', 'Kobayashi', 'Nakamura', 'Ito')),
    'USA': (('Ryan', 'Tyler', 'Jordan', 'Kyle', 'Brandon', 'Chris'), ('Mitchell', 'Carter', 'Brooks', 'Reed', 'Hayes', 'Coleman')),
    'Belgium': (('Wout', 'Pieter', 'Kevin', 'Jens', 'Thibaut', 'Dries'), ('Peeters', 'Janssens', 'Claes', 'Wouters', 'Maes', 'Goossens')),
    'Scotland': (('Callum', 'Ross', 'Fraser', 'Euan', 'Craig', 'Scott'), ('MacLeod', 'Campbell', 'Stewart', 'Murray', 'Fraser', 'Robertson')),
    'Serbia': (('Nemanja', 'Stefan', 'Miloš', 'Uroš', 'Dušan', 'Marko'), ('Jovanović', 'Petrović', 'Nikolić', 'Stanković', 'Ilić', 'Đorđević')),
}
SC_MARKET_N = 8
_SC_GRP = {'gk': (0,), 'def': (1, 2, 3), 'mid': (4, 5, 6, 7, 8), 'att': (9, 10, 11, 12)}


def _sc_all():
    try:
        return json.load(open(SC_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _sc_get(slot):
    return _sc_all().get(slot) or dict(scouts=[], reports=[], seq=0)


def _sc_put(slot, e):
    a = _sc_all()
    a[slot] = e
    os.makedirs(os.path.dirname(SC_FILE), exist_ok=True)
    tmp = SC_FILE + '.tmp'
    _jdump(a, tmp, ensure_ascii=False, indent=1)
    os.replace(tmp, SC_FILE)


def _sc_season(code):
    y, m, _ = _date_tuple(code)
    return y if m >= 7 else y - 1


def _sc_ord(code):
    import datetime
    y, m, d = _date_tuple(code)
    try:
        return datetime.date(y, m, d).toordinal()
    except Exception:
        return 0


def _sc_ord_s(o):
    import datetime
    d = datetime.date.fromordinal(o)
    return '%d/%d/%d' % (d.day, d.month, d.year)


def _sc_regions(slot):
    """Regije za skaute: lige (iz natjecanja u saveu, klubovi po ligi), reprezentacije (pozvani igraci) i slobodni igraci."""
    leagues = {}
    try:
        for c in comps_view(slot).get('comps', []):
            if c.get('kind') == 'league' and c.get('rows'):
                leagues[c['name']] = sorted({r['club'] for r in c['rows']})
    except Exception:
        pass
    d = slot_folder(slot)
    data = open(os.path.join(d, 'data.dat'), 'rb').read()
    nat = {}
    for k, nk in _national_teams(data):
        if nk in _FA_SKIP_TEAMS:
            continue
        o = mlsave.REC0 + k * mlsave.STRIDE + mlsave.SQUAD_OFF
        for i in range(mlsave.SQUAD_SLOTS):
            pid, _t = struct.unpack_from('<II', data, o + i * 8)
            if 0 < pid < 400000:
                nat.setdefault(nk, set()).add(pid)
    return leagues, nat


def _sc_pool(slot, mission, regions=None):
    """Kandidati za misiju (pravi podaci iz savea), prije skautove procjene."""
    leagues, nat = regions or _sc_regions(slot)
    pd = players_data(slot)
    rt, rg = mission.get('rt'), mission.get('region')
    if rt == 'fa':
        pool, _s = _fa_pool(slot)
        rows = [dict(r, club='', mv=0, mv_e=negotiate.estimate_value(r['ovr'], r['age']), free=True) for r in pool]
    else:
        rows = [r for r in pd['players'] if not r.get('mine')]
        if rt == 'league':
            cl = set(leagues.get(rg) or [])
            rows = [r for r in rows if r['club'] in cl]
        elif rt == 'nation':
            ids = nat.get(rg) or set()
            rows = [r for r in rows if r['id'] in ids]
            fa, _s = _fa_pool(slot)
            rows += [dict(r, club='', mv=0, mv_e=negotiate.estimate_value(r['ovr'], r['age']), free=True) for r in fa if r['id'] in ids]
    g = _SC_GRP.get(mission.get('grp') or '')
    out = []
    for r in rows:
        if not r.get('ovr') or not r.get('age'):
            continue
        if g and r['pos'] not in g:
            continue
        if mission.get('maxage') and r['age'] > int(mission['maxage']):
            continue
        if mission.get('minovr') and r['ovr'] < int(mission['minovr']):
            continue
        val = r.get('mv') or r.get('mv_e') or 0
        if mission.get('maxval') and val > int(mission['maxval']):
            continue
        pot = growth.potential(r['id'], r['age'], r['ovr'], r['pos'])
        if mission.get('talent') and not (r['age'] <= 21 and pot >= r['ovr'] + 6):
            continue
        out.append(dict(id=r['id'], name=r['name'], pos=r['pos'], ovr=r['ovr'], age=r['age'], club=r.get('club', ''), val=val, pot=pot, free=bool(r.get('free'))))
    return out


def _sc_stats(sc, mission=None):
    """Stvarne mogucnosti skauta: razina + ocjena (zvjezdice) + specijalnost (njegova liga = tocniji, vise igraca, brze)."""
    t = dict(SC_TIERS[sc['tier']])
    r = int(sc.get('rating', 3))
    if r >= 4:
        t['acc'] = max(1, t['acc'] - 1)
        t['pacc'] = max(1, t['pacc'] - 1)
    if r >= 5:
        t['n'] += 2
    if r <= 2:
        t['acc'] += 1
        t['pacc'] += 2
        t['n'] = max(3, t['n'] - 1)
    if mission and sc.get('spec') and (mission.get('region') == sc['spec'] or (sc['spec'] == 'fa' and mission.get('rt') == 'fa')):
        t['acc'] = max(1, t['acc'] - 1)
        t['pacc'] = max(1, t['pacc'] - 2)
        t['n'] += 2
        t['days'] = max(5, t['days'] - 3)
        t['spec_hit'] = True
    return t


def _sc_market(slot, gd, leagues, hired_ids):
    """Skauti dostupni za angazman: nasumicni (seed: slot + mjesec igre), mijenjaju se svaki mjesec."""
    import random
    y, m, _ = _date_tuple(gd)
    rnd = random.Random('scm|%s|%d-%d' % (slot, y, m))
    nats = sorted(SC_POOL)
    out = []
    specs = sorted(leagues) + ['fa']
    k = 0
    while len(out) < SC_MARKET_N and k < 40:
        k += 1
        nat = rnd.choice(nats)
        fn, ln = SC_POOL[nat]
        name = '%s %s' % (rnd.choice(fn), rnd.choice(ln))
        tier = rnd.choices(['local', 'regional', 'elite'], weights=[4, 4, 2])[0]
        rating = rnd.choices([2, 3, 4, 5], weights=[2, 4, 3, 1])[0]
        spec = rnd.choice(specs) if specs else ''
        sid = 'm%d%02d%d' % (y, m, k)
        if sid in hired_ids or any(o['name'] == name for o in out):
            continue
        fee = negotiate.rnd100(SC_TIERS[tier]['fee'] * (0.7 + 0.15 * rating) * rnd.uniform(0.92, 1.08), 5000)
        out.append(dict(mid=sid, name=name, nat=nat, tier=tier, rating=rating, spec=spec, fee=fee, age=rnd.randint(29, 66)))
    return out


def _sc_report(slot, sc, mission, gd):
    import random
    t = _sc_stats(sc, mission)
    pool = _sc_pool(slot, mission)
    rnd = random.Random('%s|%s|%s' % (slot, sc['id'], mission.get('start')))
    # skaut ne nadje uvijek najbolje: tezina po kvaliteti + vrijednosti za novac (+ talent), uzorak iz sireg kruga
    def score(r):
        v = r['ovr'] + (r['pot'] - r['ovr']) * (0.6 if mission.get('talent') else 0.25)
        if r['val']:
            v += max(-4, min(4, 2 - (r['val'] / 5e6)))
        return v + rnd.uniform(-t['acc'] * 1.5, t['acc'] * 1.5)
    pool.sort(key=score, reverse=True)
    wide = pool[:t['n'] * 3]
    rnd.shuffle(wide)
    picks = sorted(wide[:t['n']], key=lambda r: -r['ovr'])
    out = []
    for r in picks:
        a, pa = t['acc'], t['pacc']
        c = r['ovr'] + rnd.randint(-a // 2, a // 2) if a > 1 else r['ovr']
        lo, hi = c - a, c + a
        lo, hi = min(lo, r['ovr']), max(hi, r['ovr'])
        pc = r['pot'] + rnd.randint(-pa // 2, pa // 2)
        plo, phi = min(pc - pa, r['pot']), max(pc + pa, r['pot'])
        out.append(dict(pid=r['id'], name=r['name'], pos=r['pos'], age=r['age'], club=r['club'], free=r['free'], val=r['val'],
                        ovr=[lo, hi], pot=[max(lo, plo), min(99, phi)]))
    return dict(found=len(pool), players=out)


def _sc_tick(slot, e, gd):
    """Zavrsene misije -> izvjesca. Vraca True ako se nesto promijenilo."""
    now = _sc_ord(gd)
    ch = False
    season = _sc_season(gd)
    for sc in e['scouts']:
        m = sc.get('mission')
        if not m or now < m['end']:
            continue
        rep = _sc_report(slot, sc, m, gd)
        e['seq'] = e.get('seq', 0) + 1
        e['reports'].insert(0, dict(id=e['seq'], scout=sc['id'], scout_name=sc['name'], tier=sc['tier'], date=_sc_ord_s(m['end']), mission=m, **rep))
        e['reports'] = e['reports'][:30]
        sc['mission'] = None
        sc['done'] = sc.get('done', 0) + 1
        ch = True
    return ch


def _sc_advice(slot, s, regions, budget):
    """Asistent: sto skautirati (dubina po linijama, slabe linije u odnosu na momcad, mladi, budzet). Samo prijedlog misije."""
    leagues, nat = regions
    sq = [(p, rat(p)[0], rat(p)[1], POS.get(p, 5)) for p in s.my_squad_tags()]
    sq = [x for x in sq if x[1]]
    if not sq:
        return []
    team = sorted((x[1] for x in sq), reverse=True)[:11]
    tavg = sum(team) / len(team)
    need = dict(gk=2, df=7, mf=7, at=4)
    gmap = dict(gk='gk', df='def', mf='mid', at='att')
    lines = {k: [x for x in sq if x[3] in _SC_GRP[gmap[k]]] for k in need}
    tops = {'gk': 1, 'df': 4, 'mf': 3, 'at': 2}
    out = []
    lname = dict(gk=('golman', 'goalkeeper'), df=('obrana', 'defence'), mf=('vezni red', 'midfield'), at=('napad', 'attack'))
    cap = int(budget * 0.6 / 100000) * 100000 if budget else 0
    for k, n in need.items():
        L = sorted(lines[k], key=lambda x: -x[1])
        best = L[:tops[k]]
        bavg = sum(x[1] for x in best) / len(best) if best else 0
        short = len(L) < n
        weak = best and bavg < tavg - 2
        if short or weak:
            out.append(dict(kind='depth' if short else 'quality', line=k, grp=gmap[k], have=len(L), want=n, avg=round(bavg, 1), team=round(tavg, 1),
                            minovr=int(max(55, round(bavg if weak else bavg - 4))), maxage=0, talent=False,
                            maxval=cap if cap >= 500000 else 0, name=lname[k]))
    if len(out) < 2:
        # nema rupa: najslabija linija u odnosu na prvih 11 -> trazi igraca boljeg od trenutnog najboljeg prosjeka te linije
        cand = []
        for k in need:
            L = sorted(lines[k], key=lambda x: -x[1])[:tops[k]]
            if L and not any(o['line'] == k for o in out):
                cand.append((sum(x[1] for x in L) / len(L), k))
        if cand:
            bavg, k = min(cand)
            out.append(dict(kind='upgrade', line=k, grp=gmap[k], have=len(lines[k]), want=need[k], avg=round(bavg, 1), team=round(tavg, 1),
                            minovr=int(round(bavg)) + 1, maxage=29, talent=False, maxval=cap if cap >= 500000 else 0, name=lname[k]))
    young = [x for x in sq if x[2] <= 21]
    if len(young) < 5:
        out.append(dict(kind='youth', line='', grp='', have=len(young), want=3, minovr=60, maxage=21, talent=True, maxval=min(cap, 8000000) if cap else 0, name=('mladi', 'youth')))
    if budget < 1500000:
        for o in out:
            o['rt'], o['region'] = 'fa', ''
            o['maxval'] = 0
    # regija s najvise odgovarajucih kandidata (stvarni broj iz savea)
    for o in out:
        if o.get('rt') == 'fa':
            o['count'] = len(_sc_pool(slot, dict(rt='fa', grp=o['grp'], minovr=o['minovr'], maxage=o['maxage'], talent=o['talent']), regions))
            continue
        best = None
        for lg in leagues:
            c = len(_sc_pool(slot, dict(rt='league', region=lg, grp=o['grp'], minovr=o['minovr'], maxage=o['maxage'], maxval=o['maxval'], talent=o['talent']), regions))
            if c and (best is None or c > best[1]):
                best = (lg, c)
        if best:
            o['rt'], o['region'], o['count'] = 'league', best[0], best[1]
        else:
            o['rt'], o['region'], o['maxval'] = 'fa', '', 0
            o['count'] = len(_sc_pool(slot, dict(rt='fa', grp=o['grp'], minovr=o['minovr'], maxage=o['maxage'], talent=o['talent']), regions))
            o['nobudget'] = True
    pr = {'depth': 0, 'quality': 1, 'upgrade': 2, 'youth': 3}
    out.sort(key=lambda o: pr[o['kind']])
    return out[:3]


def _sc_severance(sc, season):
    """Odsteta pri otkazu: pola godisnje place za svaku punu sezonu ugovora iza tekuce (tekuca je vec placena i ne vraca se)."""
    left = max(0, sc.get('until', sc.get('paid', season)) - season)
    fee = sc.get('fee') or SC_TIERS[sc['tier']]['fee']
    return negotiate.rnd100(fee * 0.5 * left, 1000) if left else 0


def scouting_reports(slot):
    """Lagano: samo izvjesca (za inbox/obavijesti), uz obradu zavrsenih misija."""
    e = _sc_get(slot)
    if not e.get('scouts') and not e.get('reports'):
        return dict(items=[])
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if _sc_tick(slot, e, s.game_date_code()):
        _sc_put(slot, e)
    return dict(items=e.get('reports', [])[:12])


def scouting_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    e = _sc_get(slot)
    if _sc_tick(slot, e, gd):
        _sc_put(slot, e)
    season = _sc_season(gd)
    now = _sc_ord(gd)
    regions = _sc_regions(slot)
    budget = s.budget()
    sc = []
    for x in e['scouts']:
        m = x.get('mission')
        sc.append(dict(x, active=x.get('paid', 0) >= season, mission=dict(m, end_s=_sc_ord_s(m['end']), left=max(0, m['end'] - now)) if m else None))
    for x in sc:
        x['fee'] = x.get('fee') or SC_TIERS[x['tier']]['fee']
        x['until'] = x.get('until', x.get('paid', season))
        x['expired'] = x['until'] < season
        x['stats'] = _sc_stats(x)
        x['sev'] = _sc_severance(x, season)
        x['until_s'] = '30.6.%d' % (x['until'] + 1)
    due = sum(x['fee'] for x in sc if x.get('paid', 0) < season and not x['expired'])
    hired = {x.get('mid') for x in e['scouts']}
    market = _sc_market(slot, gd, regions[0], hired)
    try:
        adv = _sc_advice(slot, s, regions, budget)
    except Exception as ex:
        adv = []
    return dict(scouts=sc, market=market, reports=e['reports'], tiers=SC_TIERS, max=SC_MAX, season='%d/%02d' % (season, (season + 1) % 100), due=due,
                budget=budget, date=_fmt_date(gd), leagues=sorted(regions[0]), nations=sorted(regions[1]), advice=adv, game_blocks=game_blocks())


def scouting_act(body):
    slot, act = body['slot'], body['act']
    s = mlwrite.Save(slot_folder(slot))
    gd = s.game_date_code()
    season = _sc_season(gd)
    e = _sc_get(slot)
    if act == 'hire':
        if len(e['scouts']) >= SC_MAX:
            raise ValueError('imas najvise %d skauta' % SC_MAX)
        leagues = _sc_regions(slot)[0]
        mk = next((x for x in _sc_market(slot, gd, leagues, {x.get('mid') for x in e['scouts']}) if x['mid'] == body.get('mid')), None)
        if not mk:
            raise ValueError('scout is no longer on the market')
        years = max(1, min(3, int(body.get('years', 1))))
        yfee = negotiate.rnd100(mk['fee'] * (1.0, 0.95, 0.9)[years - 1], 1000)    # duzi ugovor = nize godisnje
        y, m, _ = _date_tuple(gd)
        months_left = (6 - m) % 12 + 1          # do 30.6. (ukljucivo tekuci mjesec)
        now = negotiate.rnd100(yfee * max(0.25, months_left / 12.0), 1000)
        if now > s.budget():
            raise ValueError('not enough money in the transfer budget')
        e['seq'] = e.get('seq', 0) + 1

        def fn(sv):
            sv.adjust_budget(-now)
            return 'Scout %s hired (%d-year contract). Wage until the end of the season (%d EUR) paid from the transfer budget.' % (mk['name'], years, now)
        r = _write_slot(slot, 'scout', fn)
        e['scouts'].append(dict(id=e['seq'], mid=mk['mid'], name=mk['name'], nat=mk['nat'], age=mk['age'], tier=mk['tier'], rating=mk['rating'], spec=mk['spec'],
                                fee=yfee, years=years, until=season + years - 1, hired=_fmt_date(gd), paid=season, done=0, mission=None))
        _sc_put(slot, e)
        return r
    if act == 'pay':
        unpaid = [x for x in e['scouts'] if x.get('paid', 0) < season and x.get('until', x.get('paid', season)) >= season]
        tot = sum(x.get('fee') or SC_TIERS[x['tier']]['fee'] for x in unpaid)
        if not tot:
            return dict(ok=True, message='All scouts are paid for this season.')
        if tot > s.budget():
            raise ValueError('not enough money in the transfer budget')

        def fn(sv):
            sv.adjust_budget(-tot)
            return 'Godisnja placa skauta (%d EUR) placena iz transfer budzeta.' % tot
        r = _write_slot(slot, 'scout', fn)
        for x in unpaid:
            x['paid'] = season
        _sc_put(slot, e)
        return r
    sid = int(body.get('id', 0))
    sc = next((x for x in e['scouts'] if x['id'] == sid), None)
    if act == 'dismiss_report':
        e['reports'] = [r for r in e['reports'] if r['id'] != int(body.get('rid', 0))]
        _sc_put(slot, e)
        return dict(ok=True)
    if not sc:
        raise ValueError('skaut ne postoji')
    if act == 'fire':
        sev = _sc_severance(sc, season)
        if sev:
            if sev > s.budget():
                raise ValueError('dismissal needs %d EUR compensation, and the transfer budget is not enough' % sev)

            def fn(sv):
                sv.adjust_budget(-sev)
                return 'Scout %s dismissed. Compensation for the rest of the contract: %d EUR from the transfer budget.' % (sc['name'], sev)
            r = _write_slot(slot, 'scout', fn)
        else:
            r = dict(ok=True, message='Scout %s dismissed. The contract ends this season, so no compensation (this season wage is not refunded).' % sc['name'])
        e['scouts'] = [x for x in e['scouts'] if x['id'] != sid]
        _sc_put(slot, e)
        return r
    if act == 'renew':
        fee = sc.get('fee') or SC_TIERS[sc['tier']]['fee']
        if fee > s.budget():
            raise ValueError('not enough money in the transfer budget')

        def fn(sv):
            sv.adjust_budget(-fee)
            return 'Scout %s contract extended for the season (%d EUR from the transfer budget).' % (sc['name'], fee)
        r = _write_slot(slot, 'scout', fn)
        sc['until'] = season
        sc['paid'] = season
        _sc_put(slot, e)
        return r
    if act == 'send':
        if sc.get('until', sc.get('paid', season)) < season:
            raise ValueError('scout contract has expired')
        if sc.get('paid', 0) < season:
            raise ValueError('scout is not paid for this season')
        if sc.get('mission'):
            raise ValueError('scout is already on a mission')
        rt = body.get('rt')
        if rt not in ('league', 'nation', 'fa'):
            raise ValueError('odaberi regiju')
        start = _sc_ord(gd)
        m = dict(rt=rt, region=body.get('region') or '', grp=body.get('grp') or '', maxage=int(body.get('maxage') or 0), minovr=int(body.get('minovr') or 0),
                 maxval=int(body.get('maxval') or 0), talent=bool(body.get('talent')), start=start)
        m['end'] = start + _sc_stats(sc, m)['days']
        if rt != 'fa' and not m['region']:
            raise ValueError('choose a league or a country')
        sc['mission'] = m
        _sc_put(slot, e)
        return dict(ok=True, message='%s leaves on a mission. Report arrives %s (in-game date).' % (sc['name'], _sc_ord_s(m['end'])))
    if act == 'recall':
        sc['mission'] = None
        _sc_put(slot, e)
        return dict(ok=True)
    raise ValueError('nepoznata akcija')


# ---------------------------------------------------------------- loga natjecanja i slike trenera iz igre (Sider livecpk)
def _cpk_find(rel):
    """Prva datoteka rel (npr. common/etc/pesdb/Competition.bin) u livecpk mapama redom kako ih Sider ucitava."""
    for rt in _cpk_roots():
        p = os.path.join(rt, *rel.split('/'))
        if os.path.isfile(p):
            return p
    return None


def _game_db_file(rel):
    """pc277: datoteka baze igre iz livecpk mapa ili iz cpk arhive igre (vidi _cpk_roots / _gamedb_root). None ako je nema."""
    return _cpk_find(rel)


def _wesys(path):
    import zlib
    raw = open(path, 'rb').read()
    if raw[3:8] == b'WESYS':
        return zlib.decompress(raw[16:])
    return raw


def _comp_db():
    """{comp_id: KEY} iz Competition.bin (36 B zapisi, id = u16 BE na +4) i {team_id: set(comp_id)} iz CompetitionEntry.bin (12 B: team, ?, comp u nizem bajtu)."""
    if 'compdb' in _GL:
        return _GL['compdb']
    comps, entry = {}, {}
    try:
        d = _wesys(_game_db_file('common/etc/pesdb/Competition.bin'))
        for k in range(len(d) // 36):
            r = d[k * 36:k * 36 + 36]
            comps[struct.unpack_from('>H', r, 4)[0]] = r[8:].split(b'\0')[0].decode('utf-8', 'replace')
        e = _wesys(_game_db_file('common/etc/pesdb/CompetitionEntry.bin'))
        recs = [struct.unpack_from('<III', e, k * 12) for k in range(len(e) // 12)]
        # pc413: standardna baza: nizi bajt = natjecanje, drugi bajt = redni broj kluba. Prosirene baze (60 MB) imaju natjecanja
        # iznad 255 i nizi bajt ih je pretvarao u drugu ligu (Bundesliga s logom Ligue 1, korisnik s Reddita). Za cijelu datoteku
        # se bira tumacenje koje vise zapisa pogodi u Competition.bin (16-bitno samo ako je jasno bolje).
        hit8 = sum(1 for r_ in recs if (r_[2] & 0xff) in comps)
        hit16 = sum(1 for r_ in recs if (r_[2] & 0xffff) in comps)
        wide = hit16 > hit8 * 1.2 and hit16 >= 0.8 * len(recs)
        for tid, _x, c in recs:
            entry.setdefault(tid, set()).add(c & (0xffff if wide else 0xff))
    except Exception:
        pass
    _GL['compdb'] = (comps, entry)
    return _GL['compdb']



def _career_catalog(s):
    from fl26_career_catalog import catalog
    return catalog(s.d, _cpk_roots())


def _catalog_comps(slot, result):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    cat = _career_catalog(s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    occupied = {r['ref']: r for r in cat['identity']['rows']}
    existing = [set(r['idx'] for r in c.get('rows', []) if 'idx' in r)
                for c in result.get('comps', []) if c.get('kind') == 'league']
    for league in cat['leagues']:
        members = league['members']
        if any(len(members & e) >= .8 * max(len(members), len(e)) for e in existing):
            continue
        rows = []
        for ref in sorted(members):
            o = 84 + ref * 1680
            v = {k: s.d[o+offset] for k, offset in mlsave.OFF.items()}
            # Never invent a played match or result for a missing history row.
            if v['pl'] != v['w'] + v['d'] + v['l']:
                rows = []; break
            rows.append(dict(idx=ref, name=occupied[ref]['name'], **v))
        if not rows:
            continue
        rows = [dict(club=t['name'], **{k:t[k] for k in ('idx','pl','w','d','l','gf','ga','pts','gd','pos')})
                for t in mlsave.table(rows)]
        result['comps'].append(dict(tid='db:'+str(league['cid']), kind='league',
            name=league['name'], mine=my in members, rows=rows, membership_source='active-database', emb=league['cid']))
    import fl26_competition_view
    result = fl26_competition_view.reconcile(result, cat, s.d, _season(slot, s)['matches'],
                                            _cpk_roots(), seasonstats, mlwrite.SH2, mlsave, my)
    return result


def league_places_view(slot):
    # Read-only local standings presentation; publisher cache/readers/writers stay unchanged.
    # pc316: preuzeto iz izvjestaja testera 09 (pc305 zakrpa); bez Sider svijeta / modula vraca obicni comps_view
    res = comps_view(slot)
    try:
        from pathlib import Path
        from fl26_league_places import enrich
        sider = _sider_root()
        pn = re.sub(r'\.exe$', '', str(CFG.get('pes_process', 'FL_2026')), flags=re.I)
        return enrich(res, _cpk_roots(), sider, Path(HERE) / 'data/fl26_installed_league_counts.json', Path(sider).parent / (pn + '.exe'))
    except Exception as ex:
        res['league_places_status'] = {'available': False, 'reason': str(ex)[:200]}
        return res


def comps_view(slot):
    # pc257: cijeli rezultat (s europskim fazama i katalogom liga) se cuva dok se save ne promijeni; vraca se kopija
    import copy as _copy
    try:
        _p = os.path.join(slot_folder(slot), 'data.dat')
        _st = os.stat(_p)
        _ck = (slot, _st.st_mtime, _st.st_size)
    except Exception:
        _ck = None
    _c = _GL.get('compsv')
    if _ck and _c and _c[0] == _ck:
        return _copy.deepcopy(_c[1])
    r = _comps_view1(slot)
    if _ck:
        _GL['compsv'] = (_ck, _copy.deepcopy(r))
    return r


def _comps_view1(slot):
    r = _comps_view0(slot)
    try:
        r = _catalog_comps(slot, r)
    except Exception as ex:   # pc257: bilo koja greska (drugi format/baza) -> stari prikaz, nikad pad stranice
        print('[competition catalog] read-only fallback:', ex)
    # pc259: lige iznad 255 bez imena ('Competition N') preuzmu ime lige iz baze igre s najvise istih klubova (>= 60 %)
    try:
        unnamed = [c for c in r.get('comps', []) if c.get('kind') == 'league' and str(c.get('name', '')).startswith(('Competition ', 'Ostale europske', 'Other European'))]   # pc260: i skupni naziv (rulebook 50 = Poljska u FL26)
        if unnamed:
            cat = _career_catalog(mlwrite.Save(slot_folder(slot), ro=True))
            for c in unnamed:
                mem = {x['idx'] for x in c.get('rows', []) if 'idx' in x}
                best = max(cat['leagues'], key=lambda L: len(mem & L['members']), default=None)
                if best and mem and len(mem & best['members']) >= 0.6 * len(mem):
                    c['name'] = best['name']
    except Exception as ex:
        print('[competitions] league names from database:', ex)
    # Read-only European stage projection; publisher writers/seasonstats unchanged.
    try:
        import fl26_europe_view
        es = mlwrite.Save(slot_folder(slot), ro=True)
        ev = fl26_europe_view.build(es.d, _season(slot, es)['matches'], r.get('season'),
                                   _cpk_roots(), seasonstats, mlwrite.SH2,
                                   (es.club_offset()-mlwrite.REC0)//mlwrite.STRIDE, NAMES)
        remove = set(ev['legacy_tids']) | {3, 5, 186}
        # pc257: europsko natjecanje samo ako u spremljenoj karijeri ima barem jednu utakmicu (pocetak sezone: jos nema rasporeda)
        def _eu_has(c):
            return bool(c.get('groups')) or any(p.get('fixtures') for p in (c.get('europe_stages') or []))
        evc = [c for c in ev['comps'] if _eu_has(c)]
        if evc:
            r['comps'] = [c for c in r.get('comps', []) if not (c.get('kind') == 'groups' and
                (c.get('tid') in remove or (c.get('name') == 'UEFA qualifiers' and
                                           c.get('tid') in ev['qualifier_alias_tids'])))] + evc
    except Exception as ex:   # pc257: bilo koja greska -> stari prikaz europskih natjecanja
        r['europe_stage_error'] = str(ex)
        print('[Europe stages] read-only enrichment refused:', ex)
    try:   # pc346: predsezonski turniri (npr. International Champions Cup: 4 kluba, svatko sa svakim, srpanj/kolovoz)
        r['comps'] = (r.get('comps') or []) + _preseason_comps(slot, r)
    except Exception as ex:
        print('[competitions] pre-season:', ex)
    for c in r.get('comps') or []:   # r11: logotipi natjecanja su uklonjeni
        c['emb'] = None
    return r



def _coach_names():
    """{coach_id: ime} iz dekriptirane EDIT datoteke (zapisi 88 B: u32 id, ime od +9). Kes."""
    if 'coachn' in _GL:
        return _GL['coachn']
    out = {}
    try:
        d, _src = _edit_data()
        ph = _coach_photos()
        if d and ph:
            # sidro: zapis (88 B) ciji id ima sliku (samo veliki, jedinstveni id-evi) i iza kojeg su jos 2 zapisa s id-em koji ima sliku i citljivim imenom
            def okrec(o):
                if o < 0 or o + 88 > len(d):
                    return False
                cid = struct.unpack_from('<I', d, o)[0]
                nm = d[o + 9:o + 57].split(b'\0')[0]
                return 0 < cid < (1 << 24) and len(nm) >= 3 and all(b_ >= 32 for b_ in nm)
            best = None
            for pid_ in sorted((x for x in ph if x >= 100000), reverse=True)[:300]:
                pat = struct.pack('<I', pid_)
                i = d.find(pat)
                while i >= 0:
                    if okrec(i) and okrec(i + 88) and okrec(i - 88) and (struct.unpack_from('<I', d, i + 88)[0] in ph or struct.unpack_from('<I', d, i - 88)[0] in ph):
                        best = i
                        break
                    i = d.find(pat, i + 1)
                if best is not None:
                    break
            if best is not None:
                st = best
                while okrec(st - 88):
                    st -= 88
                o = st
                while okrec(o):
                    out[struct.unpack_from('<I', d, o)[0]] = d[o + 9:o + 57].split(b'\0')[0].decode('utf-8', 'replace')
                    o += 88
    except Exception:
        out = {}
    # pc284: imena iz baze igre (Coach.bin, 100 B: u32 id, ime od +8) - FL27 drzi bazu u cpk arhivi, a EDIT datoteka
    # FL27 se ne cita, pa je trazenje menadzera po imenu bilo prazno. Baza igre ima prednost, EDIT dopunjuje.
    try:
        fp = _cpk_find('common/etc/pesdb/Coach.bin')
        if fp:
            cb = _wesys(fp)
            for o in range(0, len(cb) - 99, 100):
                cid = struct.unpack_from('<I', cb, o)[0]
                nm = cb[o + 8:o + 54].split(b'\0')[0].decode('utf-8', 'replace').strip()
                if 0 < cid < (1 << 24) and nm:
                    out[cid] = nm
    except Exception as ex:
        print('[coaches] Coach.bin:', ex)
    _GL['coachn'] = out
    return out


def _coach_photos():
    """{coach_id: putanja} iz livecpk/*/common/render/symbol/coach/coach_<id>.png."""
    if 'coachp' in _GL:
        return _GL['coachp']
    idx = {}
    for rt in _cpk_roots() + _other_cpk_roots():   # pc270: i iz Sidera drugih igara (npr. FL26 UML slike dok FL27 nema svoje)
        fd = os.path.join(rt, 'common', 'render', 'symbol', 'coach')
        if not os.path.isdir(fd):
            continue
        for f in os.listdir(fd):
            m = re.match(r'coach_(\d+)\.png$', f, re.I)
            if m and int(m.group(1)) not in idx:
                idx[int(m.group(1))] = os.path.join(fd, f)
    _GL['coachp'] = idx
    return idx


MGR_FILE = os.path.join(HERE, 'data', 'manager_photo.json')
MGR_DIR = os.path.join(HERE, 'data', 'manager_photos')


def coach_upload(body):
    """pc164: vlastita slika menadzera (JPEG/PNG kao data URL iz preglednika, vec smanjena) za ovu karijeru."""
    import base64
    slot = body['slot']
    s_ = mlwrite.Save(slot_folder(slot), ro=True)
    key = _career_id(slot, s_)
    d = str(body.get('data') or '')
    if ',' in d:
        d = d.split(',', 1)[1]
    raw = base64.b64decode(d)
    if len(raw) > 3 * 1024 * 1024 or not (raw[:3] == b'\xff\xd8\xff' or raw[:8] == b'\x89PNG\r\n\x1a\n'):
        raise ValueError('please pick a JPG or PNG image (max 3 MB)')
    os.makedirs(MGR_DIR, exist_ok=True)
    open(os.path.join(MGR_DIR, re.sub(r'[^A-Za-z0-9_.-]', '_', key) + '.jpg'), 'wb').write(raw)
    try:   # rucni odabir iz igre vise ne vrijedi
        A = json.load(open(MGR_FILE, encoding='utf-8'))
        A.pop(key, None)
        _jdump(A, MGR_FILE)
    except Exception:
        pass
    return coach_info(slot)


def coach_custom_img(key):
    fp = os.path.join(MGR_DIR, re.sub(r'[^A-Za-z0-9_.-]', '_', key or '') + '.jpg')
    return open(fp, 'rb').read() if os.path.isfile(fp) else None


def _club_coach_id(s, idx):
    v = struct.unpack_from('<I', s.d, mlwrite.REC0 + idx * mlwrite.STRIDE + 652)[0]
    return v if 0 < v < (1 << 24) else None


_GSTART = dict(t=0, v=None)


def _game_start():
    """Vrijeme pokretanja igre (epoch) ili None; kesirano 30 s (PowerShell je spor)."""
    if DEV or not game_running():
        return None
    if time.time() - _GSTART['t'] < 30:
        return _GSTART['v']
    v = None
    try:
        out = _run(['powershell', '-NoProfile', '-Command',
                              "$p=Get-Process -Name '%s' -ErrorAction SilentlyContinue | Select-Object -First 1; if($p){([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds()}" % CFG['pes_process']],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        v = int(float(out)) if out else None
    except Exception:
        v = None
    _GSTART.update(t=time.time(), v=v)
    return v


def dump_status(slot):
    """Je li igra 'povezana': postoji li F7 dump, je li iz ove karijere (vrijeme naspram save-a) i iz trenutnog pokretanja igre (treba za trening)."""
    dp = CFG.get('dump') or ''
    out = dict(exists=False, count=0, date='', career_ok=False, running=game_running(), launch_ok=False)
    if not dp or not os.path.exists(dp):
        return out
    dmt = os.path.getmtime(dp)
    out.update(exists=True, date=time.strftime('%d.%m.%Y %H:%M', time.localtime(dmt)))
    wr = dmt
    try:
        t = open(os.path.join(os.path.dirname(dp), 'players_dump.meta'), encoding='utf-8', errors='replace').read()
        m_ = re.search(r'count=(\d+)', t)
        out['count'] = int(m_.group(1)) if m_ else 0
        w_ = re.search(r'written=(\d+)', t)
        if w_:
            wr = int(w_.group(1))
    except Exception:
        pass
    ok = True
    if not DEV and slot:
        try:
            smt = os.path.getmtime(os.path.join(CFG['save_dir'], slot))
            ok = not (dmt < smt - 12 * 3600 or (dmt > smt + 3 * 3600 and not out['running']))
        except Exception:
            ok = True
    out['career_ok'] = ok
    gs = _game_start() if out['running'] else None
    out['launch_ok'] = bool(out['running'] and gs and wr >= gs - 5)
    out['game_start'] = time.strftime('%H:%M', time.localtime(gs)) if gs else ''
    return out



NEWJOB_FILE = os.path.join(HERE, 'data', 'newjob_morale.json')
NEWJOB_AFF = 92    # pc287: = 55 u igri (pocetna vrijednost) na skali appa; GrowthBridge 1.2 preracuna   # ~45 %: "zadovoljan/neutralan" (app: >=55 % sretan, 31-54 % zadovoljan)


def newjob_morale(slot, force=False):
    """pc209/pc211: novi menadzer = igraci krecu neutralno (korisnik 29.10.: igra ih na pocetku karijere drzi sve 'happy').
    Samo dok moj klub nije odigrao ligasku utakmicu (pocetak posla). Moral se postavi preko GrowthBridgea (growth.csv, 'set');
    to je upis u memoriju igre, pa vrijedi tek kad se karijera SPREMI u igri. Ako ga zivi dump kasnije ne pokaze (igra
    ponovno pokrenuta bez spremanja), naredba se posalje opet (novi tx, najvise 4 puta); 'done' tek kad dump pokaze neutralno."""
    try:
        A = json.load(open(NEWJOB_FILE, encoding='utf-8'))
    except Exception:
        A = {}
    s = mlwrite.Save(slot_folder(slot), ro=True)
    my = s.club_offset()
    club = seasonstats.club_name(s.d, (my - mlwrite.REC0) // mlwrite.STRIDE)   # pc260: team_names je do 693 (60 MB: klub iznad -> IndexError)
    key = '%s|%s' % (_career_id(slot, s), club)
    e = A.get(key)
    if not isinstance(e, dict):
        e = dict(state='done', date=e) if e and str(e).startswith('skip') else dict(state='new', tries=0)
    if e.get('state') in ('done', 'skip') and not force:
        return dict(ok=True, queued=0, state=e['state'])
    played = s.d[my + 747]
    if played and not force:
        e.update(state='skip', why='%d league games already' % played)
        A[key] = e
        _jdump(A, NEWJOB_FILE, indent=1)
        return dict(ok=True, queued=0, state='skip')
    ds = dump_status(slot)
    if not (ds.get('exists') and ds.get('career_ok')):
        return dict(ok=False, queued=0, why='nodump')
    ids = list(s.my_squad_tags())
    live = growth.read_live(CFG.get('dump') or '', ids)
    vals = [v['aff'] for v in live.values() if v.get('aff')]
    if len(vals) < max(5, len(ids) // 2):
        return dict(ok=False, queued=0, why='nomorale')   # dump bez morala (osnovna tablica): pokusaj kasnije
    vals.sort()
    med = vals[len(vals) // 2]
    if abs(med - NEWJOB_AFF) <= 20 and not force:
        e.update(state='done')
        A[key] = e
        _jdump(A, NEWJOB_FILE, indent=1)
        return dict(ok=True, queued=0, state='done')
    if e.get('state') == 'queued' and time.time() - e.get('t', 0) < 600 and not force:
        return dict(ok=True, queued=0, state='queued')   # ceka GrowthBridge / spremanje
    if e.get('tries', 0) >= 4 and not force:
        return dict(ok=True, queued=0, state='gave_up')
    pre = 'nj%x' % int(time.time())
    lines = ['%s-%d-Affection,%d,Affection,set,%d' % (pre, pid, pid, NEWJOB_AFF)
             for pid, v in live.items() if v.get('aff') is not None and abs(v['aff'] - NEWJOB_AFF) > 8]
    if lines:
        p_ = os.path.join(growth.bridge_dir(CFG), 'growth.csv')
        with open(p_, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\n'.join(lines) + '\n')
    e.update(state='queued', t=time.time(), tries=e.get('tries', 0) + 1, date=_fmt_date(s.game_date_code()))
    A[key] = e
    _jdump(A, NEWJOB_FILE, indent=1)
    return dict(ok=True, queued=len(lines), state='queued')


def intro_view(slot):
    """Podaci za uvod u karijeru: klub, trener, datum, budzet, polozaj momcadi po snazi u ligi (ocekivanja uprave), kljucni igraci."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    r = mlsave.read_save(slot_folder(slot), None)
    info = r.get('info', {})
    club = info.get('club') or aitransfers._club_name(s.d, my)
    squad = []
    for pid in s.my_squad_tags():
        ov, ag = rat(pid)
        if ov:
            squad.append(dict(id=pid, name=NAMES.get(pid, str(pid)), pos=aitransfers.POS_NAME.get(POS.get(pid, 5), '?'), ovr=ov, age=ag))
    top = sorted((p['ovr'] for p in squad), reverse=True)[:14]
    my_str = sum(top) / len(top) if top else 0
    # liga: klubovi iz moje lige (tablica) i njihova snaga (prosjek 14 najboljih)
    names = []
    try:
        cv = comps_view(slot)
        m_ = next((c for c in cv['comps'] if c['kind'] == 'league' and c['mine']), None)
        names = [x['club'] for x in (m_ or {}).get('rows', [])]
    except Exception:
        names = [x.get('club') for x in r.get('league_table', [])]
    clubs = {c['name']: c for c in aitransfers.load_clubs(s, rat, POS, my).values()}
    lg = [(n, clubs[n]['strength']) for n in names if n in clubs and n != club]
    lg.append((club, my_str))
    lg.sort(key=lambda x: -x[1])
    rank = next((i + 1 for i, x in enumerate(lg) if x[0] == club), None)
    n = len(lg)
    goal = None
    if rank and n >= 4:
        f = (rank - 1) / float(max(1, n - 1))
        goal = 'title' if rank == 1 else 'challenge' if (rank <= 3 and n >= 12) else 'europe' if f <= 0.22 else 'upper' if f <= 0.45 else 'mid' if f <= 0.75 else 'survive'
    played = 0
    for x in r.get('league_table', []):
        if x.get('club') == club:
            played = x.get('pl', 0) or 0
    sq = sorted(squad, key=lambda p: -p['ovr'])
    young = sorted((p for p in squad if (p['age'] or 99) <= 21), key=lambda p: -p['ovr'])[:1]
    vet = sorted(squad, key=lambda p: (-(p['age'] or 0), -p['ovr']))[:1]
    try:
        cid = _career_id(slot, s)
    except Exception:
        cid = ''
    return dict(career=cid, club=club, league=info.get('league', ''), date=info.get('date', ''), manager=s.manager(), budget=s.budget(), played=played,
                rank=rank, n=n, goal=goal, strength=round(my_str, 1), best=(round(lg[0][1], 1) if lg else None), best_club=(lg[0][0] if lg else None),
                avg=(round(sum(x[1] for x in lg) / len(lg), 1) if lg else None), size=len(squad),
                age=(round(sum(p['age'] or 0 for p in squad) / len(squad), 1) if squad else None),
                stars=sq[:5], young=young[0] if young else None, vet=vet[0] if vet else None,
                ladder=[dict(club=x[0], s=round(x[1], 1)) for x in lg])



def coach_info(slot, club=None):
    """Trener kluba (id, ime, ima li sliku). Za moj klub: slika koju je korisnik odabrao (data/manager_photo.json), inace nema (igra ima vlastitog menadzera bez slike)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    my_idx = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    names = mlsave.team_names(bytes(s.d), max(693, mlsave.club_layout(s.d)[0]))   # pc260
    idx = my_idx if not club else (names.index(club) if club in names else None)
    if idx is None:
        return dict(id=None)
    ph = _coach_photos()
    cn = _coach_names()
    if idx == my_idx:
        # pc147: slika menadzera po KARIJERI (ne po slotu): nova karijera u istom slotu ne nasljedjuje staru sliku.
        # Redom: rucni odabir za ovu karijeru (isti menadzer) -> trener iz bloka u saveu -> isto ime medju trenerima iz igre -> stari zapis po slotu.
        mgr = s.manager() or ''
        key = _career_id(slot, s)
        try:
            A = json.load(open(MGR_FILE, encoding='utf-8'))
        except Exception:
            A = {}
        sel, src = None, None
        cp_ = os.path.join(MGR_DIR, re.sub(r'[^A-Za-z0-9_.-]', '_', key) + '.jpg')
        if os.path.isfile(cp_) and not (isinstance(A.get(key), dict) and A[key].get('id')):
            # pc164: vlastita slika s racunala (Setup slike menadzera -> Upload)
            return dict(id=None, custom=key, v=int(os.path.getmtime(cp_)), mine=True, name=mgr, photo=True, src='custom')
        e = A.get(key)
        if isinstance(e, dict) and e.get('pid') and (not e.get('mgr') or _nm_norm(e.get('mgr')) == _nm_norm(mgr)):
            return dict(id=None, pid=int(e['pid']), mine=True, name=mgr, photo=True, src='manual')
        if isinstance(e, dict) and (not e.get('mgr') or _nm_norm(e.get('mgr')) == _nm_norm(mgr)):
            sel, src = e.get('id'), 'manual'
        elif isinstance(e, int) and key != slot:
            sel, src = e, 'manual'
        b_ = None
        if not sel:
            try:
                b_ = struct.unpack_from('<I', coaches.read_block(s, idx), 0)[0]
                # pc163: slika iz igre samo ako joj ime odgovara menadzeru: vlastiti menadzer u FL-u dobije ID cija je slika
                # nekog drugog (Mandzukic -> slika Fabregasa 28.10.)
                if b_ in ph and _nm_norm(cn.get(b_, '')) == _nm_norm(mgr):
                    sel, src = b_, 'game'
            except Exception:
                b_ = None
        if not sel and mgr:
            sel = _coach_by_name(mgr, ph, cn)
            src = 'name' if sel else None
        if not sel and mgr:
            # bivsi igrac kao menadzer (Mandzukic, Fabregas...): lice igraca iz baze
            m_ = _nm_norm(mgr)
            pp = next((k for k, v in NAMES.items() if _nm_norm(v) == m_), None)
            if pp:
                return dict(id=None, pid=pp, mine=True, name=mgr, photo=True, src='player')
        # pc208: bez slike koja odgovara imenu menadzera NE uzimamo lice trenera kluba iz igre (Guardiola kod D. Lanea 29.10.)
        # ni staru sliku po slotu; app trazi da korisnik odabere sliku.
        return dict(id=sel, mine=True, name=mgr, photo=bool(sel and sel in ph), src=src)
    cid = _club_coach_id(s, idx)
    return dict(id=cid, name=cn.get(cid, ''), photo=bool(cid in ph), mine=False)


def coach_list(q=''):
    cn = _coach_names()
    ph = _coach_photos()
    q = (q or '').strip().lower()
    out = [dict(id=k, name=cn.get(k, '')) for k in ph if not q or q in cn.get(k, '').lower()]
    out.sort(key=lambda r: (r['name'] == '', r['name']))
    if len(q) >= 3:
        # pc284: i igraci s licem (bivsi igrac kao menadzer, npr. Figo): trazi se po imenu, slika je lice igraca
        qn = _nm_norm(q)
        pl = [(k, v) for k, v in NAMES.items() if qn in _nm_norm(v)][:60]
        for k, v in pl:
            if game_face(k) or fm_face(k):
                out.append(dict(id='p%d' % k, pid=k, name=v + ' (player)'))
            if len(out) >= 200:
                break
    return dict(items=out[:200], total=len(ph))


def _nm_norm(t):
    import unicodedata
    t = unicodedata.normalize('NFKD', t or '')
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in t if not unicodedata.combining(c)).lower())


def _coach_by_name(mgr, ph, cn):
    """Menadzer s istim imenom kao trener iz igre koji ima sliku (bez kvacica i razmaka); i 'C. Fabregas' -> 'Cesc Fabregas'."""
    m = _nm_norm(mgr)
    if not m:
        return None
    parts = [x for x in re.split(r'[\s.]+', mgr or '') if x]
    last = _nm_norm(parts[-1]) if parts else ''
    first = _nm_norm(parts[0])[:1] if len(parts) > 1 else ''
    soft = []
    for k in ph:
        n = cn.get(k) or ''
        if not n:
            continue
        nn = _nm_norm(n)
        if nn == m:
            return k
        np_ = [x for x in re.split(r'[\s.]+', n) if x]
        if last and np_ and _nm_norm(np_[-1]) == last and (not first or _nm_norm(np_[0])[:1] == first):
            soft.append(k)
    return soft[0] if len(soft) == 1 else None


def coach_set(body):
    slot = body['slot']
    try:
        a = json.load(open(MGR_FILE, encoding='utf-8'))
    except Exception:
        a = {}
    v = body.get('id')
    try:
        s_ = mlwrite.Save(slot_folder(slot), ro=True)
        key, mgr = _career_id(slot, s_), s_.manager() or ''
    except Exception:
        key, mgr = slot, ''
    a.pop(slot, None)
    try:
        os.remove(os.path.join(MGR_DIR, re.sub(r'[^A-Za-z0-9_.-]', '_', key) + '.jpg'))
    except OSError:
        pass
    if v and str(v).startswith('p'):
        a[key] = dict(pid=int(str(v)[1:]), mgr=mgr)   # pc284: lice igraca kao slika menadzera
    elif v:
        a[key] = dict(id=int(v), mgr=mgr)
    else:
        a.pop(key, None)
    _jdump(a, MGR_FILE)
    return coach_info(slot)


def coach_img(cid):
    p = _coach_photos().get(int(cid))
    return open(p, 'rb').read() if p else None


# ---------------------------------------------------------------- pravi dresovi iz igre (UML_Kits): u izradi
def _kit_tex_dir(log=None):
    for rt in _cpk_roots():
        for sub in (('Asset',), ('common',), ()):
            d = os.path.join(rt, *(sub + ('model', 'character', 'uniform', 'texture', '#windx11')))
            ok = os.path.isdir(d)
            if log is not None:
                log.append('%s -> %s' % (d, ok))
            if ok:
                try:
                    if any(f.lower().startswith('u0') for f in os.listdir(d)):
                        return d
                except Exception as e:
                    if log is not None:
                        log.append('listdir: %s' % e)
    return None


def _kit_tex_dirs():
    """Sve mape s teksturama dresova u svim livecpk korijenima (redom prioriteta). Dresovi su rasporedeni po vise paketa
    (FL osnova, update-i, kit pack), pa se trazi datoteka kroz sve, ne samo u prvoj nadjenoj mapi."""
    if _GL.get('kitdirs') is not None:
        return _GL['kitdirs']
    out = []
    for rt in _cpk_roots():
        for sub in (('Asset',), ('common',), ('common', 'character0'), ('common', 'character1'), ()):
            d = os.path.join(rt, *(sub + ('model', 'character', 'uniform', 'texture', '#windx11')))
            if os.path.isdir(d) and d not in out:
                out.append(d)
    _GL['kitdirs'] = out
    return out


def _ks_dir():
    """pc379/pc383: mapa Sider kit-servera. FL26: content\\kit-server; FL27 (SP): content\\kits (modul common\\kits.lua, isti format).
    Mapa se prihvaca samo ako map.txt ima redove (team id, "mapa") I bar jedna mapirana mapa stvarno ima dres (order.ini ili
    podmapa s config.txt). Prije je zadnja pricuva uzela bilo koju mapu s map.txt (FL27 tester: content\\SleeveBadge). -> putanja ili ''."""
    root = _sider_root()
    if not root:
        return ''
    cont = os.path.join(root, 'content')
    c = _GL.get('ksdir')
    if c and c[0] == cont and time.time() - c[2] < 60:
        return c[1]
    def ok(d):
        mp = os.path.join(d, 'map.txt')
        if not os.path.isfile(mp):
            return False
        try:
            rels = []
            for line in open(mp, encoding='utf-8', errors='ignore'):
                m_ = re.match(r'\s*\d+\s*,\s*"([^"]+)"', line)
                if m_:
                    rels.append(m_.group(1).replace('\\', os.sep).replace('/', os.sep))
            for rel in rels[:40]:
                td = os.path.join(d, rel)
                if os.path.isfile(os.path.join(td, 'order.ini')):
                    return True
                try:
                    if any(os.path.isfile(os.path.join(td, x, 'config.txt')) for x in os.listdir(td)):
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False
    found = ''
    for nm in ('kit-server', 'kits', 'kitserver', 'Kit-Server', 'Kits'):
        d = os.path.join(cont, nm)
        if ok(d):
            found = d
            break
    if not found:
        try:
            for nm in sorted(os.listdir(cont)):
                d = os.path.join(cont, nm)
                if 'kit' in nm.lower() and os.path.isdir(d) and ok(d):
                    found = d
                    break
        except Exception:
            pass
    _GL['ksdir'] = (cont, found, time.time())
    return found


def _ks_empty_fl27():
    """pc383: SP FL27 ima modul za kit-server (content\\kits), ali je map.txt prazan: dresovi su samo u cpk arhivama igre."""
    try:
        root = _sider_root()
        mp = os.path.join(root, 'content', 'kits', 'map.txt') if root else ''
        if not mp or not os.path.isfile(mp):
            return False
        return not any(re.match(r'\s*\d+\s*,', l) for l in open(mp, encoding='utf-8', errors='ignore'))
    except Exception:
        return False


def _kitserver_tex(tid, k):
    """Dres iz Sider kit-servera: content\\kit-server\\map.txt (team id -> mapa), order.ini (redoslijed dresova p1, p2...),
    <dres>\\config.txt (KitFile=...). -> putanja do .ftex ili None."""
    try:
        ks = _ks_dir()   # pc379: FL27 drzi dresove u content\\kits
        mp = os.path.join(ks, 'map.txt')
        if not ks or not os.path.isfile(mp):
            return None
        mt = os.path.getmtime(mp)
        if _GL.get('ksmap_mt') != mt:
            M = {}
            for line in open(mp, encoding='utf-8', errors='ignore'):
                m_ = re.match(r'\s*(\d+)\s*,\s*"([^"]+)"', line)
                if m_:
                    M[int(m_.group(1))] = m_.group(2).replace('\\', os.sep).replace('/', os.sep)
            _GL['ksmap'], _GL['ksmap_mt'] = M, mt
        rel = (_GL.get('ksmap') or {}).get(tid)
        if not rel:
            return None
        td = os.path.join(ks, rel)
        order = []
        try:
            order = [x.strip().lstrip('\ufeff') for x in open(os.path.join(td, 'order.ini'), encoding='utf-8-sig', errors='ignore') if x.strip()]
        except Exception:
            pass
        outfield = [x for x in order if x.lower().startswith('p')] or ['p1', 'p2', 'p3']
        if k < 1 or k > len(outfield):
            return None
        kd = os.path.join(td, outfield[k - 1])
        kf = None
        try:
            for line in open(os.path.join(kd, 'config.txt'), encoding='utf-8', errors='ignore'):
                m_ = re.match(r'\s*KitFile\s*=\s*([^\s;]+)', line)
                if m_:
                    kf = m_.group(1)
                    break
        except Exception:
            pass
        for nm in ([kf] if kf else []) + ['u%04dp%d' % (tid, k)]:
            fp = os.path.join(kd, nm + '.ftex')
            if os.path.isfile(fp):
                return fp
    except Exception:
        return None
    return None



def _unwesys(raw):
    """pc381: datoteke u cpk arhivama FL27 (npr. lica igraca u Data/dt14_all.cpk, common/render/symbol/player/<id>.dds) imaju
    16 B zaglavlje 'WESYS' i zlib sazete podatke; ispod je obican DDS/PNG. (Nasao tester na Linuxu, FL27.)"""
    # pc414: tester (FL27, CrossOver): datoteke znaju pocinjati s 00 01 01 + 'WESYS' (kao i baza igre, vidi _wesys raw[3:8]);
    # prije se provjeravao samo pocetak, pa su lica ostajala sazeta i app ih nije mogao prikazati
    if b'WESYS' not in (raw[:5], raw[3:8]):
        return raw
    import zlib
    for st in (16, 12, 20, 8):
        try:
            return zlib.decompress(raw[st:])
        except Exception:
            pass
    try:
        return zlib.decompressobj(-15).decompress(raw[16:])
    except Exception:
        return raw



def kit_img(club, k=1):
    """Tekstura pravog dresa iz igre (UML_Kits: u<team id 4 zn.>p<k>.ftex, BC7) kao PNG 512x512 (mip 2), kes u data/kits.
    Preglednik od nje slaze prednju stranu dresa (majica, rukavi, hlacice). None ako nema teksture."""
    import ftex
    import bc7
    def miss(why):
        try:
            k_ = (club, int(k))
            if k_ not in _GL.setdefault('kitmiss', set()):
                _GL['kitmiss'].add(k_)
                open(os.path.join(HERE, 'data', '_kitmiss.log'), 'a', encoding='utf-8').write('%s | %s k%d | %s | dirs=%d\n' % (time.strftime('%Y-%m-%d %H:%M'), club, int(k), why, len(_kit_tex_dirs())))
        except Exception:
            pass
        return None
    tid = _team_id(club)
    if not tid:
        return miss('no team id')
    fn = 'u%04dp%d.ftex' % (int(tid), int(k))
    src = _kitserver_tex(int(tid), int(k))      # pc163: Sider kit-server (content\kit-server) ima prednost, kao u igri
    for d in ([] if src else _kit_tex_dirs()):
        if os.path.isfile(os.path.join(d, fn)):
            src = os.path.join(d, fn)
            break
    if not src:
        return miss('no %s' % fn)
    cd = os.path.join(HERE, 'data', 'kits')
    cp = os.path.join(cd, fn.replace('.ftex', '_%d.png' % int(os.path.getmtime(src))))
    if os.path.isfile(cp):
        return open(cp, 'rb').read()
    raw = open(src, 'rb').read()
    data, lv = ftex.mip_data(raw, 2)
    w = max(1, struct.unpack_from('<H', raw, 10)[0] >> lv)
    h = max(1, struct.unpack_from('<H', raw, 12)[0] >> lv)
    fmt = struct.unpack_from('<H', raw, 8)[0]
    if fmt == 0xB:
        px = bc7.decode(data, w, h)
    else:
        w, h, px = ftex.decode(raw, 2)
    for i in range(3, len(px), 4):
        px[i] = 255
    png = dds.to_png(w, h, px)
    os.makedirs(cd, exist_ok=True)
    for f in os.listdir(cd):
        if f.startswith(fn.replace('.ftex', '_')):
            try:
                os.remove(os.path.join(cd, f))
            except OSError:
                pass
    open(cp, 'wb').write(png)
    return png

# ---------------------------------------------------------------- prodaja igraca
_SETC = {}
_JOBD = {}


def _job_days(slot, s):
    """pc316: dana u igri od pocetka sadasnjeg posla (uprava: 'since'); 999 ako se ne zna."""
    k = (slot, s.game_date_code())
    if _JOBD.get(slot, (None,))[0] == k:
        return _JOBD[slot][1]
    import datetime as _dt
    n = 999
    try:
        cid = _career_id(slot, s)
        B = (json.load(open(BOARD_FILE, encoding='utf-8')) or {}).get(cid) or {}
        sc = (B.get('cur') or {}).get('since')
        if sc:
            d_, m_, y_ = [int(x) for x in sc.split('/')]
            gc = s.game_date_code()
            n = (_dt.date(gc & 0xffff, (gc >> 16) & 0xff, gc >> 24) - _dt.date(y_, m_, d_)).days
    except Exception:
        n = 999
    _JOBD[slot] = (k, n)
    return n


def _settled_cached(slot, s):
    """pc315: skup tek dovedenih igraca (settled_protect bez nasumicnih iznimaka), kesiran po slotu i datumu igre."""
    try:
        _rmt = os.path.getmtime(REALMOVES_FILE)
    except OSError:
        _rmt = 0
    k = (slot, s.game_date_code(), len(s.d), _rmt)   # pc379: i kad stignu stvarni transferi
    c = _SETC.get(slot)
    if c and c[0] == k:
        return c[1]
    import datetime as _dt
    out = set()
    try:
        out |= set(s.recent_joins(400))
    except Exception:
        pass
    try:
        gc = s.game_date_code()
        now = _dt.date(gc & 0xffff, (gc >> 16) & 0xff, gc >> 24)
        for pid, v in real_moves(slot).items():
            y_, m_, d_ = [int(x) for x in v['date'].split('-')]
            if -60 <= (now - _dt.date(y_, m_, d_)).days <= 400:
                out.add(int(pid))
    except Exception:
        pass
    _SETC[slot] = (k, out)
    return out


def _offers_for(slot, s, gd, month_key, pid, lv, listed, ask=None):
    """Deterministicne ponude AI klubova (seed: slot, igrac, mjesec igre). -> lista dict(club, off, fee, ceil)."""
    ovr, age = rat(pid)
    y, m, _ = _date_tuple(gd)
    ml = None
    if lv.get('cy'):
        ml = (lv['cy'] - y) * 12 + (lv['cm'] - m)
    f = negotiate.facts(ovr, lv.get('age') or age or 25, lv.get('mv', 0), lv.get('sal', 0), ml, listed)
    r = negotiate._rng('sell', slot, pid, month_key)
    cnt = r.choice([2, 2, 3, 4]) if listed else (1 if r.random() < 0.35 else 0)
    if not listed and cnt and pid in _nfs(slot, s):
        cnt = 0   # pc398: 'nije na prodaju'
    if not listed and cnt and _job_days(slot, s) < 7:
        cnt = 0   # pc316: prvi tjedan novog posla: nitko jos ne nudi za tvoje igrace
    if not listed and cnt and not real_moves_ready():
        # pc379: stvarni transferi (tko je ovo ljeto tek dosao u klub) jos nisu ucitani (prvo pokretanje, nema interneta):
        # u prvoj godini svijeta igre ne nudi za nikoga s liste, osim rijetko (inace ponude za igrace kupljene ovo ljeto u stvarnosti)
        try:
            if (y, m) < (_real_cutoff() + 1, 7) and r.random() >= 0.05:
                cnt = 0
        except Exception:
            pass
    if not listed and cnt:
        # pc315: nitko ne nudi za igraca koji je tek dosao (u karijeri ili ovo ljeto u stvarnosti), osim rijetko;
        # za kljucne igrace (14 najboljih) ponude su rjedje. Prije: Liverpool 1.8. nove karijere imao je 9 ponuda (Isak, Wirtz, van Dijk...)
        try:
            if pid in _settled_cached(slot, s) and r.random() >= 0.05:
                cnt = 0
            else:
                _mo_ = sorted((rat(q)[0] or 0 for q in s.my_squad_tags()), reverse=True)
                if ovr and len(_mo_) >= 14 and ovr >= _mo_[13] and r.random() >= 0.4:
                    cnt = 0
        except Exception as ex:
            print('[offers] settled:', ex)
    if getattr(s, 'ro', False):   # pc413: samo-za-citanje save: popis klubova jednom po pogledu (Asistent ga je trazio 25 puta)
        clubs = getattr(s, '_aic', None)
        if clubs is None:
            clubs = s._aic = s.ai_clubs()
    else:
        clubs = s.ai_clubs()
    if not clubs or not ovr:
        return []
    base = negotiate.club_ask(f, 'balanced')
    out = []
    used = set()
    tiers = _club_tiers(slot, s)
    fins = _club_fin(slot, s)
    wage = _wages(slot, s).get(pid, 0)
    ptr = persona.traits(pid)
    _mo = [rat(q)[0] for q in s.my_squad_tags() if rat(q)[0]]
    my_str = (sum(sorted(_mo, reverse=True)[:14]) / min(14, len(_mo))) if _mo else None
    # pc201: prije je svaki od 'cnt' pokusaja birao nasumican klub i odustao ako mu placa ne stane; za dobro placene igrace
    # (tester 60 MB: 3 igraca na listi do zadnjeg dana roka) to je cesto davalo 0 ponuda. Sada: do cnt ponuda iz vise pokusaja,
    # samo klubovi kojima placa (uz pristanak na ~25% nizu placu) i naknada stanu.
    _att = 0
    while len(out) < cnt and _att < cnt * 6:
        _att += 1
        # kupac mora odgovarati igracu: snaga kluba blizu OVR-a igraca, i klub si mora moci priustiti naknadu (po razini kluba)
        pool = []
        for c in clubs:
            t = tiers.get((c[0] - mlwrite.REC0) // mlwrite.STRIDE)
            if t is None or c[0] in used:
                continue
            tier, strength = t
            if not (ovr - 8 <= strength <= ovr + 8):
                continue
            _fi = fins.get((c[0] - mlwrite.REC0) // mlwrite.STRIDE) or {}
            if wage and wage * 0.75 > _fi.get('wres', 1e18):
                continue
            pool.append((c, tier))
        if not pool:
            break
        c, tier = pool[r.randrange(len(pool))]
        used.add(c[0])
        fee = negotiate.rnd100(base * r.uniform(0.78, 1.0 if listed else 0.9) * (0.78 if _on_strike(slot, pid) else 1.0), 100)
        cap = TIER_CAP.get(tier)
        if cap is not None and fee > cap:
            continue
        ceil = negotiate.rnd100(fee * r.uniform(1.0, 1.18), 100)
        cidx = (c[0] - mlwrite.REC0) // mlwrite.STRIDE
        fin = fins.get(cidx) or {}
        if fin.get('budget') is not None and ceil > fin['budget']:
            ceil = negotiate.rnd100(fin['budget'], 100)          # klub ne moze platiti vise od svog budzeta
            if ceil < fee * 0.9:
                continue
            fee = min(fee, ceil)
        if ask:
            if ceil < ask * 0.85:
                continue                                          # klub ne dosize trazenu cijenu
            fee = min(ceil, max(fee, negotiate.rnd100(ask * r.uniform(0.85, 0.95), 100)))
        wres = fin.get('wres', 1e18)
        if wage and wage * 0.75 > wres:
            continue                                              # ni placa uz ~25% smanjenja ne stane u salary budget kupca
        # kupac nudi placu: manji klubovi znaju ponuditi vise da privuku igraca
        bstr = tiers[cidx][1]
        fac = r.uniform(0.95, 1.3) + (0.1 if (my_str is not None and bstr < my_str) else 0.0)
        wage_offer = negotiate.rnd100(min(wage * fac, wres), 100) if wage else 0
        ex = persona.exit_view(f, ptr, my_str, bstr, listed, rk=persona.squad_rank(_mo, ovr), wage=wage, wage_offer=wage_offer)
        out.append(dict(off=c[0], club=c[1], fee=fee, ceil=ceil, score=ex['score'], will=ex['status'], why=ex['why'], pro=ex['pro'], wage=wage, wage_offer=wage_offer))
    return out


def _loan_end(s, half):
    """Kraj posudbe: pola sezone (31/12 ako smo u ljetnom roku, inace 30/6) ili do kraja sezone (30/6)."""
    y, m, _ = _date_tuple(s.game_date_code())
    if m >= 7:
        return (31 << 24) | (12 << 16) | y if half else (30 << 24) | (6 << 16) | (y + 1)
    return (30 << 24) | (6 << 16) | y


def _long_injured(s):
    """Moji igraci s ozljedom od 6+ mjeseci (bajt 0x148 = dani ozljede u zivom dumpu; bez dumpa nitko nije na popisu)."""
    try:
        d = CFG.get('dump') or ''
        mine = [q for q in s.squad_ids() if q]
        live = growth.read_live(d, mine)
        out = {q for q, v in live.items() if v.get('inj', 0) >= 180}
        try:
            W_ = world_injuries()[0]
            out |= {q for q in mine if W_.get(q, 0) >= 180}
        except Exception:
            pass
        return out
    except Exception:
        return set()


def _loan_stance(slot, pid, ctx, s):
    """FM-style: will the owner club loan the player to me at all? -> dict(kind open|reluctant|refuse, mult, why, reason)."""
    pd = players_data(slot)
    club = ctx.get('club') or ''
    squad = sorted([r for r in pd['players'] if r['club'] == club and r['ovr']], key=lambda r: -r['ovr'])
    rk = next((i for i, r in enumerate(squad) if r['id'] == pid), None)
    me = next((r for r in pd['players'] if r['id'] == pid), None) or {}
    listed = bool(me.get('loan'))
    lst = {}
    try:
        lst = ai_listings(slot, s).get(pid) or {}
    except Exception:
        pass
    listed = listed or lst.get('kind') == 'loan'
    reason = lst.get('reason') if lst.get('kind') == 'transfer' else None
    f = ctx['f']
    if reason == 'wants_out':
        return dict(kind='refuse', mult=1.0, reason=reason, why='He wants to leave %s for good. A loan does not solve that for the club or the player: only a permanent transfer is possible.' % club)
    # igrac sam odbija ako na njegovoj poziciji vec imas dovoljno boljih (ne bi dobio minute); iznimka: dugotrajna ozljeda (6+ mj.) tvog igraca na toj poziciji
    crowd_ = ctx.get('crowd', 0)
    ppos = POS.get(pid)
    tol = 1 if (rk is not None and rk >= 14) else 0
    if crowd_ > tol:
        n_ = crowd_ + _SLOTS.get(ppos, 1) - 1
        return dict(kind='refuse', mult=1.0, reason=reason, why='He turned it down: you already have %d player%s at %s who are as good or better, so he would not get the minutes he is looking for.' % (n_, '' if n_ == 1 else 's', mlwrite.RPOS.get(ppos, '?')))
    if f['age'] <= 23 and f['ovr'] >= 55 and negotiate_rank(ctx) > 8:
        return dict(kind='refuse', mult=1.0, reason=reason, why='The club only sends young players on loan where they will play. In your squad he would be a backup.')
    if listed:
        return dict(kind='open', mult=0.95, reason=reason, why='The club is offering him on loan.')
    if rk is None or len(squad) < 12:
        return dict(kind='open', mult=1.1, reason=reason, why='')
    if rk <= 5:
        return dict(kind='refuse', mult=1.0, reason=reason, why='Key player for the club: not available on loan.')
    r = negotiate._rng('loanstance', slot, pid, ctx['month_key'])
    if rk <= 13:
        if f['months_left'] is not None and f['months_left'] <= 6 and r.random() < 0.5:
            return dict(kind='reluctant', mult=1.3, reason=reason, why='His contract is about to expire: the club would loan him for a higher fee.')
        if r.random() < 0.15:
            return dict(kind='reluctant', mult=1.8, reason=reason, why='The club counts on him in the first team and would only loan him for a very high fee.')
        return dict(kind='refuse', mult=1.0, reason=reason, why='The club counts on him in the first team: not available on loan.')
    return dict(kind='open', mult=1.15, reason=reason, why='Not on the loan list, but outside the first team: the club is willing to talk.')


def negotiate_rank(ctx):
    my = ctx['my']
    return negotiate_squad_rank(my, ctx['f']['ovr'])


negotiate_squad_rank = persona.squad_rank


def _loan_in_terms(slot, pid):
    """Uvjeti posudbe igraca U moj klub (do kraja sezone). Dvije varijante: bez opcije i s opcijom otkupa."""
    ctx = neg_context(slot, pid)
    s, f = ctx['save'], ctx['f']
    _has, _onloan, _own = s.player_loan_state(pid)
    if _onloan:
        st_ = dict(kind='refuse', mult=1.0, reason=None, why='He is already out on loan from his own club, so he cannot be loaned on to anyone. Pick a player who is under contract with his club.')
    elif not _own:
        st_ = dict(kind='refuse', mult=1.0, reason=None, why='He has no owner club (free agent or not loanable in this game).')
    else:
        st_ = _loan_stance(slot, pid, ctx, s)
    mv = f['mv']
    y, m, _ = _date_tuple(s.game_date_code())
    end = _loan_end(s, False)
    wage = _wages(slot, s).get(pid, 0) or f['sal']
    buy = negotiate.rnd100(mv * 1.1, 100)
    opt_end = (31 << 24) | (8 << 16) | (y + (3 if m >= 7 else 2))
    mult = st_['mult']
    return dict(stance=st_, pid=pid, name=NAMES.get(pid, str(pid)), club=ctx.get('club') or '', mv=mv, end=end, wage_now=s.player_wages().get(pid, 0), committed=s.wage_commitment() + s.pending_loan_wage(), end_s=_fmt_date(end), budget=struct.unpack_from('<I', s.d, s.BUDGET)[0] * 100,
                plain=dict(fee=max(50000, negotiate.rnd100(mv * 0.08 * mult, 100))),
                option=dict(fee=negotiate.rnd100(buy * 0.35 * mult, 100), buy=negotiate.rnd100(buy * (1 + (mult - 1) * 0.5), 100), wage=negotiate.rnd100(wage * 1.6, 100), release=negotiate.rnd100(buy * 1.14 * (1 + (mult - 1) * 0.5), 100), end=opt_end,
                            end_s=_fmt_date(opt_end)))


def loan_in_terms(body):
    slot, pid = body['slot'], int(body['pid'])
    return _loan_in_terms(slot, pid)


def loan_in_do(body):
    """Posudba igraca u moj klub: kind = 'plain' | 'option'. Igrac ostaje ugovorom kod vlasnika."""
    slot, pid, kind = body['slot'], int(body['pid']), body.get('kind', 'plain')
    s = mlwrite.Save(slot_folder(slot))
    reg_check(slot, s, pid)
    if pid in _moved(slot, s):
        raise ValueError('player has already changed clubs in this transfer window')
    if kind == 'finish':
        # ponuda je poslana NATIVNO u igri (spremljena); app je samo "prihvati" (status 4 + dnevnik + red dogadjaja)
        if pid in s.my_squad_tags():
            raise ValueError('player is already in your club')
        if s._squad_len(s.club_offset()) >= 40:
            raise ValueError('squad is full (40)')
        try:
            _club0 = neg_context(slot, pid).get('club') or ''
        except Exception:
            _club0 = ''
        r = _write_slot(slot, 'loan_in', lambda sv: sv.loan_in_finish(pid))
        _mark_moved(slot, s, pid)
        try:
            s2 = mlwrite.Save(slot_folder(slot))
            ot = s2.option_terms(pid)
            dl = next((x for x in s2.list_deals() if x['pid'] == pid), None) or {}
            _ev_add(slot, 'signed', pid, frm=_club0, fee=dl.get('fee', 0), wage=0, years=0, until=_fmt_date(_loan_end(s2, False)), loan=True, option=(ot['buy'] if ot else 0),
                    opt=(dict(wage=ot['wage'], release=ot['release'], end_s=_fmt_date(ot['end'])) if ot else None))
        except Exception:
            pass
        return dict(ok=True, message='The offer from the game is complete. Load the save in the game and simulate ONE day: then the player arrives.', detail=r)
    if pid in {x['pid'] for x in s.list_deals()} or pid in s.my_squad_tags():
        raise ValueError('player is already in your club or has a deal')
    if s._squad_len(s.club_offset()) >= 40:
        raise ValueError('squad is full (40)')
    T = _loan_in_terms(slot, pid)
    if T['stance']['kind'] == 'refuse':
        raise ValueError(T['name'] + ': ' + T['stance']['why'])
    # posudba ne trosi salary budget u igri (potvrdio korisnik 27.10.), placa se samo naknada iz transfer budzeta
    o = T['option'] if kind == 'option' else T['plain']
    fee = o['fee']
    opt = dict(buy=o['buy'], wage=o['wage'], release=o['release'], end=o['end']) if kind == 'option' else None
    # nativni tok: upisuje se samo "dogovoreno" stanje (s opcijom otkupa jos uvjeti ugovora + cijena otkupa), igra posudbu sama dovrsi sljedeci dan
    if _lq_should_queue(s, pid, body):
        _lq_add(slot, s, dict(pid=pid, src='direct', kind=kind, fee=fee, club=T['club']))
        return dict(ok=True, queued=True, message='%s: loan agreed (fee %d EUR). Another loan is still waiting to arrive, and the game only completes one per day, so this one is queued. After the next day in the game the app writes it.' % (T['name'], fee))
    multi = bool(body.get('multi')) and _is_owner()   # pc150: test vise posudbi odjednom, samo vlasnik
    r = _write_slot(slot, 'loan_in', lambda sv: sv.loan_in_pending(pid, fee, T['end'], option=opt, multi=multi), pid=pid)
    _mark_moved(slot, s, pid)
    try:
        if not str(r).startswith('loaned'):
            _lp_add(slot, s, pid, fee, 0, T['club'], (r or {}).get('backup') if isinstance(r, dict) else None)
    except Exception as ex:
        print('[loanpend]', ex)
    try:
        _ev_add(slot, 'signed', pid, frm=T['club'], fee=fee, wage=0, years=0, until=T['end_s'], loan=True, option=(o['buy'] if kind == 'option' else 0), opt=(dict(wage=o['wage'], release=o['release'], end_s=T['option']['end_s']) if kind == 'option' else None))
    except Exception:
        pass
    if str(r).startswith('loaned'):
        return dict(ok=True, message='%s: loan until %s, fee %d EUR. The player is in the squad right away: load the save in the game.' % (T['name'], T['end_s'], fee), detail=r)
    return dict(ok=True, message='%s: loan agreed until %s, fee %d EUR%s. Load the save in the game and simulate ONE day: then the player arrives.' % (T['name'], T['end_s'], fee, (', opcija otkupa %d EUR' % o['buy']) if kind == 'option' else ''), detail=r)


# ---------------------------------------------------------------- pregovori o posudbi (igrac IZ drugog kluba kod mene)
LNEG = None


def _lneg_store():
    global LNEG
    if LNEG is None:
        LNEG = negotiate.Store(os.path.join(HERE, 'data', 'loan_negotiations.json'))
    return LNEG


def _lneg_asks(T, kind, mood):
    k = {'eager': 0.92, 'balanced': 1.0, 'hard': 1.12}[mood]
    if kind == 'option':
        return dict(fee=negotiate.rnd100(T['option']['fee'] * k, 100), buy=negotiate.rnd100(T['option']['buy'] * k, 100))
    return dict(fee=negotiate.rnd100(T['plain']['fee'] * k, 100), buy=0)


def _lneg_view(slot, pid, rec, T=None, s=None):
    T = T or _loan_in_terms(slot, pid)
    s = s or mlwrite.Save(slot_folder(slot), ro=True)
    return dict(pid=pid, name=T['name'], club=T['club'], kind=rec['kind'], stage=rec['stage'], round=rec['round'], club_rounds=negotiate.CLUB_ROUNDS,
                log=rec['log'], fee=rec.get('fee'), buy=rec.get('buy'), last_counter=rec.get('last_counter'), tone=rec.get('mood'),
                stance=T['stance'], end_s=T['end_s'], wage_now=T['wage_now'], committed=T['committed'], budget=T['budget'], mv=T['mv'],
                option=dict(wage=T['option']['wage'], release=T['option']['release'], end_s=T['option']['end_s']) if rec['kind'] == 'option' else None,
                locked_until=rec.get('lock_until') and _fmt_date(rec['lock_until']),
                waiting=(_fmt_due(rec['pending']['due']) if rec.get('pending') else None), terms=rec.get('terms'), p_round=rec.get('p_round', 0),
                p_last=rec.get('p_last'), half_ok=(_date_tuple(s.game_date_code())[1] >= 7), half_end=_fmt_date(_loan_end(s, True)), roles=list(negotiate.ROLES),
                dem=rec.get('dem'), today=_fmt_due(s.game_date_code()))


def lneg_start(body):
    slot, pid, kind = body['slot'], int(body['pid']), body.get('kind', 'plain')
    if kind not in ('plain', 'option'):
        raise ValueError('invalid loan type')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    reg_check(slot, s, pid)
    if pid in {x['pid'] for x in s.list_deals()} or pid in s.my_squad_tags():
        raise ValueError('player is already in your club or has a deal')
    if pid in _moved(slot, s):
        raise ValueError('player has already changed clubs in this transfer window')
    if s._squad_len(s.club_offset()) >= 40:
        raise ValueError('squad is full (40)')
    st = _lneg_store()
    T = _loan_in_terms(slot, pid)
    if T['stance']['kind'] == 'refuse':
        return _lneg_view(slot, pid, dict(stage='refused', kind=kind, round=0, log=[dict(who='club', decision='stance', why=T['stance']['why'])], mood=None), T, s)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    rec = st.get(slot, pid)
    try:
        _cid = _career_id(slot, s)
    except Exception:
        _cid = None
    if rec and rec['stage'] != 'dead' and _neg_expired(rec, gd, _cid):
        rec = None
    if rec and rec['stage'] == 'dead' and _cmp_date(gd, rec.get('lock_until', 0)) < 0:
        return _lneg_view(slot, pid, rec, T, s)
    if rec and rec['stage'] in ('club', 'player', 'ready') and (rec['kind'] == kind or rec['stage'] != 'club'):
        if _lneg_tick(slot, pid, rec, s):
            st.put(slot, pid, rec)
        return _lneg_view(slot, pid, rec, T, s)
    rec = dict(stage='club', kind=kind, round=0, log=[], mood=negotiate.club_mood(slot, pid, 'loan-%d-%d-%s' % (y, m, kind)), date=gd, career=_cid)
    st.put(slot, pid, rec)
    return _lneg_view(slot, pid, rec, T, s)


def lneg_offer(body):
    slot, pid = body['slot'], int(body['pid'])
    fee, buy = int(body.get('fee') or 0), int(body.get('buy') or 0)
    st = _lneg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'club':
        raise ValueError('negotiation is not open')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    T = _loan_in_terms(slot, pid)
    if fee <= 0 or (rec['kind'] == 'option' and buy <= 0):
        raise ValueError('invalid offer')
    if rec['kind'] == 'plain':
        buy = 0
    if T['stance']['kind'] == 'refuse':
        raise ValueError(T['stance']['why'])
    if fee > T['budget']:
        raise ValueError('Not enough transfer budget for this offer.')
    rec['round'] += 1
    rec['log'].append(dict(who='you', fee=fee, buy=buy))
    ask = _lneg_asks(T, rec['kind'], rec['mood'])
    lc = rec.get('last_counter')
    if lc and fee >= lc['fee'] and buy >= lc['buy']:
        r = dict(decision='accept', counter=None, hint='hot')
    else:
        r = negotiate.loan_reply(ask, fee, buy, rec['mood'], rec['round'])
    ent = dict(who='club', decision=r['decision'], hint=r.get('hint'), counter=r.get('counter'))
    rec['log'].append(ent)
    if r['decision'] == 'accept':
        rec.update(stage='player', fee=fee, buy=buy, p_round=0)
        ctx = neg_context(slot, pid)
        rec['dem'] = persona.demanded_role(persona.squad_rank(ctx['my'], ctx['f']['ovr']), ctx['f']['age'])
        rec['log'].append(dict(who='player', ev='loan_hesitant', dem=rec['dem'], d=_fmt_date(s.game_date_code())))
    elif r['decision'] == 'counter':
        rec['last_counter'] = r['counter']
    elif r['decision'] == 'walk':
        rec['stage'] = 'dead'
        rec['lock_until'] = _add_days(s.game_date_code(), negotiate.LOCK_DAYS)
    st.put(slot, pid, rec)
    return _lneg_view(slot, pid, rec, T, s)


LOAN_P_ROUNDS = 3


def _lneg_eval(slot, pid, rec, ctx, role, length, bonus):
    """Igrac vaze uvjete posudbe: minute (obecana uloga), trajanje, bonus za lojalnost. -> (odluka, sto trazi, razlozi)"""
    f = ctx['f']
    ptr = persona.traits(pid)
    ap = persona.appeal(f, ptr, ctx['my'], ctx['cur_str'], ctx['my_str'], role, ctx['crowd'])
    dem = ap['dem']
    want_bonus = negotiate.rnd100(max(10000, (f['sal'] or 0) * (0.04 + 0.12 * ptr['money'])), 1000)
    tot = ap['score'] + 0.1
    if length == 'full':
        tot += 0.08 if f['age'] <= 23 else 0.02
    else:
        tot += 0.06 if negotiate.ROLES.index(role) > negotiate.ROLES.index(dem) else -0.04
    tot += min(0.25, 0.25 * bonus / float(want_bonus)) if want_bonus else 0
    rnd_no = rec.get('p_round', 0)
    if ap['score'] < persona.REFUSE - 0.1:
        return 'refuse', None, ap['neg'][:2] or ['step_down']
    if tot >= 0.15 or (rnd_no >= LOAN_P_ROUNDS and tot >= 0.02):
        return 'accept', None, []
    if rnd_no >= LOAN_P_ROUNDS or tot < -0.3:
        return 'refuse', None, ap['neg'][:2] or ['minutes']
    want = {}
    if negotiate.ROLES.index(role) > negotiate.ROLES.index(dem):
        want['role'] = dem
    if bonus < want_bonus:
        want['bonus'] = want_bonus
    if length == 'half' and f['age'] <= 23:
        want['length'] = 'full'
    if not want:
        want['bonus'] = negotiate.rnd100(max(bonus * 1.3, want_bonus), 1000)
    return 'counter', want, ap['neg'][:2]


def lneg_terms(body):
    """Razgovor s igracem o posudbi: uloga, trajanje (half/full), bonus za lojalnost (EUR iz transfer budzeta)."""
    slot, pid = body['slot'], int(body['pid'])
    role, length, bonus = body.get('role', 'starter'), body.get('length', 'full'), max(0, int(body.get('bonus') or 0))
    if role not in negotiate.ROLES or length not in ('half', 'full'):
        raise ValueError('invalid terms')
    st = _lneg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'player':
        raise ValueError('talks with the player are not open')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if rec.get('pending'):
        raise ValueError('The player asked for time to think (answer by %s).' % _fmt_due(rec['pending']['due']))
    if length == 'half' and _date_tuple(s.game_date_code())[1] < 7:
        raise ValueError('A half-season loan is only possible in the summer window.')
    if (rec.get('fee') or 0) + bonus > s.budget():
        raise ValueError('Not enough transfer budget for the fee plus the bonus.')
    T = _loan_in_terms(slot, pid)
    rec['p_round'] = rec.get('p_round', 0) + 1
    gd = s.game_date_code()
    rec['log'].append(dict(who='you', ev='loan_terms', role=role, length=length, bonus=bonus, d=_fmt_date(gd)))
    r = nego2.rng('lthink', slot, pid, rec['p_round'])
    if r.random() < 0.3 and rec['p_round'] < LOAN_P_ROUNDS:
        due = _due(gd, 1)
        if _cmp_date(due, gd) > 0:
            rec['pending'] = dict(kind='player', due=due, role=role, length=length, bonus=bonus)
            rec['log'].append(dict(who='player', ev='loan_think', until=_fmt_due(due), d=_fmt_date(gd)))
            st.put(slot, pid, rec)
            return _lneg_view(slot, pid, rec, T, s)
    _lneg_resolve(slot, pid, rec, s, role, length, bonus)
    st.put(slot, pid, rec)
    return _lneg_view(slot, pid, rec, T, s)


def _lneg_resolve(slot, pid, rec, s, role, length, bonus):
    ctx = neg_context(slot, pid)
    dec, want, why = _lneg_eval(slot, pid, rec, ctx, role, length, bonus)
    d = _fmt_date(s.game_date_code())
    if dec == 'accept':
        rec['log'].append(dict(who='player', ev='loan_accept', role=role, length=length, bonus=bonus, d=d))
        rec.update(stage='ready', terms=dict(role=role, length=length, bonus=bonus))
    elif dec == 'counter':
        rec['p_last'] = want
        rec['log'].append(dict(who='player', ev='loan_counter', want=want, why=why, d=d))
    else:
        rec['log'].append(dict(who='player', ev='loan_refuse', why=why, d=d))
        rec['stage'] = 'dead'
        rec['lock_until'] = _add_days(s.game_date_code(), negotiate.LOCK_DAYS)


def _lneg_tick(slot, pid, rec, s):
    pe = rec.get('pending')
    if not pe or _cmp_date(s.game_date_code(), pe['due']) < 0:
        return False
    rec.pop('pending', None)
    _lneg_resolve(slot, pid, rec, s, pe['role'], pe['length'], pe['bonus'])
    return True


LQ_FILE = os.path.join(HERE, 'data', 'loan_queue.json')


def _lq_all():
    try:
        return json.load(open(LQ_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _lq_key(slot, s):
    try:
        return _career_id(slot, s)
    except Exception:
        return slot


def _lq_add(slot, s, item):
    a = _lq_all()
    L = a.setdefault(_lq_key(slot, s), [])
    L[:] = [x for x in L if x.get('pid') != item['pid']]
    L.append(dict(item, queued=time.strftime('%Y-%m-%d %H:%M'), date=_fmt_date(s.game_date_code())))
    _jdump(a, LQ_FILE, ensure_ascii=False, indent=1)


def _lq_drop(slot, s, pid):
    a = _lq_all()
    k = _lq_key(slot, s)
    a[k] = [x for x in a.get(k, []) if x.get('pid') != pid]
    _jdump(a, LQ_FILE, ensure_ascii=False, indent=1)


def loan_queue_view(slot, s=None):
    """pc153: posudbe koje cekaju svoj red. Igra u jednom danu izvrsi samo jedan dolazak, a ostale app-ove dogovore obrise
    (lista dogovora za izvrsenje se isprazni: Saibari/Mendy 21.8., Bonny 22.8. na ML4 28.10.) -> app upisuje jednu po jednu."""
    try:
        s = s or mlwrite.Save(slot_folder(slot), ro=True)
        L = _lq_all().get(_lq_key(slot, s), [])
        waiting = s.loans_waiting()
    except Exception:
        return dict(items=[], ready=False, waiting=[])
    for x in L:
        x['name'] = NAMES.get(x['pid'], str(x['pid']))
    return dict(items=L, ready=bool(L) and not waiting, waiting=[NAMES.get(p, str(p)) for p in waiting])


def loan_queue_run(body):
    """Upisi sljedecu posudbu iz reda (kad prethodna stigne)."""
    slot = body['slot']
    s = mlwrite.Save(slot_folder(slot), ro=True)
    V = loan_queue_view(slot, s)
    if not V['items']:
        raise ValueError('no loans are waiting in the queue')
    if not V['ready']:
        raise ValueError('%s has not arrived yet: simulate a day in the game first.' % ', '.join(V['waiting']))
    it = V['items'][0]
    try:
        if it.get('src') == 'lneg':
            r = lneg_finish(dict(slot=slot, pid=it['pid'], _from_queue=True))
        else:
            r = loan_in_do(dict(slot=slot, pid=it['pid'], kind=it.get('kind', 'plain'), _from_queue=True))
    except ValueError as ex:
        if 'already' not in str(ex) and 'game is running' not in str(ex):
            _lq_drop(slot, s, it['pid'])    # vise nije moguce (rok, budzet, igrac otisao): makni iz reda i javi
        raise
    _lq_drop(slot, s, it['pid'])
    return r


def loan_queue_drop(body):
    slot = body['slot']
    s = mlwrite.Save(slot_folder(slot), ro=True)
    _lq_drop(slot, s, int(body['pid']))
    return loan_queue_view(slot, s)


def _lq_should_queue(s, pid, body):
    """Treba li posudbu staviti u red umjesto upisa: vec ceka druga app/igra posudba (samo prosireni format)."""
    if body.get('multi') or body.get('_from_queue'):
        return False
    try:
        w = s.loans_waiting()
    except Exception:
        return False
    return bool(w) and pid not in w


def lneg_finish(body):
    slot, pid = body['slot'], int(body['pid'])
    st = _lneg_store()
    rec = st.get(slot, pid)
    if not rec or rec['stage'] != 'ready':
        raise ValueError('negotiation is not finished')
    s = mlwrite.Save(slot_folder(slot))
    if pid in {x['pid'] for x in s.list_deals()} or pid in s.my_squad_tags():
        raise ValueError('player is already in your club or has a deal')
    if pid in _moved(slot, s):
        raise ValueError('player has already changed clubs in this transfer window')
    if s._squad_len(s.club_offset()) >= 40:
        raise ValueError('squad is full (40)')
    T = _loan_in_terms(slot, pid)
    fee = rec['fee']
    if fee > T['budget']:
        raise ValueError('Not enough transfer budget for this offer.')
    # posudba ne trosi salary budget u igri (potvrdio korisnik 27.10.), placa se samo naknada iz transfer budzeta
    opt = None
    if rec['kind'] == 'option':
        opt = dict(buy=rec['buy'], wage=T['option']['wage'], release=negotiate.rnd100(rec['buy'] * 1.14, 100), end=T['option']['end'])
    tm = rec.get('terms') or {}
    end_ = _loan_end(s, True) if tm.get('length') == 'half' else T['end']
    lbonus = int(tm.get('bonus') or 0)
    if fee + lbonus > T['budget']:
        raise ValueError('Not enough transfer budget for the fee plus the bonus.')

    if _lq_should_queue(s, pid, body):
        _lq_add(slot, s, dict(pid=pid, src='lneg', kind=rec['kind'], fee=fee, club=T['club']))
        rec['queued'] = True
        st.put(slot, pid, rec)
        return dict(ok=True, queued=True, message='%s: loan agreed (fee %d EUR). Another loan is still waiting to arrive, and the game only completes one per day, so this one is queued. After the next day in the game the app writes it.' % (T['name'], fee))

    def _fn(sv):
        r_ = sv.loan_in_pending(pid, fee, end_, option=opt)
        if lbonus:
            sv.adjust_budget(-lbonus)
        return r_
    r = _write_slot(slot, 'loan_in', _fn, pid=pid)
    _mark_moved(slot, s, pid)
    T['end_s'] = _fmt_date(end_)
    try:
        _lp_add(slot, s, pid, fee, lbonus, T['club'], (r or {}).get('backup') if isinstance(r, dict) else None)
    except Exception as ex:
        print('[loanpend]', ex)
    try:
        if tm.get('role') in ('key', 'starter'):
            promise_add(slot, s, pid, tm['role'])
    except Exception:
        pass
    rec['stage'] = 'done'
    st.put(slot, pid, rec)
    try:
        _ev_add(slot, 'signed', pid, frm=T['club'], fee=fee, wage=0, years=0, until=T['end_s'], loan=True, option=(rec['buy'] if opt else 0), opt=(dict(wage=opt['wage'], release=opt['release'], end_s=T['option']['end_s']) if opt else None))
    except Exception:
        pass
    return dict(ok=True, message='%s: loan agreed until %s, fee %d EUR%s. Load the save in the game and simulate ONE day: then the player arrives.' % (T['name'], T['end_s'], fee, (', opcija otkupa %d EUR' % rec['buy']) if opt else ''), detail=r)


def loan_do(body):
    """Izvrsi ponudu za posudbu (bez opcije otkupa): igrac odlazi u klub, naknada u budzet, vlasnik ostaje."""
    slot, pid, off = body['slot'], int(body['pid']), int(body['off'])
    s = mlwrite.Save(slot_folder(slot))
    if pid in s.loaned_in_pids():
        raise ValueError(LOANED_MSG)
    if pid in _moved(slot, s):
        raise ValueError('player has already changed clubs in this transfer window')
    y, m, _ = _date_tuple(s.game_date_code())
    mk = _sell_mk(s.game_date_code())
    live, _ = read_dump()
    lv = (live or {}).get(pid) or {}
    e = _tl_norm(_tl_slot(slot).get(str(pid), dict(tl=False, loan=False)))
    if not e['loan']:
        raise ValueError('player is not on the loan list')
    o = next((x for x in _loan_offers_for(slot, s, mk, pid, lv, e) if x['off'] == off), None)
    if not o:
        raise ValueError('offer no longer exists, refresh')
    if o['will'] == 'reluctant' and not body.get('force'):
        raise ValueError('The player is not thrilled; confirm again.')
    if True:
        # Svi formati: app upisuje stanje 'dogovoreno' kao nakon prihvacene ponude u igri (izmjereno na 45 MB, Zehnter -> Valencia;
        # klasicni format koristi iste tablice kao dolazna posudba). Odlazak izvrsi igra sljedeci dan.
        # Stari put (ponuda koju prihvacas u igri) postoji samo na 45 MB (inject_loan_offer).
        if body.get('via_offer') and s.ext:
            r = _write_slot(slot, 'loan_offer', lambda sv: sv.inject_loan_offer(pid, off, o['fee'], o['end']))
            _ev_add(slot, 'loan_offer', pid, to=o['club'], fee=o['fee'], until=o['end_s'])
            r = dict(r) if isinstance(r, dict) else dict(ok=True)
            r['message'] = ('The offer from %s was sent to the game. In the game open Transfers > Team Negotiations, find %s and accept the offer: ' 'the game completes the loan.' % (o['club'], NAMES.get(pid, str(pid))))
            return r
        r = _write_slot(slot, 'loan', lambda sv: sv.loan_out_pending(pid, off, o['fee'], o['end']))
        _mark_moved(slot, s, pid)
        _ev_add(slot, 'loaned', pid, to=o['club'], fee=o['fee'], until=o['end_s'])
        r = dict(r) if isinstance(r, dict) else dict(ok=True)
        r['message'] = ('Loan to %s agreed (fee is already in the budget). %s leaves after the next day in the game; ' 'until then you see him in Team Negotiations in the game.' % (o['club'], NAMES.get(pid, str(pid))))
        return r
    r = _write_slot(slot, 'loan', lambda sv: sv.sell_player(pid, o['fee'], off, POS, loan_end=o['end']))
    _mark_moved(slot, s, pid)
    _ev_add(slot, 'loaned', pid, to=o['club'], fee=o['fee'], until=o['end_s'])
    return r


def _loan_offers_for(slot, s, mk, pid, lv, e):
    """Ponude za posudbu tvog igraca (lista posudbi u appu). Deterministicno po (slot, igrac, mjesec). Izvrsenje u savu jos nije dekodirano."""
    ovr, age = rat(pid)
    if not ovr:
        return []
    r = negotiate._rng('loan', slot, pid, mk)
    tiers = _club_tiers(slot, s)
    fins = _club_fin(slot, s)
    wage = _wages(slot, s).get(pid, 0)
    mv = lv.get('mv') or negotiate.estimate_value(ovr, age or 22)
    ptr = persona.traits(pid)
    _mo = [rat(q)[0] for q in s.my_squad_tags() if rat(q)[0]]
    rk = persona.squad_rank(_mo, ovr)
    names = {}
    pool = []
    for c in s.ai_clubs():
        ci = (c[0] - mlwrite.REC0) // mlwrite.STRIDE
        t = tiers.get(ci)
        if t is None:
            continue
        # klub u kojem bi igrao: nesto slabiji ili slican, ali ne puno slabiji
        if ovr - 12 <= t[1] <= ovr + 2:
            shm = (e.get('loan_share') if e and e.get('loan_share') is not None else 100) / 100.0
            if wage * max(0.5, shm) > (fins.get(ci) or {}).get('wres', 1e18):
                continue                                  # klub ne moze platiti ni polovicu place
            pool.append((c, ci, t))
    out = []
    for _ in range(r.choice([1, 2, 2]) if pool else 0):
        c, ci, t = pool.pop(r.randrange(len(pool)))
        sh = (e.get('loan_share') if e and e.get('loan_share') is not None else 100) / 100.0
        share_pay = r.choice([0.5, 0.75, 1.0])
        if share_pay < sh:
            share_pay = min(1.0, sh)           # klub placa najmanje koliko trazis
        wres = (fins.get(ci) or {}).get('wres', 1e18)
        if wage * share_pay > wres:
            share_pay = max(sh, 0.5)
            if wage * share_pay > wres:
                continue
        fee = negotiate.rnd100(mv * r.uniform(0.08, 0.28), 100)      # u igri naknada posudbe ~25-40% vrijednosti
        buy = None                                                    # opcija otkupa zasad nije podrzana (nema uzorka iz igre)
        half = r.random() < 0.5
        bench_here = rk >= 11
        plays = ovr >= t[1] - 3
        will = 'willing' if (bench_here and plays) else ('reluctant' if not bench_here else 'willing')
        out.append(dict(pid=pid, off=c[0], club=c[1], share=int(share_pay * 100), fee=fee, buy=buy, will=will, end=_loan_end(s, half), end_s=_fmt_date(_loan_end(s, half)),
                        pro=(['minutes_ok'] if bench_here and plays else []), why=([] if bench_here else ['minutes'])))
    return out


TIER_CAP = {'big': None, 'mid': 45_000_000, 'small': 9_000_000}   # najvisa naknada koju klub te razine ponudi (EUR)
_TIERS = {}


_FIN = {}


def _club_fin(slot, s):
    """idx kluba -> dict(budget EUR (pocetni budzet iz sava), wres EUR (rezerva place = SAL_RESERVE zbroja placa)); kesirano po savu."""
    key = (slot, len(s.d), bytes(s.d[0:64]))
    c = _FIN.get(slot)
    if c and c[0] == key:
        return c[1]
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    clubs = _tier_clubs(s, my)
    w = s.player_wages()
    out = {}
    for i, cl in clubs.items():
        b0 = struct.unpack_from('<I', s.d, mlwrite.REC0 + mlwrite.STRIDE * i + 1600)[0]
        out[i] = dict(budget=(b0 * 100 if 0 < b0 < 0xFFFFFFFF else None),
                      wres=aitransfers.SAL_RESERVE * sum(w.get(p['pid'], 0) for p in cl['players']))
    _FIN[slot] = (key, out, w)
    return out


def _wages(slot, s):
    _club_fin(slot, s)
    return _FIN[slot][2]


def _club_tiers(slot, s):
    """idx kluba -> (razina, snaga); kesirano po savu."""
    key = (slot, len(s.d), bytes(s.d[0:64]))
    c = _TIERS.get(slot)
    if c and c[0] == key:
        return c[1]
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    clubs = _tier_clubs(s, my)
    out = {i: (c['tier'], c['strength']) for i, c in clubs.items()}
    _TIERS[slot] = (key, out)
    return out


def _my_nation(s):
    """pc300: reprezentacija koju menadzer vodi uz klub (igra: ponuda reprezentacije prihvacena). Zapis momcadi s kontrolorom 0 (+0x41d)
    koji je reprezentacija (iza granice klubova ili u skupu reprezentacija). -> indeks ili None."""
    try:
        lim, nat = mlsave.club_layout(s.d)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        for ref in range(2400):
            o = 80 + ref * 1680
            if o + 0x41e > len(s.d):
                break
            k = struct.unpack_from('<I', s.d, o)[0]
            if k == 0xffffffff:
                continue
            if (k & 0x3fff) != ref:
                break
            if ref == my or not (ref >= lim or ref in nat):
                continue
            if s.d[o + 0x41d] == 0 and seasonstats.club_name(s.d, ref):
                return ref
    except Exception:
        return None
    return None


def _nation_fixtures(s, M, gd=None):
    """Utakmice moje reprezentacije iz rasporeda (iste tablice kao klupske). -> (ime, [dict])"""
    nat = _my_nation(s)
    if nat is None:
        return None, []
    cn = lambda ci: seasonstats.club_name(s.d, ci)
    out = []
    for m in sorted([m for m in M['matches'] if nat in (m['home'], m['away']) and m['home'] != m['away']], key=seasonstats.sort_key):
        home = m['home'] == nat
        oi = m['away'] if home else m['home']
        if not cn(oi):
            continue
        r = dict(y=m['y'], m=m['m'], d=m['dd'], date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']), tid=m['tid'], home=home, opp=cn(oi), opp_idx=oi,
                 played=bool(m['played']), nat=cn(nat))
        if m['played']:
            gh = seasonstats.match_score(m)[0]
            ga = seasonstats.match_score(m)[1]
            gf, gaa = (gh, ga) if home else (ga, gh)
            r.update(gf=gf, ga=gaa, res='W' if gf > gaa else ('L' if gf < gaa else 'D'))
        out.append(r)
    return cn(nat), out


def next_match(slot):
    """Sljedeca utakmica izravno iz rasporeda u save-u (datumi, natjecanje, domaci/gost); Sider telemetrija samo kao rezerva."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    club_limit, national_clubs = mlsave.club_layout(s.d)   # pc256 (tester 60 MB, Report 06): klubovi iznad 750 (PAOK u SL2: 2 -> 30 utakmica)
    def _ok(m):   # prazni/smeceni zapisi rasporeda (isti klub s obje strane, indeksi izvan klubova, bez imena)
        return (m['home'] != m['away'] and 0 <= m['home'] < club_limit and 0 <= m['away'] < club_limit and m['home'] not in national_clubs and m['away'] not in national_clubs
                and seasonstats.club_name(s.d, m['home']) and seasonstats.club_name(s.d, m['away']))
    mm = sorted([m for m in M['matches'] if my in (m['home'], m['away']) and _ok(m)], key=seasonstats.sort_key)
    played = [m for m in mm if m['played']]
    if not played and not mm:
        return next_match_tel(slot)
    cur_season = played[-1]['season'] if played else mm[0]['season']
    try:
        gc = s.game_date_code()
        gd = (gc & 0xffff, (gc >> 16) & 0xff, gc >> 24)
    except Exception:
        gd = None
    # pc236: nova sezona (1.7.) jos bez odigrane utakmice: sezona iz datuma igre, ne iz starih zapisa rasporeda
    if gd:
        _gs = gd[0] if gd[1] >= 7 else gd[0] - 1
        if any(m['season'] == _gs for m in mm) and (not played or played[-1]['season'] < _gs):
            cur_season = _gs
    fut = [m for m in mm if not m['played'] and m['season'] == cur_season and (gd is None or (m['y'], m['m'], m['dd']) >= gd)]
    if not fut:
        return next_match_tel(slot)
    ids = {}
    try:
        ids = json.load(open(_dbf('teamids.json'), encoding='utf-8'))
    except Exception:
        pass
    cnt = {}
    for m in mm:
        if m['season'] == cur_season:
            cnt[m['tid']] = cnt.get(m['tid'], 0) + 1
    league = max(cnt, key=lambda k: cnt[k]) if cnt else None
    # Match Calendar's same-day conflict policy; first cup/European games have no played history yet.
    real = {m['tid'] for m in played if m['season'] == cur_season}
    real.add(league)
    known_days = {(m['y'], m['m'], m['dd']) for m in mm
                  if m['season'] == cur_season and m['tid'] in real}
    fut = [m for m in fut if m['tid'] in real or (m['y'], m['m'], m['dd']) not in known_days] or fut
    _fg = _foreign_tids(s, {m['tid'] for m in fut} - real, M, cur_season)
    fut = [m for m in fut if m['tid'] not in _fg] or fut
    # pc304: natjecanje s neodigranom utakmicom u proslosti je zaostali zapis u saveu (Brentford: br. 14 s Real Oviedom 23.6., 1.7., 21.8. ... nijednom odigrano)
    if gd:
        _st = {m['tid'] for m in mm if m['season'] == cur_season and not m['played'] and m['tid'] != league and (m['y'], m['m'], m['dd']) < gd}
        fut = [m for m in fut if m['tid'] not in _st] or fut
    def rnd(m):
        return len([x for x in mm if x['season'] == cur_season and x['tid'] == m['tid'] and sseq(x) < sseq(m)])
    def sseq(x):
        return seasonstats.sort_key(x)
    def fx(m):
        home = m['home'] == my
        oi = m['away'] if home else m['home']
        return dict(tournament=m['tid'], round=rnd(m), home=home, opp_idx=oi, opp=seasonstats.club_name(s.d, oi),
                    date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']))
    rows = [fx(m) for m in fut]
    nxt = rows[0]
    info = club_lineup_info(slot, nxt['opp_idx'])
    nat_name, nat_fx = _nation_fixtures(s, M, gd)
    nat_next = next((r for r in nat_fx if not r['played'] and (gd is None or (r['y'], r['m'], r['d']) >= gd)), None)
    return dict(club=seasonstats.club_name(s.d, my), played=len(played), league=league, next=nxt, opponent=info, fixtures=rows[:8], source='save', mine_recent=club_matches(slot, s, my, limit=5),
                nation=nat_name, nation_next=nat_next)


def calendar_view(slot):
    """Kalendar mog kluba za tekucu sezonu: sve utakmice (odigrane s rezultatom i buduce) iz rasporeda u save-u."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    club_limit, national_clubs = mlsave.club_layout(s.d)   # pc256 (tester 60 MB, Report 06)
    cn = lambda ci: seasonstats.club_name(s.d, ci)

    def _ok(m):
        return m['home'] != m['away'] and 0 <= m['home'] < club_limit and 0 <= m['away'] < club_limit and m['home'] not in national_clubs and m['away'] not in national_clubs and cn(m['home']) and cn(m['away'])
    mm = sorted([m for m in M['matches'] if my in (m['home'], m['away']) and _ok(m)], key=seasonstats.sort_key)
    gd = None
    try:
        gc = s.game_date_code()
        gd = (gc & 0xffff, (gc >> 16) & 0xff, gc >> 24)
    except Exception:
        pass
    season = None
    if gd:
        season = gd[0] if gd[1] >= 7 else gd[0] - 1
    seas = {m['season'] for m in mm}
    if season not in seas:
        pl = [m for m in mm if m['played']]
        season = pl[-1]['season'] if pl else (min(seas) if seas else None)
    mm = [m for m in mm if m['season'] == season]
    cnt = {}
    for m in mm:
        cnt[m['tid']] = cnt.get(m['tid'], 0) + 1
    league = max(cnt, key=lambda k: cnt[k]) if cnt else None
    real = {m['tid'] for m in mm if m['played']}
    real.add(league)
    # natjecanja bez ijedne odigrane utakmice (osim lige) su cesto duhovi u rasporedu: zadrzi ih samo ako imaju buducu utakmicu nakon danasnjeg datuma i nisu u istom danu kao liga
    rnd = {}
    out = []
    for m in mm:
        rnd[m['tid']] = rnd.get(m['tid'], 0) + 1
        home = m['home'] == my
        oi = m['away'] if home else m['home']
        r = dict(y=m['y'], m=m['m'], d=m['dd'], date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']), tid=m['tid'], round=rnd[m['tid']], home=home,
                 opp=cn(oi), opp_idx=oi, played=bool(m['played']), ghost=m['tid'] not in real)
        if m['played']:
            gh = seasonstats.match_score(m)[0]
            ga = seasonstats.match_score(m)[1]
            gf, gaa = (gh, ga) if home else (ga, gh)
            r.update(gf=gf, ga=gaa, res='W' if gf > gaa else ('L' if gf < gaa else 'D'))
        out.append(r)
    # duhovi koji padaju na isti dan kao prava utakmica se izbacuju
    days = {(r['y'], r['m'], r['d']) for r in out if not r['ghost']}
    out = [r for r in out if not r['ghost'] or (r['y'], r['m'], r['d']) not in days]
    _fg = _foreign_tids(s, {r['tid'] for r in out if r['ghost']}, M, season)   # pc277: zalutali zapisi natjecanja u koja klub nije prijavljen
    out = [r for r in out if not (r['ghost'] and r['tid'] in _fg)]
    if gd:   # pc304: natjecanje s neodigranom utakmicom u proslosti = zaostali zapisi (vidi next_match)
        _st = {r['tid'] for r in out if not r['played'] and r['tid'] != league and (r['y'], r['m'], r['d']) < gd}
        out = [r for r in out if r['tid'] not in _st]
    pos = {}
    try:
        for c in comps_view(slot).get('comps', []):
            if c.get('kind') == 'league' and c.get('rows'):
                for row in c['rows']:
                    pos.setdefault(row['club'], dict(pos=row['pos'], pts=row['pts'], n=len(c['rows']), lg=c['name']))
    except Exception:
        pass
    for r in out:
        r['opp_pos'] = pos.get(r['opp'])
    # pc300: utakmice reprezentacije koju vodis (iste sezone), oznacene s nat
    nat_name, nat_fx = _nation_fixtures(s, M, gd)
    if nat_fx and season is not None:
        lo, hi = (season, 7, 1), (season + 1, 6, 30)
        for r in nat_fx:
            if lo <= (r['y'], r['m'], r['d']) <= hi:
                rn = sum(1 for x in out if x.get('nat') and x['tid'] == r['tid']) + 1
                out.append(dict(r, round=rn, ghost=False, opp_pos=None))
        out.sort(key=lambda r: (r['y'], r['m'], r['d']))
    # pc300: imena natjecanja iz baze igre za sve tid-ove u kalendaru (prije: 'Competition #14' za ona koja app ne zna napamet)
    cnames = {}
    for t_ in {r['tid'] for r in out}:
        try:
            nm_ = COMP_LEAGUES.get(t_) or (COMP_GROUPS.get(t_) or [None, None])[1] or _reg_comp_name(t_)
        except Exception:
            nm_ = None
        if nm_:
            cnames[t_] = nm_
    return dict(club=cn(my), my_pos=pos.get(cn(my)), season=season, today=dict(y=gd[0], m=gd[1], d=gd[2]) if gd else None, league=league, matches=out,
                nation=nat_name, comp_names=cnames)


def next_match_tel(slot):
    """Sljedeca utakmica iz Sider telemetrije (raspored koji je igra iscrtala u ML-u) + moj klub iz save-a."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    tp = CFG.get('telemetry') or ''
    if not os.path.exists(tp):
        return dict(error='no telemetry.json (Sider module MLImmersion)')
    tel = json.load(open(tp, encoding='utf-8'))
    ids = json.load(open(_dbf('teamids.json'), encoding='utf-8'))
    name_to_tid = {v: int(k) for k, v in ids.items()}
    my = s.club_name()
    my_tid = name_to_tid.get(my) or name_to_tid.get(my + ' FC')
    mo = s.club_offset()
    played = s.d[mo + 747]
    clubs = {}
    _lim, _nat = mlsave.club_layout(s.d)   # pc186: i klubovi iznad 580 (prosirena baza)
    for n in range(_lim):
        if n in _nat:
            continue
        o = mlwrite.REC0 + n * mlwrite.STRIDE
        if o + mlwrite.STRIDE > len(s.d):
            break
        nm = bytes(s.d[o:o + 48]).split(b'\0')[0].decode('utf-8', 'replace')
        if nm:
            clubs.setdefault(nm, n)
    fx = [f for f in (tel.get('schedule_fixtures') or []) if my_tid in (f['home_team'], f['away_team'])]
    live = tel.get('fixture')
    if live and my_tid in (live['home_team'], live['away_team']) and not any(f['key'] == live['key'] for f in fx):
        fx.append(live)
    rows = []
    for f in sorted(fx, key=lambda f: (f['tournament_id'], f['match_info'])):
        home = f['home_team'] == my_tid
        opp = f['away_team'] if home else f['home_team']
        on = ids.get(str(opp), str(opp))
        idx = clubs.get(on)
        rows.append(dict(tournament=f['tournament_id'], round=f['match_info'], home=home, opp_id=opp,
                         opp=on, opp_idx=idx, date=f.get('date')))
    # liga = natjecanje s najvise unosa; sljedeca = kolo == odigrano
    from collections import Counter
    cnt = Counter(r['tournament'] for r in rows)
    league = cnt.most_common(1)[0][0] if cnt else None
    nxt = None
    for r in rows:
        if r['tournament'] == league and r['round'] >= played:
            nxt = r
            break
    info = None
    if nxt and nxt['opp_idx'] is not None:
        info = club_lineup_info(slot, nxt['opp_idx'])
    return dict(club=my, played=played, league=league, next=nxt, opponent=info, fixtures=rows,
                telemetry_time=tel.get('written_at'))


def club_lineup_info(slot, idx):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    o = mlwrite.REC0 + idx * mlwrite.STRIDE
    nm = bytes(s.d[o:o + 48]).split(b'\0')[0].decode('utf-8', 'replace')
    f, roles = s.club_formation(idx)
    ids = s.club_lineup(idx)
    names = {}
    try:
        names = {p[0]: p[2] for p in json.load(open(_dbf('players.json'), encoding='utf-8'))}
        pos = json.load(open(_dbf('positions.json')))
    except Exception:
        pos = {}
    def _ov(i):
        try:
            return rat(i)[0]
        except Exception:
            return None
    pl = [dict(id=i, name=names.get(i, str(i)), pos=pos.get(str(i)), ovr=_ov(i)) for i in ids]
    slots = [dict(role=r, x=x, y=y) for r, x, y in s.club_slots(idx)]
    _po = s.PLAN0 + 600 * idx
    fluid = bool(s.d[_po - 5 + FLUID_FLAG])   # pc173: prekidac Fluid Formation (prije: bajt izgradnje igre)
    presets = [dict(formation=q['formation'], slots=[dict(role=r, x=x, y=y) for r, x, y in q['slots']]) for q in s.club_presets(idx)]
    try:
        scout = scout_report(slot, s, idx, ids)
    except Exception as e:
        scout = dict(error=str(e))
    try:
        recent = club_matches(slot, s, idx, limit=5)
    except Exception:
        recent = []
    try:
        tac = s.club_tactics(idx)
        if tac:
            sq = s.club_squad_ids(idx) if hasattr(s, 'club_squad_ids') else []
            for a in tac['adv']:
                a['player_name'] = names.get(sq[a['player']]) if a.get('player') is not None and a['id'] in (8, 10, 15) and a['player'] < len(sq) else None
    except Exception as e:
        tac = None
    return dict(idx=idx, name=nm, formation=f, fluid=fluid, presets=presets, slots=slots, xi=pl[:11], bench=pl[11:18], scout=scout, recent=recent, tactics=tac,
                tac_changes=[l for l in ((auto_view().get(slot) or {}).get('tac') or {}).get('log', []) if l.get('idx') == idx][-3:])


_STATS = {}


def _season(slot, s):
    key = (slot, len(s.d), bytes(s.d[0:64]))
    c = _STATS.get(slot)
    if c and c[0] == key:
        return c[1]
    r = seasonstats.compute(s.d)
    _STATS[slot] = (key, r)
    return r


def _bench(M, club, m, starters):
    """Procjena klupe: ostatak sastava kluba (sadasnji igraci + oni koji su ove sezone nastupili za klub) minus početnih 11; najboljih 7 po OVR-u."""
    inv = M.get('_inv')
    if inv is None:
        inv = {}
        for pid, ci in M['cur'].items():
            inv.setdefault(ci, set()).add(pid)
        M['_inv'] = inv
    key = ('_seas', club, m['season'])
    seas = M.get(key)
    if seas is None:
        seas = set(seasonstats.agg(M, m['season'], club=club).keys())
        M[key] = seas
    ids = (inv.get(club, set()) | seas) - set(starters)
    srt = sorted(ids, key=lambda i: -rat(i)[0])
    gk = [i for i in srt if POS.get(i, 5) == 0][:1]
    out = gk + [i for i in srt if i not in gk][:7 - len(gk)]
    out.sort(key=lambda i: (POS.get(i, 5) != 0, -rat(i)[0]))
    return [dict(id=i, name=NAMES.get(i, str(i)), pos=POS.get(i, 5), ovr=rat(i)[0]) for i in out]


def club_matches(slot, s, club, season=None, limit=None, detail=False):
    """Odigrane utakmice kluba (najnovija prva): datum, natjecanje, protivnik, rezultat (zbroj golova igraca), strijelci i (detail) svi igraci."""
    M = _season(slot, s)
    d = s.d
    names = NAMES
    ms = [m for m in M['matches'] if m['played'] and club in (m['home'], m['away']) and (season is None or m['season'] == season)]
    ms.sort(key=seasonstats.sort_key, reverse=True)
    if limit:
        ms = ms[:limit]
    out = []
    for m in ms:
        home = m['home'] == club
        mine = [r for r in m['rows'] if r[1] == club]
        theirs = [r for r in m['rows'] if r[1] != club]
        gf, ga = seasonstats.match_score_for(m, club)
        opp = m['away'] if home else m['home']
        sc = sorted([r for r in mine if r[2] or r[3]], key=lambda r: (-r[2], -r[3]))
        e = dict(club=club, my=seasonstats.club_name(d, club), n=m['n'], date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']), tid=m['tid'], season=m['season'], home=home,
                 opp=seasonstats.club_name(d, opp), opp_idx=opp, gf=gf, ga=ga, res='W' if gf > ga else 'L' if gf < ga else 'D',
                 scorers=[dict(id=r[0], name=names.get(r[0], str(r[0])), g=r[2], a=r[3]) for r in sc])
        if detail:
            e['bench'] = _bench(M, club, m, [r[0] for r in mine][:11])
            e['opp_bench'] = _bench(M, opp, m, [r[0] for r in theirs][:11])
        if detail:
            e['players'] = [dict(id=r[0], name=names.get(r[0], str(r[0])), pos=POS.get(r[0], 5), g=r[2], a=r[3], rating=round(r[4], 1)) for r in mine]
            e['opp_players'] = [dict(id=r[0], name=names.get(r[0], str(r[0])), pos=POS.get(r[0], 5), g=r[2], a=r[3], rating=round(r[4], 1)) for r in theirs]
        out.append(e)
    return out


def scout_report(slot, s, idx, xi_ids):
    """Strukturirani izvjestaj o protivniku (tekst slaze frontend): snaga linija, kljucni igrac, prijetnje, slabosti."""
    ab = {n: i for i, n in enumerate(RATAB)} if RATAB else {}

    def att(pid, name):
        r = RAT.get(pid)
        return r[10][ab[name]] if r and name in ab else 0
    xi = [dict(id=i, name=NAMES.get(i, str(i)), pos=POS.get(i, 5), ovr=rat(i)[0]) for i in xi_ids[:11]]
    def avg(l):
        return round(sum(p['ovr'] for p in l) / len(l), 1) if l else None
    lines = dict(gk=avg([p for p in xi if p['pos'] == 0]), df=avg([p for p in xi if p['pos'] in (1, 2, 3)]),
                 mf=avg([p for p in xi if p['pos'] in (4, 5, 6, 7, 8)]), fw=avg([p for p in xi if p['pos'] in (9, 10, 11, 12)]))
    # moja najbolja 11 (GK + 10 najboljih)
    mine = [dict(pos=POS.get(i, 5), ovr=rat(i)[0]) for i in s.my_squad_tags()]
    g = sorted([p['ovr'] for p in mine if p['pos'] == 0], reverse=True)[:1]
    o = sorted([p['ovr'] for p in mine if p['pos'] != 0], reverse=True)[:10]
    my_avg = round(sum(g + o) / max(1, len(g + o)), 1)
    op_avg = avg(xi)
    diff = round(op_avg - my_avg, 1) if op_avg is not None else None
    level = None if diff is None else (5 if diff >= 3 else 4 if diff >= 1 else 3 if diff > -1.5 else 2 if diff > -3.5 else 1)
    # sezona: igraci koji su jos u klubu
    M = _season(slot, s)
    seas = seasonstats.played_seasons(M)
    season = None
    for se in reversed(seas):
        if any(m['played'] and m['season'] == se and idx in (m['home'], m['away']) for m in M['matches']):
            season = se
            break
    tot = {}
    form = {}
    if season is not None:
        tot = {p: x for p, x in seasonstats.agg(M, season, club=idx).items() if M['cur'].get(p) == idx}
        form = {p: x for p, x in seasonstats.agg(M, season, club=idx, last_ids=seasonstats.last_n(M, season, idx)).items() if M['cur'].get(p) == idx}
    sc = seasonstats.score
    def mk(pid, x, why):
        return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=rat(pid)[0], app=x['app'], g=x['g'], a=x['a'],
                    rating=round(x['rs'] / x['app'], 1) if x['app'] else None, why=why)
    key = None
    if tot:
        pid = max(tot, key=lambda k: sc(tot[k]))
        key = mk(pid, tot[pid], 'season')
    hot = None
    hc = [k for k in form if form[k]['app'] >= 2] or list(form)
    if hc:
        pid = max(hc, key=lambda k: sc(form[k]))
        if sc(form[pid]) > 0:
            hot = mk(pid, form[pid], 'form')
    best = max([p for p in xi if p['pos'] != 0], key=lambda p: p['ovr'], default=None)
    top_sc = max(tot, key=lambda k: (tot[k]['g'], tot[k]['a']), default=None)
    scorer = None
    if top_sc is not None and tot[top_sc]['g']:
        scorer = dict(id=top_sc, name=NAMES.get(top_sc, str(top_sc)), g=tot[top_sc]['g'], app=tot[top_sc]['app'])
    fast = max(xi, key=lambda p: att(p['id'], 'Speed'), default=None)
    fin = max([p for p in xi if p['pos'] >= 8], key=lambda p: att(p['id'], 'Finishing'), default=None)
    heads = max([p for p in xi if p['pos'] != 0], key=lambda p: att(p['id'], 'Heading') + att(p['id'], 'Jump'), default=None)
    defs = [p for p in xi if p['pos'] in (1, 2, 3)]
    slow = min(defs, key=lambda p: att(p['id'], 'Speed'), default=None)
    weak = min([p for p in xi if p['pos'] != 0], key=lambda p: p['ovr'], default=None)
    def tag(p, nm):
        return dict(id=p['id'], name=p['name'], pos=p['pos'], v=att(p['id'], nm)) if p else None
    # forma kluba
    o_ = mlwrite.REC0 + idx * mlwrite.STRIDE
    played, pts = s.d[o_ + 747], s.d[o_ + 746]
    wide = sum(1 for r, x, y in s.club_slots(idx) if r in (2, 3, 6, 7, 9, 10))
    nd = sum(1 for r, x, y in s.club_slots(idx) if r == 4)
    nf = sum(1 for r, x, y in s.club_slots(idx) if r in (9, 10, 11, 12))
    return dict(op_avg=op_avg, my_avg=my_avg, diff=diff, level=level, lines=lines, key=key, hot=hot, best=dict(id=best['id'], name=best['name'], pos=best['pos'], ovr=best['ovr']) if best else None,
                scorer=scorer, fast=tag(fast, 'Speed'), finisher=tag(fin, 'Finishing'), aerial=tag(heads, 'Heading'),
                slow_def=tag(slow, 'Speed'), weak=dict(id=weak['id'], name=weak['name'], pos=weak['pos'], ovr=weak['ovr']) if weak else None,
                played=played, pts=pts, wide=wide, dmf=nd, fwd=nf)


SD_ATTR = ['Speed', 'Acceleration', 'Finishing', 'Heading', 'Jump', 'Stamina', 'PhysicalContact', 'Dribbling', 'LowPass', 'LoftedPass',
           'DefensiveAwareness', 'BallWinning', 'Aggression', 'OffensiveAwareness', 'BallControl', 'KickingPower', 'PlaceKicking', 'Curl', 'Balance',
           'GKAwareness', 'GKCatching', 'GKReflexes', 'GKReach']


def _sd_p(pid, role, x, y, ab):
    r = RAT.get(pid)
    a = {}
    if r:
        for n in SD_ATTR:
            if n in ab:
                a[n] = r[10][ab[n]]
    return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=role, ovr=(r[0] if r else 0), age=(r[1] if r else None),
                h=(r[2] if r else None), foot=('L' if r and r[4] == 'True' else 'R'), x=x, y=y, a=a)


def scout_deep(slot):
    """Detaljna analiza sljedeceg protivnika: igraci s atributima, usporedba linija s tvojom postavom, dvoboji po bokovima, prijetnje iz zraka/slobodnjaci."""
    nm = next_match(slot)
    n = nm.get('next') or {}
    oi = n.get('opp_idx')
    if oi is None:
        return dict(error='no opponent')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    ab = {k: i for i, k in enumerate(RATAB)} if RATAB else {}
    ids = s.club_lineup(oi)
    slots = s.club_slots(oi)
    opp = []
    if ids:
        opp.append(_sd_p(ids[0], 0, 52, 0, ab))
    for i, (r, x, y) in enumerate(slots):
        if i + 1 < len(ids):
            opp.append(_sd_p(ids[i + 1], r, x, y, ab))
    bench = [_sd_p(p, POS.get(p, 5), 0, 0, ab) for p in ids[11:18]]
    # moja postava (kickoff formacija)
    sq = s.squad_ids()
    lu = s.lineup()
    idx2id = {i: p for i, p in enumerate(sq) if p}
    my_ids = [idx2id.get(i) for i in lu[:11]]
    rows = rows_json(s, 0)
    # kod tvoje formacije je 'y' bok (mali = lijevo), a 'x' dubina; kod protivnika obrnuto (x bok, veliki = njihova lijeva), zato bok = rows y
    mine = [_sd_p(pid, rows[i]['pos'], rows[i]['y'], rows[i]['x'], ab) for i, pid in enumerate(my_ids) if pid]
    for p in mine:   # moj GK je uvijek prvi u formaciji
        pass

    def tl(l, k):
        v = [p['a'].get(k) for p in l if p['a'].get(k) is not None]
        return round(sum(v) / len(v), 1) if v else None
    defs = lambda l: [p for p in l if p['pos'] in (1, 2, 3)]
    mids = lambda l: [p for p in l if p['pos'] in (4, 5, 6, 7, 8)]
    fwds = lambda l: [p for p in l if p['pos'] in (9, 10, 11, 12)]
    gks = lambda l: [p for p in l if p['pos'] == 0]
    avg_o = lambda l: round(sum(p['ovr'] for p in l) / len(l), 1) if l else None

    def team(l):
        return dict(ovr=avg_o(l), gk=avg_o(gks(l)), df=avg_o(defs(l)), mf=avg_o(mids(l)), fw=avg_o(fwds(l)),
                    spd_df=tl(defs(l), 'Speed'), spd_fw=tl(fwds(l) + [p for p in l if p['pos'] in (6, 7, 8)], 'Speed'),
                    sta=tl([p for p in l if p['pos'] != 0], 'Stamina'), phy=tl([p for p in l if p['pos'] != 0], 'PhysicalContact'),
                    air_df=tl(defs(l), 'Heading'), h_df=round(sum(p['h'] or 0 for p in defs(l)) / max(1, len(defs(l))), 1),
                    pas_mf=tl(mids(l), 'LowPass'), drb=tl(fwds(l), 'Dribbling'), fin=tl(fwds(l), 'Finishing'), age=round(sum(p['age'] or 0 for p in l) / max(1, len(l)), 1))

    def nearest(p, pool, mirror=False):   # x je kod protivnika zrcalan u odnosu na tvoj (njihov veliki x = njihova lijeva), pa bez zrcaljenja lijevo krilo ide na njihovog desnog beka
        tx = 104 - p['x'] if mirror else p['x']
        c = [q for q in pool if q['pos'] != 0]
        return min(c, key=lambda q: (abs(q['x'] - tx) + abs(q['y'] - (46 - p['y'])) * 0.2), default=None)
    att_roles = (6, 7, 8, 9, 10, 11, 12)
    threats = sorted([p for p in opp if p['pos'] in att_roles], key=lambda p: -p['ovr'])[:5]
    duels = []
    for p in threats:
        pool = {12: (1, 4), 11: (1, 4), 9: (2, 3), 10: (2, 3), 8: (4, 5, 1), 6: (2, 3, 5, 6, 7), 7: (2, 3, 5, 6, 7)}.get(p['pos'], (1, 2, 3, 4))
        q = nearest(p, [m for m in mine if m['pos'] in pool] or [m for m in mine if m['pos'] in (1, 2, 3, 4)])
        if q:
            duels.append(dict(opp=p, mine=q))
    chances = []
    my_att = sorted([m for m in mine if m['pos'] in att_roles], key=lambda p: -p['ovr'])[:4]
    for p in my_att:
        pool = {12: (1, 4), 11: (1, 4), 9: (2, 3), 10: (2, 3), 8: (4, 5, 1), 6: (2, 3, 5, 6, 7), 7: (2, 3, 5, 6, 7)}.get(p['pos'], (1, 2, 3, 4))
        q = nearest(p, [o for o in opp if o['pos'] in pool] or [o for o in opp if o['pos'] in (1, 2, 3, 4)])
        if q:
            chances.append(dict(mine=p, opp=q))
    outf = [p for p in opp if p['pos'] != 0]
    aerial = sorted(outf, key=lambda p: -((p['a'].get('Heading') or 0) + (p['a'].get('Jump') or 0) + (p['h'] or 170) / 4))[:3]
    fk = sorted(outf, key=lambda p: -((p['a'].get('PlaceKicking') or 0) + (p['a'].get('Curl') or 0)))[:2]
    # fazne formacije
    ph = []
    for q in s.club_presets(oi):
        rl = [r for r, x, y in q['slots']]
        ph.append(dict(formation=q['formation'], df=sum(1 for r in rl if r in (1, 2, 3)), mf=sum(1 for r in rl if r in (4, 5, 6, 7, 8)), fw=sum(1 for r in rl if r in (9, 10, 11, 12))))
    my_idx = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    try:
        mt = s.club_tactics(my_idx, own=True)
    except Exception:
        mt = None
    return dict(club=seasonstats.club_name(s.d, oi), opp=opp, bench=bench, mine=mine, t_opp=team(opp), t_mine=team(mine), duels=duels, chances=chances,
                aerial=aerial, fk=fk, phases=ph, my_tactics=mt)



COMP_LEAGUES = {17: 'Premier League', 18: 'Serie A', 19: 'La Liga', 20: 'Bundesliga', 21: 'Eredivisie', 22: 'Liga Portugal', 50: 'Ostale europske lige',
                79: 'EFL Championship', 80: 'La Liga 2', 81: '2. Bundesliga', 82: 'Serie B', 116: 'Ligue 1', 117: 'Super League Greece', 118: 'Süper Lig',
                134: 'Scottish Premiership', 147: 'Danish Superliga', 155: 'Belgian Pro League'}
COMP_GROUPS = {3: ('Champions League', 'Champions League'), 5: ('Europa League', 'Europa League')}
# pc264: Football Life 2027 ima druge brojeve liga (izmjereno na prvom FL27 saveu, Liverpool 1.8.2026, raspored + clanovi):
# 20 = Ligue 1 (FL26: Bundesliga), 50 = Bundesliga (FL26: 'ostale'), 81 = Ligue 2 (FL26: 2. Bundesliga), 115 = Belgija, 116 = Rusija (FL26: Ligue 1)
COMP_LEAGUES_FL27 = {17: 'Premier League', 18: 'Serie A', 19: 'La Liga', 20: 'Ligue 1', 21: 'Eredivisie', 22: 'Liga Portugal', 50: 'Bundesliga',
                     79: 'EFL Championship', 80: 'La Liga 2', 81: 'Ligue 2', 82: 'Serie B', 115: 'Belgian Pro League', 116: 'Russian Premier League',
                     117: 'Super League Greece', 118: 'Süper Lig', 134: 'Scottish Premiership', 147: 'Danish Superliga'}
_GAME = dict(v='fc27', save=None, fl26=None, regs=None)
_GAME_HDR = {}


def _game_of(folder):
    """Format of the career SAVE being read: 'fl27' / 'pes17' / 'fl26'.
    This no longer selects the game or the database - FC 27 is the only game -
    but the save readers and the read-only guard still need to know the format."""
    try:
        if pes17.is_pes17(folder):
            return 'pes17'
    except Exception:
        pass
    try:
        p_ = os.path.join(folder, 'header.dat')
        k_ = (p_, os.path.getmtime(p_))
        if k_ not in _GAME_HDR:
            _GAME_HDR[k_] = 'fl27' if b'Football Life 2027' in open(p_, 'rb').read() else 'fl26'
        return _GAME_HDR[k_]
    except Exception:
        return 'fl26'


DB_FILES = ('players.json', 'ratings.json', 'positions.json', 'playpos.json', 'teamids.json', 'comps.json')


def _db_dir():
    """FC 27 is the only game: the player database is always data/fc27."""
    return os.path.join(HERE, 'data', 'fc27')


def _dbf(name):
    """Database file for the current game.

    No FL26 fallback: falling back would silently serve another game's player
    ids, so the wrong names and ratings would show against FC 27 squads.
    """
    return os.path.join(_db_dir(), name)


def _db_dir_w():
    """Folder the database importer writes to (data/fc27)."""
    d_ = _db_dir()
    if not os.path.isdir(d_):
        os.makedirs(d_, exist_ok=True)
    return d_


def _db_own(name, default):
    """pc268: baza SAMO ove igre (bez FL26 zamjene): za usporedbu i spajanje kod uvoza druge igre."""
    p_ = os.path.join(_db_dir(), name)
    try:
        return json.load(open(p_, encoding='utf-8'))
    except Exception:
        return default


def _sync_game(folder):
    """FC 27 is the only game, so the competition tables and the database never
    switch. `folder` is a decrypted career save: its FORMAT is still detected so
    the save readers and the read-only guard keep working. Replacing that save
    layer with a native career is the next milestone."""
    g = _game_of(folder)
    if g == _GAME['save']:
        return _GAME['v']
    _GAME['save'] = g
    _GL.clear()
    try:
        reload_db()
    except Exception as ex:
        print('[game] database:', ex)
    return _GAME['v']


def _qint(q, k, default=0):
    """Read an int query argument without throwing on junk input."""
    try:
        return int((q.get(k, [''])[0] or '').strip())
    except (ValueError, TypeError):
        return default


def _fc27_tables():
    """Competition names and registration rules for FC 27.

    The FL26 defaults must be DROPPED, not merged: FC 27 reuses the same small
    ids for different competitions (17 is Ligue 2, not Premier League) and 12
    FL26 ids do not exist in FC 27 at all, so merging leaves stale names behind.
    Nationality ids differ too, so regrules.EU is swapped for the EA set.
    """
    COMP_LEAGUES.clear()
    COMP_GROUPS.clear()
    try:
        for _k, _v in json.load(open(_dbf('comps.json'), encoding='utf-8')).items():
            if _v.get('kind') == 'groups':
                COMP_GROUPS[int(_k)] = (_v.get('name') or 'Competition %s' % _k,
                                        _v.get('name_en') or _v.get('name') or 'Competition %s' % _k)
            elif _v.get('name'):
                COMP_LEAGUES[int(_k)] = _v['name']
    except Exception as ex:
        print('[fc27] competitions:', ex)
    regrules.RULES.clear()
    regrules.RULES.update(regrules.RULES_FC27)
    regrules.DOMESTIC.clear()
    regrules.DOMESTIC.update(regrules.DOMESTIC_FC27)
    regrules.EU.clear()
    regrules.EU.update(regrules.EU_FC27)
    # FC 27 ships its own overall rating; recomputing it with the PES attribute
    # weights would produce a different number from the mapped attributes.
    dbimport.USE_GAME_OVR = True
    dbimport.BASE_PATH = None


_fc27_tables()



def _L(x):
    return [t.strip() for t in x.split('|')]


LEAGUE_CLUBS = {
 'Premier League': _L("Arsenal FC|Aston Villa FC|AFC Bournemouth|Brentford FC|Brighton & Hove Albion FC|Chelsea FC|Crystal Palace FC|Everton FC|Fulham FC|Ipswich Town FC|Liverpool FC|Manchester City FC|Manchester United FC|Newcastle United FC|Nottingham Forest FC|Southampton FC|Sunderland AFC|Tottenham Hotspur FC|West Ham United FC|Wolverhampton Wanderers FC"),
 'Serie A': _L("Atalanta BC|Bologna FC 1909|Cagliari Calcio|Como 1907|US Cremonese|ACF Fiorentina|Genoa CFC|Hellas Verona FC|FC Internazionale Milano|Juventus FC|SS Lazio|US Lecce|AC Milan|SSC Napoli|Parma Calcio 1913|AC Pisa 1909|AS Roma|US Sassuolo|Torino FC|Udinese Calcio"),
 'La Liga': _L("Deportivo Alavés|Athletic Club|Atlético de Madrid|FC Barcelona|RC Celta de Vigo|Elche CF|RCD Espanyol|Getafe CF|Girona FC|Levante UD|RCD Mallorca|CA Osasuna|Rayo Vallecano|Real Betis Balompié|Real Madrid CF|Real Oviedo|Real Sociedad de Fútbol|Sevilla FC|Valencia CF|Villarreal CF"),
 'Bundesliga': _L("FC Augsburg|Bayer 04 Leverkusen|FC Bayern München|Borussia Dortmund|Borussia Mönchengladbach|Eintracht Frankfurt|Sport-Club Freiburg|Hamburger SV|1. FC Heidenheim 1846|TSG Hoffenheim|1. FC Köln|RB Leipzig|1. FSV Mainz 05|FC St. Pauli|VfB Stuttgart|1. FC Union Berlin|SV Werder Bremen|VfL Wolfsburg"),
 'Eredivisie': _L("AFC Ajax|AZ Alkmaar|Excelsior Rotterdam|Feyenoord Rotterdam|Fortuna Sittard|Go Ahead Eagles|FC Groningen|SC Heerenveen|Heracles Almelo|NAC Breda|NEC Nijmegen|PEC Zwolle|PSV Eindhoven|Sparta Rotterdam|SC Telstar|FC Twente|FC Utrecht|FC Volendam"),
 'Liga Portugal': _L("FC Alverca|FC Arouca|AVS Futebol SAD|SL Benfica|SC Braga|Casa Pia AC|GD Estoril Praia|CF Estrela da Amadora|FC Famalicão|Gil Vicente FC|Moreirense FC|CD Nacional|FC Porto|Rio Ave FC|CD Santa Clara|Sporting CP|CD Tondela|Vitória SC"),
 'Ligue 1': _L("Angers SCO|AJ Auxerre|Stade Brestois 29|Havre AC|RC Lens|Lille OSC|FC Lorient|Olympique Lyonnais|Olympique Marseille|FC Metz|AS Monaco FC|FC Nantes|OGC Nice Côte d'Azur|Paris FC|Paris Saint-Germain FC|Stade Rennais FC|RC Strasbourg Alsace|Toulouse FC"),
 'Belgian Pro League': _L("RSC Anderlecht|Royal Antwerp FC|Cercle Brugge KSV|Sporting Charleroi SC|Club Brugge KV|FCV Dender EH|KRC Genk|KAA Gent|RAAL La Louvière|OH Leuven|KV Mechelen|Sint-Truiden VV|Royal Standard de Liège|Royale Union Saint-Gilloise|KVC Westerlo|SV Zulte Waregem"),
 'Scottish Premiership': _L("Aberdeen FC|Celtic FC|Dundee FC|Dundee United FC|Falkirk FC|Heart of Midlothian FC|Hibernian FC|Kilmarnock FC|Livingston FC|Motherwell FC|Rangers FC|St. Mirren FC"),
 'Süper Lig': _L("Aytemiz Alanyaspor|Fraport-TAV Antalyaspor|Medipol Başakşehir FK|Beşiktaş JK|Eyüpspor|Fatih Karagümrük SK|Fenerbahçe SK|Galatasaray AŞ|Gaziantep FK|Gençlerbirliği SK|Göztepe SK|Kasimpaşa SK|Yukatel Kayserispor|Kocaelispor|İttifak Holding Konyaspor|Çaykur Rizespor|Samsunspor|Trabzonspor Kulübü"),
 'Super League Greece': _L("AEK Athens FC|AE Larissa FC|Aris FC|Asteras Tripolis FC|Atromitos FC|AE Kifisia FC|Levadiakos FC|OFI Crete FC|Olympiacos FC|Panathinaikos FC|Panetolikos FC|Panserraikos FC|PAOK FC|Volos FC"),
 'Danish Superliga': _L("AGF Aarhus|Brøndby IF|FC Fredericia|FC København|FC Midtjylland|FC Nordsjælland|Odense Boldklub|Randers FC|Silkeborg IF|SønderjyskE|Vejle BK|Viborg FF"),
 'EFL Championship': _L("Birmingham City FC|Blackburn Rovers FC|Bristol City FC|Charlton Athletic FC|Burnley FC|Derby County FC|Wolverhampton Wanderers FC|West Ham United FC|Leicester City FC|Middlesbrough FC|Millwall FC|Norwich City FC|Oxford United FC|Portsmouth FC|Preston North End FC|Queens Park Rangers FC|Sheffield United FC|Sheffield Wednesday FC|Southampton FC|Stoke City FC|Swansea City AFC|Watford FC|West Bromwich Albion FC|Wrexham AFC"),
 '2. Bundesliga': _L("DSC Arminia Bielefeld|VfL Bochum 1848|SV Darmstadt 98|SG Dynamo Dresden|Eintracht Braunschweig|SV Elversberg|Fortuna Düsseldorf|SpVgg Greuther Fürth|Hannover 96|Hertha BSC|1. FC Kaiserslautern|Karlsruher SC|Holstein Kiel|1. FC Magdeburg|1. FC Nürnberg|SC Paderborn 07|SC Preußen Münster|FC Schalke 04|TSV 1860 München|FC Hansa Rostock|SSV Jahn Regensburg|1.FC Saarbrücken"),
 'La Liga 2': _L("Albacete Balompié|UD Almería|FC Andorra|Burgos CF|Cádiz CF|CD Castellón|AD Ceuta FC|Córdoba CF|Cultural y Deportiva Leonesa|RC Deportivo de La Coruña|SD Eibar|Granada CF|SD Huesca|UD Las Palmas|CD Leganés|Málaga CF|CD Mirandés|Racing de Santander|Real Sociedad de Fútbol B|Real Sporting de Gijón|Real Valladolid CF|Real Zaragoza"),
 'Serie B': _L("US Avellino 1912|SSC Bari|Carrarese Calcio 1908|US Catanzaro 1929|Cesena FC|Empoli FC|Frosinone Calcio|SS Juve Stabia|Mantova 1911|Modena FC|AC Monza|Calcio Padova|Palermo FC|Pescara Calcio 1936|AC Reggiana 1919|UC Sampdoria|Spezia Calcio|FC Südtirol|Venezia FC|Virtus Entella"),
 'Ostale europske lige': _L("APOEL FC|FC Astana|FC Basel 1893|FK Crvena Zvezda|GNK Dinamo Zagreb|FC Dynamo Kiev|FCSB|Ferencvárosi TC|HJK Helsinki|KKS Lech Poznań|PFC Ludogorets 1945|Maccabi Tel-Aviv FC|Malmö FF|FC Red Bull Salzburg|Rosenborg BK|SK Slavia Praha|ŠK Slovan Bratislava|BSC Young Boys"),
 'Brasileirão Série A': _L("Clube Atlético Mineiro|EC Bahia|Botafogo FR|Red Bull Bragantino|Ceará SC|SC Corinthians Paulista|Cruzeiro EC|CR Flamengo|Fluminense FC|Fortaleza EC|Grêmio FBPA|SC Internacional|EC Juventude|Mirassol FC|SE Palmeiras|Santos FC|São Paulo FC|Sport Club do Recife|CR Vasco da Gama|EC Vitória"),
 'Brasileirão Série B': _L("Atlético Clube Goianiense|Avaí FC|Botafogo FC|Associação Chapecoense de Futebol|Coritiba FC|Clube de Regatas Brasil|Criciúma EC|Cuiabá EC|Associação Ferroviária de Esportes|Goiás EC|Grêmio Novorizontino|Operário Ferroviário EC|Paysandu SC|Clube do Remo|Vila Nova FC|Volta Redonda FC|Amazonas FC|América FC"),
 'Liga Profesional Argentina': _L("AA Argentinos Juniors|CA Tucumán|CA Banfield|CA Barracas Central|CA Belgrano|CA Boca Juniors|CA Central Córdoba|CSD Defensa y Justicia|Deportivo Riestra|Club Estudiantes de La Plata|CD Godoy Cruz Antonio Tomba|CA Huracán|CA Independiente|CS Independiente Rivadavia|Instituto Atlético Central Córdoba|CA Lanús|CA Newell's Old Boys|CA Platense|Racing Club|CA River Plate|CA Rosario Central|CA San Lorenzo de Almagro|CA Talleres|CA Tigre|CA Unión|CA Vélez Sarsfield"),
 'MLS': _L("Atlanta United FC|Austin FC|Charlotte FC|Chicago Fire FC|FC Cincinnati|Colorado Rapids|Columbus Crew|Los Angeles FC|Los Angeles Galaxy|Inter Miami CF|Minnesota United FC|Nashville SC|New York City FC|New York Red Bulls|Orlando City SC|Philadelphia Union|Portland Timbers|San Diego FC|Seattle Sounders FC|Vancouver Whitecaps FC"),
 'J1 League': _L("Albirex Niigata|Avispa Fukuoka|Cerezo Osaka|Fagiano Okayama|FC Tokyo|Gamba Osaka|Kashima Antlers|Kashiwa Reysol|Kawasaki Frontale|Kyoto Sanga FC|FC Machida Zelvia|Nagoya Grampus|Sanfrecce Hiroshima|Shimizu S-Pulse|Shonan Bellmare|Tokyo Verdy|Urawa Red Diamonds|Vissel Kobe|Yokohama FC|Yokohama F. Marinos"),
 'Primera Chile': _L("Audax Italiano La Florida|CD Cobresal|CSD Colo-Colo|CD Coquimbo Unido|Club Deportes Iquique|Club Deportes Limache|Everton de Viña del Mar|CD Huachipato|CD La Serena|CD Ñublense|CD O'Higgins|CD Palestino|Unión Española|CD Unión La Calera|CD Universidad Católica|Club Universidad de Chile"),
 'Primera A Colombia': _L("Águilas Doradas Rionegro|Alianza FC|América de Cali|Atlético Nacional|CA Bucaramanga|Boyacá Chicó FC|Club Deportes Tolima|Asociación Deportivo Cali|Asociación Deportivo Pasto|Deportivo Pereira|Envigado FC|Fortaleza CEIF|Deportivo Independiente Medellín|CDP Junior FC|CD La Equidad Seguros|Llaneros FC|Millonarios FC|CD Once Caldas|Club Independiente Santa Fe|Unión Magdalena"),
 'Saudi Pro League': _L("Al Ahli Saudi FC|Damac FC|Ettifaq Club|Al Fateh SC|Al Fayha Club|Al Hilal Saudi FC|Al Ittihad Club|Al Khaleej FC|Al Kholood Club|Al Nassr FC|NEOM SC|Al Okhdood Club|Al Qadsiah FC|Al Riyadh SC|Al Shabab FC|Al Taawoun FC"),
 'Russian Premier League': _L("FK Akhmat Grozny|FK Akron Togliatti|FC Baltika Kaliningrad|PFK CSKA Moskva|FK Dinamo Makhachkala|FK Dinamo Moskva|FK Krasnodar|FK Lokomotiv Moskva|FK Orenburg|FK Pari Nizhny Novgorod|FK Rostov|FK Rubin Kazan|PFK Krylia Sovetov Samara|PFC Sochi|FK Spartak Moskva|FK Zenit St. Petersburg"),
}


def _block_comps(d, my_idx, have):
    """Lige iz zapisa klubova u save-u (W/D/L/GF/GA) po popisu klubova, neovisno o odigranim utakmicama. Preskace lige koje vec postoje (po imenu)."""
    out = []
    try:
        recs = mlsave.team_records(d)
        byname = {}
        for t in recs:
            byname.setdefault(t['name'], t)
        for nm, clubs in LEAGUE_CLUBS.items():
            if nm in have:
                continue
            b = [byname[c] for c in clubs if c in byname]
            if len(b) < max(8, int(len(clubs) * 0.7)):
                continue
            idxs = [t['idx'] for t in b]
            rows = [dict(club=t['name'], idx=t['idx'], pl=t['pl'], w=t['w'], d=t['d'], l=t['l'], gf=t['gf'], ga=t['ga'], pts=t['pts'], gd=t['gd'], pos=t['pos'])
                    for t in mlsave.table(b)]
            out.append(dict(tid='n:' + nm, kind='league', name=nm, mine=my_idx in idxs, rows=rows))
    except Exception:
        pass
    return out


def _preseason_comps(slot, r):
    """pc346: kratki turniri u srpnju/kolovozu (3-8 klubova, svatko igra barem 2 utakmice) kojih nema medju natjecanjima:
    tablica, rezultati i raspored iz save-a. Samo citanje."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    season = r.get('season')
    if season is None:
        return []
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    have = {c.get('tid') for c in r.get('comps') or []}
    cn = lambda ci: seasonstats.club_name(s.d, ci)
    by = {}
    for m in M['matches']:
        if m['season'] == season and m['home'] != m['away']:
            by.setdefault(m['tid'], []).append(m)
    out = []
    for tid, ms in by.items():
        if tid in have or tid in (3, 5, 186) or tid in COMP_LEAGUES:
            continue
        if any(m['m'] not in (7, 8) for m in ms):
            continue
        games = {}
        for m in ms:
            for c_ in (m['home'], m['away']):
                games[c_] = games.get(c_, 0) + 1
        if not (3 <= len(games) <= 8) or min(games.values()) < 2 or not all(cn(c_) for c_ in games):
            continue
        rows = {c_: dict(club=cn(c_), idx=c_, pl=0, w=0, d=0, l=0, gf=0, ga=0, pts=0, gd=0, form=[]) for c_ in games}
        res = []
        for m in sorted(ms, key=seasonstats.sort_key):
            if not m['played']:
                continue
            gh = seasonstats.match_score(m)[0]
            ga = seasonstats.match_score(m)[1]
            for c_, f_, g_ in ((m['home'], gh, ga), (m['away'], ga, gh)):
                t = rows[c_]
                t['pl'] += 1; t['gf'] += f_; t['ga'] += g_
                t['w'] += f_ > g_; t['d'] += f_ == g_; t['l'] += f_ < g_
                t['form'].append('W' if f_ > g_ else ('L' if f_ < g_ else 'D'))
            res.append(dict(d='%02d/%02d' % (m['dd'], m['m']), y=m['y'], home=cn(m['home']), away=cn(m['away']), hg=gh, ag=ga, hi=m['home'], ai=m['away']))
        tb = list(rows.values())
        for t in tb:
            t['pts'] = 3 * t['w'] + t['d']; t['gd'] = t['gf'] - t['ga']
        tb.sort(key=lambda t: (-t['pts'], -t['gd'], -t['gf'], t['club']))
        for i, t in enumerate(tb, 1):
            t['pos'] = i
        fx = [dict(d='%02d/%02d' % (m['dd'], m['m']), y=m['y'], home=cn(m['home']), away=cn(m['away']), hi=m['home'], ai=m['away'])
              for m in sorted(ms, key=seasonstats.sort_key) if not m['played']]
        nm = None
        try:
            nm = _reg_comp_name(tid)
        except Exception:
            pass
        out.append(dict(tid=tid, kind='league', name=nm or 'Pre-season tournament', preseason=True, mine=False, my_in=my in games,
                        rows=tb, results=list(reversed(res)), fixtures=fx, scorers=[], assists=[], rated=[]))
    out.sort(key=lambda c: (not c['my_in'], c['name']))
    return out


def _reg_comp_name(tid):
    """pc259: ime natjecanja iz CompetitionRegulation.bin (prvi livecpk korijen koji ga ima, kao Sider): roditelj (10 bita) -> ime.
    Prednost domacoj ligi (vrsta 4), zatim glavnoj fazi (2). Bez baze ili za nepoznati broj: None."""
    c = _GL.get('regnames')
    if c is None:
        c = {}
        try:
            import fl26_europe_view
            from pathlib import Path
            path = _game_db_file('common/etc/pesdb/CompetitionRegulation.bin')   # pc277: i iz cpk arhiva igre (FL27)
            if path is not None:
                path = Path(path)
                rows, _sha = fl26_europe_view.regulations(path)
                _GL['regcomp'] = {r['key'] & 0x3ff: r.get('competition') for r in rows.values() if not r['parent']}
                pri = {4: 0, 2: 1, 3: 2, 1: 3}
                best = {}
                for r in rows.values():
                    k = (r['parent'] or r['key']) & 0x3ff
                    p_ = pri.get(r['kind'], 9)
                    if r['name'] and (k not in best or p_ < best[k][0]):
                        best[k] = (p_, r['name'])
                c = {k: v[1] for k, v in best.items()}
        except Exception as ex:
            print('[competitions] regulation names:', ex)
            c = {}
        _GL['regnames'] = c
    return c.get(tid)


def _foreign_tids(s, tids, M=None, season=None):
    """pc277: natjecanja (broj iz rasporeda) u koja moj klub NIJE prijavljen prema bazi igre (CompetitionRegulation -> natjecanje,
    CompetitionEntry -> klubovi). Raspored u saveu zna imati zalutale zapise (FL27: Liverpool - Aston Villa 31.8. u 'FIFA World Cup'
    i 'Johan Cruyff Shield'). Bez baze ili nepoznatog kluba: prazan skup (nista se ne izbacuje)."""
    try:
        _reg_comp_name(0)
        rc = _GL.get('regcomp') or {}
        comps, entry = _comp_db()
        if not rc or not entry:
            return set()
        team = struct.unpack_from('<I', s.d, s.club_offset() - 4)[0] >> 14   # kljuc kluba = team ID << 14 | indeks
        if team not in entry:
            return set()
        mine = entry[team]
        out = {t for t in tids if rc.get(t) is not None and (rc[t] & 0xff) not in mine}
        if M is not None and out:
            # prijave u bazi su s pocetka svijeta (klub se kasnije kvalificira u EL itd.): izbaci samo natjecanja s malo zapisa u sezoni
            n = {}
            for m in M['matches']:
                if m['tid'] in out and (season is None or m['season'] == season):
                    n[m['tid']] = n.get(m['tid'], 0) + 1
            out = {t for t in out if n.get(t, 0) < 10}
            # pc346: predsezonski turnir (International Champions Cup...): klubovi su pozvani, nisu u prijavama baze. Moj klub ima
            # barem 2 utakmice tog natjecanja, sve u srpnju/kolovozu -> pravo natjecanje, ne zalutali zapis
            if out:
                my_ = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
                pm = {}
                for m in M['matches']:
                    if m['tid'] in out and (season is None or m['season'] == season) and my_ in (m['home'], m['away']):
                        pm.setdefault(m['tid'], []).append(m['m'])
                out = {t for t in out if not (len(pm.get(t, [])) >= 2 and all(mo in (7, 8) for mo in pm[t]))}
        return out
    except Exception as ex:
        print('[ghosts]', ex)
        return set()


def _comps_view0(slot):
    """Tablice svih natjecanja iz utakmica u save-u (rezultat = zbroj golova igraca): lige i grupne faze LP/EL. Moja liga je prva."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    d = s.d
    seasons = seasonstats.played_seasons(M)
    my_idx = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    # tekuca sezona po datumu igre (ne zadnja odigrana): na pocetku sezone, prije prve utakmice, lige se grade iz rasporeda
    season = None
    try:
        gc = s.game_date_code()
        gy, gmo = gc & 0xffff, (gc >> 16) & 0xff
        season = gy if gmo >= 7 else gy - 1
    except Exception:
        pass
    allseas = {m['season'] for m in M['matches']}
    if season not in allseas:
        season = seasons[-1] if seasons else (max(allseas) if allseas else None)
    if season is None:
        return dict(season=None, comps=_block_comps(d, my_idx, set()))
    cn = lambda ci: seasonstats.club_name(d, ci)
    by = {}
    other = {}
    for m in M['matches']:
        if m['season'] == season and m['home'] != m['away']:
            if m['tid'] in COMP_LEAGUES or m['tid'] in COMP_GROUPS:
                by.setdefault(m['tid'], []).append(m)
            elif my_idx in (m['home'], m['away']) or True:
                other.setdefault(m['tid'], []).append(m)
    try:
        _my_lg = mlsave.read_description(slot_folder(slot)).get('league') or ''
    except Exception:
        _my_lg = ''

    def _split(ms):
        """pc232: vise liga pod istim brojem natjecanja (npr. 'ostale europske lige', ili dodatne lige iz FL26 Mod Studija):
        klubovi iste lige igraju medjusobno, razlicitih nikad. Skupine povezanih klubova = zasebne lige."""
        par = {}
        def f(x):
            while par.setdefault(x, x) != x:
                par[x] = par.get(par[x], par[x])
                x = par[x]
            return x
        for m in ms:
            if m['home'] < 4000 and m['away'] < 4000:
                a_, b_ = f(m['home']), f(m['away'])
                if a_ != b_:
                    par[a_] = b_
        g = {}
        for c in list(par):
            g.setdefault(f(c), set()).add(c)
        return [cl for cl in g.values() if len(cl) >= 8]

    # pc259: natjecanja iznad 255 (60 MB): liga ako je krug svaki-sa-svakim (>= 8 klubova), ime iz baze natjecanja igre
    xnames = {}
    for tid, ms in list(other.items()):
        if tid < 256 or tid in by:
            continue
        for cl in _split(ms):
            sub = [m for m in ms if m['home'] in cl and m['away'] in cl]
            if len(sub) >= len(cl) * (len(cl) - 1) // 2:
                by.setdefault(tid, []).extend(sub)
                xnames[tid] = _reg_comp_name(tid) or ('Competition %d' % tid)
    items = []
    for tid, ms in by.items():
        if tid in COMP_GROUPS:
            items.append((tid, ms, None))
            continue
        parts = _split(ms)
        if len(parts) <= 1:
            items.append((tid, ms, None))
        else:
            for cl in parts:
                items.append((tid, [m for m in ms if m['home'] in cl and m['away'] in cl], cl))
    # moja liga pod brojem natjecanja koji app ne poznaje (lige iz FL26 Mod Studija): krug svaki-sa-svakim u kojem sam ja
    if not any(my_idx in {m['home'] for m in ms_} | {m['away'] for m in ms_} for _t, ms_, _c in items if _t in COMP_LEAGUES):
        for tid, ms in other.items():
            for cl in _split(ms):
                if my_idx not in cl:
                    continue
                sub = [m for m in ms if m['home'] in cl and m['away'] in cl]
                if sum(1 for m in sub if my_idx in (m['home'], m['away'])) >= len(cl) - 1:
                    items.append((tid, sub, cl))

    def standings(ms, clubs):
        T = {c: dict(club=cn(c), idx=c, pl=0, w=0, d=0, l=0, gf=0, ga=0) for c in clubs}
        for m in ms:
            if not m['played']:
                continue
            h, a = m['home'], m['away']
            if h not in T or a not in T:
                continue
            gh = seasonstats.match_score_for(m, h)[0]
            ga = seasonstats.match_score_for(m, h)[1]
            for c, f, g in ((h, gh, ga), (a, ga, gh)):
                t = T[c]
                t['pl'] += 1; t['gf'] += f; t['ga'] += g
                if f > g: t['w'] += 1
                elif f < g: t['l'] += 1
                else: t['d'] += 1
        rows = list(T.values())
        for t in rows:
            t['pts'] = 3 * t['w'] + t['d']
        return mlsave.game_ranks(rows, mlsave.results_of([m for m in ms if m['home'] in T and m['away'] in T]), 'idx')   # pc316: kao u igri

    comps = []
    for tid, ms, part in items:
        cnt = {}
        for m in ms:
            cnt[m['home']] = cnt.get(m['home'], 0) + 1
            cnt[m['away']] = cnt.get(m['away'], 0) + 1
        if tid in COMP_GROUPS:
            # u saveu zna biti smeca: utakmice prazne/nevazece ekipe (indeks 2025, 4095, prazno ili necitljivo ime) -> van, inace se stvori laznu "skupinu"
            _ok = {}
            def _valid(ci):
                if ci not in _ok:
                    try:
                        nm_ = cn(ci) if 0 <= ci < 4000 else ''
                    except Exception:
                        nm_ = ''
                    _ok[ci] = bool(nm_) and nm_.strip() != '' and '\ufffd' not in nm_ and all(ch.isprintable() for ch in nm_)
                return _ok[ci]
            ms = [m for m in ms if _valid(m['home']) and _valid(m['away'])]
            if not ms:
                continue
            cnt = {}
            for m in ms:
                cnt[m['home']] = cnt.get(m['home'], 0) + 1
                cnt[m['away']] = cnt.get(m['away'], 0) + 1
            # neodigrana utakmica s klubom koji se u natjecanju pojavljuje samo jednom (ostatak kvalifikacija/raspored) ne pravi zasebnu skupinu
            mxc = max(cnt.values())
            if mxc >= 4:
                ms = [m for m in ms if m['played'] or (cnt[m['home']] > 1 and cnt[m['away']] > 1)]
            par = {}
            def f(x):
                while par.setdefault(x, x) != x:
                    x = par[x]
                return x
            for m in ms:
                par[f(m['home'])] = f(m['away'])
            g = {}
            for c in list(par):
                g.setdefault(f(c), set()).add(c)
            groups = []
            for k, cl in g.items():
                gm = [m for m in ms if m['home'] in cl]
                groups.append((min(m['n'] for m in gm), standings(gm, cl)))
            groups.sort(key=lambda x: x[0])
            # bocna ploca: zadnji rezultati, sljedece utakmice, strijelci i asistenti natjecanja
            def _sc(m):
                gh = seasonstats.match_score(m)[0]
                return gh, seasonstats.match_score(m)[1]
            mk_ = lambda m: dict(h=cn(m['home']), a=cn(m['away']), d='%d.%d.%d' % (m['dd'], m['m'], m['y']), mine=(my_idx in (m['home'], m['away'])))
            pl_ = sorted([m for m in ms if m['played']], key=lambda m: (m['y'], m['m'], m['dd'], m['n']))
            res = [dict(mk_(m), s='%d:%d' % _sc(m)) for m in pl_[-10:]][::-1]
            nx_ = sorted([m for m in ms if not m['played']], key=lambda m: (m['y'], m['m'], m['dd'], m['n']))
            nxt = [mk_(m) for m in nx_[:10]]
            gs, ast = {}, {}
            for m in pl_:
                for r in m['rows']:
                    if r[2]:
                        gs.setdefault(r[0], [0, r[1]])[0] += r[2]
                    if r[3]:
                        ast.setdefault(r[0], [0, r[1]])[0] += r[3]
            top = lambda D: [dict(pid=p_, name=NAMES.get(p_, str(p_)), club=cn(v[1]), n=v[0]) for p_, v in sorted(D.items(), key=lambda kv: -kv[1][0])[:8]]
            comps.append(dict(tid=tid, kind='groups', name=COMP_GROUPS[tid][0], name_en=COMP_GROUPS[tid][1], mine=any(c == my_idx for c in cnt),
                              groups=[dict(name=chr(65 + i), rows=r) for i, (_, r) in enumerate(groups)],
                              side=dict(res=res, nxt=nxt, scorers=top(gs), assists=top(ast), md=max([cnt_ for cnt_ in [sum(1 for m in pl_ if m['home'] == c_ or m['away'] == c_) for c_ in cnt]] or [0]))))
        else:
            mx = max(cnt.values())
            clubs = [c for c, n in cnt.items() if n >= max(1 if mx <= 2 else 2, mx * 0.5) and c < 4000]
            if len(clubs) < 8:
                continue
            rows_ = standings(ms, clubs)
            ext = {}
            try:
                cs_ = set(clubs)
                pm = sorted([m for m in ms if m['played'] and m['home'] in cs_ and m['away'] in cs_], key=seasonstats.sort_key)

                def _sc(m):
                    gh_ = seasonstats.match_score(m)[0]
                    ga_ = seasonstats.match_score(m)[1]
                    return gh_, ga_
                fm_ = {}
                res_ = []
                for m in pm:
                    gh_, ga_ = _sc(m)
                    for c_, f_, g_ in ((m['home'], gh_, ga_), (m['away'], ga_, gh_)):
                        fm_.setdefault(c_, []).append('W' if f_ > g_ else ('L' if f_ < g_ else 'D'))
                    res_.append(dict(d='%02d/%02d' % (m['dd'], m['m']), y=m['y'], home=cn(m['home']), away=cn(m['away']), hg=gh_, ag=ga_, hi=m['home'], ai=m['away']))
                for r_ in rows_:
                    r_['form'] = fm_.get(r_['idx'], [])[-5:]
                fx_ = sorted([m for m in M['matches'] if m['tid'] == tid and m['season'] == season and not m['played'] and m['home'] in cs_ and m['away'] in cs_], key=seasonstats.sort_key)[:60]
                ag_ = seasonstats.agg(M, season, tid)

                def _pr(pid, x):
                    return dict(id=pid, name=NAMES.get(pid, str(pid)), club=cn(x['clubs'][-1]) if x['clubs'] else '', ci=x['clubs'][-1] if x['clubs'] else None, app=x['app'], g=x['g'], a=x['a'], rating=round(x['rs'] / x['app'], 2) if x['app'] else None)
                allp = [_pr(pid, x) for pid, x in ag_.items() if x['clubs'] and x['clubs'][-1] in cs_]
                ext = dict(results=list(reversed(res_))[:80],
                           fixtures=[dict(d='%02d/%02d' % (m['dd'], m['m']), y=m['y'], home=cn(m['home']), away=cn(m['away']), hi=m['home'], ai=m['away']) for m in fx_],
                           scorers=sorted([r for r in allp if r['g']], key=lambda r: (-r['g'], -r['a'], r['app']))[:20],
                           assists=sorted([r for r in allp if r['a']], key=lambda r: (-r['a'], -r['g'], r['app']))[:20],
                           rated=sorted([r for r in allp if r['app'] >= 5 and r['rating']], key=lambda r: (-r['rating'], -r['app']))[:10])
            except Exception:
                ext = {}
            _nm = COMP_LEAGUES.get(tid) or xnames.get(tid) or (_my_lg if my_idx in clubs else '') or ('Competition %d' % tid)
            if part is not None:
                if my_idx in clubs and _my_lg:
                    _nm = _my_lg
                else:
                    _nm = '%s (%s)' % (COMP_LEAGUES.get(tid, 'League'), rows_[0]['club'] if rows_ else '')
            comps.append(dict(tid=tid, kind='league', name=_nm, mine=my_idx in clubs, rows=rows_, **ext))
    mineleague = [c for c in comps if c['kind'] == 'league' and c['mine']]
    for c in mineleague[1:]:
        c['mine'] = False
    order = {'groups': 1, 'league': 2}
    comps.sort(key=lambda c: (0 if c['kind'] == 'league' and c['mine'] else order[c['kind']], c['tid'] if c['kind'] == 'groups' else 0, (lambda _o: _o.index(c['tid']) if c['tid'] in _o else 100 + (c['tid'] if isinstance(c['tid'], int) else 0))([17, 19, 18, 20, 116, 21, 22, 118, 155, 134, 117, 147, 79, 81, 80, 82, 50]) if c['kind'] == 'league' else 0))
    for c in comps:
        if c['kind'] == 'groups':
            c['mine'] = False
    cov = set(c['name'] for c in comps if c['kind'] == 'league')
    comps += _block_comps(d, my_idx, cov)
    return dict(season=season, comps=comps)


def stats_view(slot, season=None, tid=None, club=None):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    d = s.d
    names = {}
    pos = {}
    try:
        names = {p[0]: p[2] for p in json.load(open(_dbf('players.json'), encoding='utf-8'))}
        pos = json.load(open(_dbf('positions.json')))
    except Exception:
        pass
    my_idx = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    cn = lambda ci: seasonstats.club_name(d, ci)
    seasons = seasonstats.played_seasons(M)
    if not seasons:
        return dict(seasons=[], season=None, tids=[], clubs=[], scorers=[], assists=[], club=[], my_idx=my_idx, club_idx=my_idx, club_name=cn(my_idx))
    season = int(season) if season not in (None, '') else seasons[-1]
    ms = [m for m in M['matches'] if m['played'] and m['season'] == season]
    mine = {}
    allt = {}
    for m in ms:
        allt[m['tid']] = allt.get(m['tid'], 0) + 1
        if my_idx in (m['home'], m['away']):
            mine[m['tid']] = mine.get(m['tid'], 0) + 1
    league = max(mine, key=lambda k: mine[k]) if mine else (max(allt, key=lambda k: allt[k]) if allt else None)
    tids = [dict(tid=t_, rows=r, mine=(t_ == league)) for t_, r in sorted(allt.items(), key=lambda kv: -kv[1]) if r >= 1]
    tid = int(tid) if tid not in (None, '') else league
    club = int(club) if club not in (None, '') else my_idx
    cur = M['cur']
    ag = seasonstats.agg(M, season, tid)

    def row(pid, x):
        n = x['app']
        return dict(id=pid, name=names.get(pid, str(pid)), pos=pos.get(str(pid)), club=' → '.join(cn(c) for c in x['clubs']),
                    app=n, g=x['g'], a=x['a'], rating=round(x['rs'] / n, 1) if n else None)
    lg = [row(pid, x) for pid, x in ag.items()]
    scorers = sorted([r for r in lg if r['g']], key=lambda r: (-r['g'], -r['a'], r['app']))[:20]
    assists = sorted([r for r in lg if r['a']], key=lambda r: (-r['a'], -r['g'], r['app']))[:20]
    cl = seasonstats.agg(M, season, club=club)
    lastids = seasonstats.last_n(M, season, club)
    fm = seasonstats.agg(M, season, club=club, last_ids=lastids)
    whole = seasonstats.agg(M, season)
    rows = []
    for pid, x in cl.items():
        r = row(pid, x)
        r['club'] = cn(club)
        r['score'] = seasonstats.score(x)
        f = fm.get(pid)
        r['form'] = seasonstats.score(f) if f else None
        r['fg'], r['fa'], r['fapp'] = (f['g'], f['a'], f['app']) if f else (0, 0, 0)
        c_now = cur.get(pid)
        r['left_to'] = cn(c_now) if c_now is not None and c_now != club else None
        prev = [c for c in whole.get(pid, {}).get('clubs', []) if c != club]
        r['came_from'] = cn(prev[0]) if prev and c_now == club else None
        rows.append(r)
    rows.sort(key=lambda r: -r['score'])
    stay = [r for r in rows if not r['left_to']] or rows
    key = stay[0]['id'] if stay else None
    hotc = [r for r in stay if r['form'] is not None and r['fapp'] >= 2] or [r for r in stay if r['form'] is not None]
    hot = max(hotc, key=lambda r: r['form'])['id'] if hotc and max(r['form'] for r in hotc) > 0 else None
    cl_idx = sorted({c for m in ms for c in (m['home'], m['away'])})
    clubs = sorted([dict(idx=i, name=cn(i)) for i in cl_idx], key=lambda c: c['name'])
    return dict(seasons=seasons, season=season, clubs=clubs, league=league, tid=tid, tids=tids, club_idx=club, club_name=cn(club),
                scorers=scorers, assists=assists, club=rows, key=key, hot=hot, form_n=len(lastids), my_idx=my_idx)



def awards_view(slot, season=None):
    """Nagrade lige iz odigranih utakmica u save-u: mjesecne (igrac, mladi igrac, golman, trener, gol mjeseca) i sezonske
    (zlatna kopacka, asistent, igrac sezone, mladi igrac, zlatne rukavice, trener sezone, momcad sezone)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    d = s.d
    cn = lambda ci: seasonstats.club_name(d, ci)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    seasons = seasonstats.played_seasons(M)
    if not seasons:
        return dict(seasons=[], season=None, months=[], season_awards=None, my=cn(my))
    season = int(season) if season not in (None, '') else seasons[-1]
    allm = [m for m in M['matches'] if m['season'] == season and m['home'] != m['away']]
    cnt = {}
    for m in allm:
        if my in (m['home'], m['away']):
            cnt[m['tid']] = cnt.get(m['tid'], 0) + 1
    if not cnt:
        for m in allm:
            cnt[m['tid']] = cnt.get(m['tid'], 0) + 1
    tid = max(cnt, key=lambda k: cnt[k]) if cnt else None
    lm = sorted([m for m in allm if m['tid'] == tid], key=seasonstats.sort_key)
    played = [m for m in lm if m['played']]
    try:
        gc = s.game_date_code()
        today = (gc & 0xffff, (gc >> 16) & 0xff)
    except Exception:
        today = None
    cnames = {}
    try:
        cnames = _coach_names()
    except Exception:
        pass

    def coach(ci):
        if ci == my:
            return s.manager() or ''
        try:
            nm_ = cnames.get(_club_coach_id(s, ci), '')
            if not nm_:
                nm_ = coaches.block_name(coaches.read_block(s, ci))   # pc315: ime iz bloka trenera u saveu (bez EDIT datoteke)
            return nm_ or ''
        except Exception:
            return ''

    def pinfo(pid, ci=None):
        o, a = rat(pid)
        return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=o, age=a, club=cn(ci) if ci is not None else None)

    def goals(m):
        gh = seasonstats.match_score(m)[0]
        ga = seasonstats.match_score(m)[1]
        return gh, ga

    def block(ms, min_app):
        P = {}
        T = {}
        cs = {}
        for m in ms:
            gh, ga = goals(m)
            for ci, f, a in ((m['home'], gh, ga), (m['away'], ga, gh)):
                t = T.setdefault(ci, dict(p=0, w=0, d=0, l=0, gf=0, ga=0, n=0))
                t['n'] += 1
                t['gf'] += f
                t['ga'] += a
                if f > a:
                    t['w'] += 1
                    t['p'] += 3
                elif f == a:
                    t['d'] += 1
                    t['p'] += 1
                else:
                    t['l'] += 1
            for pid, ci, g, a, r in m['rows']:
                x = P.setdefault(pid, dict(app=0, g=0, a=0, rs=0.0, ci=ci, cs=0))
                x['app'] += 1
                x['g'] += g
                x['a'] += a
                x['rs'] += r
                x['ci'] = ci
                conc = ga if ci == m['home'] else gh
                if POS.get(pid, 5) == 0 and conc == 0:
                    x['cs'] += 1
        def row(pid, x):
            e = pinfo(pid, x['ci'])
            e.update(app=x['app'], g=x['g'], a=x['a'], cs=x['cs'], rating=round(x['rs'] / x['app'], 2) if x['app'] else None,
                     score=seasonstats.score(x), mine=x['ci'] == my)
            return e
        el = [row(pid, x) for pid, x in P.items() if x['app'] >= min_app]
        best = sorted(el, key=lambda e: (-e['score'], -(e['rating'] or 0)))
        young = [e for e in best if e['age'] and e['age'] <= 21]
        gks = sorted([e for e in el if e['pos'] == 0], key=lambda e: (-e['cs'], -(e['rating'] or 0)))
        mgr = sorted(T.items(), key=lambda kv: (-kv[1]['p'], -(kv[1]['gf'] - kv[1]['ga']), -kv[1]['gf']))
        mg = [dict(club=cn(ci), coach=coach(ci), mine=ci == my, **t) for ci, t in mgr[:3] if t['n'] >= 1]
        return P, best, young, gks, mg

    months = []
    keys = []
    for m in played:
        k = (m['y'], m['m'])
        if k not in keys:
            keys.append(k)
    for (y, mo) in keys:
        ms = [m for m in played if m['y'] == y and m['m'] == mo]
        rounds = max([sum(1 for m in ms if ci in (m['home'], m['away'])) for ci in {c for m in ms for c in (m['home'], m['away'])}] or [1])
        P, best, young, gks, mg = block(ms, max(1, (rounds + 1) // 2))
        # gol mjeseca: deterministicki odabir medu strijelcima mjeseca
        evs = []
        for m in ms:
            gh, ga = goals(m)
            for pid, ci, g, a, r in m['rows']:
                if g:
                    opp = m['away'] if ci == m['home'] else m['home']
                    ast = [r2[0] for r2 in m['rows'] if r2[1] == ci and r2[3] and r2[0] != pid]
                    evs.append(dict(pid=pid, ci=ci, opp=opp, g=g, ast=ast[0] if ast else None, date='%02d.%02d.%d' % (m['dd'], m['m'], m['y']),
                                    score='%d-%d' % ((gh, ga) if ci == m['home'] else (ga, gh)), r=r))
        gom = None
        if evs:
            evs.sort(key=lambda e: (-e['r'], e['pid']))
            e = evs[(y * 13 + mo * 7) % min(len(evs), 6)]
            gom = pinfo(e['pid'], e['ci'])
            gom.update(opp=cn(e['opp']), date=e['date'], score=e['score'], assist=NAMES.get(e['ast'], '') if e['ast'] else '', mine=e['ci'] == my)
        done = today is not None and (today[0], today[1]) > (y, mo)
        months.append(dict(y=y, m=mo, done=done, matches=len(ms), potm=best[:4], young=young[:3], gk=gks[:2], manager=mg, goal=gom))
    # sezona
    tot_rounds = max([sum(1 for m in lm if ci in (m['home'], m['away'])) for ci in {c for m in lm for c in (m['home'], m['away'])}] or [1])
    pl_rounds = max([sum(1 for m in played if ci in (m['home'], m['away'])) for ci in {c for m in played for c in (m['home'], m['away'])}] or [1])
    P, best, young, gks, mg = block(played, max(1, int(pl_rounds * 0.4)))
    allp = [dict(pinfo(pid, x['ci']), app=x['app'], g=x['g'], a=x['a'], rating=round(x['rs'] / x['app'], 2), mine=x['ci'] == my) for pid, x in P.items() if x['app']]
    boot = sorted([e for e in allp if e['g']], key=lambda e: (-e['g'], e['app'], -e['rating']))[:5]
    ast = sorted([e for e in allp if e['a']], key=lambda e: (-e['a'], e['app'], -e['rating']))[:5]
    def pick(cands, n, taken):
        out = []
        for e in cands:
            if e['id'] in taken:
                continue
            out.append(e)
            taken.add(e['id'])
            if len(out) >= n:
                break
        return out
    taken = set()
    byr = sorted([e for e in best], key=lambda e: (-(e['rating'] or 0), -e['score']))
    tots = dict(gk=pick([e for e in byr if e['pos'] == 0], 1, taken), cb=pick([e for e in byr if e['pos'] == 1], 2, taken),
                lb=pick([e for e in byr if e['pos'] == 2], 1, taken), rb=pick([e for e in byr if e['pos'] == 3], 1, taken),
                mf=pick([e for e in byr if e['pos'] in (4, 5, 6, 7, 8)], 3, taken), fw=pick([e for e in byr if e['pos'] in (9, 10, 11, 12)], 3, taken))
    over = len(played) >= len(lm) and len(lm) > 0
    sa = dict(final=over, rounds=pl_rounds, total_rounds=tot_rounds, boot=boot, assists=ast, pots=best[:5], young=young[:3], glove=gks[:3],
              manager=mg, team=tots)
    try:
        lg_ = _comp_name(tid) if '_comp_name' in globals() else ''
        its = []
        for mo_ in months:
            if not mo_.get('done'):
                continue
            d_ = '%04d-%02d-28' % (mo_['y'], mo_['m'])
            for lab, lst in (('potm', mo_.get('potm')), ('young', mo_.get('young')), ('gk', mo_.get('gk'))):
                if lst:
                    w_ = lst[0]
                    its.append(('award', d_, 'aw:%s:%s-%s:%s' % (tid, mo_['y'], mo_['m'], lab), w_['id'], [w_.get('club')],
                                dict(award=lab, period='month', y=mo_['y'], m=mo_['m'], league=lg_, name=w_.get('name'), club=w_.get('club'), mine=w_.get('mine'))))
            g_ = mo_.get('goal')
            if g_:
                its.append(('award', d_, 'aw:%s:%s-%s:goal' % (tid, mo_['y'], mo_['m']), g_['id'], [g_.get('club')],
                            dict(award='goal', period='month', y=mo_['y'], m=mo_['m'], league=lg_, name=g_.get('name'), club=g_.get('club'), opp=g_.get('opp'), mine=g_.get('mine'))))
        if sa.get('final'):
            d_ = '%04d-06-30' % (season + 1)
            for lab, lst in (('pots', sa.get('pots')), ('young_season', sa.get('young')), ('glove', sa.get('glove')), ('boot', sa.get('boot'))):
                if lst:
                    w_ = lst[0]
                    its.append(('award', d_, 'aw:%s:%s:%s' % (tid, season, lab), w_['id'], [w_.get('club')],
                                dict(award=lab, period='season', season_y=season, league=lg_, name=w_.get('name'), club=w_.get('club'), mine=w_.get('mine'))))
        if its:
            world(slot, s).add_many(its)
    except Exception as ex:
        print('[world] awards:', ex)
    return dict(seasons=seasons, season=season, tid=tid, league=_comp_name(tid) if '_comp_name' in globals() else None, my=cn(my),
                months=months, season_awards=sa, today=dict(y=today[0], m=today[1]) if today else None)


# ---------------------------------------------------------------- Momcad kola, Zlatna lopta, bonusi nagrada (pc95)
def _today_ord(s):
    import datetime
    y, m, d = _date_tuple(s.game_date_code())
    try:
        return datetime.date(y, m, d).toordinal()
    except Exception:
        return 0


def _my_league_tid(M, my, season):
    cnt = {}
    for m in M['matches']:
        if m['season'] == season and my in (m['home'], m['away']) and m['home'] != m['away']:
            cnt[m['tid']] = cnt.get(m['tid'], 0) + 1
    return max(cnt, key=lambda k: cnt[k]) if cnt else None


def _league_list(slot):
    try:
        cv = comps_view(slot)
    except Exception:
        return []
    return [c for c in cv.get('comps') or [] if c.get('kind') == 'league' and isinstance(c.get('tid'), int) and len(c.get('rows') or []) >= 6]


def _pinfo(s, pid, ci=None):
    o, a = rat(pid)
    return dict(id=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=o, age=a,
                club=seasonstats.club_name(s.d, ci) if ci is not None else None, ci=ci)


def _totw_weeks(slot, s, M, tid, season):
    ms = [m for m in M['matches'] if m['played'] and m['tid'] == tid and m['season'] == season and m['home'] != m['away']]
    by = {}
    for m in ms:
        by.setdefault(awardslib.week_key(m), []).append(m)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    out = []
    for k in sorted(by):
        t = awardslib.totw(by[k], lambda p: POS.get(p, 5), lambda p, ci: _pinfo(s, p, ci))
        for e in t['xi']:
            e['mine'] = e['ci'] == my
        out.append(dict(key='%d-%d' % k, k=k, label=awardslib.week_label(k), end=awardslib.week_end_ord(k), **t))
    return out


def totw_view(slot, tid=None, week=None):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    seasons = seasonstats.played_seasons(M)
    if not seasons:
        return dict(leagues=[], weeks=[])
    season = seasons[-1]
    mytid = _my_league_tid(M, my, season)
    leagues = [dict(tid=c['tid'], name=official_comp_name(c['tid'], c.get('name')), mine=c['tid'] == mytid) for c in _league_list(slot)]
    tid = int(tid) if tid not in (None, '') else mytid
    W = _totw_weeks(slot, s, M, tid, season)
    today = _today_ord(s)
    sel = next((w for w in W if w['key'] == week), None) or (W[-1] if W else None)
    apps = {}
    for w in W:
        for e in w['xi']:
            a = apps.setdefault(e['id'], dict(e, n=0, potw=0))
            a['n'] += 1
            if w['potw'] and w['potw']['id'] == e['id']:
                a['potw'] += 1
    lead = sorted(apps.values(), key=lambda a: (-a['n'], -a['potw'], a['name']))[:12]
    for a in lead:
        a.pop('sc', None)
    return dict(leagues=leagues, tid=tid, league=next((l['name'] for l in leagues if l['tid'] == tid), ''), season=season,
                weeks=[dict(key=w['key'], label=w['label'], n=w['n'], done=w['end'] < today, potw=(w['potw'] or {}).get('name'),
                            mine=sum(1 for e in w['xi'] if e['mine'])) for w in W],
                week=(dict(key=sel['key'], label=sel['label'], n=sel['n'], done=sel['end'] < today, xi=sel['xi'], potw=sel['potw']) if sel else None),
                leaders=lead, my_count=sum(a['n'] for a in apps.values() if a.get('mine')))


def _league_weights(slot, s, M):
    """Snaga lige (prosjek najjacih 14 igraca klubova) -> tezina za Zlatnu loptu; i bodovi uspjeha klubova po tablici."""
    sq = {}
    for pid, ci in M['cur'].items():
        o = rat(pid)[0]
        if o:
            sq.setdefault(ci, []).append(o)
    cstr = {ci: sum(sorted(v, reverse=True)[:14]) / float(min(14, len(v))) for ci, v in sq.items() if len(v) >= 11}
    lw, cb, names = {}, {}, {}
    for c in _league_list(slot):
        rows = c.get('rows') or []
        st = [cstr[r['idx']] for r in rows if r.get('idx') in cstr]
        if not st:
            continue
        avg = sum(st) / len(st)
        w = max(0.45, min(1.25, 0.55 + (avg - 70) * 0.065))
        lw[c['tid']] = w
        names[c['tid']] = official_comp_name(c['tid'], c.get('name'))
        for r in rows:
            if r.get('pl', 0) >= 5:
                bonus = {1: 9, 2: 4.5, 3: 2.5, 4: 1.5}.get(r.get('pos'), 0)
                if bonus:
                    cb[r['idx']] = cb.get(r['idx'], 0) + bonus * w
    return lw, cb, names


EU_TIDS = (3, 5)


def ballon_view(slot, season=None):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    seasons = seasonstats.played_seasons(M)
    if not seasons:
        return dict(seasons=[], ranking=[])
    season = int(season) if season not in (None, '') else seasons[-1]
    lw, cb, lnames = _league_weights(slot, s, M)
    st = {}
    for m in M['matches']:
        if not m['played'] or m['season'] != season or m['home'] == m['away']:
            continue
        gh = seasonstats.match_score(m)[0]
        ga = seasonstats.match_score(m)[1]
        for pid, ci, g, a, r in m['rows']:
            x = st.setdefault(pid, dict(app=0, g=0, a=0, rs=0.0, cs=0, ci=ci, lg_apps={}, eu=0))
            x['app'] += 1
            x['g'] += g
            x['a'] += a
            x['rs'] += r
            x['ci'] = ci
            if (ga if ci == m['home'] else gh) == 0:
                x['cs'] += 1
            if m['tid'] in lw:
                x['lg_apps'][m['tid']] = x['lg_apps'].get(m['tid'], 0) + 1
            elif m['tid'] in EU_TIDS:
                x['eu'] += 1
    R = awardslib.ballon(st, lw, cb, lambda p: POS.get(p, 5), lambda p: rat(p)[1], lambda p: rat(p)[0])
    mytid = _my_league_tid(M, my, season)
    lm = [m for m in M['matches'] if m['tid'] == mytid and m['season'] == season]
    final = bool(lm) and all(m['played'] for m in lm) or any(m['season'] > season and m['played'] for m in M['matches'])

    def row(e, i):
        d = _pinfo(s, e['pid'], e['ci'])
        lg = max(st[e['pid']]['lg_apps'].items(), key=lambda kv: kv[1])[0] if st[e['pid']]['lg_apps'] else None
        d.update(rank=i + 1, pts=e['pts'], app=e['app'], g=e['g'], a=e['a'], cs=e['cs'], rating=e['rating'], mine=e['ci'] == my,
                 league=lnames.get(lg, ''))
        return d
    # pc245: Zlatnu loptu mogu dobiti samo igraci iz liga petica (vecina nastupa u PL, LaLigi, Serie A, Bundesligi ili Ligue 1)
    TOP5 = {17, 18, 19, 20, 116}
    def _top5(e):
        la = st.get(e['pid'], {}).get('lg_apps') or {}
        return bool(la) and max(la.items(), key=lambda kv: kv[1])[0] in TOP5
    RB = [e for e in R if _top5(e)] or R
    top = [row(e, i) for i, e in enumerate(RB[:30])]
    gb = [row(e, i) for i, e in enumerate([e for e in R if e['age'] and e['age'] <= 21][:10])]
    ya = [row(e, i) for i, e in enumerate([e for e in R if e['pos'] == 0][:10])]
    mine = [row(e, i) for i, e in enumerate(R) if e['ci'] == my][:5]
    for e in mine:
        e['rank'] = next((i + 1 for i, x in enumerate(RB) if x['pid'] == e['id']), None)
    played = sum(1 for m in lm if m['played'])
    return dict(seasons=seasons, season=season, final=final, progress=dict(played=played, total=len(lm)), ranking=top, golden_boy=gb, yashin=ya, mine=mine,
                leagues=sorted(({'name': lnames[t], 'w': round(w, 2)} for t, w in lw.items()), key=lambda x: -x['w'])[:12])


_AGR = {}


def _award_grants(slot):
    """Dodijeli bonuse za trening i moral za nagrade tvojih igraca (svaka nagrada samo jednom).
    Nagrade starije od 45 dana pri prvom pokretanju samo se zabiljeze (bez bonusa)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    key = (len(s.d), bytes(s.d[:64]), s.game_date_code())
    if _AGR.get(slot) == key:
        return []
    _AGR[slot] = key
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    seasons = seasonstats.played_seasons(M)
    if not seasons:
        return []
    today = _today_ord(s)
    found = []          # (kljuc, vrsta, pid, datum_ord, opis)
    season = seasons[-1]
    mytid = _my_league_tid(M, my, season)
    if mytid is not None:
        for w in _totw_weeks(slot, s, M, mytid, season):
            if w['end'] >= today:
                continue
            for e in w['xi']:
                if e['mine']:
                    found.append(('w:%s:%s:%s' % (mytid, w['key'], e['id']), 'totw', e['id'], w['end'], w['label']))
            if w['potw'] and w['potw'].get('mine'):
                found.append(('pw:%s:%s' % (mytid, w['key']), 'potw', w['potw']['id'], w['end'], w['label']))
    for se in seasons[-2:]:
        try:
            A = awards_view(slot, se)
        except Exception as ex:
            print('[awards] view:', ex)
            continue
        import datetime
        for mo in A.get('months') or []:
            if not mo.get('done'):
                continue
            d0 = datetime.date(mo['y'], mo['m'], 28).toordinal()
            for lab in ('potm', 'young', 'gk'):
                lst = mo.get(lab) or []
                if lst and lst[0].get('mine'):
                    found.append(('m:%s:%s-%s:%s' % (A.get('tid'), mo['y'], mo['m'], lab), lab, lst[0]['id'], d0, '%s/%s' % (mo['m'], mo['y'])))
            g_ = mo.get('goal')
            if g_ and g_.get('mine'):
                found.append(('m:%s:%s-%s:goal' % (A.get('tid'), mo['y'], mo['m']), 'goal', g_['id'], d0, '%s/%s' % (mo['m'], mo['y'])))
        sa = A.get('season_awards') or {}
        if sa.get('final'):
            d0 = datetime.date(se + 1, 6, 30).toordinal()
            for lab, k_ in (('pots', 'pots'), ('young', 'young_season'), ('glove', 'glove'), ('boot', 'boot')):
                lst = sa.get(lab) or []
                if lst and lst[0].get('mine'):
                    found.append(('s:%s:%s:%s' % (A.get('tid'), se, k_), k_, lst[0]['id'], d0, str(se)))
            for grp_, lst in (sa.get('team') or {}).items():
                for e in lst or []:
                    if e.get('mine'):
                        found.append(('ts:%s:%s:%s' % (A.get('tid'), se, e['id']), 'tots', e['id'], d0, str(se)))
        try:
            B = ballon_view(slot, se)
        except Exception as ex:
            print('[awards] ballon:', ex)
            B = {}
        if B.get('final'):
            d0 = datetime.date(se + 1, 7, 15).toordinal()
            rk = B.get('ranking') or []
            for e in rk[:10]:
                if e.get('mine'):
                    k_ = 'ballon' if e['rank'] == 1 else 'ballon_top3' if e['rank'] <= 3 else 'ballon_top10'
                    found.append(('bd:%s:%s' % (se, e['id']), k_, e['id'], d0, str(se)))
            for lab, lst in (('golden_boy', B.get('golden_boy')), ('yashin', B.get('yashin'))):
                if lst and lst[0].get('mine'):
                    found.append(('%s:%s' % (lab, se), lab, lst[0]['id'], d0, str(se)))
            try:
                its = []
                for e in rk[:3]:
                    its.append(('award', '%04d-07-15' % (se + 1), 'bd:%s:%s' % (se, e['id']), e['id'], [e.get('club')],
                                dict(award='ballon' if e['rank'] == 1 else 'ballon_top3', period='season', season_y=se, rank=e['rank'], name=e['name'], club=e.get('club'), mine=e.get('mine'))))
                for lab, lst in (('golden_boy', B.get('golden_boy')), ('yashin', B.get('yashin'))):
                    if lst:
                        e = lst[0]
                        its.append(('award', '%04d-07-15' % (se + 1), '%s:%s' % (lab, se), e['id'], [e.get('club')],
                                    dict(award=lab, period='season', season_y=se, name=e['name'], club=e.get('club'), mine=e.get('mine'))))
                world(slot, s).add_many(its)
            except Exception as ex:
                print('[world] ballon:', ex)
    if not found:
        return []
    gs = growth.load_state(HERE)
    sl = gs.setdefault(slot, {})
    keys = set(sl.get('award_keys') or [])
    first = 'award_keys' not in sl
    ab = sl.setdefault('award_bonus', {})
    pst = sl.setdefault('players', {})
    new, aff = [], []
    squad = set(s.my_squad_tags())
    for k, kind, pid, d0, lbl in found:
        if k in keys:
            continue
        keys.add(k)
        if pid not in squad or (first and today - d0 > 45) or today - d0 > 400:
            continue
        pts, a_, label = awardslib.BONUS[kind]
        ab[str(pid)] = round(ab.get(str(pid), 0) + pts, 3)
        if awardslib.POT_UP.get(kind):
            p_ = pst.setdefault(str(pid), {})
            p_['bump'] = p_.get('bump', 0) + awardslib.POT_UP[kind]
        aff.append((pid, 'Affection', a_))
        new.append(dict(kind=kind, pid=pid, label=label, when=lbl, pts=pts, aff=a_))
    sl['award_keys'] = sorted(keys)[-3000:]
    growth.save_state(HERE, gs)
    if aff:
        agg = {}
        for p_, f_, d_ in aff:
            agg[p_] = agg.get(p_, 0) + d_
        rows = [(p_, 'Affection', min(24, d_)) for p_, d_ in agg.items()]
        try:
            for p_, f_, d_, n_ in press.chunks(rows):
                growth.queue(CFG, [(p_, f_, d_)], 'aw%d-%d' % (today, n_))
        except Exception as ex:
            print('[awards] queue:', ex)
    big = [n for n in new if n['kind'] != 'totw']
    tw = {}
    for n in new:
        if n['kind'] == 'totw':
            tw.setdefault(n['when'], []).append(n['pid'])
    try:
        for n in big:
            _ev_add(slot, 'award', n['pid'], award=n['kind'], label=n['label'], period=n['when'], pts=n['pts'])
        for wk, pids in list(tw.items())[-3:]:
            _ev_add(slot, 'totw', pids[0], week=wk, pids=pids, names=[NAMES.get(p, str(p)) for p in pids])
    except Exception as ex:
        print('[awards] events:', ex)
    return new


def _award_grants_safe(slot):
    try:
        return _award_grants(slot)
    except Exception as ex:
        print('[awards] grants:', ex)
        return []



# ---------------------------------------------------------------- AI postave po vaznosti utakmice (pc96)
def _club_strengths(M):
    sq = {}
    for pid, ci in M['cur'].items():
        o = rat(pid)[0]
        if o:
            sq.setdefault(ci, []).append(o)
    return {ci: sum(sorted(v, reverse=True)[:14]) / float(min(14, len(v))) for ci, v in sq.items() if len(v) >= 11}


def ai_lineups_plan(slot, s, M, my, horizon=10):
    """Za sljedecu utakmicu (lige ili Europe, u iducih `horizon` dana) svakog AI kluba: vaznost i nova postava.
    -> lista dict(idx, club, n, date, opp, level, why, new=[redoslijed indeksa], xi=[pid], out=[pid], inn=[pid])"""
    import datetime
    y, mo, d = _date_tuple(s.game_date_code())
    today = datetime.date(y, mo, d)
    leagues = _league_list(slot)
    ltids = {c['tid'] for c in leagues}
    table = {}
    for c in leagues:
        rows = c.get('rows') or []
        n = len(rows)
        if n < 6:
            continue
        srt = sorted(rows, key=lambda r: r.get('pos') or 99)
        lead = srt[0].get('pts', 0)
        safe = srt[n - 3].get('pts', 0) if n >= 4 else 0
        for r in rows:
            table[r['idx']] = dict(pos=r.get('pos'), n=n, pts=r.get('pts', 0), pl=r.get('pl', 0), leader_pts=lead, safe_pts=safe, tid=c['tid'])
    cstr = _club_strengths(M)
    up = {}
    _clim = mlsave.club_layout(s.d)[0]
    for x in M['matches']:
        if x['played'] or x['home'] == x['away'] or x['home'] >= _clim or x['away'] >= _clim:   # pc256: granica klubova iz club_layout
            continue
        if x['tid'] not in ltids and x['tid'] not in ailineup.EU_TIDS:
            continue
        try:
            dt = datetime.date(x['y'], x['m'], x['dd'])
        except Exception:
            continue
        if dt < today or (dt - today).days > 60:
            continue
        for ci in (x['home'], x['away']):
            up.setdefault(ci, []).append((dt, x))
    recent = {}
    played = sorted([x for x in M['matches'] if x['played']], key=seasonstats.sort_key)[-4000:]
    for x in played:
        try:
            dt = datetime.date(x['y'], x['m'], x['dd'])
        except Exception:
            continue
        for pid, ci, g, a, r in x['rows']:
            recent.setdefault(pid, []).append((dt, r, ci))
    out = []
    try:   # pc353: ozljede (Injuries For All / dump) za hitnu formaciju
        inj_w, _src = world_injuries()
    except Exception:
        inj_w = {}
    lib_ = None
    for ci, L in up.items():
        if ci == my:
            continue
        L.sort(key=lambda t: t[0])
        dt, x = L[0]
        if (dt - today).days > horizon:
            continue
        try:
            roles = [int(v) for v in s.d[s.PLAN0 + 600 * ci:s.PLAN0 + 600 * ci + 10]]
            if any(r_ < 1 or r_ > 12 for r_ in roles):
                continue
            o = mlwrite.REC0 + ci * mlwrite.STRIDE
            n = s.d[o + 1058]
            sq = [struct.unpack_from('<I', s.d, o + mlwrite.SQUAD_OFF + 8 * k)[0] for k in range(n)]
            blo = s.TAC0 + 600 * ci + 484
            BL = [int(v) for v in s.d[blo:blo + n]]
        except Exception:
            continue
        if n < 14 or sorted(BL) != list(range(n)):
            continue
        opp = x['away'] if x['home'] == ci else x['home']
        kind = 'eu' if x['tid'] in ailineup.EU_TIDS else 'league'
        tb = table.get(ci) or {}
        nxt = L[1] if len(L) > 1 else None
        # zadnja odigrana utakmica kluba
        lastd = None
        for pid in sq:
            for t, r, c2 in reversed(recent.get(pid, [])):
                if c2 == ci:
                    lastd = t if lastd is None or t > lastd else lastd
                    break
        ctx = dict(kind=kind, my_str=cstr.get(ci), opp_str=cstr.get(opp), pos=tb.get('pos'), n=tb.get('n'), pts=tb.get('pts'),
                   leader_pts=tb.get('leader_pts'), safe_pts=tb.get('safe_pts'),
                   progress=(tb.get('pl', 0) / float(2 * (tb['n'] - 1))) if tb.get('n') else 0,
                   days_since=((dt - lastd).days if lastd else None), days_to_next=((nxt[0] - dt).days if nxt else None),
                   next_kind=(('eu' if nxt[1]['tid'] in ailineup.EU_TIDS else 'league') if nxt else None))
        level, score, why = ailineup.importance(ctx)
        congested = (ctx['days_since'] is not None and ctx['days_since'] <= 3) or (ctx['days_to_next'] is not None and ctx['days_to_next'] <= 2)
        if congested:
            why.append('congested')
        # pc353 (Alex): hitna formacija - ozljede ostave ulogu formacije bez igraca -> za tu utakmicu sustav koji momcad moze popuniti
        if inj_w and EMERG_FORMATION:
            try:
                dd_ = max(1, (dt - today).days + 1)
                avail = {i for i in range(n) if inj_w.get(sq[i], 0) < dd_}
                need = {}
                for r_ in roles:
                    need[r_] = need.get(r_, 0) + 1
                short = [r_ for r_, k_ in need.items() if sum(1 for i in avail if mlwrite.DIST[r_][POS.get(sq[i], 5)] <= 1) < k_]
                if short and len(avail) >= 13:
                    if lib_ is None:
                        lib_ = _formation_library(s)
                    cur_lab = mlwrite.plan_label(roles)
                    fit_ = {r_: sum(1 for i in avail if mlwrite.DIST[r_][POS.get(sq[i], 5)] <= 1) for r_ in range(1, 13)}

                    def _gap(lab):   # koliko uloga formacije ostaje bez igraca
                        rl = list(lib_[lab][:10])
                        return sum(max(0, rl.count(r_) - fit_.get(r_, 0)) for r_ in set(rl))
                    order = sorted((lab for lab in lib_ if lab != cur_lab and _gap(lab) == 0),
                                   key=lambda lab: -sum(min(need.get(r_, 0), list(lib_[lab][:10]).count(r_)) for r_ in set(lib_[lab][:10])))
                    fs = _formation_switch(s, ci, '', None, lib_, avail=avail, cands=order[:12])
                    if fs:
                        cur11 = [sq[b] for b in BL[:11]]
                        xi_p = [sq[b] for b in fs['new'][:11]]
                        out.append(dict(idx=ci, club=seasonstats.club_name(s.d, ci), n=x['n'], tid=x['tid'], date='%02d.%02d.%d' % (x['dd'], x['m'], x['y']),
                                        opp=seasonstats.club_name(s.d, opp), opp_idx=opp, home=x['home'] == ci, level=level, score=score,
                                        why=why + ['emergency_formation'], new=fs['new'], blo=blo, xi=xi_p,
                                        out=[p for p in cur11 if p not in xi_p], inn=[p for p in xi_p if p not in cur11],
                                        form=dict(plan=fs['plan'], blk=fs['blk'].hex(), orig=bytes(s.d[fs['plan']:fs['plan'] + len(fs['blk'])]).hex(),
                                                  frm=fs['frm'], to=fs['to'], short=[mlwrite.POS_NAMES[r_] if hasattr(mlwrite, 'POS_NAMES') else r_ for r_ in short])))
                        continue
            except Exception as ex:
                print('[emergency formation]', ex)
        if level == 'normal' and not congested:
            continue
        squad = []
        for i in range(n):
            pid = sq[i]
            ov, ag = rat(pid)
            if not ov:
                continue
            rr = [r for t, r, c2 in recent.get(pid, []) if t < dt][-5:]
            form = (sum(rr) / len(rr) - 6.3) if len(rr) >= 2 else 0.0
            tired = any(0 <= (dt - t).days <= 3 for t, r, c2 in recent.get(pid, []))
            squad.append(dict(i=i, pid=pid, pos=POS.get(pid, 5), ovr=ov, age=ag, form=form, tired=tired))
        if len(squad) < 14 or not any(p['pos'] == 0 for p in squad):
            continue
        xi, bench = ailineup.pick_xi([0] + roles, squad, mlwrite.DIST, level, congested, '%s|%s|%s' % (slot, ci, x['n']), BL[:11])
        if set(xi) == set(BL[:11]):
            continue
        new = xi + bench + [b for b in BL if b not in xi and b not in bench]
        if sorted(new) != list(range(n)):
            continue
        cur11 = [sq[b] for b in BL[:11]]
        xi_p = [sq[b] for b in xi]
        out.append(dict(idx=ci, club=seasonstats.club_name(s.d, ci), n=x['n'], tid=x['tid'], date='%02d.%02d.%d' % (x['dd'], x['m'], x['y']),
                        opp=seasonstats.club_name(s.d, opp), opp_idx=opp, home=x['home'] == ci, level=level, score=score, why=why,
                        new=new, blo=blo, xi=xi_p, out=[p for p in cur11 if p not in xi_p], inn=[p for p in xi_p if p not in cur11]))
    return out


EMERG_FORMATION = True


def _emerg_restore(s, lu, M):
    """pc353: hitne formacije: kad je utakmica odigrana, klub se vraca na svoju formaciju (postava prema njoj). -> [(plan, blk, blo, new)]"""
    E = lu.get('emerg') or {}
    if not E:
        return []
    done = {x['n'] for x in M['matches'] if x['played']}
    out = []
    for k, e in list(E.items()):
        if e['n'] not in done:
            continue
        ci = int(k)
        orig = bytes.fromhex(e['orig'])
        lab = mlwrite.plan_label(list(orig[:10]))
        try:
            fs = _formation_switch(s, ci, '', None, {lab: orig}, force_lab=lab)
        except Exception:
            fs = None
        if fs:
            out.append((e['plan'], orig, fs['blo'], fs['new']))
        else:
            out.append((e['plan'], orig, None, None))
        E.pop(k, None)
    return out


def _lu_verify(lu, M):
    """Usporedi planirane postave s odigranim utakmicama (redovi utakmice = prvih 11)."""
    done = {}
    for x in M['matches']:
        if x['played']:
            done[x['n']] = x
    st = lu.setdefault('stats', dict(n=0, hit=0))
    keep = {}
    for k, pl in (lu.get('plans') or {}).items():
        x = done.get(pl['n'])
        if x is None:
            keep[k] = pl
            continue
        real = [r[0] for r in x['rows'] if r[1] == pl['idx']]
        if len(real) != 11:
            continue
        h = len(set(real) & set(pl['xi']))
        st['n'] += 1
        st['hit'] += h
        hist = lu.setdefault('checked', [])
        hist.append(dict(club=pl['club'], date=pl['date'], level=pl['level'], hit=h))
        del hist[:-60]
    lu['plans'] = keep



# ---------------------------------------------------------------- Identitet sezone: price koje se prate (pc96)
STORY_FILE = os.path.join(HERE, 'data', 'stories.json')


def _stories_all():
    try:
        return json.load(open(STORY_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _club_idx_by_name(s, name):
    for ci in range(mlsave.club_layout(s.d)[0]):   # pc256: i klubovi iznad 750 (60 MB)
        try:
            if seasonstats.club_name(s.d, ci) == name:
                return ci
        except Exception:
            break
    return None


def _story_create(slot, s, M, my, season, lg, prev):
    """Glavne price sezone iz stanja na pocetku (ili kad se prvi put otvori): utrka za naslov, borba za opstanak,
    wonderkid, trener pod pritiskom, tvoja misija, povratak, utrka strijelaca + naslijedene iz prosle sezone."""
    rows = lg.get('rows') or []
    cstr = _club_strengths(M)
    lig = [r['idx'] for r in rows if r.get('idx') is not None]
    by_str = sorted(lig, key=lambda i: -cstr.get(i, 60))
    cn = lambda ci: seasonstats.club_name(s.d, ci)
    st = []
    fav = by_str[:3]
    st.append(dict(kind='title', title='The title race', clubs=[cn(c) for c in fav], idx=fav,
                   teaser='%s start as favourites, with %s and %s close behind.' % (cn(fav[0]), cn(fav[1]), cn(fav[2]))))
    if prev and prev.get('champion'):
        ch = prev['champion']
        st.append(dict(kind='defend', title='Can %s defend the title?' % ch, clubs=[ch], idx=[_club_idx_by_name(s, ch)],
                       teaser='Last season\'s champions start with a target on their backs.'))
    bot = by_str[-4:]
    st.append(dict(kind='relegation', title='The fight to stay up', clubs=[cn(c) for c in bot], idx=bot,
                   teaser='On paper %s look most at risk.' % ', '.join(cn(c) for c in bot[:3])))
    # wonderkid: najbolji igrac do 21 u ligi (OVR + potencijal)
    best = None
    for pid, ci in M['cur'].items():
        if ci not in lig:
            continue
        ov, ag = rat(pid)
        if not ov or not ag or ag > 21:
            continue
        pot = growth.potential(pid, ag, ov, POS.get(pid, 5))
        sc = ov + 0.6 * pot
        if best is None or sc > best[0]:
            best = (sc, pid, ci, ov, ag, pot)
    if best:
        _, pid, ci, ov, ag, pot = best
        st.append(dict(kind='wonderkid', title='Wonderkid watch: %s' % NAMES.get(pid, ''), pid=pid, clubs=[cn(ci)], idx=[ci],
                       teaser='%d years old, OVR %d at %s. Everyone is watching to see how far he goes.' % (ag, ov, cn(ci))))
    # trener pod pritiskom: drugi najjaci klub (ocekuje se naslov), ili klub s najvecim podbacivanjem ako se vec igralo
    hot = None
    pl_ = max([r.get('pl', 0) for r in rows] or [0])
    if pl_ >= 4:
        exp = {c: k + 1 for k, c in enumerate(by_str)}
        cands = [(r['pos'] - exp.get(r['idx'], r['pos']), r['idx']) for r in rows if exp.get(r['idx'], 99) <= 6 and r['idx'] != my]
        if cands:
            g, hot = max(cands)
            if g < 3:
                hot = None
    if hot is None:
        hot = next((c for c in by_str[:4] if c != my and c != fav[0]), None)
    if hot is not None:
        st.append(dict(kind='hotseat', title='Under pressure at %s' % cn(hot), clubs=[cn(hot)], idx=[hot],
                       teaser='Anything less than a top-%d finish and the %s manager could be gone.' % (max(2, by_str.index(hot) + 1), cn(hot))))
    # tvoja misija
    try:
        B = board_view(slot)
        if B.get('goal_txt'):
            st.append(dict(kind='mission', title='Your mission: %s' % B['goal_txt'], clubs=[cn(my)], idx=[my], target=B.get('target'),
                           teaser='The board has set the target. Your reputation depends on it.'))
        jobs = [j for j in (B.get('jobs') or []) if j.get('club') and j['club'] != cn(my)]
    except Exception:
        jobs = []
    # povratak: tvoj bivsi klub u ligi, ili igrac kojeg si prodao
    ret = None
    for j in reversed(jobs):
        ci = _club_idx_by_name(s, j['club'])
        if ci in lig:
            ret = dict(kind='return', title='Back to %s' % j['club'], clubs=[j['club']], idx=[ci], who='you',
                       teaser='You %s %s. This season you face them again.' % ('were sacked by' if j.get('reason') == 'sacked' else 'left', j['club']))
            break
    if not ret:
        sold = [e for e in _ev_all(slot) if e.get('kind') == 'sold' and e.get('pid')]
        for e in reversed(sold):
            ci = M['cur'].get(int(e['pid']))
            if ci in lig and ci != my:
                ret = dict(kind='return', title='%s against his old club' % NAMES.get(int(e['pid']), ''), pid=int(e['pid']), clubs=[cn(ci)], idx=[ci], who='player',
                           teaser='You sold him to %s. Now he wants to show you what you lost.' % cn(ci))
                break
    if ret:
        st.append(ret)
    if prev and prev.get('nemesis'):
        nm = prev['nemesis']
        st.append(dict(kind='revenge', title='Revenge on %s?' % nm, clubs=[nm], idx=[_club_idx_by_name(s, nm)],
                       teaser='Last season they %s.' % prev.get('nemesis_why', 'had the better of you')))
    st.append(dict(kind='boot', title='The Golden Boot race', clubs=[], idx=[], teaser='Who will finish as the league\'s top scorer?'))
    for i, x in enumerate(st):
        x['id'] = '%s-%d' % (x['kind'], i)
    return st


def _story_status(slot, s, M, my, season, lg, x, final):
    """Trenutno stanje price (i zavrsetak kad je sezona gotova). -> (tekst, zavrseno_tekst ili None, ishod 'good'|'bad'|None)"""
    rows = sorted(lg.get('rows') or [], key=lambda r: r.get('pos') or 99)
    cn = lambda ci: seasonstats.club_name(s.d, ci)
    if not rows:
        return '', None, None
    # pc298: prije prvog kola nema smisla 'X vodi s 0 bodova, 0 ispred Y'
    if not any((r.get('pl') or r.get('p') or r.get('played') or r.get('pts') or 0) for r in rows):
        return 'The season has not started yet.', None, None
    pos = {r['idx']: r for r in rows}
    k = x['kind']
    n = len(rows)
    if k in ('title', 'defend'):
        lead = rows[0]
        sec = rows[1]
        txt = '%s lead with %d points, %d ahead of %s.' % (lead['club'], lead['pts'], lead['pts'] - sec['pts'], sec['club'])
        if k == 'defend' and x['idx'] and x['idx'][0] in pos:
            r = pos[x['idx'][0]]
            txt = '%s are %d%s, %d points off the top.' % (r['club'], r['pos'], _ordsfx(r['pos']), lead['pts'] - r['pts'])
        if final:
            if k == 'title':
                fav = lead['idx'] in x['idx']
                return txt, '%s are champions%s.' % (lead['club'], '' if fav else ', against the odds'), 'good' if lead['idx'] == my else None
            ok = x['idx'] and lead['idx'] == x['idx'][0]
            return txt, ('They did it: back-to-back titles.' if ok else 'The crown has a new owner: %s.' % lead['club']), None
        return txt, None, None
    if k == 'relegation':
        b3 = rows[-3:]
        txt = 'In the drop zone now: %s.' % ', '.join(r['club'] for r in b3)
        if final:
            return txt, 'Relegated: %s.' % ', '.join(r['club'] for r in b3), ('bad' if my in [r['idx'] for r in b3] else None)
        return txt, None, None
    if k == 'wonderkid':
        a = seasonstats.agg(M, season).get(x.get('pid')) or dict(app=0, g=0, a=0, rs=0)
        rt = (a['rs'] / a['app']) if a['app'] else 0
        txt = '%d apps, %d goals, %d assists%s.' % (a['app'], a['g'], a['a'], (', average rating %.2f' % rt) if a['app'] else '')
        if final:
            good = a['app'] >= 20 and (a['g'] + a['a'] >= 12 or rt >= 6.9)
            return txt, ('A breakthrough season. A star is born.' if good else 'Not the season everyone expected. Next year will tell.'), None
        return txt, None, None
    if k == 'hotseat':
        ci = x['idx'][0] if x['idx'] else None
        r = pos.get(ci)
        sacked = False
        try:
            e = auto_view().get(slot) or {}
            lg_ = ((e.get('tac') or {}).get('log') or [])
            sacked = any(l.get('kind') == 'coach' and l.get('coach_ev') == 'sacked' and l.get('name') == cn(ci) for l in lg_)
        except Exception:
            pass
        txt = ('%s are %d%s.' % (r['club'], r['pos'], _ordsfx(r['pos'])) if r else '') + (' The manager has already been sacked.' if sacked else '')
        if sacked:
            return txt, 'The board pulled the trigger: the manager was sacked.', None
        if final:
            return txt, 'The manager survived the season.', None
        return txt, None, None
    if k == 'mission':
        r = pos.get(my)
        tg = x.get('target') or n
        txt = ('You are %d%s, the target is top %d.' % (r['pos'], _ordsfx(r['pos']), tg)) if r else ''
        if final and r:
            ok = r['pos'] <= tg
            return txt, ('Mission accomplished.' if ok else 'Mission failed.'), ('good' if ok else 'bad')
        return txt, None, None
    if k in ('return', 'revenge'):
        ci = x['idx'][0] if x['idx'] else None
        res = []
        for m in sorted(M['matches'], key=seasonstats.sort_key):
            if m['season'] != season or not m['played'] or m['tid'] != lg['tid'] or {m['home'], m['away']} != {my, ci}:
                continue
            gf, ga = seasonstats.match_score_for(m, my)
            res.append('W' if gf > ga else 'L' if gf < ga else 'D')
            if x.get('who') == 'player' and x.get('pid'):
                g_ = sum(r_[2] for r_ in m['rows'] if r_[0] == x['pid'])
                if g_:
                    res[-1] += '*'
        txt = ('Results so far: %s.' % ' '.join(res)) if res else 'You have not met yet.'
        if final or len(res) >= 2:
            w = sum(1 for r_ in res if r_.startswith('W'))
            l = sum(1 for r_ in res if r_.startswith('L'))
            done = ('You came out on top.' if w > l else 'They had the last laugh.' if l > w else 'Honours even.')
            return txt, done, ('good' if w > l else 'bad' if l > w else None)
        return txt, None, None
    if k == 'boot':
        A = seasonstats.agg(M, season, tid=lg['tid'])
        top = sorted(A.items(), key=lambda kv: (-kv[1]['g'], kv[1]['app']))[:3]
        txt = ', '.join('%s %d' % (NAMES.get(p, str(p)), a['g']) for p, a in top)
        if final and top:
            return txt, '%s wins the Golden Boot with %d goals.' % (NAMES.get(top[0][0], ''), top[0][1]['g']), ('good' if M['cur'].get(top[0][0]) == my else None)
        return txt, None, None
    return '', None, None


def _ordsfx(n):
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(n if n < 20 else n % 10, 'th')


def stories_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    seasons = seasonstats.played_seasons(M)
    y, mo, d = _date_tuple(s.game_date_code())
    season = seasons[-1] if seasons else (y if mo >= 7 else y - 1)
    tid = _my_league_tid(M, my, season)
    lg = next((c for c in _league_list(slot) if c['tid'] == tid), None)
    if not lg:
        return dict(season=season, stories=[], prev=None)
    cid = _career_id(slot, s)
    A = _stories_all()
    C = A.setdefault(cid, {})
    key = str(season)
    prev = (C.get(str(season - 1)) or {}).get('snap')
    lm = [m for m in M['matches'] if m['tid'] == tid and m['season'] == season]
    final = bool(lm) and all(m['played'] for m in lm)
    ch = False
    if key not in C:
        C[key] = dict(created=_fmt_date(s.game_date_code()), league=official_comp_name(tid, lg.get('name')), stories=_story_create(slot, s, M, my, season, lg, prev))
        ch = True
        try:
            _ev_add(slot, 'season_preview', None, season=season, titles=[x['title'] for x in C[key]['stories']])
            world(slot, s).add_many([('story_open', worldlib.date_str(s.game_date_code()), 'so:%s:%s' % (season, x['id']), x.get('pid'), x.get('clubs') or [],
                                      dict(title=x['title'], kind=x['kind'], season_y=season)) for x in C[key]['stories']])
        except Exception as ex:
            print('[stories] open:', ex)
    S_ = C[key]
    out = []
    closed_now = []
    for x in S_['stories']:
        try:
            txt, done, outc = _story_status(slot, s, M, my, season, lg, x, final)
        except Exception as ex:
            txt, done, outc = '', None, None
            print('[stories]', x.get('kind'), ex)
        if done and not x.get('closed'):
            x['closed'] = done
            x['outcome'] = outc
            x['closed_on'] = _fmt_date(s.game_date_code())
            closed_now.append(x)
            ch = True
        out.append(dict(x, now=txt))
    if final and not S_.get('snap'):
        rows = sorted(lg.get('rows') or [], key=lambda r: r.get('pos') or 99)
        nem, why_ = None, None
        for m in lm:
            pass
        rec = {}
        for m in lm:
            if my not in (m['home'], m['away']):
                continue
            op = m['away'] if m['home'] == my else m['home']
            gf, ga = seasonstats.match_score_for(m, my)
            r_ = rec.setdefault(op, [0, 0])
            r_[0] += 1 if ga > gf else 0
            r_[1] += ga - gf
        if rec:
            op, (ls, gd_) = max(rec.items(), key=lambda kv: (kv[1][0], kv[1][1]))
            if ls >= 2 or gd_ >= 4:
                nem = seasonstats.club_name(s.d, op)
                why_ = 'beat you twice' if ls >= 2 else 'humiliated you'
        mr = next((r for r in rows if r['idx'] == my), None)
        S_['snap'] = dict(champion=rows[0]['club'] if rows else None, relegated=[r['club'] for r in rows[-3:]], my_pos=mr['pos'] if mr else None,
                          nemesis=nem, nemesis_why=why_)
        ch = True
    try:
        if _retire_check(slot, s, M, my, C, key):
            ch = True
        if _retire_confirm(slot, s, M, C):
            ch = True
    except Exception as ex:
        print('[retire]', ex)
    if final and not S_.get('finale'):
        try:
            S_['finale'] = _season_finale(slot, s, M, my, season, lm, lg)
            ch = True
            F_ = S_['finale']
            for k_ in ('title', 'escape', 'goal', 'verdict'):
                if F_.get(k_):
                    _ev_add(slot, 'finale', F_[k_].get('pid') if k_ == 'goal' else None, part=k_, txt=F_[k_]['txt'], kind2=F_[k_].get('kind'))
        except Exception as ex:
            print('[finale]', ex)
    if closed_now:
        try:
            for x in closed_now:
                if x['kind'] in ('mission', 'return', 'revenge', 'title') or x.get('outcome'):
                    _ev_add(slot, 'story_close', x.get('pid'), title=x['title'], closed=x['closed'], outcome=x.get('outcome'))
            world(slot, s).add_many([('story_close', worldlib.date_str(s.game_date_code()), 'sc:%s:%s' % (season, x['id']), x.get('pid'), x.get('clubs') or [],
                                      dict(title=x['title'], kind=x['kind'], closed=x['closed'], season_y=season)) for x in closed_now])
        except Exception as ex:
            print('[stories] close:', ex)
    if ch:
        _jdump(A, STORY_FILE, ensure_ascii=False, indent=1)
    past = []
    for k_, v in sorted(C.items()):
        if k_ != key and isinstance(v, dict):
            past.append(dict(season=int(k_), league=v.get('league'), snap=v.get('snap'), stories=[dict(title=x['title'], closed=x.get('closed'), outcome=x.get('outcome'), kind=x['kind']) for x in v.get('stories', [])]))
    retire = [dict(pid=int(k_), **v) for k_, v in (S_.get('retire') or {}).items() if v.get('state') in ('announced', 'retired')]
    extra = {}
    try:
        extra = _stories_extra(slot, s, M, my, season, lg, lm, out)
    except Exception as ex:
        print('[stories] extra:', ex)
    return dict(season=season, league=S_.get('league'), created=S_.get('created'), final=final, stories=out, prev=prev, past=past[::-1],
                finale=S_.get('finale'), retire=retire, my=seasonstats.club_name(s.d, my), **extra)


def _stories_extra(slot, s, M, my, season, lg, lm, out):
    """Podaci za izgled stranice: tablica lige, strijelci, wonderkid, misija, raspored, kljucni datumi, napredak sezone."""
    import datetime
    cn = lambda ci: seasonstats.club_name(s.d, ci)
    rows = sorted(lg.get('rows') or [], key=lambda r: r.get('pos') or 99)
    table = [dict(pos=r['pos'], club=r['club'], pts=r.get('pts', 0), pl=r.get('pl', 0), gd=r.get('gd', 0), mine=r['idx'] == my) for r in rows]
    mym = [m for m in lm if my in (m['home'], m['away'])]
    prog = dict(played=sum(1 for m in mym if m['played']), total=len(mym))
    A = seasonstats.agg(M, season, tid=lg['tid'])
    boot = [dict(pid=p, name=NAMES.get(p, str(p)), app=a['app'], g=a['g'], club=cn(a['clubs'][-1]) if a.get('clubs') else '')
            for p, a in sorted(A.items(), key=lambda kv: (-kv[1]['g'], kv[1]['app']))[:3]]
    for x in out:
        k = x['kind']
        if k == 'wonderkid' and x.get('pid'):
            ovr, age = rat(x['pid'])
            a = seasonstats.agg(M, season).get(x['pid']) or dict(app=0, g=0, a=0, rs=0)
            x['player'] = dict(pid=x['pid'], name=NAMES.get(x['pid'], ''), pos=POS.get(x['pid'], 5), age=age, ovr=ovr, app=a['app'], g=a['g'], a=a['a'],
                               rating=round(a['rs'] / a['app'], 2) if a['app'] else None)
        elif k == 'mission':
            r = next((t for t in table if t['mine']), None)
            x['bar'] = dict(pos=r['pos'] if r else None, target=x.get('target'), n=len(table))
        elif k in ('return', 'revenge'):
            res = []
            for m in sorted(lm, key=seasonstats.sort_key):
                if m['played'] and x.get('idx') and {m['home'], m['away']} == {my, x['idx'][0]}:
                    gf, ga = seasonstats.match_score_for(m, my)
                    res.append(dict(score='%d-%d' % (gf, ga), res='W' if gf > ga else 'L' if gf < ga else 'D', home=m['home'] == my))
            x['results'] = res
    # raspored: sljedecih 5 utakmica mog kluba (liga, Europa, kupovi u kojima smo)
    y, mo, d = _date_tuple(s.game_date_code())
    today = datetime.date(y, mo, d)
    names = {}
    try:
        for c in comps_view(slot).get('comps') or []:
            if isinstance(c.get('tid'), int):
                names[c['tid']] = official_comp_name(c['tid'], c.get('name'))
    except Exception:
        pass
    mytids = {m['tid'] for m in M['matches'] if m['played'] and my in (m['home'], m['away'])}
    fx = []
    for m in M['matches']:
        if m['played'] or my not in (m['home'], m['away']) or m['home'] == m['away'] or m['tid'] not in mytids:
            continue
        try:
            dt = datetime.date(m['y'], m['m'], m['dd'])
        except Exception:
            continue
        if dt < today:
            continue
        opp = m['away'] if m['home'] == my else m['home']
        if opp >= mlsave.club_layout(s.d)[0]:   # pc256
            continue
        fx.append((dt, dict(date=dt.strftime('%a %d %b'), comp=names.get(m['tid'], ''), opp=cn(opp), home=m['home'] == my)))
    fx.sort(key=lambda t: t[0])
    fixtures = [f for _, f in fx[:5]]
    # kljucni datumi
    kd = []
    def add(dt, t, c):
        if dt >= today:
            kd.append((dt, dict(date=dt.strftime('%a %d %b %Y'), t=t, c=c)))
    sy = season
    add(datetime.date(sy + 1, 1, 1), 'Winter transfer window opens', 'blue')
    add(datetime.date(sy + 1, 1, 31), 'Winter transfer window closes', 'red')
    last = max([datetime.date(m['y'], m['m'], m['dd']) for m in lm] or [today])
    add(last, '%s final day' % (names.get(lg['tid']) or 'League'), 'purple')
    add(datetime.date(sy + 1, 6, 30), 'End of season', 'purple')
    add(datetime.date(sy + 1, 7, 1), 'Summer transfer window opens', 'blue')
    add(datetime.date(sy, 8, 31), 'Summer transfer window closes', 'red')
    kd.sort(key=lambda t: t[0])
    return dict(table=table, boot=boot, progress=prog, fixtures=fixtures, keydates=[k for _, k in kd[:5]])



# ---------------------------------------------------------------- Zivot kluba: navijaci reagiraju na odluke (pc97)
_CSTART = {}


def _contract_starts(s):
    """{pid: datum pocetka ugovora (kod)} iz zapisa igraca (+148)."""
    key = (len(s.d), bytes(s.d[:64]))
    c = _CSTART.get('k')
    if c == key:
        return _CSTART['v']
    chunks, _ = s._chunks()
    big = b''.join(chunks)
    out = {}
    for k in range((len(big) - 144) // 156):
        r = 144 + 156 * k
        out[struct.unpack_from('<I', big, r + 48)[0]] = struct.unpack_from('<I', big, r + 148)[0]
    _CSTART.update(k=key, v=out)
    return out


def fan_favourite(slot, s, pid, M=None, my=None):
    """Koliko je igrac miljenik navijaca (0-100) i zasto: kvaliteta u momcadi, staz u klubu, nastupi i golovi ove sezone, nagrade."""
    M = M or _season(slot, s)
    my = my if my is not None else (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    why, sc = [], 0
    ovr, age = rat(pid)
    mo = sorted((rat(q)[0] for q in s.my_squad_tags() if rat(q)[0]), reverse=True)
    rk = sum(1 for o in mo if o > (ovr or 0)) + 1
    if rk <= 3:
        sc += 30; why.append('one of the best players')
    elif rk <= 7:
        sc += 15; why.append('a key player')
    try:
        st = _contract_starts(s).get(pid)
        y, m_, _ = _date_tuple(st) if st else (0, 0, 0)
        gy, gm, _ = _date_tuple(s.game_date_code())
        yrs = (gy - y) + (gm - m_) / 12.0 if y > 1990 else 0
        if yrs >= 4:
            sc += 25; why.append('%d years at the club' % int(yrs))
        elif yrs >= 2:
            sc += 12; why.append('%d years at the club' % int(yrs))
    except Exception:
        pass
    seasons = seasonstats.played_seasons(M)
    if seasons:
        a = seasonstats.agg(M, seasons[-1], club=my).get(pid)
        if a:
            if a['app'] >= 15:
                sc += 10; why.append('%d games this season' % a['app'])
            if a['g'] >= 5:
                sc += min(20, a['g'] * 2); why.append('%d goals this season' % a['g'])
    try:
        aw = [e for e in world(slot, s).player(pid)['awards'] if e.get('mine')]
        if aw:
            sc += min(15, 5 * len(aw)); why.append('%d awards' % len(aw))
    except Exception:
        pass
    if age and age >= 30 and rk <= 11:
        sc += 5
    return min(100, sc), why


def _fan_react(slot, kind, pid, kw):
    """Navijaci reagiraju na prodaju (i na veliko pojacanje): raspolozenje, vijest, malo i uprava."""
    if not pid or kind not in ('sold', 'signed'):
        return
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    delta, why, rival = 0, [], False
    if kind == 'sold':
        fav, why = fan_favourite(slot, s, pid, M, my)
        to = kw.get('to') or ''
        try:
            lg = next((c for c in _league_list(slot) if any(r.get('idx') == my for r in c.get('rows') or [])), None)
            rows = (lg or {}).get('rows') or []
            ti = _club_idx_by_name(s, to)
            mine_r = next((r for r in rows if r['idx'] == my), None)
            to_r = next((r for r in rows if r['idx'] == ti), None)
            if to_r and (to_r['pos'] <= 4 or (mine_r and to_r['pos'] < mine_r['pos'])):
                rival = True
        except Exception:
            pass
        delta = -round(fav / 8.0) - (4 if rival and fav >= 30 else 0)
        if fav < 25 and not rival:
            delta = 0
        if delta == 0:
            return
        fee = kw.get('fee') or 0
        try:
            mv = negotiate.estimate_value(*rat(pid)) if rat(pid)[0] else 0
            if fee and mv and fee >= 1.4 * mv:
                delta = int(delta * 0.6); why.append('the fee was huge')
        except Exception:
            pass
    else:
        ovr = rat(pid)[0] or 0
        mo = sorted((rat(q)[0] for q in s.my_squad_tags() if rat(q)[0] and q != pid), reverse=True)
        if not mo or ovr < mo[min(2, len(mo) - 1)]:
            return
        delta = 3 if ovr >= mo[0] else 2
        why = ['a statement signing']
        try:
            frm = kw.get('frm') or ''
            fi = _club_idx_by_name(s, frm)
            lg = next((c for c in _league_list(slot) if any(r.get('idx') == my for r in c.get('rows') or [])), None)
            if lg and any(r['idx'] == fi and r['pos'] <= 4 for r in lg.get('rows') or []):
                delta += 2; why.append('taken from a rival')
                rival = True
        except Exception:
            pass
    a = _press_load()
    st = a.setdefault(slot, {})
    st['fans'] = max(-20, min(20, st.get('fans', 0) + delta))
    _press_save(a)
    if delta <= -8:
        try:
            _board_adjust(slot, s, -2, 'fans_angry')
        except Exception:
            pass
    _ev_add(slot, 'fans_react', pid, delta=delta, why=why, rival=rival, act=kind, to=kw.get('to'), frm=kw.get('frm'), _nofan=True)



# ---------------------------------------------------------------- Zivot kluba: zvijezda odbija produljenje (pc97)
DRAMA_FILE = os.path.join(HERE, 'data', 'dramas.json')


def _drama_all():
    try:
        return json.load(open(DRAMA_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _drama_save(a):
    os.makedirs(os.path.dirname(DRAMA_FILE), exist_ok=True)
    _jdump(a, DRAMA_FILE, ensure_ascii=False, indent=1)


def drama_tick(slot, s, rows):
    """Kljucni igrac kojem istice ugovor (<= 12 mj.) moze odbiti produljenje: ambiciozan, malo odan ili prerastao klub.
    Javljaju se veci klubovi. Izbor: prodati sad, pustiti da ode besplatno, ili zadnji pokusaj (puno veca placa).
    -> {pid: stanje} (samo aktivne drame)"""
    A = _drama_all()
    D = A.setdefault(slot, {})
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    season = y if m >= 7 else y - 1
    squad = set(s.my_squad_tags())
    mo = sorted((r['ovr'] for r in rows if r['ovr']), reverse=True)
    top5 = mo[4] if len(mo) >= 5 else 0
    avg14 = sum(mo[:14]) / float(max(1, min(14, len(mo))))
    ch = False
    try:
        tiers = _club_tiers(slot, s)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        my_str = (tiers.get(my) or (None, avg14))[1]
    except Exception:
        tiers, my_str = {}, avg14
    for r in rows:
        pid = r['pid']
        k = str(pid)
        e = D.get(k)
        if e and e.get('state') in ('refuses', 'last_try', 'refuses_final', 'keep', 'listed'):
            if pid not in squad:
                sold = any(x.get('kind') == 'sold' and x.get('pid') == pid for x in _ev_all(slot)[-200:])
                e['state'] = 'sold' if sold else 'left_free'
                e['ended'] = _fmt_date(gd)
                ch = True
                if not sold:
                    try:
                        _board_adjust(slot, s, -3, 'star_free')
                        _ev_add(slot, 'star_left_free', pid, to=(e.get('interest') or [''])[0])
                    except Exception:
                        pass
            continue
        if e or pid not in squad or r.get('loaned_in'):
            continue
        ml = r.get('months')
        if ml is None or ml <= 0 or ml > 12 or (r['ovr'] or 0) < top5 or (r['age'] or 30) >= 32:
            continue
        tr = persona.traits(pid)
        push = 0.25 * tr['ambition'] + 0.2 * (1 - tr['loyalty']) + (0.25 if (r['ovr'] or 0) >= avg14 + 4 else 0) + 0.1 * tr['money']
        rnd = negotiate._rng('drama', slot, pid, season)
        if rnd.random() > push:
            D[k] = dict(state='calm', season=season)       # odluceno: ovaj put ne radi dramu
            ch = True
            continue
        big = sorted([(st_, ci) for ci, (tier, st_) in tiers.items() if max(my_str + 1.5, (r['ovr'] or 70) - 6) <= st_ <= (r['ovr'] or 70) + 3], reverse=True)[:12]
        rnd.shuffle(big)
        interest = [seasonstats.club_name(s.d, ci) for _, ci in big[:3]] or ['a bigger club']
        D[k] = dict(state='refuses', since=_fmt_date(gd), season=season, interest=interest, months=ml)
        ch = True
        try:
            _ev_add(slot, 'star_refuses', pid, interest=interest, months=ml)
            _ev_add(slot, 'interest', pid, to=interest[0])
        except Exception:
            pass
    if ch:
        _drama_save(A)
    return {int(k): v for k, v in D.items() if v.get('state') in ('refuses', 'last_try', 'refuses_final', 'keep', 'listed')}


def agent_deadline(body):
    """pc283: agent je dao rok ('ako do X ne cujem ponudu, razgovaramo s drugima'), a rok je prosao bez pregovora o ugovoru:
    pokrece se drama 'igrac odbija produljenje' (veci klubovi zainteresirani, izbor prodaj / pusti / zadnji pokusaj).
    Ako je ugovor u medjuvremenu produljen, igrac otisao ili drama vec traje: nista."""
    slot, pid = body['slot'], int(body['pid'])
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if pid not in s.my_squad_tags():
        return dict(ok=True, started=False, why='not in squad')
    A = _drama_all()
    D = A.setdefault(slot, {})
    e = D.get(str(pid))
    if e and e.get('state') not in ('calm',):
        return dict(ok=True, started=False, why='already')
    until = body.get('until') or ''
    try:
        c = s.read_contracts([pid]).get(pid) or {}
        now_until = '%d/%d' % (c.get('m'), c.get('y'))
        if until and now_until.lstrip('0') != str(until).lstrip('0') and str(c.get('y')) not in str(until):
            return dict(ok=True, started=False, why='renewed')
    except Exception:
        pass
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    season = y if m >= 7 else y - 1
    try:
        tiers = _club_tiers(slot, s)
        my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        my_str = (tiers.get(my) or (None, 75))[1]
        ovr = rat(pid)[0] or 75
        big = sorted([(st_, ci) for ci, (tier, st_) in tiers.items() if ci != my and max(my_str + 1.5, ovr - 6) <= st_ <= ovr + 3], reverse=True)[:12]
        rnd = negotiate._rng('agentdl', slot, pid, season)
        rnd.shuffle(big)
        interest = [seasonstats.club_name(s.d, ci) for _, ci in big[:3]] or ['a bigger club']
    except Exception:
        interest = ['a bigger club']
    D[str(pid)] = dict(state='refuses', since=_fmt_date(gd), season=season, interest=interest, months=12, cause='agent_deadline')
    _drama_save(A)
    try:
        _ev_add(slot, 'star_refuses', pid, interest=interest, months=12)
        _ev_add(slot, 'interest', pid, to=interest[0])
    except Exception:
        pass
    return dict(ok=True, started=True, interest=interest)


def drama_choice(body):
    slot, pid, ch = body['slot'], int(body['pid']), body['choice']
    s = mlwrite.Save(slot_folder(slot), ro=True)
    A = _drama_all()
    e = (A.get(slot) or {}).get(str(pid))
    if not e or e.get('state') not in ('refuses', 'refuses_final', 'keep', 'last_try', 'listed'):
        raise ValueError('no contract stand-off for this player')
    msg = ''
    if ch == 'sell':
        cur = _tl_slot(slot)
        t = _tl_norm(cur.get(str(pid), dict(tl=False, loan=False)))
        ovr, age = rat(pid)
        mv = negotiate.estimate_value(ovr, age or 25) if ovr else 0
        t.update(tl=True, reason='unhappy', ask=int(mv * (0.6 + 0.04 * min(10, e.get('months', 6)))) if mv else None, added=_fmt_date(s.game_date_code()))
        cur[str(pid)] = t
        _tl_save(slot, cur)
        e['state'] = 'listed'
        msg = 'He is on the transfer list. Clubs know his contract is running out, so expect offers below his value.'
    elif ch == 'keep':
        e['state'] = 'keep'
        try:
            for p_, f_, d_, n_ in press.chunks([(pid, 'Affection', -6)]):
                growth.queue(CFG, [(p_, f_, d_)], 'dr%d-%d' % (pid & 0xffff, n_))
        except Exception:
            pass
        msg = 'He stays until his contract ends, then leaves on a free. He is not happy about it.'
    elif ch == 'last_try':
        if e.get('state') == 'refuses_final':
            raise ValueError('He has already said no to your final offer.')
        e['state'] = 'last_try'
        msg = 'One last try: he will only listen to a much bigger offer (about 40% above his normal demand). Make it in contract talks.'
    else:
        raise ValueError('unknown choice')
    e['choice'] = ch
    _drama_save(A)
    _ev_add(slot, 'star_choice', pid, choice=ch)
    return dict(ok=True, message=msg, state=e['state'])


def _drama_of(slot, pid):
    return ((_drama_all().get(slot) or {}).get(str(pid)) or {})



# ---------------------------------------------------------------- Zivot kluba: kraj sezone (pc97)
def _table_from(ms):
    T = {}
    for m in ms:
        gh = seasonstats.match_score(m)[0]
        ga = seasonstats.match_score(m)[1]
        for ci, f, a in ((m['home'], gh, ga), (m['away'], ga, gh)):
            t = T.setdefault(ci, [0, 0, 0])
            t[0] += 3 if f > a else 1 if f == a else 0
            t[1] += f - a
            t[2] += f
    return sorted(T.items(), key=lambda kv: (-kv[1][0], -kv[1][1], -kv[1][2]))


def _season_finale(slot, s, M, my, season, lm, lg):
    """Kraj sezone: je li naslov (i ispadanje) odlucen u zadnjem kolu, gol sezone, presuda za tvoj klub, ocekivana umirovljenja."""
    cn = lambda ci: seasonstats.club_name(s.d, ci)
    played = sorted([m for m in lm if m['played']], key=seasonstats.sort_key)
    last = {}
    for m in played:
        last[m['home']] = m
        last[m['away']] = m
    lastset = {id(m) for m in last.values()}
    before = _table_from([m for m in played if id(m) not in lastset])
    final = _table_from(played)
    out = {}
    champ = final[0][0] if final else None
    if before and champ is not None:
        lead_b = before[0]
        gap = lead_b[1][0] - (dict(before).get(champ, [0])[0])
        sec_gap = lead_b[1][0] - before[1][1][0] if len(before) > 1 else 99
        if lead_b[0] != champ:
            out['title'] = dict(kind='snatch', champ=cn(champ), lost=cn(lead_b[0]), txt='%s snatched the title on the final day! %s were top going into the last round.' % (cn(champ), cn(lead_b[0])))
        elif sec_gap <= 3:
            out['title'] = dict(kind='final_day', champ=cn(champ), txt='%s held their nerve on the final day to win the title.' % cn(champ))
        else:
            out['title'] = dict(kind='early', champ=cn(champ), txt='%s are champions.' % cn(champ))
    n = len(final)
    if n >= 6:
        rel_b = {c for c, _ in before[-3:]}
        rel_f = {c for c, _ in final[-3:]}
        esc_ = rel_b - rel_f
        down = rel_f - rel_b
        if esc_:
            out['escape'] = dict(clubs=[cn(c) for c in esc_], down=[cn(c) for c in down], txt='Great escape on the final day: %s survived, %s went down.' % (', '.join(cn(c) for c in esc_), ', '.join(cn(c) for c in down)))
    # gol sezone: najbolje ocijenjeni gol mjeseca
    try:
        A = awards_view(slot, season)
        gs = [mo['goal'] for mo in A.get('months') or [] if mo.get('goal')]
        if gs:
            g = sorted(gs, key=lambda x: (-(x.get('ovr') or 0), x.get('id')))[(season * 7) % len(gs)]
            out['goal'] = dict(pid=g['id'], name=g['name'], club=g.get('club'), opp=g.get('opp'), date=g.get('date'), mine=g.get('mine'),
                               txt='Goal of the season: %s for %s against %s (%s).' % (g['name'], g.get('club'), g.get('opp'), g.get('date')))
    except Exception as ex:
        print('[finale] goal:', ex)
    # presuda za tvoj klub
    myp = next((k + 1 for k, (c, _) in enumerate(final) if c == my), None)
    try:
        B = board_view(slot)
        tg = B.get('target') or n
    except Exception:
        tg = n
    if myp:
        if myp == 1:
            v = ('champions', 'Champions! The city is painted in your colours. Open-top bus, fireworks, a night nobody will forget.')
        elif myp <= tg:
            v = ('met', 'Objective met: %d%s. The fans applaud you off the pitch and the board is pleased.' % (myp, _ordsfx(myp)))
        elif myp > n - 3:
            v = ('relegated', 'Relegated. Silence in the stands, tears on the pitch. A dark day for the club.')
        else:
            v = ('missed', 'Objective missed: %d%s, the target was top %d. The fans are disappointed and the board wants answers.' % (myp, _ordsfx(myp), tg))
        out['verdict'] = dict(kind=v[0], pos=myp, target=tg, txt=v[1])
    return out


def _retire_check(slot, s, M, my, C, key):
    """Proljece (ozujak-svibanj): veterani tvog kluba najavljuju umirovljenje (35+, ili 34+ uz pad kvalitete).
    Nakon nove sezone: tko je nestao iz svih klubova = umirovljen."""
    y, mo, _ = _date_tuple(s.game_date_code())
    S_ = C[key]
    ret = S_.setdefault('retire', {})
    ch = False
    if mo in (3, 4, 5):
        for pid in s.my_squad_tags():
            if str(pid) in ret:
                continue
            ovr, age = rat(pid)
            if not age or age < 34 or (age == 34 and (ovr or 0) >= 76):
                continue
            r = negotiate._rng('retire', slot, pid, key)
            if r.random() < (0.75 if age >= 36 else 0.5):
                ret[str(pid)] = dict(name=NAMES.get(pid, ''), age=age, d=_fmt_date(s.game_date_code()), state='announced')
                ch = True
                try:
                    _ev_add(slot, 'retire_announce', pid, age=age)
                except Exception:
                    pass
            else:
                ret[str(pid)] = dict(state='staying')
                ch = True
    return ch


def _retire_confirm(slot, s, M, C):
    """Najavljeni koji vise nisu ni u jednom klubu (nova sezona) -> umirovljeni."""
    ch = False
    cur = M.get('cur') or {}
    for k_, v in C.items():
        if not isinstance(v, dict):
            continue
        for pid, e in (v.get('retire') or {}).items():
            if e.get('state') == 'announced' and int(pid) not in cur:
                e['state'] = 'retired'
                ch = True
                try:
                    _ev_add(slot, 'retired', int(pid), age=e.get('age'))
                except Exception:
                    pass
    return ch



# ---------------------------------------------------------------- Zivot kluba: AI treneri mijenjaju formaciju (pc97)
FORM_BY_PROFILE = {
    'lowblock': ('5-4-1', '5-3-2', '4-1-4-1', '5-2-2-1'),
    'counter': ('4-4-2', '5-3-2', '4-4-1-1', '4-2-3-1'),
    'possession': ('4-3-3', '4-2-1-3', '3-2-4-1', '4-2-3-1'),
    'highpress': ('4-3-3', '4-2-1-3', '3-2-4-1', '4-2-4'),
    'wings': ('4-3-3', '3-4-3', '4-2-1-3', '4-2-4'),
    'balanced': ('4-2-3-1', '4-4-2', '4-3-3', '4-1-4-1'),
}


def _formation_library(s):
    """Formacije koje vec postoje u saveu: oznaka -> 33 B plana (10 uloga, 1 B, 22 B koordinata) najcescce varijante."""
    import collections
    seen = collections.defaultdict(collections.Counter)
    for i in range(700):
        o = s.PLAN0 + 600 * i
        if o + 40 > len(s.d):
            break
        try:
            lab, roles = s.club_formation(i)
        except Exception:
            break
        if lab:
            # pc166: sve tri formacije (otvaranje / u posjedu / bez posjeda = fluidna formacija), 99 B, kako ih ima neki klub iz baze
            seen[lab][bytes(s.d[o:o + 99])] += 1
    out = {}
    for lab, c in seen.items():
        fl = [b for b, _n in c.most_common() if b[33:66] != b[:33] or b[66:99] != b[:33]]
        out[lab] = fl[0] if fl else c.most_common(1)[0][0]   # radije varijanta s pravom fluidnom formacijom
    return out


FLUID_FLAG_OK = True   # pc174: potvrdeno u igri 28.10. (Sassuolo 1 = On, Genoa 0 = Off)
FLUID_FLAG = 160   # pc173: bajt u zapisu taktike kluba (PLAN0-5+600*idx): 1 = "Fluid Formation: On" (100 klubova iz baze, svi veliki; moj klub 1)


def _fluid_flag_off(s, idx):
    return s.PLAN0 - 5 + 600 * idx + FLUID_FLAG


def _fluid_plan(s, my):
    """pc167: klubovi kojima su sve tri formacije iste (nema fluidne formacije) dobiju formacije u posjedu / bez posjeda
    od kluba iz baze koji ima isti raspored uloga na otvaranju. Otvaranje i postava kluba se ne diraju.
    -> [(offset, 66 B)]"""
    import collections
    recs = {}
    for i in range(mlsave.club_layout(s.d)[0]):   # pc258: svi klubovi (60 MB)
        o = s.PLAN0 + 600 * i
        if o + 99 > len(s.d):
            break
        b = bytes(s.d[o:o + 99])
        roles = list(b[:10])
        if any(r < 1 or r > 12 for r in roles):
            continue
        ok = all(1 <= r <= 12 for k in (1, 2) for r in b[33 * k:33 * k + 10])
        if ok:
            recs[i] = b
    donors = collections.defaultdict(list)
    for i, b in recs.items():
        if b[33:66] != b[:33] or b[66:99] != b[:33]:
            donors[tuple(sorted(b[:10]))].append(b)
    out = []
    for i, b in sorted(recs.items()):
        roles = list(b[:10])
        if i == my or list(b[33:43]) != roles or list(b[66:76]) != roles:
            continue   # pc173: vec ima drugi oblik u posjedu ili bez posjeda (isti raspored uloga = nema prave fluidne)
        cand = donors.get(tuple(sorted(roles)))
        if not cand:
            continue
        strong = [d for d in cand if list(d[33:43]) != list(d[:10]) or list(d[66:76]) != list(d[:10])]   # stvarno druga formacija, ne samo pomak
        cand = strong or cand
        exact = [d for d in cand if list(d[:10]) == roles]
        d = (exact or cand)[i % len(exact or cand)]
        # slot kluba i -> slot donora j iste uloge, najblizi po koordinatama na otvaranju
        free = list(range(10))
        mp = []
        for a in range(10):
            js = [j for j in free if d[j] == roles[a]]
            j = min(js, key=lambda j: (d[11 + 2 * j] - b[11 + 2 * a]) ** 2 + (d[12 + 2 * j] - b[12 + 2 * a]) ** 2)
            free.remove(j)
            mp.append(j)
        nb = bytearray()
        for k in (1, 2):
            q = d[33 * k:33 * k + 33]
            blk = bytearray(33)
            blk[10] = q[10]
            for a, j in enumerate(mp):
                blk[a] = q[j]
                blk[11 + 2 * a] = q[11 + 2 * j]
                blk[12 + 2 * a] = q[12 + 2 * j]
            nb += blk
        out.append((s.PLAN0 + 600 * i + 33, bytes(nb)))
    # pc173: i prekidac "Fluid Formation" (inace igra formacije u posjedu / bez posjeda ne koristi)
    newb = {o_ - 33 - s.PLAN0: True for o_, _b in out}
    for i, b in (recs.items() if FLUID_FLAG_OK else ()):
        if i == my:
            continue
        o_ = _fluid_flag_off(s, i)
        differ = (i * 600 in newb) or b[33:66] != b[:33] or b[66:99] != b[:33]
        if differ and s.d[o_] == 0:
            out.append((o_, b'\x01'))
    return out


def _formation_switch(s, idx, prof, rnd, lib, force_lab=None, avail=None, cands=None):
    """Nova formacija za klub (prema novom profilu taktike) i postava koja joj odgovara. -> dict ili None
    pc353: avail = indeksi igraca koji mogu igrati (hitna formacija zbog ozljeda), cands = vlastiti popis formacija."""
    cur, roles0 = s.club_formation(idx)
    if not cur:
        return None
    o = mlwrite.REC0 + idx * mlwrite.STRIDE
    n = s.d[o + 1058]
    sq = [struct.unpack_from('<I', s.d, o + mlwrite.SQUAD_OFF + 8 * k)[0] for k in range(n)]
    blo = s.TAC0 + 600 * idx + 484
    BL = [int(v) for v in s.d[blo:blo + n]]
    if n < 16 or sorted(BL) != list(range(n)):
        return None
    pl = [(i, POS.get(sq[i], 5), rat(sq[i])[0] or 60) for i in range(n) if avail is None or i in avail]
    if len(pl) < 11:
        return None
    if cands is None:
        cands = [force_lab] if force_lab else [lab for lab in FORM_BY_PROFILE.get(prof, ()) if lab in lib and lab != cur]
        if rnd is not None:
            rnd.shuffle(cands)
    for lab in cands:
        blk = lib[lab]
        roles = list(blk[:10])
        need = {}
        for r_ in roles:
            need[r_] = need.get(r_, 0) + 1
        if any(sum(1 for _, p_, _ in pl if mlwrite.DIST[r_][p_] <= 1) < k for r_, k in need.items()):
            continue
        allr = [0] + roles
        cost = [[-(ov) + 2.5 * mlwrite.DIST[r_][p_] for (_, p_, ov) in pl] for r_ in allr]
        pick = mlwrite.hungarian(cost)
        xi = [pl[j][0] for j in pick]
        new = xi + [b for b in BL if b not in xi]
        return dict(frm=cur, to=lab, blk=blk, new=new, blo=blo, plan=s.PLAN0 + 600 * idx)
    return None


def club_formation_test(body):
    """pc172 (test): AI klubu promijeni formaciju (sve tri: otvaranje / u posjedu / bez posjeda) i postavu. body {slot, idx, to}"""
    import random as _r
    slot, idx, to = body['slot'], int(body['idx']), body.get('to') or ''
    s = mlwrite.Save(slot_folder(slot), ro=True)
    lib = _formation_library(s)
    if to not in lib:
        return dict(ok=False, error='formation not in this save', available=sorted(lib))
    before = club_lineup_info(slot, idx)
    fs = _formation_switch(s, idx, '', _r.Random(idx), lib, force_lab=to)
    if not fs:
        return dict(ok=False, error='the squad cannot fill %s' % to, available=sorted(lib))

    def fn(sv):
        sv.d[fs['plan']:fs['plan'] + len(fs['blk'])] = fs['blk']
        sv.d[fs['blo']:fs['blo'] + len(fs['new'])] = bytes(fs['new'])
        sv.d[fs['plan'] - 5 + FLUID_FLAG] = 1
        return 'formation test %s -> %s' % (fs['frm'], fs['to'])
    _write_slot(slot, 'aiformation', fn)
    after = club_lineup_info(slot, idx)
    pick = lambda L: dict(formation=L['formation'], presets=[p_['formation'] for p_ in L['presets']],
                          xi=[(x['name'], x['pos'], x['ovr']) for x in L['xi']], roles=[x['role'] for x in L['slots']])
    return dict(ok=True, club=before['name'], before=pick(before), after=pick(after))


def club_fluid_test(body):
    """pc173 (test): samo prekidac Fluid Formation za AI klub. body {slot, idx, on}"""
    slot, idx, on = body['slot'], int(body['idx']), 1 if body.get('on', True) else 0
    s = mlwrite.Save(slot_folder(slot))
    o_ = _fluid_flag_off(s, idx)
    before = s.d[o_]

    def fn(sv):
        sv.d[o_] = on
        return 'fluid flag %d -> %d' % (before, on)
    _write_slot(slot, 'aifluid', fn)
    return dict(ok=True, idx=idx, before=before, after=on)


def club_formations(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    out = []
    _lim, _nat = mlsave.club_layout(s.d)
    for n in range(_lim):
        if n in _nat:
            continue
        o = mlwrite.REC0 + n * mlwrite.STRIDE
        if o + mlwrite.STRIDE > len(s.d):
            break
        nm = bytes(s.d[o:o + 48]).split(b'\0')[0].decode('utf-8', 'replace')
        if len(nm) < 3 or not all(c.isprintable() for c in nm):
            continue
        f, roles = s.club_formation(n)
        out.append(dict(idx=n, name=nm, formation=f, roles=roles))
    return out


def _pre_window(gd):
    """pc404: zadnja dva tjedna prije roka (17.-31.12. i 16.-30.6.): klubovi vec salju ponude za tvoje igrace za sljedeci rok."""
    try:
        y, m, d = _date_tuple(gd)
        return (m == 12 and d >= 17) or (m == 6 and d >= 16)
    except Exception:
        return False


def _sell_mk(gd):
    """Kljuc mjeseca za ponude: u tjednima prije roka vec mjesec roka (sijecanj / srpanj), da ponuda ostane ista kad se rok otvori."""
    y, m, d = _date_tuple(gd)
    if m == 12 and d >= 17:
        return '%d-1' % (y + 1)
    if m == 6 and d >= 16:
        return '%d-7' % y
    return '%d-%d' % (y, m)


def sell_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    mk = _sell_mk(gd)
    live, _ = read_dump()
    st = _neg_store()
    fm = mlwrite.Save.flag_map(s.d)
    moved = _moved(slot, s)
    tl_app = _tl_slot(slot)
    rows = []
    cts = s.read_contracts(list(s.my_squad_tags()))
    _li = s.loaned_in_pids()
    # pc315: ponude samo dok je prijelazni rok otvoren (izvan roka app ionako ne dopusta prodaju; prije su stizale i 5.9.)
    try:
        _inwin = win_state(gd)[2] == 'in' or _pre_window(gd)   # pc404: i dva tjedna prije roka
    except Exception:
        _inwin = True
    for pid in s.my_squad_tags():
        lv = (live or {}).get(pid) or {}
        locked = pid in moved or pid in _li
        ae = _tl_norm(tl_app[str(pid)]) if str(pid) in tl_app else None
        tl_on = bool(ae and ae['tl'])
        loan_on = bool(ae and ae['loan'])
        listed = bool(lv.get('tl') or fm.get(pid, (False, False))[0] or tl_on)
        ovr, age = rat(pid)
        _c = cts.get(pid) or {}
        _sf = negotiate.facts(ovr, lv.get('age') or age or 25, lv.get('mv', 0), _c.get('sal') or lv.get('sal', 0), None, False)
        offs = []
        for o in ([] if (locked or not _inwin) else _offers_for(slot, s, gd, mk, pid, lv, listed, ae.get('ask') if tl_on else None)):
            offs.append(_sell_fields(slot, o, _sell_rec(slot, pid, o['off'], mk, o), mk))
        rows.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), ovr=ovr, age=lv.get('age') or age, pos=POS.get(pid, 5),
                         mv=_sf['mv'], mv_est=_sf['est'], sal=_sf['sal'], until=('%d/%d' % (_c['m'], _c['y'])) if _c.get('y') else '',
                         listed=listed, locked=locked, loaned_in=(pid in _li), offers=offs,
                         app_listed=tl_on, ask=(ae or {}).get('ask') if tl_on else None, reason=(ae or {}).get('reason') if tl_on else None,
                         loan_listed=loan_on, loan_share=(ae or {}).get('loan_share'), loan_buy=(ae or {}).get('loan_buy'),
                         loan_offers=(_loan_offers_for(slot, s, mk, pid, lv, ae) if loan_on and not locked and _inwin else [])))
    try:
        _M = _season(slot, s)
        _my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        for r_ in rows:
            f_, w_ = fan_favourite(slot, s, r_['pid'], _M, _my)
            r_['fav'] = f_
            r_['fav_why'] = w_
    except Exception as ex:
        print('[fans] fav:', ex)
    rows.sort(key=lambda r: (-len(r['offers']), -r['ovr']))
    return dict(players=rows, budget=s.budget(), squad=len(rows), live=bool(live))


def _on_strike(slot, pid):
    try:
        return (_req_all().get(slot, {}).get(str(pid)) or {}).get('status') == 'forced'
    except Exception:
        return False


FORM_GOAL = (3, 4, 5, 6, 8, 10)


def form_news(slot):
    """Dogadjaji forme iz odigranih utakmica: golovi/asistencije zaredom, hat-trick, serija visokih ocjena, suša. Bez stanja: racuna se iz save-a."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    d = s.d
    my = None
    try:
        my = s.my_club_idx() if hasattr(s, 'my_club_idx') else None
    except Exception:
        my = None
    mine_ids = set(s.my_squad_tags())
    ms = sorted([m for m in M['matches'] if m['played']], key=seasonstats.sort_key)
    st = {}
    out = []
    TOP5 = ('La Liga', 'Premier League', 'Serie A', 'Bundesliga', 'Ligue 1')
    top5 = set()
    try:
        for c_ in comps_view(slot).get('comps', []):
            if c_.get('kind') == 'league' and c_.get('name') in TOP5:
                top5 |= {r_.get('club') for r_ in (c_.get('rows') or [])}
    except Exception:
        pass

    def add(kind, pid, ci, m, **kw):
        ovr, age = rat(pid)
        mine = pid in mine_ids
        if not mine and (ovr or 0) < 70:
            return
        out.append(dict(kind=kind, pid=pid, name=NAMES.get(pid, str(pid)), ovr=ovr, pos=POS.get(pid, 5), club=seasonstats.club_name(d, ci), mine=mine,
                        when='%d/%d/%d' % (m['dd'], m['m'], m['y']), date=m['y'] * 10000 + m['m'] * 100 + m['dd'], n=m['n'], **kw))
    last_season = None
    for m in ms:
        if m['season'] != last_season:
            st = {}
            last_season = m['season']
        for club in (m['home'], m['away']):
            rows = [r for r in m['rows'] if r[1] == club]
            seen = {r[0] for r in rows}
            for pid, x in st.items():
                if x['club'] == club and pid not in seen:
                    x.update(g=0, a=0, hi=0, dry=0, gt=0, l3=[], hot=False)
            for pid, _c, g, a, rt in rows:
                x = st.setdefault(pid, dict(club=club, g=0, a=0, hi=0, dry=0, gt=0))
                x['club'] = club
                cn_ = seasonstats.club_name(d, club)
                big_ = cn_ in top5
                # hat-trick: top 5 liga uvijek, ostale lige samo zvijezde (OVR 80+) ili 4+ gola
                if g >= 3 and (pid in mine_ids or big_ or (rat(pid)[0] or 0) >= 80 or g >= 4):
                    add('hattrick' if g == 3 else 'poker', pid, club, m, goals=g)
                # igrac u formi: 4+ gola u zadnje 3 utakmice (jednom po nizu)
                L3 = (x.get('l3') or [])[-2:] + [g]
                x['l3'] = L3
                if sum(L3) >= 4 and len(L3) == 3 and not x.get('hot') and (pid in mine_ids or big_ or (rat(pid)[0] or 0) >= 78):
                    x['hot'] = True
                    add('hot', pid, club, m, n_=3, goals=sum(L3))
                elif sum(L3) < 3:
                    x['hot'] = False
                if g > 0:
                    x['g'] += 1; x['gt'] += g
                    if x['g'] in FORM_GOAL:
                        add('goal_streak', pid, club, m, n_=x['g'], goals=x['gt'])
                else:
                    x['g'] = 0; x['gt'] = 0
                if a > 0:
                    x['a'] += 1
                    if x['a'] in (3, 5):
                        add('assist_streak', pid, club, m, n_=x['a'])
                else:
                    x['a'] = 0
                if rt >= 7.5:
                    x['hi'] += 1
                    if x['hi'] in (4, 6):
                        add('form_streak', pid, club, m, n_=x['hi'])
                else:
                    x['hi'] = 0
                if g == 0 and a == 0 and POS.get(pid, 5) >= 9:
                    x['dry'] += 1
                    if x['dry'] in (8, 12):
                        add('drought', pid, club, m, n_=x['dry'])
                else:
                    x['dry'] = 0
    out.sort(key=lambda e: (-e['date'], -e['n']))
    return dict(items=out[:150])


def venue_info(name):
    from fl26_venue_metadata import lookup
    return lookup(HERE, name)

def venue_kit_info(name):
    from fl26_venue_metadata import merge
    return merge(HERE, name, wiki.fetch_kit(name, CREST_DIR))


WIKI_DIR = os.path.join(HERE, 'data', 'wiki')


def _wiki_web():
    """Dohvat portreta i opisa s Wikipedije (internet). Zadano ISKLJUCENO (config.json: "wiki_web": true); vec spremljeno u kesu se i dalje koristi."""
    return bool(CFG.get('wiki_web', False))  # r7: offline by default in the PES 2017 edition; set wiki_web:true to allow Wikipedia lookups


def wiki_info(slot, pid):
    name = NAMES.get(pid)
    if not name:
        return dict(ok=False)
    if not _wiki_web() and not os.path.exists(os.path.join(WIKI_DIR, '%d.json' % pid)):
        return dict(ok=False)
    r = wiki.fetch(pid, name, WIKI_DIR, rat(pid)[1] or None)
    r = dict(r)
    r['img'] = bool(r.get('img')) and os.path.exists(os.path.join(WIKI_DIR, 'img', '%s.jpg' % pid))
    return r


_WQ = []
_WT = {'t': None}


def _wiki_worker():
    while _WQ:
        pid = _WQ.pop(0)
        try:
            r = wiki.fetch(pid, NAMES.get(pid, ''), WIKI_DIR, rat(pid)[1] or None)
            if r and r.get('error') and not r.get('ok'):
                if '429' in r['error']:
                    _WQ.insert(0, pid)
                    time.sleep(60)          # Wikipedia traži da usporimo
                    continue
        except Exception:
            pass
        time.sleep(1.0)
    _WT['t'] = None


def wiki_prefetch(pids):
    """Pozadinsko dohvacanje portreta za popise (jedan po jedan, sa stankom)."""
    n = 0
    if not _wiki_web():
        return dict(ok=True, queued=0)
    for pid in pids:
        pid = int(pid)
        if pid in _WQ or pid not in NAMES:
            continue
        try:
            c = json.load(open(os.path.join(WIKI_DIR, '%s.json' % pid), encoding='utf-8'))
            if c.get('ok') or not c.get('error'):
                continue
        except Exception:
            pass
        _WQ.append(pid); n += 1
    if _WQ and (_WT['t'] is None or not _WT['t'].is_alive()):
        _WT['t'] = threading.Thread(target=_wiki_worker, daemon=True)
        _WT['t'].start()
    return dict(queued=n, left=len(_WQ))


CREST_DIR = os.path.join(HERE, 'data', 'crests')
_CQ = []
_CT = {'t': None}



COMP_WIKI = {3: 'UEFA Champions League', 5: 'UEFA Europa League', 17: 'Premier League', 18: 'Serie A', 19: 'La Liga', 20: 'Bundesliga', 21: 'Eredivisie',
             22: 'Primeira Liga', 79: 'EFL Championship', 80: 'Segunda División', 81: '2. Bundesliga', 82: 'Serie B', 116: 'Ligue 1', 117: 'Super League Greece',
             118: 'Süper Lig', 134: 'Scottish Premiership', 147: 'Danish Superliga', 155: 'Belgian Pro League'}


LEAGUE_WIKI = {'Serie A': 'Serie A', 'La Liga': 'La Liga', 'Bundesliga': 'Bundesliga', 'Eredivisie': 'Eredivisie', 'Liga Portugal': 'Primeira Liga', 'Ligue 1': 'Ligue 1', 'Ligue 2': 'Ligue 2',
               'Belgian Pro League': 'Belgian Pro League', 'Scottish Premiership': 'Scottish Premiership', 'Süper Lig': 'Süper Lig', 'Super League Greece': 'Super League Greece',
               'Danish Superliga': 'Danish Superliga', 'EFL Championship': 'EFL Championship', '2. Bundesliga': '2. Bundesliga', 'La Liga 2': 'Segunda División', 'Serie B': 'Serie B',
               'Brasileirão Série A': 'Campeonato Brasileiro Série A', 'Brasileirão Série B': 'Campeonato Brasileiro Série B', 'Liga Profesional Argentina': 'Argentine Primera División',
               'MLS': 'Major League Soccer', 'J1 League': 'J1 League', 'Primera Chile': 'Chilean Primera División', 'Primera A Colombia': 'Categoría Primera A',
               'Saudi Pro League': 'Saudi Pro League', 'Russian Premier League': 'Russian Premier League', 'Premier League': 'Premier League',
               'Champions League': 'UEFA Champions League', 'Europa League': 'UEFA Europa League',
               # pc347: predsezonski turniri i superkupovi iz baze igre
               'International Champions Cup NA': 'International Champions Cup', 'International Champions Cup SA': 'International Champions Cup',
               'International Champions Cup Asia': 'International Champions Cup', 'International Champions Cup': 'International Champions Cup',
               'The FA Community Shield': 'FA Community Shield', 'FA Community Shield': 'FA Community Shield'}



SCENE_T = {'Dribbling': ['Dribbling'], 'Passing': ['Pass (association football)', 'Playmaker'], 'Shooting': ['Penalty kick (association football)', 'Free kick (association football)'],
           'Defending': ['Defender (association football)', 'Tackle (association football)'], 'Mental': ['Captain (association football)', 'Captain\'s armband'],
           'Goalkeeper': ['Goalkeeper (association football)'], 'Pace': ['Winger (association football)', 'Sprint (running)'], 'None': ['Association football', 'Football pitch']}


def scene_img(kind):
    """Pozadinska fotografija za skills karticu: glavna slika Wikipedia clanka (data/scenes/<kind>.jpg). Neuspjeh se pamti 1 dan."""
    if kind not in SCENE_T:
        return None
    d = os.path.join(HERE, 'data', 'scenes')
    fp = os.path.join(d, kind + '.jpg')
    try:
        return open(fp, 'rb').read()
    except Exception:
        pass
    miss = fp + '.miss'
    try:
        if time.time() - os.path.getmtime(miss) < 86400:
            return None
    except Exception:
        pass
    import urllib.parse
    for t in SCENE_T[kind]:
        try:
            sm = wiki._get('%s/api/rest_v1/page/summary/%s' % (wiki.API, urllib.parse.quote(t.replace(' ', '_'), safe='')))
            th = (sm.get('thumbnail') or {}).get('source')
            if not th:
                continue
            b = None
            big = re.sub(r'/\d+px-', '/960px-', th)
            for u in ((big, th) if big != th else (th,)):
                try:
                    b = wiki._get(u, binary=True)
                    if b and len(b) > 4000:
                        break
                except Exception:
                    b = None
            if b:
                os.makedirs(d, exist_ok=True)
                open(fp, 'wb').write(b)
                return b
        except Exception:
            continue
    try:
        os.makedirs(d, exist_ok=True)
        open(miss, 'w').write('x')
    except Exception:
        pass
    return None

_STAD_FAIL = {}

_GL = {}


def _sider_root():
    """SiderAddons mapa iz putanje dumpa (.../SiderAddons/content/ml-immersion/bridge/players_dump.bin) ili CFG['sider']."""
    if CFG.get('sider'):
        return CFG['sider']
    p = os.path.normpath(CFG.get('dump') or '')
    parts = p.replace('\\', '/').split('/')
    if 'content' in parts:
        return os.sep.join(p.replace('\\', '/').split('/')[:parts.index('content')]) or None
    return None



def _cpk_roots():
    """Sve livecpk mape kao ih vidi Sider: redom iz sider.ini (cpk.root = ..., prva ima prednost), pa ostale podmape livecpk-a."""
    if 'roots' in _GL:
        return _GL['roots']
    out = []
    root = _sider_root()
    try:
        for line in open(os.path.join(root, 'sider.ini'), encoding='utf-8', errors='ignore'):
            m = re.match(r'\s*cpk\.root\s*=\s*"?([^";\r\n]+)"?', line)
            if m:
                pth = m.group(1).strip().replace('\\', os.sep).replace('/', os.sep)
                if not os.path.isabs(pth):
                    pth = os.path.normpath(os.path.join(root, pth))
                if os.path.isdir(pth) and pth not in out:
                    out.append(pth)
    except Exception:
        pass
    try:
        lc = os.path.join(root, 'livecpk')
        for d_ in sorted(os.listdir(lc)):
            pth = os.path.join(lc, d_)
            if os.path.isdir(pth) and pth not in out:
                out.append(pth)
    except Exception:
        pass
    _GL['roots'] = out
    return out



def _other_cpk_roots():
    """pc270: livecpk mape Sidera ostalih igara iz config.json 'profiles' (npr. FL26 kad je odabrana FL27), za slike kojih nova igra nema."""
    if 'roots_o' in _GL:
        return _GL['roots_o']
    out, cur = [], os.path.normcase(os.path.normpath(_sider_root() or ''))
    for pr in (CFG.get('profiles') or {}).values():
        sd = (pr or {}).get('sider') or ''
        if not sd and (pr or {}).get('dump'):
            parts = os.path.normpath(pr['dump']).replace('\\', '/').split('/')
            sd = os.sep.join(parts[:parts.index('content')]) if 'content' in parts else ''
        if not sd or os.path.normcase(os.path.normpath(sd)) == cur:
            continue
        lc = os.path.join(sd, 'livecpk')
        try:
            for d_ in sorted(os.listdir(lc)):
                pth = os.path.join(lc, d_)
                if os.path.isdir(pth) and pth not in out:
                    out.append(pth)
        except Exception:
            pass
    _GL['roots_o'] = out
    return out



def _save_team_ids():
    """pc256 (tester 60 MB, Report 06): ime kluba -> team ID izravno iz trenutne karijere. Zapis kluba (1680 B od 80):
    u32 kljuc (team ID << 14 | indeks), ime od +4. Samo jedinstvena imena (npr. dva 'Club Nacional' se preskacu).
    teamids.json moze biti zastario (tester: 398 klubova, a karijera ih ima 1.868) pa su grbovi isli s interneta (i krivi)."""
    slot = _CUR_SLOT.get('slot')
    if not slot:
        return {}
    try:
        p = os.path.join(slot_folder(slot), 'data.dat')
        st = os.stat(p)
        key = (p, st.st_mtime, st.st_size)
    except Exception:
        return {}
    c = _GL.get('stid')
    if c and c[0] == key:
        return c[1]
    out = {}
    try:
        with open(p, 'rb') as fh:
            d = fh.read(80 + 2400 * 1680)
        names = {}
        for ref in range(2400):
            o = 80 + ref * 1680
            if o + 74 > len(d):
                break
            k = struct.unpack_from('<I', d, o)[0]
            if k == 0xffffffff or (k & 0x3fff) != ref or not (k >> 14):
                continue
            try:
                nm = d[o + 4:o + 74].split(b'\0')[0].decode('utf-8')
            except UnicodeDecodeError:
                continue
            if nm.strip():
                names.setdefault(nm, set()).add(k >> 14)
        out = {nm: next(iter(t)) for nm, t in names.items() if len(t) == 1}
    except Exception:
        out = {}
    _GL['stid'] = (key, out)
    return out


def _team_name_map():
    """{ime kluba: team id} iz baze (teamids.json). Samo podaci, bez slika."""
    if 'n2t' not in _GL:
        try:
            ids = json.load(open(_dbf('teamids.json'), encoding='utf-8'))
            _GL['n2t'] = {v: int(k) for k, v in ids.items()}
        except Exception:
            _GL['n2t'] = {}
    return _GL['n2t']


def _team_id(name):
    """Team ID iz igre za ime kluba: prvo iz trenutne karijere (pc256), pa data/teamids.json, a ako ga ni tamo nema
    (stara baza bez npr. Wolfsburga/Mainza), iz EDIT datoteke iz mape saveova (svi klubovi s ID-evima). Usporedba i po normaliziranom imenu."""
    _team_name_map()
    t = _save_team_ids().get(name)
    if t:
        return t
    n2t = _GL.get('n2t') or {}
    t = n2t.get(name) or n2t.get((name or '') + ' FC') or n2t.get(re.sub(r'\s+FC$', '', name or ''))
    if t:
        return t
    import unicodedata
    def nk(x):
        x = unicodedata.normalize('NFKD', x or '').encode('ascii', 'ignore').decode().lower()
        return re.sub(r'[^a-z0-9]', '', x)
    if 'n2tx' not in _GL:
        m = {}
        try:
            ed, _ = _edit_data()
            if ed:
                for k, v in dbimport.teams_from_edit(ed).items():
                    m[nk(v)] = k
        except Exception:
            pass
        for v, k in n2t.items():
            m.setdefault(nk(v), k)
        _GL['n2tx'] = m
    return _GL['n2tx'].get(nk(name))



def wiki_img(pid):
    try:
        return open(os.path.join(WIKI_DIR, 'img', '%d.jpg' % pid), 'rb').read()
    except Exception:
        return None

def wiki_photo(pid):
    try:
        c = json.load(open(os.path.join(WIKI_DIR, '%d.json' % pid), encoding='utf-8'))
    except Exception:
        c = None
    if not c or not c.get('ok'):
        name = NAMES.get(pid)
        c = wiki.fetch(pid, name, WIKI_DIR, rat(pid)[1] or None) if (name and _wiki_web()) else None
    if not c or not c.get('ok') or not c.get('title'):
        return None
    if not _wiki_web():
        return wiki_img(pid)
    return wiki.fetch_photo(pid, c['title'], WIKI_DIR, NAMES.get(pid) or '')


EV_FILE = os.path.join(HERE, 'data', 'events.json')


def _ev_add(slot, kind, pid, **kw):
    """Dogadjaji tvog kluba za Vijesti (zahtjevi, strikeovi, prodaje...)."""
    nofan = kw.pop('_nofan', False)
    if not nofan and kind in ('sold', 'signed') and not kw.get('loan'):
        try:
            _fan_react(slot, kind, pid, kw)
        except Exception as ex:
            print('[fans]', ex)
    try:
        a = json.load(open(EV_FILE, encoding='utf-8'))
    except Exception:
        a = {}
    s = mlwrite.Save(slot_folder(slot), ro=True)
    L = a.setdefault(slot, [])
    ovr, age = rat(pid) if pid else (0, 0)
    L.append(dict(kind=kind, pid=pid, name=NAMES.get(pid, '') if pid else '', ovr=ovr, age=age, when=_fmt_date(s.game_date_code()), n=len(L), **kw))
    del L[:-400]
    os.makedirs(os.path.dirname(EV_FILE), exist_ok=True)
    _jdump(a, EV_FILE, ensure_ascii=False, indent=1)
    try:
        it = _world_ev_item(kind, pid, worldlib.date_str(s.game_date_code()), dict(kw, name=NAMES.get(pid, '') if pid else '', ovr=ovr, age=age), _my_club_name(s))
        world(slot, s).add(it[0], it[1], it[2], pid=it[3], clubs=it[4], **it[5])
    except Exception as ex:
        print('[world] ev:', ex)


def loan_options(slot):
    """Posudbe s opcijom otkupa koje sam doveo: podsjetnik prije isteka posudbe (ako ne otkupim, igrac se vraca u klub vlasnik)."""
    import datetime
    try:
        ev = json.load(open(EV_FILE, encoding='utf-8')).get(slot, [])
    except Exception:
        ev = []
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = _date_tuple(s.game_date_code())
    today = datetime.date(gd[0], gd[1], gd[2])
    mine = s.my_squad_tags()
    li = s.loaned_in_pids()
    seen = {}
    for e in ev:
        if e.get('kind') == 'signed' and e.get('loan') and e.get('option') and e.get('pid') in mine and e['pid'] in li:
            seen[e['pid']] = e
    out = []
    for pid, e in seen.items():
        try:
            d, m, y = [int(x) for x in str(e.get('until')).split('/')]
            left = (datetime.date(y, m, d) - today).days
        except Exception:
            continue
        if left < 0:
            continue
        o = e.get('opt') or {}
        out.append(dict(pid=pid, name=e.get('name') or NAMES.get(pid, str(pid)), club=e.get('frm', ''), buy=e.get('option'), wage=o.get('wage'), release=o.get('release'),
                        contract_until=o.get('end_s'), loan_until=e.get('until'), days_left=left, due=left <= 45))
    out.sort(key=lambda r: r['days_left'])
    return dict(items=out, date=_fmt_date(s.game_date_code()))


SEEN_FILE = os.path.join(HERE, 'data', 'loan_seen.json')


def _detect_loan_arrivals(slot):
    """Posudbe koje su dosle mimo appa (npr. prihvacene direktno u igri): dodaj vijest s detaljima iz save-a. Prvi poziv samo zapamti postojece."""
    try:
        s = mlwrite.Save(slot_folder(slot), ro=True)
        now = s.loaned_in_pids()
    except Exception:
        return
    try:
        a = json.load(open(SEEN_FILE, encoding='utf-8'))
    except Exception:
        a = {}
    if slot not in a:
        a[slot] = sorted(now)
    else:
        seen = set(a[slot])
        try:
            have = {e.get('pid') for e in json.load(open(EV_FILE, encoding='utf-8')).get(slot, []) if e.get('kind') == 'signed' and e.get('loan')}
        except Exception:
            have = set()
        for pid in sorted(now - seen):
            if pid not in have:
                ot = s.option_terms(pid)
                ec = s.loan_end_code(pid)
                _ev_add(slot, 'signed', pid, frm='', fee=0, wage=0, years=0, until=_fmt_date(ec) if ec else '', loan=True, option=(ot['buy'] if ot else 0),
                        opt=(dict(wage=ot['wage'], release=ot['release'], end_s=_fmt_date(ot['end'])) if ot else None))
        a[slot] = sorted(seen | now)
    # krivo prepoznate "posudbe" (transfer bez datuma kraja posudbe, prikaz 0/0/65535) se micu iz popisa potpisa
    try:
        ev = json.load(open(EV_FILE, encoding='utf-8'))
        L = ev.get(slot, [])
        bad = [x for x in L if x.get('kind') == 'signed' and x.get('loan') and not x.get('frm') and x.get('pid') not in now
               and (not x.get('until') or '65535' in str(x.get('until')) or str(x.get('until')).startswith('0/0'))]
        if bad:
            ev[slot] = [x for x in L if x not in bad]
            _jdump(ev, EV_FILE, ensure_ascii=False)
            a[slot] = [p_ for p_ in a.get(slot, []) if p_ in now]
    except Exception:
        pass
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    _jdump(a, SEEN_FILE)


def events_view(slot):
    try:
        _detect_loan_arrivals(slot)
    except Exception:
        pass
    try:
        items = json.load(open(EV_FILE, encoding='utf-8')).get(slot, [])
    except Exception:
        return dict(items=[])
    # zastita od starih podataka: dogadjaji s datumom poslije danasnjeg datuma u saveu dolaze iz drugog (novijeg) savea
    # istog slota (npr. ucitana starija kopija ili nova karijera) i ne prikazuju se
    try:
        y, m, d = _date_tuple(mlwrite.Save(slot_folder(slot), ro=True).game_date_code())
        today = y * 10000 + m * 100 + d
        items = [e for e in items if _when_num(e.get('when')) <= today]
    except Exception as ex:
        print('[events] filter:', ex)
    return dict(items=items)


def _when_num(w):
    m_ = re.match(r'\s*(\d{1,2})/(\d{1,2})/(\d{4})', str(w or ''))
    return int(m_.group(3)) * 10000 + int(m_.group(2)) * 100 + int(m_.group(1)) if m_ else 0


REQ_FILE = os.path.join(HERE, 'data', 'requests.json')
REQ_STRIKES = 3


def _req_all():
    try:
        return json.load(open(REQ_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _req_save(slot, d):
    a = _req_all()
    a[slot] = d
    os.makedirs(os.path.dirname(REQ_FILE), exist_ok=True)
    _jdump(a, REQ_FILE, ensure_ascii=False, indent=1)


REQ_NEW_MONTHS = 3          # novi igrac se prva 3 mjeseca ne zali
REQ_GRACE = 8               # novi trener: nitko se ne zali prvih 8 utakmica karijere


PROM_FILE = os.path.join(HERE, 'data', 'promises.json')
PROM_SHARE = {'key': 0.70, 'starter': 0.50, 'rotation': 0.25, 'prospect': 0.10}


def _promises(slot):
    try:
        return json.load(open(PROM_FILE, encoding='utf-8')).get(slot, {})
    except Exception:
        return {}


def _prom_save(slot, d):
    try:
        a = json.load(open(PROM_FILE, encoding='utf-8'))
    except Exception:
        a = {}
    a[slot] = d
    os.makedirs(os.path.dirname(PROM_FILE), exist_ok=True)
    _jdump(a, PROM_FILE, ensure_ascii=False, indent=1)


def promise_add(slot, s, pid, role):
    """Pri potpisu zapamti obecanu ulogu; igra od tada prati minute."""
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    n = len([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])])
    d = _promises(slot)
    d[str(pid)] = dict(role=role, base=n, state='ok')
    _prom_save(slot, d)


def promise_check(slot, s):
    """Ako igrac ne igra koliko mu je obecano: 'upset' (nezadovoljan, forma -1), pa 'angry' (ne dolazi na trening, forma -2, trazi odlazak)."""
    d = _promises(slot)
    if not d:
        return
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    squad = set(s.my_squad_tags())
    ch = False
    for k in list(d):
        pid, e = int(k), d[k]
        if pid not in squad:
            d.pop(k); ch = True
            continue
        base = e.get('base', 0)
        if len(ms) < base:
            base = e['base'] = 0
        since = ms[base:]
        if len(since) < 5:
            continue
        apps = sum(1 for m in since if any(r[0] == pid and r[1] == my for r in m['rows']))
        share = apps / float(len(since))
        need = PROM_SHARE.get(e.get('role'), 0.25) - 0.12
        st = e.get('state', 'ok')
        if share >= need:
            if st != 'ok':
                e['state'] = 'ok'; ch = True
            continue
        if st == 'ok':
            e['state'] = 'upset'; e['at'] = len(since); ch = True
            _ev_add(slot, 'promise_upset', pid, role=e.get('role'), share=round(share, 2))
        elif st == 'upset' and len(since) >= e.get('at', 5) + 5:
            e['state'] = 'angry'; ch = True
            _ev_add(slot, 'promise_angry', pid, role=e.get('role'), share=round(share, 2))
            reqs = _req_all().get(slot, {})
            if str(pid) not in reqs:
                reqs[str(pid)] = dict(status='open', reason='broken', mk='', since=_fmt_date(s.game_date_code()), urgent=True, strikes=1)
                _req_save(slot, reqs)
    if ch:
        _prom_save(slot, d)


def player_requests(slot):
    """Faza 3: nezadovoljni igraci traze odlazak (klupa/ambicija). Deterministicno po (slot, igrac, mjesec); stanje u data/requests.json."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    try:
        promise_check(slot, s)
    except Exception:
        pass
    try:
        addon_check(slot, s)
    except Exception:
        pass
    y, m, _ = _date_tuple(s.game_date_code())
    mk = '%d-%d' % (y, m)
    squad = list(s.my_squad_tags())
    ov = {q: rat(q) for q in squad}
    mo = [v[0] for v in ov.values() if v[0]]
    top = sorted(mo, reverse=True)[:11]
    avg11 = sum(top) / len(top) if top else 0
    st = _req_all().get(slot, {})
    ch = False
    # tek dosli igraci (potpis/transfer unutar zadnjih REQ_NEW_MONTHS mjeseci) se ne mogu zaliti
    newb = set()
    try:
        for q, c in s.read_contracts(squad).items():
            if c.get('sy') and 2000 < c['sy'] < 2100:
                if (y - c['sy']) * 12 + (m - (c.get('sm') or 1)) < REQ_NEW_MONTHS:
                    newb.add(q)
    except Exception:
        pass
    for k in list(st):
        if int(k) in newb and st[k].get('status') in ('open', 'refused'):
            st.pop(k); ch = True
    for k in list(st):
        if int(k) not in squad:
            st.pop(k); ch = True
    # koliko zadnjih utakmica (sve redom) igrac nije bio u prvih 11 - zali se tek nakon vise takvih utakmica
    xi_hist = []
    try:
        _M = _season(slot, s)
        _my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        _ms = [m_ for m_ in _M['matches'] if m_['played'] and _my in (m_['home'], m_['away'])]
        _ms.sort(key=seasonstats.sort_key, reverse=True)
        xi_hist = [set(r_[0] for r_ in m_['rows'] if r_[1] == _my) for m_ in _ms[:16]]
    except Exception:
        xi_hist = []

    def _missed(q):
        n_ = 0
        for xs in xi_hist:
            if q in xs:
                break
            n_ += 1
        return n_
    def _form10(q):
        n_ = min(10, len(xi_hist))
        a_ = sum(1 for xs in xi_hist[:10] if q in xs)
        return a_, n_
    # novi trener: prvih REQ_GRACE utakmica karijere nitko se ne zali (stari otvoreni zahtjevi iz tog razdoblja se brisu)
    try:
        _career_n = len([m_ for m_ in _M['matches'] if m_['played'] and _my in (m_['home'], m_['away'])]) + 0
        _all_s = seasonstats.played_seasons(_M) if hasattr(seasonstats, 'played_seasons') else []
    except Exception:
        _career_n, _all_s = 99, []
    grace = _career_n < REQ_GRACE and len(_all_s) <= 1
    if grace:
        for k in list(st):
            if st[k].get('status') == 'open' and not st[k].get('strikes'):
                st.pop(k); ch = True
    for pid in squad:
        ovr, age = ov[pid]
        if not ovr or pid in newb or grace:
            continue
        key = str(pid)
        e = st.get(key)
        tr = persona.traits(pid)
        a10, n10 = _form10(pid)
        # igrac koji stvarno igra (nastupio u >=60% zadnjih ~10 utakmica i nije preskocio 3 zadnje) se ne zali na minute, a stari zahtjev se brise
        regular = n10 >= 4 and a10 >= 0.6 * n10 and _missed(pid) < 3
        if regular and e and e.get('status') in ('open', 'refused', 'promised') and e.get('reason') in ('minutes', 'broken'):
            st.pop(key); ch = True
            continue
        rk = persona.squad_rank(mo, ovr)
        bench = rk >= 11 and ovr >= avg11 - 9 and (age or 25) >= 21
        # jaci igrac (blizu prve 11) se zali nakon 4 utakmice izvan prvih 11; slabiji tek nakon 7 i puno rjede
        strong = ovr >= avg11 - 4
        need_miss = 4 if strong else 7
        qfac = 1.0 if strong else 0.35
        reason = None
        if bench and not regular and tr['ego'] >= 0.45 and _missed(pid) >= need_miss:
            reason = 'minutes'
        elif tr['ambition'] > 0.75 and ovr >= avg11 + 3 and tr['loyalty'] < 0.6 and len(xi_hist) >= 10:
            reason = 'ambition'
        if e and e.get('status') == 'promised' and e.get('mk') != mk:
            if bench and not regular:
                e.update(status='open', reason='broken', mk=mk, urgent=True, strikes=e.get('strikes', 0) + 1); ch = True
                if e['strikes'] >= REQ_STRIKES:
                    e['status'] = 'forced'; tlist_set(dict(slot=slot, pid=pid, on=True, reason='unhappy', ask=None))
                    _ev_add(slot, 'req_forced', pid, strikes=e['strikes'])
                else:
                    _ev_add(slot, 'req_broken', pid, strikes=e['strikes'])
            else:
                st.pop(key); ch = True
            continue
        if e and e.get('status') == 'refused' and e.get('mk') != mk and reason:
            e.update(status='open', mk=mk, urgent=True); ch = True
            continue
        if e and xi_hist and e.get('status') == 'open' and e.get('reason') == 'minutes' and not e.get('strikes') and not e.get('urgent') and _missed(pid) < need_miss:
            st.pop(key); ch = True      # stari zahtjev iz vremena prije ovog pravila: igrac nije dovoljno utakmica izvan prve 11
            continue
        if e or not reason:
            continue
        if persona._rng('req', slot, pid, mk).random() < (0.25 + 0.4 * tr['ego']) * (qfac if reason == 'minutes' else 1.0):
            st[key] = dict(status='open', reason=reason, mk=mk, since=_fmt_date(s.game_date_code()), urgent=False); ch = True
    if ch:
        _req_save(slot, st)
    out = []
    for k, e in st.items():
        pid = int(k)
        ovr, age = ov.get(pid, (0, 0))
        a10, n10 = _form10(pid)
        out.append(dict(pid=pid, name=NAMES.get(pid, k), ovr=ovr, age=age, pos=POS.get(pid, 5), status=e['status'], reason=e['reason'], apps=a10, of=n10,
                        since=e.get('since'), urgent=bool(e.get('urgent')), strikes=e.get('strikes', 0), max_strikes=REQ_STRIKES, club=e.get('club'), rank=persona.squad_rank(mo, ovr) + 1))
    out.sort(key=lambda r: (r['status'] not in ('open', 'forced'), -r['ovr']))
    return dict(items=out)


def player_request_act(body):
    slot, pid, act = body['slot'], int(body['pid']), body['act']
    st = _req_all().get(slot, {})
    e = st.get(str(pid))
    if not e:
        raise ValueError('no request')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    y, m, _ = _date_tuple(s.game_date_code())
    if e.get('status') != 'open':
        raise ValueError('request already resolved this month')
    e['mk'] = '%d-%d' % (y, m)
    if act == 'release':
        tlist_set(dict(slot=slot, pid=pid, on=True, reason='unhappy', ask=None))
        e['status'] = 'released'
        _ev_add(slot, 'req_release', pid, reason=e.get('reason'))
    elif act == 'promise':
        e['status'] = 'promised'; e['urgent'] = False
        _ev_add(slot, 'req_promise', pid, reason=e.get('reason'))
    elif act == 'reassure':
        # razgovor: ako igrac stvarno igra, brojke ga uvjere i zahtjev nestaje; ako ne igra, ne vjeruje ti
        M_ = _season(slot, s)
        my_ = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        ms_ = [m_ for m_ in M_['matches'] if m_['played'] and my_ in (m_['home'], m_['away'])]
        ms_.sort(key=seasonstats.sort_key, reverse=True)
        h_ = [any(r_[0] == pid and r_[1] == my_ for r_ in m_['rows']) for m_ in ms_[:10]]
        if len(h_) >= 3 and sum(h_) >= 0.6 * len(h_) and h_[0]:
            _ev_add(slot, 'req_calmed', pid, reason=e.get('reason'))
            st2 = {**_req_all().get(slot, {})}
            st2.pop(str(pid), None)
            _req_save(slot, st2)
            return player_requests(slot)
        raise ValueError('He does not buy it: he played %d of the last %d matches.' % (sum(h_), len(h_)))
    elif act == 'refuse':
        e['strikes'] = e.get('strikes', 0) + 1
        e['status'] = 'refused'
        if e['strikes'] >= REQ_STRIKES:
            e['status'] = 'forced'
            tlist_set(dict(slot=slot, pid=pid, on=True, reason='unhappy', ask=None))
            _ev_add(slot, 'req_forced', pid, strikes=e['strikes'])
        else:
            _ev_add(slot, 'req_refuse', pid, strikes=e['strikes'], reason=e.get('reason'))
    else:
        raise ValueError('nepoznata radnja')
    _req_save(slot, {**_req_all().get(slot, {}), str(pid): e})
    return player_requests(slot)


def _find_offer(slot, s, pid, off):
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    mk = _sell_mk(gd)
    live, _ = read_dump()
    lv = (live or {}).get(pid) or {}
    fm = mlwrite.Save.flag_map(s.d)
    app = _tl_slot(slot).get(str(pid))
    app = _tl_norm(app) if app else None
    if app and not app['tl']:
        app = None
    listed = bool(lv.get('tl') or fm.get(pid, (False, False))[0] or app)
    if pid in _moved(slot, s):
        raise ValueError('player has already changed clubs in this transfer window')
    for o in _offers_for(slot, s, gd, mk, pid, lv, listed, (app or {}).get('ask')):
        if o['off'] == off:
            return o, mk
    raise ValueError('offer no longer exists (it may have expired)')


SELL_ROUNDS = negotiate.SELL_ROUNDS


def _sell_key(pid, off):
    return -(pid * 1000 + off % 1000)


def _expires(gd):
    import calendar
    y, m, _ = _date_tuple(gd)
    return '%d/%d/%d' % (calendar.monthrange(y, m)[1], m, y)


def _sell_rec(slot, pid, off, mk, o):
    """Zapis pregovora za ponudu (vrijedi do kraja mjeseca igre). Stari zapisi bez 'stage' se normaliziraju."""
    w = _neg_store().get(slot, _sell_key(pid, off))
    if not (w and w.get('mk') == mk):
        w = dict(mk=mk, fee=o['fee'], start=o['fee'], rounds=0, stage='club', log=[])
    w.setdefault('stage', 'dead' if w.get('gone') else 'club')
    w.setdefault('log', [])
    w.setdefault('start', o['fee'])
    w.setdefault('p_round', 0)
    return w


def _sell_put(slot, pid, off, w):
    w['pid'], w['off'] = pid, off
    if w.pop('_refnow', None):
        try:
            _ev_add(slot, 'sale_refused', pid, to=w.get('club'))
        except Exception:
            pass
    _neg_store().put(slot, _sell_key(pid, off), w)


def _will_shown(o, w):
    """pc216: da igrac odbija ('refuses') vidi se tek kad odbije (nakon dogovora klubova); do tada izgleda kao da nerado odlazi."""
    if o['will'] == 'refuses' and not w.get('gone'):
        return 'reluctant'
    return o['will']


def _sell_fields(slot, o, w, mk, full=False):
    d = dict(off=o['off'], club=o['club'], fee=w['fee'], start=w['start'], asked=bool(w['rounds']), rounds=w['rounds'], max_rounds=SELL_ROUNDS,
             p_round=w.get('p_round', 0), p_rounds=negotiate.SELL_P_ROUNDS, stage=w['stage'], gone=bool(w.get('gone')), why_gone=w.get('why_gone'),
             will=_will_shown(o, w), why=o['why'], pro=o['pro'], wage=o.get('wage', 0), wage_offer=o['wage_offer'],
             bonus_pct=w.get('bonus_pct'), last_counter=w.get('last_counter'), p_last_counter=w.get('p_last_counter'),
             waiting=(_fmt_due(w['pending']['due']) if w.get('pending') else None), wait_kind=(w['pending'].get('kind') if w.get('pending') else None),
             wait_why=(w['pending'].get('why') if w.get('pending') else None), tactics=w.get('tactics') or [], deadline=bool(w.get('deadline')))
    if full:
        d['log'] = w['log']
        d['tone'] = w.get('mood')
    return d


def _sell_neg_view(slot, s, pid, off, o, w, mk):
    live, _ = read_dump()
    lv = (live or {}).get(pid) or {}
    ovr, age = rat(pid)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    until = ('%d/%d' % (lv['cm'], lv['cy'])) if lv.get('cy') else ''
    app = _tl_slot(slot).get(str(pid))
    app = _tl_norm(app) if app else None
    d = _sell_fields(slot, o, w, mk, True)
    d.update(pid=pid, name=NAMES.get(pid, str(pid)), ovr=ovr, age=lv.get('age') or age, pos=POS.get(pid, 5), mv=lv.get('mv', 0), sal=lv.get('sal', 0),
             until=until, budget=s.budget(), squad=len(list(s.my_squad_tags())), expires=_expires(gd), round_max=SELL_ROUNDS,
             ask=(app or {}).get('ask') if app and app['tl'] else None, listed=bool(lv.get('tl') or (app and app['tl'])))
    so = (_addons(slot).get(str(pid)) or {})
    if so.get('sellon'):
        d['sell_on'] = dict(pct=so['sellon'], club=so.get('club', ''), src='app')
    else:
        g = _game_sellon(s, pid)
        if g:
            d['sell_on'] = dict(pct=g[0], club=g[1], src='game')
    return d


def _sell_ctx(body):
    slot, pid, off = body['slot'], int(body['pid']), int(body['off'])
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if pid in s.loaned_in_pids():
        raise ValueError(LOANED_MSG)
    o, mk = _find_offer(slot, s, pid, off)
    w = _sell_rec(slot, pid, off, mk, o)
    w['mood'] = w.get('mood_set') or negotiate.buyer_mood(slot, pid, off, mk)
    w['club'] = o['club']
    gd = s.game_date_code()
    last = _win_last(gd)
    w['deadline'] = bool(last is not None and _cmp_date(_add_days(gd, 4), last) >= 0)
    o['ceil'] = negotiate.rnd100(o['ceil'] * w.get('ceil_mult', 1.0) * (1.05 if w['deadline'] else 1.0), 100)
    if _sell_tick(slot, pid, off, s, o, w):
        _sell_put(slot, pid, off, w)
    return slot, pid, off, s, o, mk, w


def _month_last(gd):
    import calendar
    y, m, _ = _date_tuple(gd)
    return (calendar.monthrange(y, m)[1] << 24) | (m << 16) | y


def _sell_tick(slot, pid, off, s, o, w):
    """Pustio si kupca da ceka: kad rok dospije, kupac podigne ponudu, ne napravi nista ili odustane."""
    pe = w.get('pending')
    gd = s.game_date_code()
    if not pe or _cmp_date(gd, pe['due']) < 0:
        return False
    w.pop('pending', None)
    if pe.get('kind') == 'leak':
        _sell_leak_resolve(slot, pid, off, w, o, gd)
        return True
    if pe.get('kind') == 'stall':
        w['log'].append(dict(who='club', stage='club', ev='stall_over', why=pe.get('why'), d=_fmt_date(gd)))
        if pe.get('want'):
            _sell_counter_reply(w, o, pe['want'], gd)
        return True
    r = nego2.rng('swait', slot, pid, off, w.get('mk'))
    p_up, p_walk = {'eager': (0.65, 0.05), 'balanced': (0.45, 0.15), 'hard': (0.25, 0.3)}.get(w['mood'], (0.45, 0.15))
    if w.get('deadline'):
        p_up, p_walk = min(0.9, p_up + 0.25), max(0.0, p_walk - 0.1)
    x = r.random()
    d = _fmt_date(gd)
    if x < p_walk:
        w.update(gone=True, stage='dead', why_gone='club')
        w['log'].append(dict(who='club', stage='club', ev='wait_walk', d=d))
    elif x < p_walk + p_up:
        nf = negotiate.rnd100(min(o['ceil'], w['fee'] * r.uniform(1.04, 1.12)), 100)
        if nf <= w['fee']:
            nf = negotiate.rnd100(w['fee'] * 1.03, 100)
            w['ceil_mult'] = w.get('ceil_mult', 1.0) * 1.03
        w['fee'] = nf
        w['log'].append(dict(who='club', stage='club', ev='wait_raise', amount=nf, d=d))
    else:
        w['log'].append(dict(who='club', stage='club', ev='wait_nothing', d=d))
    return True



SELL_STALL = ('board', 'director_away', 'finance', 'own_sale', 'coach_check', 'owner', 'medical_files', 'agent_fee')


def _sell_leak_resolve(slot, pid, off, w, o, gd):
    """Vijest o prodaji izasla u medije (dan-dva nakon curenja). Kupac moze podici ponudu, naljutiti se ili odustati,
    javi se drugi klub, ili vijest prode nezapazeno."""
    r = nego2.rng('sleak', slot, pid, off, w.get('mk'))
    d = _fmt_date(gd)
    mood = w.get('mood') or 'balanced'
    p_work = {'eager': 0.5, 'balanced': 0.38, 'hard': 0.24}.get(mood, 0.38) + (0.12 if w.get('deadline') else 0)
    p_angry = {'eager': 0.18, 'balanced': 0.26, 'hard': 0.36}.get(mood, 0.26)
    p_rival = 0.14 if (o.get('ovr') or rat(pid)[0] or 0) >= 72 else 0.07
    p_walk = {'eager': 0.04, 'balanced': 0.08, 'hard': 0.14}.get(mood, 0.08)
    x = r.random()
    if x < p_walk:
        w.update(gone=True, stage='dead', why_gone='club')
        w['log'].append(dict(who='club', stage='club', ev='leak_walk', d=d))
    elif x < p_walk + p_angry:
        w['mood_set'] = 'hard'
        w['angry'] = True
        nf = negotiate.rnd100(w['fee'] * r.uniform(0.93, 0.98), 100)
        w['fee'] = min(w['fee'], nf)
        w['log'].append(dict(who='club', stage='club', ev='leak_angry', amount=w['fee'], d=d))
    elif x < p_walk + p_angry + p_rival:
        w['ceil_mult'] = w.get('ceil_mult', 1.0) * r.uniform(1.07, 1.13)
        nf = negotiate.rnd100(w['fee'] * r.uniform(1.06, 1.11), 100)
        w['fee'] = max(w['fee'], nf)
        w['log'].append(dict(who='club', stage='club', ev='leak_rival', amount=w['fee'], d=d))
    elif x < p_walk + p_angry + p_rival + p_work:
        w['ceil_mult'] = w.get('ceil_mult', 1.0) * r.uniform(1.03, 1.08)
        nf = negotiate.rnd100(w['fee'] * r.uniform(1.02, 1.06), 100)
        w['fee'] = max(w['fee'], nf)
        w['log'].append(dict(who='club', stage='club', ev='leak_works', amount=w['fee'], d=d))
    else:
        w['log'].append(dict(who='club', stage='club', ev='leak_quiet', d=d))
    w['log'].append(dict(who='player', stage='club', ev='leak_player', d=d, v=r.randint(0, 3)))


def _sell_counter_reply(w, o, want, gd):
    r = negotiate.buyer_reply(o['ceil'], w['mood'], w['fee'], want, w['rounds'])
    w['log'].append(dict(who='club', stage='club', decision=r['decision'], hint=r.get('hint'), counter=r.get('counter')))
    if r['decision'] == 'accept':
        w['fee'] = want
        _sell_next(o, w)
    elif r['decision'] == 'counter':
        w['fee'] = r['counter']
        w['last_counter'] = r['counter']
    elif r['decision'] == 'walk':
        w.update(gone=True, stage='dead', why_gone='club')
    return r


def sell_tactic(body):
    """Taktike pri prodaji (svaka jednom po ponudi): wait (pusti ih da cekaju), bluff (tvrdis da imas vecu ponudu), leak (pustis vijest medijima)."""
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    tac = body.get('tactic')
    if w.get('gone') or w['stage'] == 'dead':
        raise ValueError('the club withdrew its offer')
    if w['stage'] != 'club':
        raise ValueError('price already agreed')
    if w.get('pending'):
        raise ValueError('You are already letting them wait (until %s).' % _fmt_due(w['pending']['due']))
    used = set(w.get('tactics') or [])
    if tac in used:
        raise ValueError('You already tried that with this club.')
    gd = s.game_date_code()
    d = _fmt_date(gd)
    r = nego2.rng('stac', slot, pid, off, mk, tac)
    if tac == 'wait':
        lim = _month_last(gd)
        wl = _win_last(gd)
        if wl is not None and _cmp_date(wl, lim) < 0:
            lim = wl
        due = _add_days(gd, r.randint(2, 4))
        if _cmp_date(due, lim) > 0:
            due = lim
        if _cmp_date(due, gd) <= 0:
            raise ValueError('There is no time left to make them wait: the offer expires today.')
        w['pending'] = dict(kind='wait', due=due)
        w['log'].append(dict(who='you', stage='club', ev='wait', until=_fmt_due(due), d=d))
    elif tac == 'bluff':
        claim = int(body.get('claim') or 0)
        if claim <= w['fee']:
            raise ValueError('Claim a bid higher than their current offer.')
        others = [x for x in _offers_for(slot, s, gd, mk, pid, ((read_dump()[0] or {}).get(pid) or {}), True) if x['off'] != off]
        real = any(x['fee'] >= claim * 0.95 for x in others)
        w['log'].append(dict(who='you', stage='club', ev='bluff', amount=claim, d=d))
        ratio = claim / float(o['ceil'] or 1)
        if real:
            ok = r.random() < 0.8
        else:
            ok = r.random() < max(0.05, {'eager': 0.6, 'balanced': 0.45, 'hard': 0.3}.get(w['mood'], 0.45) - max(0.0, ratio - 1.05) * 2)
        if ok:
            if claim > o['ceil']:
                w['ceil_mult'] = w.get('ceil_mult', 1.0) * min(1.15, claim / float(o['ceil']))
            nf = negotiate.rnd100(min(claim, o['ceil'] * min(1.15, max(1.0, claim / float(o['ceil'])))) * r.uniform(0.96, 1.0), 100)
            w['fee'] = max(w['fee'], nf)
            w['log'].append(dict(who='club', stage='club', ev='bluff_works', amount=w['fee'], real=real, d=d))
        else:
            w['mood_set'] = 'hard'
            if r.random() < (0.15 if real else 0.35):
                w.update(gone=True, stage='dead', why_gone='club')
                w['log'].append(dict(who='club', stage='club', ev='bluff_walk', d=d))
            else:
                w['fee'] = negotiate.rnd100(w['fee'] * 0.95, 100)
                w['log'].append(dict(who='club', stage='club', ev='bluff_caught', amount=w['fee'], d=d))
    elif tac == 'leak':
        w['leak'] = True
        lim = _month_last(gd)
        wl = _win_last(gd)
        if wl is not None and _cmp_date(wl, lim) < 0:
            lim = wl
        due = _add_days(gd, r.randint(1, 2))
        if _cmp_date(due, lim) > 0:
            due = lim
        w['log'].append(dict(who='you', stage='club', ev='leak', d=d, outlet=r.randint(0, 5)))
        if _cmp_date(due, gd) <= 0:
            _sell_leak_resolve(slot, pid, off, w, o, gd)     # zadnji dan roka: vijest odmah
        else:
            w['pending'] = dict(kind='leak', due=due)
        try:
            _neg_world(slot, 'sale_leak', pid, o['club'])
        except Exception:
            pass
    else:
        raise ValueError('unknown tactic')
    used.add(tac)
    w['tactics'] = sorted(used)
    _sell_put(slot, pid, off, w)
    return _sell_neg_view(slot, s, pid, off, o, w, mk)


def sell_open(body):
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    return _sell_neg_view(slot, s, pid, off, o, w, mk)


def _sell_next(o, w):
    w['last_counter'] = None
    if o['will'] == 'refuses':
        # pc216: igrac koji ne zeli u taj klub to kaze tek kad se klubovi dogovore (prije se ponuda nije mogla ni pregovarati)
        w['log'].append(dict(who='player', stage='player', decision='walk', why=(o.get('why') or [])[:2]))
        w.update(gone=True, stage='dead', why_gone='player', _refnow=True)
        return
    w['stage'] = 'ready' if o['will'] == 'willing' else 'player'


def sell_counter(body):
    """Pregovor s klubom kupcem (do 3 kruga): prihvati, uzvrati, drži cijenu ili odustane."""
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    if w.get('gone') or w['stage'] == 'dead':
        raise ValueError('the player turned the move down' if w.get('why_gone') == 'player' else 'the club withdrew its offer')
    if w['stage'] != 'club':
        raise ValueError('price already agreed')
    if w.get('pending'):
        raise ValueError('Waiting for their answer until %s.' % _fmt_due(w['pending']['due']))
    if w['rounds'] >= SELL_ROUNDS:
        raise ValueError('The price talks are over: accept their offer or let them go.')
    cur, want = w['fee'], int(body['fee'])
    if want <= cur:
        raise ValueError('asks for more than the current offer')
    w['rounds'] += 1
    w['log'].append(dict(who='you', stage='club', amount=want))
    gd = s.game_date_code()
    if not w.get('stalled') and not w.get('deadline'):
        rs = nego2.rng('sstall', slot, pid, off, mk, w['rounds'])
        if rs.random() < 0.13:
            due = _add_days(gd, rs.randint(1, 3))
            lim = _month_last(gd)
            wl = _win_last(gd)
            if wl is not None and _cmp_date(wl, lim) < 0:
                lim = wl
            if _cmp_date(due, lim) > 0:
                due = lim
            if _cmp_date(due, gd) > 0:
                w['stalled'] = True
                why = rs.choice(SELL_STALL)
                w['pending'] = dict(kind='stall', due=due, why=why, want=want)
                w['log'].append(dict(who='club', stage='club', ev='stall', why=why, until=_fmt_due(due), d=_fmt_date(gd)))
                _sell_put(slot, pid, off, w)
                v = _sell_neg_view(slot, s, pid, off, o, w, mk)
                v['result'] = 'stall'
                return v
    r = negotiate.buyer_reply(o['ceil'], w['mood'], cur, want, w['rounds'])
    ent = dict(who='club', stage='club', decision=r['decision'], hint=r.get('hint'), counter=r.get('counter'))
    w['log'].append(ent)
    if r['decision'] == 'accept':
        w['fee'] = want
        _sell_next(o, w)
    elif r['decision'] == 'counter':
        w['fee'] = r['counter']
        w['last_counter'] = r['counter']
    elif r['decision'] == 'walk':
        w.update(gone=True, stage='dead', why_gone='club')
    _sell_put(slot, pid, off, w)
    v = _sell_neg_view(slot, s, pid, off, o, w, mk)
    v['result'] = {'accept': 'accepted', 'counter': 'counter', 'reject': 'hold', 'walk': 'withdrawn'}[r['decision']]
    return v


def sell_agree(body):
    """Prihvacas trenutnu ponudu kluba kao dogovorenu cijenu (bez daljnjeg cjenkanja)."""
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    if w.get('gone') or w['stage'] == 'dead':
        raise ValueError('the player turned the move down' if w.get('why_gone') == 'player' else 'the club withdrew its offer')
    if w['stage'] != 'club':
        raise ValueError('price already agreed')
    if w.get('pending'):
        raise ValueError('Waiting for their answer until %s.' % _fmt_due(w['pending']['due']))
    w['log'].append(dict(who='you', stage='club', amount=w['fee'], agree=True))
    w['log'].append(dict(who='club', stage='club', decision='accept', hint='hot', counter=w['fee']))
    _sell_next(o, w)
    _sell_put(slot, pid, off, w)
    return _sell_neg_view(slot, s, pid, off, o, w, mk)


def sell_bonus(body):
    """Razgovor s igracem koji nerado odlazi: nudis mu dio naknade (%) kao bonus za pristanak."""
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    if w['stage'] != 'player':
        raise ValueError('talks with the player are not in progress')
    pct = float(body['pct'])
    if not (0 <= pct <= negotiate.BONUS_MAX):
        raise ValueError('bonus mora biti izmedju 0 i %d%%' % negotiate.BONUS_MAX)
    pm = negotiate.seller_player_mood(slot, pid, off, mk)
    ask = negotiate.bonus_ask(o['score'], persona.traits(pid), pm)
    if w.get('leak'):
        ask = min(negotiate.BONUS_MAX, round(ask * 1.2 * 2) / 2)   # vijest u medijima: igrac je uznemiren
    w['p_round'] = w.get('p_round', 0) + 1
    w['log'].append(dict(who='you', stage='player', pct=pct))
    lc = w.get('p_last_counter')
    r = dict(decision='accept', counter=pct, hint='hot') if (lc is not None and pct >= lc) else negotiate.bonus_reply(ask, pct, w['p_round'])
    w['log'].append(dict(who='player', stage='player', decision=r['decision'], hint=r.get('hint'), counter=r.get('counter'), why=o['why'][:2]))
    if r['decision'] == 'accept':
        w.update(stage='ready', bonus_pct=pct)
    elif r['decision'] == 'counter':
        w['p_last_counter'] = r['counter']
    elif r['decision'] == 'walk':
        w.update(gone=True, stage='dead', why_gone='player')
        _ev_add(slot, 'sale_refused', pid, to=o.get('club'))
    _sell_put(slot, pid, off, w)
    v = _sell_neg_view(slot, s, pid, off, o, w, mk)
    v['result'] = {'accept': 'accepted', 'counter': 'counter', 'reject': 'hold', 'walk': 'refused'}[r['decision']]
    return v



def _team_name_by_id(tid):
    """Ime kluba za team ID iz igre: EDIT datoteka (sve ekipe), pa data/teamids.json."""
    if 't2n' not in _GL:
        m = {}
        try:
            ed, _ = _edit_data()
            if ed:
                m.update({int(k): v for k, v in dbimport.teams_from_edit(ed).items()})
        except Exception:
            pass
        try:
            for k, v in json.load(open(_dbf('teamids.json'), encoding='utf-8')).items():
                if len(v) > 5:
                    m.setdefault(int(k), v)
        except Exception:
            pass
        _GL['t2n'] = m
    return _GL['t2n'].get(int(tid)) or ''


def player_terms_view(slot, pid):
    """Uvjeti ugovora koje je dogovorila igra (odstetna klauzula, bonusi, sell-on bivsem klubu)."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    t = s.player_terms(int(pid)) or {}
    if t.get('sell_on_team'):
        t['sell_on_club_name'] = _team_name_by_id(t['sell_on_team'])
    return t


def _game_sellon(s, pid):
    """(postotak, ime kluba) ako igrac ima sell-on klauzulu iz igre prema bivsem klubu, inace None."""
    try:
        t = s.player_terms(pid) or {}
    except Exception:
        return None
    if t.get('sell_on'):
        return t['sell_on'], _team_name_by_id(t.get('sell_on_team') or 0)
    return None


def sell_do(body):
    slot, pid, off, s, o, mk, w = _sell_ctx(body)
    if o['will'] == 'refuses':
        raise ValueError('player does not want to join that club')
    if w.get('gone') or w['stage'] == 'dead':
        raise ValueError('the club withdrew its offer')
    if w['stage'] == 'player' or (w['stage'] == 'club' and o['will'] != 'willing'):
        raise ValueError('Igrac nerado odlazi: prvo razgovaraj s njim.')
    if w['stage'] == 'done':
        raise ValueError('vec prodano')
    fee = w['fee']
    if int(body.get('fee', fee)) != fee:
        raise ValueError('offer amount changed, refresh')
    bonus = int(round(fee * (w.get('bonus_pct') or 0) / 100.0 / 100.0)) * 100
    so = _addons(slot).get(str(pid)) or {}
    gso = None if so.get('sellon') else _game_sellon(s, pid)
    if gso:
        so = dict(sellon=gso[0], club=gso[1], game=True)    # sell-on iz ugovora u igri (bivsi klub dobiva svoj dio)
    sellon_amt = int(round(fee * (so.get('sellon') or 0) / 100.0 / 100.0)) * 100
    my_so = max(0, min(30, int(body.get('sellon') or 0)))
    disc = int(round(fee * my_so * SELLON_DISC / 100.0)) * 100
    net = fee - bonus - sellon_amt - disc

    def fn(sv):
        return sv.sell_player(pid, net, off, POS)
    r = _write_slot(slot, 'sell', fn)
    _mark_moved(slot, s, pid)
    _tl_remove(slot, pid)
    if my_so:
        try:
            a = _so_all(); a.setdefault(slot, {})[str(pid)] = dict(pct=my_so, buyer=o.get('club'), fee=fee - disc); _so_save(a)
        except Exception:
            pass
    w['stage'] = 'done'
    _sell_put(slot, pid, off, w)
    _ev_add(slot, 'sold', pid, to=o.get('club'), fee=fee, wage=o.get('wage_offer') or 0, bonus=bonus)
    if sellon_amt:
        try:
            if not so.get('game'):
                d = _addons(slot); d.pop(str(pid), None); _addons_save(slot, d)
            _ev_add(slot, 'sellon_paid', pid, fee=sellon_amt, to=so.get('club', ''))
        except Exception:
            pass
    if (bonus or sellon_amt or disc) and isinstance(r, dict):
        r['message'] = (r.get('message') or '') + ' (player bonus %d EUR, sell-on to previous club %d EUR, discount for your sell-on %d EUR, net written %d EUR)' % (bonus, sellon_amt, disc, net)
    return r


# ---------------- produljenje ugovora ----------------
CT_MAXY = 5


def _ct_ctx(slot, pid):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if pid not in s.my_squad_tags():
        raise ValueError('player is not in your squad')
    if pid in s.loaned_in_pids():
        raise ValueError(LOANED_MSG)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    live, _ = read_dump()
    lv = dict((live or {}).get(pid) or {})
    c = s.read_contracts([pid]).get(pid) or {}
    if c.get('y'):
        lv.update(sal=c['sal'] or lv.get('sal', 0), cy=c['y'], cm=c['m'])
    ovr, age = rat(pid)
    ml = (lv['cy'] - y) * 12 + (lv['cm'] - m) if lv.get('cy') else None
    f = negotiate.facts(ovr, lv.get('age') or age or 25, lv.get('mv', 0), lv.get('sal', 0), ml, False)
    my = [rat(p)[0] for p in s.squad_ids() if p]
    my = [o for o in my if o]
    mk_ = '%d-%d' % (y, m)
    season_end = y + 1 if m >= 9 else y
    return dict(s=s, f=f, my=my, mk=mk_, y=y, m=m, ml=ml, season_end=season_end, cy=lv.get('cy'), cm=lv.get('cm'), sal=f['sal'])


def contract_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    y, m, _ = _date_tuple(gd)
    live, _ = read_dump()
    cts = s.read_contracts(list(s.my_squad_tags()))
    my = [o for o in (rat(p)[0] for p in s.squad_ids() if p) if o]
    rows = []
    _li = s.loaned_in_pids()
    for pid in s.my_squad_tags():
        lv = dict((live or {}).get(pid) or {})
        c = cts.get(pid) or {}
        if c.get('y'):
            lv.update(sal=c['sal'] or lv.get('sal', 0), cy=c['y'], cm=c['m'])
        ovr, age = rat(pid)
        ml = (lv['cy'] - y) * 12 + (lv['cm'] - m) if lv.get('cy') else None
        f = negotiate.facts(ovr, lv.get('age') or age or 25, lv.get('mv', 0), lv.get('sal', 0), ml, False)
        mood = negotiate.player_mood(slot, pid, '%d-%d' % (y, m))
        role = negotiate.role_demand(my, f)
        rows.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), ovr=ovr, age=f['age'], pos=POS.get(pid, 5), mv=f['mv'], sal=f['sal'],
                         until=('%d/%d' % (lv['cm'], lv['cy'])) if lv.get('cy') else '', months=ml, role=role, mood=mood, loaned_in=(pid in _li)))
    rows.sort(key=lambda r: (r['months'] if r['months'] is not None else 999, -r['ovr']))
    try:
        dr = drama_tick(slot, s, rows)
        for r in rows:
            if r['pid'] in dr:
                r['drama'] = dr[r['pid']]
    except Exception as ex:
        print('[drama]', ex)
    try:
        bad = [dict(pid=m[0], name=NAMES.get(m[0], str(m[0]))) for m in s.tail_mismatch()]
    except Exception:
        bad = []
    return dict(players=rows, budget=s.budget(), date=_fmt_date(gd), season_end=(y + 1 if m >= 9 else y), maxy=CT_MAXY, tail_bad=bad)


def contract_offer(body):
    slot, pid = body['slot'], int(body['pid'])
    wage, years, rnd_no = int(body['wage']), int(body['years']), int(body.get('round', 1))
    if not 1 <= years <= CT_MAXY:
        raise ValueError('contract years 1-%d' % CT_MAXY)
    c = _ct_ctx(slot, pid)
    mood = negotiate.player_mood(slot, pid, c['mk'])
    role = negotiate.role_demand(c['my'], c['f'])
    dr = _drama_of(slot, pid)
    if dr.get('state') in ('refuses', 'refuses_final', 'keep', 'listed'):
        return dict(decision='reject', counter=None, hint='He has made up his mind: he wants to leave and will not sign a new contract.' if dr.get('state') != 'refuses_final' else 'He turned down your final offer. There is nothing left to talk about.', mood=mood)
    ask = negotiate.wage_ask(c['f'], mood, c['my'], role, years)
    if dr.get('state') == 'last_try':
        ask2 = int(ask * 1.4 / 1000) * 1000
        if wage < ask2:
            return dict(decision='counter', counter=ask2, hint='This is your last chance. He wants a contract that shows how much the club needs him.', mood=mood)
        ok = negotiate._rng('lasttry', slot, pid, c['mk']).random() < 0.45
        if not ok:
            A = _drama_all()
            A.setdefault(slot, {}).setdefault(str(pid), {})['state'] = 'refuses_final'
            _drama_save(A)
            return dict(decision='reject', counter=None, hint='He thought about it, but his heart is set on a move. He says no.', mood=mood)
        A = _drama_all()
        A.setdefault(slot, {}).setdefault(str(pid), {})['state'] = 'won_over'
        _drama_save(A)
        return dict(decision='accept', counter=None, hint='He is convinced. Sign it before he changes his mind.', mood=mood)
    r = negotiate.player_reply(c['f'], mood, c['my'], wage, years, role, rnd_no)
    return dict(decision=r['decision'], counter=ask if r['decision'] == 'counter' else r.get('counter'), hint=r.get('hint'), mood=mood)


def _youth_season_end(sv):
    gd = sv.game_date_code()
    y, m = gd & 0xffff, (gd >> 16) & 0xff
    return y + 1 if m >= 9 else y


def youth_terms(slot, pid):
    sv = mlwrite.Save(slot_folder(slot), ro=True)
    if not sv.can_promote():
        return dict(ok=False, why='format')
    if sv.youth_in_table(pid) is None:
        return dict(ok=False, why='notyouth')
    cur = (sv.read_contracts([pid]).get(pid) or {}).get('sal', 0)
    sug = max(30000, int(round(cur * 1.35 / 100.0)) * 100)
    n = sv._squad_len(sv.club_offset())
    return dict(ok=True, cur=cur, sal=sug, season_end=_youth_season_end(sv), squad=n)


def youth_sign(body):
    slot, pid = body['slot'], int(body['pid'])
    if pid in broken_players(slot) and not body.get('force'):
        raise ValueError('%s is marked as a player the game crashes on (Team Plan). Not signed. Unmark him in the youth list if you want to try anyway.'
                         % broken_players(slot)[pid])
    sal, years = int(body['wage']), int(body['years'])
    num = body.get('number')
    num = int(num) if num not in (None, '') else None
    if not 1 <= years <= 5:
        raise ValueError('contract years 1-5')
    if sal < 10000:
        raise ValueError('wage is too low')
    box = {}

    def fn(sv):
        end_year = _youth_season_end(sv) + years
        box['yr'] = end_year
        return sv.promote_youth(pid, sal, end_year, number=num)
    r = _write_slot(slot, 'youth', fn)
    try:
        _ev_add(slot, 'signed', pid, frm='', fee=0, wage=sal, years=years, until=box.get('yr'), bonus=0, sellon=0)
    except Exception:
        pass
    return r


def contract_sign(body):
    slot, pid = body['slot'], int(body['pid'])
    wage, years = int(body['wage']), int(body['years'])
    if not 1 <= years <= CT_MAXY:
        raise ValueError('contract years 1-%d' % CT_MAXY)
    c = _ct_ctx(slot, pid)
    mood = negotiate.player_mood(slot, pid, c['mk'])
    role = negotiate.role_demand(c['my'], c['f'])
    dr = _drama_of(slot, pid)
    if dr.get('state') in ('refuses', 'refuses_final', 'keep', 'listed', 'last_try'):
        raise ValueError('He will not sign a new contract.')
    need = negotiate.wage_ask(c['f'], mood, c['my'], role, years)
    if dr.get('state') == 'won_over':
        need = int(need * 1.4 / 1000) * 1000
    if wage < need:
        raise ValueError('player did not accept those terms')
    end_year = c['season_end'] + years
    old = (c['cm'], c['cy'], c['sal'])

    def fn(sv):
        return sv.extend_contract(pid, wage, end_year)
    r = _write_slot(slot, 'contract', fn)
    _ev_add(slot, 'renewed', pid, wage=wage, years=years, until=end_year, old_wage=old[2])
    if dr.get('state') == 'won_over':
        A = _drama_all()
        A.setdefault(slot, {}).setdefault(str(pid), {})['state'] = 'signed'
        _drama_save(A)
    r['until'] = '8/%d' % end_year
    return r



def contract_sync(body):
    """Popravak: kopija ugovora (placa/datum) u tablici na kraju save-a uskladi sa zapisom igraca (za igrace produzene starijom verzijom appa)."""
    slot = body['slot']
    bad = [m[0] for m in mlwrite.Save(slot_folder(slot)).tail_mismatch()]
    if not bad:
        return dict(ok=True, fixed=0)
    r = _write_slot(slot, 'ctsync', lambda sv: 'uskladeno %d' % (sv._sync_tail(bad) and len(bad)))
    r['fixed'] = len(bad)
    return r

# ---------------- press konferencije ----------------
PRESS_FILE = os.path.join(HERE, 'data', 'press.json')


def _press_load():
    try:
        return json.load(open(PRESS_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _press_save(a):
    os.makedirs(os.path.dirname(PRESS_FILE), exist_ok=True)
    _jdump(a, PRESS_FILE, ensure_ascii=False, indent=1)


def _press_confs(slot):
    """Konferencije koje cekaju: potpisani igraci (dogovori u igri) + zadnja odigrana utakmica."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    done = _press_load().get(slot, {}).get('done', {})
    my_idx = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    club = seasonstats.club_name(s.d, my_idx)
    out = []
    try:
        for x in deals_info(slot)['deals']:
            cid = 's%d' % x['pid']
            if cid not in done:
                out.append(dict(id=cid, kind='signing', pid=x['pid'], name=NAMES.get(x['pid'], str(x['pid'])), fee=x.get('fee', 0), club=club,
                                ovr=rat(x['pid'])[0], pos=POS.get(x['pid'], 5)))
    except Exception:
        pass
    try:
        ms = club_matches(slot, s, my_idx, None, 1, True)
    except Exception:
        ms = []
    try:
        nx_ = next_match(slot).get('next') or {}
        if nx_.get('opp'):
            pcid = 'p%s_%s' % (nx_.get('date', '').replace('.', ''), nx_.get('opp_idx'))
            if pcid not in done:
                out.append(dict(id=pcid, kind='prematch', club=club, opp=nx_['opp'], opp_idx=nx_.get('opp_idx'), date=nx_.get('date'), home=nx_.get('home')))
    except Exception as ex:
        print('[press] prematch:', ex)
    if ms:
        m = ms[0]
        cid = 'm%s' % m['n']
        if cid not in done:
            pl = [p for p in m.get('players', []) if p['rating']]
            star = max(pl, key=lambda p: (p['rating'], p['g'] * 2 + p['a'])) if pl else None
            weak = min(pl, key=lambda p: p['rating']) if pl else None
            if weak and weak['rating'] >= 6.2:
                weak = None
            out.append(dict(id=cid, kind='match', club=club, opp=m['opp'], gf=m['gf'], ga=m['ga'], res=m['res'], date=m['date'], home=m['home'], n=m['n'],
                            star=star and dict(id=star['id'], name=star['name'], rating=star['rating']), weak=weak and dict(id=weak['id'], name=weak['name'], rating=weak['rating'])))
    return s, club, out



def story_view(slot):
    """Price: povezani lanci dogadjaja (lib/story.py) iz rezultata, forme, ugovora i zahtjeva."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    y, m, _ = _date_tuple(s.game_date_code())
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    res = club_matches(slot, s, my, limit=6)
    fv = form_view(slot)['players']
    cv = contract_view(slot)['players']
    rq = player_requests(slot)['items']
    mo = sorted([r['ovr'] for r in cv if r['ovr']], reverse=True)[:11]
    my_avg = sum(mo) / len(mo) if mo else 0
    rivals = []
    try:
        clubs = aitransfers.load_clubs(s, rat, POS, my)
        rivals = [(c['name'], c['strength']) for c in sorted(clubs.values(), key=lambda c: -c['strength']) if c['strength'] > my_avg][:8]
    except Exception:
        rivals = []
    items = story.build(slot, '%d-%d' % (y, m), res, fv, cv, rq, rivals, my_avg)
    for o in items:
        o['players'] = [dict(pid=p, name=NAMES.get(p, str(p)), ovr=rat(p)[0]) for p in (o.get('pids') or [])]
    return dict(items=items, date=_fmt_date(s.game_date_code()), club=seasonstats.club_name(s.d, my), played=len(res))


TALKS_FILE = os.path.join(HERE, 'data', 'talks.json')
TALK_REQ = {'minutes': 'minutes', 'ambition': 'ambition', 'interest': 'interest', 'broken': 'broken'}


def _talks_all():
    try:
        return json.load(open(TALKS_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _talks_hist(slot):
    return _talks_all().get(slot, {})


def _talk_recent(H, pid, topic, gd, days):
    for h in reversed(H.get(str(pid), [])):
        if topic in (None, h.get('topic')):
            d0 = _parse_any_date(h.get('d'))
            if d0 and _cmp_date(_add_days(d0, days), gd) > 0:
                return True
    return False


def talks_view(slot):
    """Svlacionica: igraci koji traze razgovor + cijela momcad (pozovi igraca) + povijest razgovora."""
    s = mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    squad = list(s.my_squad_tags())
    H = _talks_hist(slot)
    pend = []
    seen = set()
    try:
        for r in player_requests(slot).get('items') or []:
            if r.get('status') in ('open', 'forced') and r['pid'] in squad:
                tp = TALK_REQ.get(r.get('reason'), 'minutes')
                if not _talk_recent(H, r['pid'], tp, gd, 10):
                    pend.append(dict(pid=r['pid'], name=r['name'], topic=tp, urgent=bool(r.get('urgent') or r.get('status') == 'forced'), club=r.get('club')))
                    seen.add(r['pid'])
    except Exception as ex:
        print('[talks] req:', ex)
    try:
        for k, e in _promises(slot).items():
            pid = int(k)
            if e.get('state') in ('upset', 'angry') and pid in squad and pid not in seen and not _talk_recent(H, pid, 'broken', gd, 10):
                pend.append(dict(pid=pid, name=NAMES.get(pid, k), topic='broken', urgent=e.get('state') == 'angry', role=e.get('role')))
                seen.add(pid)
    except Exception:
        pass
    try:
        for c in contract_view(slot).get('players') or []:
            if c.get('loaned_in') or c['pid'] in seen or c.get('months') is None:
                continue
            if c.get('role') in ('key', 'starter') and 0 < c['months'] <= 12 and not _talk_recent(H, c['pid'], 'contract', gd, 60):
                pend.append(dict(pid=c['pid'], name=c['name'], topic='contract', urgent=c['months'] <= 6, months=c['months']))
                seen.add(c['pid'])
    except Exception as ex:
        print('[talks] contracts:', ex)
    live = {}
    try:
        live = growth.read_live(CFG.get('dump') or '', squad) or {}
    except Exception:
        live = {}
    sq = []
    for pid in squad:
        lv = live.get(pid) or {}
        last = (H.get(str(pid)) or [{}])[-1]
        sq.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=rat(pid)[0], aff=lv.get('aff'), form=lv.get('form'),
                       last=last.get('d'), last_oc=last.get('outcome'), busy=_talk_recent(H, pid, None, gd, 7)))
    sq.sort(key=lambda r: -(r['ovr'] or 0))
    hist = []
    for k, L in H.items():
        for h in L[-5:]:
            hist.append(dict(h, pid=int(k), name=NAMES.get(int(k), k)))
    hist.sort(key=lambda h: (_date_tuple(_parse_any_date(h.get('d')) or 0), h.get('n', 0)), reverse=True)
    pend.sort(key=lambda x: (not x.get('urgent'), x['name']))
    return dict(pending=pend, squad=sq, history=hist[:30], live=bool(live), today=_fmt_date(gd))


def _talk_ctx(slot, s, pid, topic):
    tr = persona.traits(pid)
    nm = NAMES.get(pid, '')
    ctx = dict(first=(nm.split()[0] if nm else ''))
    try:
        lv = (growth.read_live(CFG.get('dump') or '', [pid]) or {}).get(pid) or {}
        if lv.get('aff') is not None and lv['aff'] < 110:
            ctx['low_mood'] = 1
        if lv.get('form') is not None:
            ctx['form'] = lv['form']
    except Exception:
        pass
    try:
        r = (_req_all().get(slot, {}) or {}).get(str(pid)) or {}
        ctx['broken'] = min(2, r.get('strikes', 0))
        ctx['club_int'] = r.get('club')
    except Exception:
        pass
    mo = [rat(q)[0] for q in s.my_squad_tags() if rat(q)[0]]
    ovr, age = rat(pid)
    dem = persona.demanded_role(persona.squad_rank(mo, ovr), age or 25)
    ctx['dem'] = dem
    ctx['role_gap'] = 1 if dem in ('rotation', 'prospect') else (-1 if dem == 'key' else 0)
    top = sorted(mo, reverse=True)[:14]
    ctx['step_down'] = 1 if top and ovr and ovr > sum(top) / len(top) + 3 else 0
    return tr, ctx


def talk_start(body):
    slot, pid, topic = body['slot'], int(body['pid']), body['topic']
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if pid not in set(s.my_squad_tags()):
        raise ValueError('player is not in your squad')
    if topic in ('praise', 'encourage', 'warn', 'role') and _talk_recent(_talks_hist(slot), pid, None, s.game_date_code(), 7):
        raise ValueError('You spoke to him less than a week ago. Give it some time.')
    tr, ctx = _talk_ctx(slot, s, pid, topic)
    seed = '%s|%s|%s' % (slot, pid, s.game_date_code())
    return dict(pid=pid, name=NAMES.get(pid, str(pid)), topic=topic, opening=talkslib.opening(topic, ctx, seed), options=talkslib.options(topic, ctx),
                dem=ctx.get('dem'), traits=dict((k, round(v, 2)) for k, v in tr.items()))


def talk_reply(body):
    slot, pid, topic, ch = body['slot'], int(body['pid']), body['topic'], body['choice']
    s = mlwrite.Save(slot_folder(slot), ro=True)
    if pid not in set(s.my_squad_tags()):
        raise ValueError('player is not in your squad')
    gd = s.game_date_code()
    tr, ctx = _talk_ctx(slot, s, pid, topic)
    seed = '%s|%s|%s' % (slot, pid, gd)
    text = (body.get('text') or '').strip()[:400]
    adj = 0.0
    if text:
        try:
            adj = nlu.understand_talk(topic, talkslib.options(topic, ctx), text)['adj']
        except Exception:
            adj = 0.0
    r = talkslib.resolve(topic, ch, tr, ctx, seed, adj)
    notes = []
    act = r['action']
    req = (_req_all().get(slot, {}) or {}).get(str(pid))
    try:
        if act == 'req_promise' and req and req.get('status') == 'open':
            player_request_act(dict(slot=slot, pid=pid, act='promise'))
            notes.append('Promise noted: he expects more minutes this month.')
        elif act == 'req_release' and r['outcome'] in ('delighted', 'content') and req and req.get('status') == 'open':
            player_request_act(dict(slot=slot, pid=pid, act='release'))
            notes.append('He is now on the transfer list. Offers will follow.')
        elif act == 'req_refuse' and req and req.get('status') == 'open':
            player_request_act(dict(slot=slot, pid=pid, act='refuse'))
            notes.append('Request refused. If he stays unhappy, it can turn into a transfer demand.')
        elif act in ('promise_key', 'promise_starter') and r['outcome'] != 'angry':
            promise_add(slot, s, pid, act.split('_')[1])
            notes.append('Role promised (%s). The app tracks his minutes: break it and he will be upset.' % act.split('_')[1])
        elif act == 'promise_reset':
            d = _promises(slot)
            if str(pid) in d:
                M = _season(slot, s)
                my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
                d[str(pid)].update(state='ok', base=len([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])]))
                _prom_save(slot, d)
                notes.append('He gets a fresh start: his minutes are counted again from today.')
        elif act == 'promise_angry':
            d = _promises(slot)
            if str(pid) in d:
                d[str(pid)]['state'] = 'angry'
                _prom_save(slot, d)
        elif act == 'go_contract' and r['outcome'] in ('delighted', 'content'):
            notes.append('He is open to a new deal: go to Contracts to offer terms.')
        if r['outcome'] == 'angry' and req and req.get('status') == 'open' and act != 'req_refuse':
            player_request_act(dict(slot=slot, pid=pid, act='refuse'))
            notes.append('The talk went badly: it counts as a refused request.')
        if r['outcome'] in ('delighted', 'content') and topic in ('minutes', 'broken') and req and req.get('status') == 'open' and act is None:
            st2 = {**_req_all().get(slot, {})}
            st2.pop(str(pid), None)
            _req_save(slot, st2)
            notes.append('He accepts it for now. The request is withdrawn.')
    except Exception as ex:
        notes.append(str(ex))
    queued = 0
    rows = [(pid, 'Affection', r['aff'])]
    for p_, f_, d_, n_ in press.chunks(rows):
        queued += growth.queue(CFG, [(p_, f_, d_)], 'tk%s-%d-%d' % (topic, gd & 0xffffff, n_))
    if r['form']:
        a0 = _press_load()
        fs0 = a0.setdefault(slot, {}).setdefault('form', {})
        try:
            c0 = len(_form_targets(slot)[1])
        except Exception:
            c0 = 0
        fs0.setdefault('bias', {})[str(pid)] = dict(v=r['form'], c0=c0)
        _press_save(a0)
        try:
            queued += form_commit(slot).get('queued', 0)
        except Exception:
            pass
    A = _talks_all()
    L = A.setdefault(slot, {}).setdefault(str(pid), [])
    opt = next((o['t'] for o in talkslib.options(topic, ctx) if o['id'] == ch), ch)
    L.append(dict(d=_fmt_date(gd), topic=topic, choice=ch, said=text or opt, meant=opt if text else None, outcome=r['outcome'], reply=r['reply'], aff=r['aff'], form=r['form'], n=len(L)))
    del L[:-20]
    _jdump(A, TALKS_FILE, ensure_ascii=False, indent=1)
    try:
        if r['outcome'] in ('angry', 'delighted') or topic in ('ambition', 'interest', 'broken'):
            _ev_add(slot, 'talk', pid, topic=topic, outcome=r['outcome'], quote=(text[:160] if text else None), reply=r['reply'])
    except Exception:
        pass
    return dict(r, notes=notes, queued=queued, bridge=growth.enabled(CFG), said=text or opt, meant=opt if text else None)


def say_talk(body):
    """Slobodan tekst u razgovoru -> koju opciju je igrac 'cuo'."""
    slot, pid, topic = body['slot'], int(body['pid']), body['topic']
    text = (body.get('text') or '').strip()[:400]
    if len(text) < 2:
        raise ValueError('Say something first.')
    s = mlwrite.Save(slot_folder(slot), ro=True)
    tr, ctx = _talk_ctx(slot, s, pid, topic)
    opts = talkslib.options(topic, ctx)
    u = nlu.understand_talk(topic, opts, text)
    meant = next((o['t'] for o in opts if o['id'] == u['pick']), None)
    return dict(pick=u['pick'], conf=u['conf'], low=u['low'], meant=meant, feats=u['feats'], options=opts,
                confused=talkslib.CONFUSED if u['pick'] is None else None)


def say_press(body):
    """Slobodan odgovor novinaru -> koji od ponudenih odgovora je to (ton i posljedice ostaju ista pravila)."""
    slot, cid, i = body['slot'], body['id'], int(body['i'])
    text = (body.get('text') or '').strip()[:500]
    if len(text) < 2:
        raise ValueError('Say something first.')
    _, _, confs = _press_confs(slot)
    conf = next((c for c in confs if c['id'] == cid), None)
    if not conf:
        raise ValueError('press conference not available')
    qs = _press_questions(slot, conf)
    if not 0 <= i < len(qs):
        raise ValueError('bad question')
    q = qs[i]
    u = nlu.understand_press(q, text)
    o = next(x for x in q['opts'] if x['id'] == u['pick'])
    return dict(pick=u['pick'], tone=u['tone'], conf=u['conf'], low=u['low'], meant=o['t'], feats=u['feats'],
                echo=nlu.echo_press(q, u['tone'], u['low'], '%s|%s|%d|%s' % (slot, cid, i, text)))


def press_view(slot):
    try:
        press_promises_check(slot)
    except Exception as ex:
        print('[press] promises:', ex)
    s, club, confs = _press_confs(slot)
    st = _press_load().get(slot, {})
    pids = list(s.my_squad_tags())
    live = None
    try:
        live = growth.read_live(CFG.get('dump') or '', pids)
    except Exception:
        live = None
    squad = []
    for pid in pids:
        lv = (live or {}).get(pid) or {}
        squad.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=rat(pid)[0], aff=lv.get('aff'), form=lv.get('form')))
    squad.sort(key=lambda r: -r['ovr'])
    return dict(club=club, pending=confs, history=st.get('hist', [])[-15:][::-1], squad=squad, live=bool(live), bridge=growth.enabled(CFG),
                promises=list(reversed(st.get('promises', [])[-10:])), fans=st.get('fans', 0))


# ---------------- forma iz utakmica ----------------
def _form_targets(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = sorted([m for m in M['matches'] if m['played'] and my in (m['home'], m['away'])], key=seasonstats.sort_key)
    squad = set(s.my_squad_tags())
    t = formengine.compute(ms, my, lambda p: POS.get(p, 5))
    t = {p: v for p, v in t.items() if p in squad}
    st = _press_load().get(slot, {}).get('form', {})
    bias = st.get('bias', {})
    for pid, v in t.items():
        b = bias.get(str(pid))
        v['bias'] = b['v'] if b and len(ms) - b['c0'] < 3 else 0
        v['target'] = formengine.with_bias(v['level'], v['bias'])
    try:
        for k, pr in _promises(slot).items():
            if int(k) in t and pr.get('state') in ('upset', 'angry'):
                t[int(k)]['target'] = max(0, t[int(k)]['target'] - (1 if pr['state'] == 'upset' else 2))
    except Exception:
        pass
    return s, ms, t, st


def form_commit(slot):
    s, ms, t, st = _form_targets(slot)
    if not ms:
        return dict(ok=False, queued=0)
    a = _press_load()
    sl = a.setdefault(slot, {})
    fs = sl.setdefault('form', {})
    sent = fs.setdefault('sent', {})
    lastn = ms[-1]['n']
    live = None
    try:
        live = growth.read_live(CFG.get('dump') or '', list(t))
    except Exception:
        live = None
    rows = []
    for pid, v in t.items():
        cur = ((live or {}).get(pid) or {}).get('form')
        if (str(pid) in sent and sent[str(pid)] == [v['target'], lastn]) or (cur is not None and cur == v['target'] and str(pid) in sent):
            continue
        rows.append((pid, v['target']))
    n = 0
    if rows:
        p_ = os.path.join(growth.bridge_dir(CFG), 'growth.csv')
        with open(p_, 'a', encoding='utf-8', newline='\n') as fh:
            for pid, tg in rows:
                fh.write('fe%d-%d-%d,%d,Form,set,%d\n' % (lastn, tg, pid, pid, tg))
                sent[str(pid)] = [tg, lastn]
                n += 1
    _press_save(a)
    return dict(ok=True, queued=n, bridge=growth.enabled(CFG))


# ---------------------------------------------------------------- Asistent menadzera
_GRP_MIN = {'gk': 2, 'def': 6, 'mid': 6, 'fw': 4}
_GRP_N = {'gk': ('golmana', 'goalkeepers'), 'def': ('braniča', 'defenders'), 'mid': ('veznih', 'midfielders'), 'fw': ('napadača', 'forwards')}


def _eur(v):
    v = v or 0
    return ('€%.1fM' % (v / 1e6)) if v >= 1e6 else ('€%dk' % round(v / 1e3))


# ---------------------------------------------------------------- prihod od utakmice (pc195)
# Publika po vaznosti utakmice i prihod od ulaznica za tvoje domace utakmice. Ideja i postoci publike: Michele & Claude,
# "Pubblico Vero" (FL26 Master League Realism Mods). App prihod upisuje u transfer budzet kad ga potvrdis (save se pise).
GATE_FILE = os.path.join(HERE, 'data', 'gate.json')


def _gate_load():
    try:
        return json.load(open(GATE_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _gate_attendance(m, kind, last_of_tid, opp_big, my_big, mo):
    """(postotak domacih, opis) po vrsti utakmice."""
    if kind == 'league':
        if opp_big or mo in (4, 5):
            return 92, 'big match'
        return (85 if my_big else 68), 'league match'
    if kind == 'groups':
        return (98, 'European knockout') if mo in (2, 3, 4, 5) else (88, 'European group stage')
    if last_of_tid and mo in (4, 5, 6):
        return 100, 'cup final'
    if mo in (1, 2, 3, 4, 5):
        return 90, 'cup quarter/semi-final'
    if mo in (7, 8):
        return 92, 'super cup / early season'
    return 52, 'cup, early round'


def gate_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    g = _gate_load()
    # pc313: po karijeri (prije po slotu: nova karijera u istom slotu dobila bi prihod za vec odigrane utakmice)
    try:
        cid = _career_id(slot, s)
    except Exception:
        cid = slot
    if cid not in g and slot in g and g[slot].get('career') in (None, cid):
        g[cid] = g.pop(slot)
    e = g.setdefault(cid, {})
    e['career'] = cid
    played = [m for m in M['matches'] if m['played'] and m['home'] == my]
    key = lambda m: '%d|%d|%d|%d|%d' % (m['season'], m['tid'], m['y'], m['m'], m['dd'])
    if 'base' not in e:
        # prvi put: sve vec odigrano se ne racuna (bez retroaktivnog dobitka)
        e['base'] = True
        e['done'] = [key(m) for m in played]
        os.makedirs(os.path.dirname(GATE_FILE), exist_ok=True)
        _jdump(g, GATE_FILE, indent=1)
    done = set(e.get('done') or [])
    try:
        clubs_ = aitransfers.load_clubs(s, rat, POS, my)
        idn = aitransfers.club_identities(clubs_)
    except Exception:
        idn = {}
    strength = {}
    try:
        order = sorted(clubs_.values(), key=lambda c: -c['strength'])
        top = {c['idx'] for c in order[:max(1, int(len(order) * 0.06))]}
    except Exception:
        top = set()
    my_big = idn.get(my) == 'big' or my in top
    seats, price = (50000, 35) if my_big else (18000, 18)
    real_cap = None
    try:   # pc382: pravi kapacitet stadiona (venue_metadata, Wikipedia); prije svi 'veliki' 50.000, ostali 18.000 (BVB: 13.000 prosjek)
        _vi = venue_info(_my_club_name(s)) or {}
        if _vi.get('cap'):
            real_cap = int(str(_vi['cap']).replace(',', ''))
            seats = real_cap   # cijena ulaznice ostaje ista (ekonomija Michele & Claude), mijenja se samo broj mjesta
    except Exception:
        pass
    try:   # pc316: prosirenje stadiona
        seats = int(seats * (1 + 0.06 * _inv_level(slot, s, 'stadium')))
    except Exception:
        pass
    rows, tot, allr = [], 0, []
    _tn = mlsave.team_names(s.d, mlsave.club_layout(s.d)[0])
    for m in sorted(played, key=seasonstats.sort_key):
        k = key(m)
        tid = m['tid']
        kind = 'league' if tid in COMP_LEAGUES else 'groups' if tid in COMP_GROUPS else 'cup'
        same = [x for x in M['matches'] if x['tid'] == tid and x['season'] == m['season']]
        last = bool(same) and max(same, key=seasonstats.sort_key) is m
        opp = m['away']
        pct, what = _gate_attendance(m, kind, last, idn.get(opp) == 'big' or opp in top, my_big, m['m'])
        import random as _rnd
        pct = max(50, min(100, pct + _rnd.Random(k).randint(-4, 4)))
        crowd = int(seats * pct / 100)
        money = int(round(crowd * price / 100.0)) * 100
        r_ = dict(key=k, date='%d.%d.%d' % (m['dd'], m['m'], m['y']), opp=(_tn[opp] if opp < len(_tn) else str(opp)),
                  what=what, pct=pct, crowd=crowd, money=money, y=m['y'], mo=m['m'], done=k in done)
        allr.append(r_)
        if k in done:
            continue
        tot += money
        rows.append(r_)
    return dict(ok=True, seats=seats, price=price, rows=rows, total=tot, big=my_big, all=allr, real_cap=real_cap)


def gate_report(slot):
    """pc313: mjesecni izvjestaj o ulaznicama (sve domace utakmice sezone po mjesecima, naplaceno ili ne)."""
    v = gate_view(slot)
    months = {}
    for r in v.get('all') or []:
        k = '%04d-%02d' % (r['y'], r['mo'])
        e = months.setdefault(k, dict(month=k, y=r['y'], mo=r['mo'], rows=[], crowd=0, money=0, open=0))
        e['rows'].append(r)
        e['crowd'] += r['crowd']
        e['money'] += r['money']
        if not r['done']:
            e['open'] += r['money']
    out = sorted(months.values(), key=lambda x: x['month'], reverse=True)
    for e in out:
        e['avg_pct'] = round(sum(r['pct'] for r in e['rows']) / len(e['rows'])) if e['rows'] else 0
    return dict(ok=True, seats=v['seats'], price=v['price'], months=out, open=v['total'],
                season_money=sum(e['money'] for e in out), season_crowd=sum(e['crowd'] for e in out))


def gate_collect(body):
    slot = body['slot']
    v = gate_view(slot)
    if not v['rows']:
        return dict(ok=True, message='No new home matches since the last collection.', total=0)
    tot = v['total']
    r = _write_slot(slot, 'gate', lambda sv: (sv.adjust_budget(tot), 'match-day income %d EUR from %d home matches' % (tot, len(v['rows'])))[1])
    g = _gate_load()
    try:
        cid = _career_id(slot, mlwrite.Save(slot_folder(slot), ro=True))
    except Exception:
        cid = slot
    e = g.setdefault(cid, {})
    e['done'] = list(set(e.get('done') or []) | {x['key'] for x in v['rows']})
    e.setdefault('log', []).append(dict(when=time.strftime('%Y-%m-%d %H:%M'), total=tot, n=len(v['rows'])))
    _jdump(g, GATE_FILE, indent=1)
    msg = 'Match-day income: %s EUR from %d home matches added to the transfer budget.' % ('{:,}'.format(tot), len(v['rows']))
    return dict(ok=True, message=msg, total=tot, detail=r)


# ---------------------------------------------------------------- revalorizacija na kraju sezone (pc197; Michele & Claude)
REVAL_FILE = os.path.join(HERE, 'data', 'revalue.json')
REVAL_WORLD = True
REVAL_WORLD_DAMP, REVAL_WORLD_MIN, REVAL_WORLD_MAX = 0.6, 0.8, 1.6   # pc353: ista formula (Economia Lunga) i za igrace AI klubova: tko zabija i igra dobro, vrijedi vise


def _revalue_world(s, M, season, my):
    """pc353: zasluge svih igraca AI klubova u sezoni -> {pid: merit}. Klub mora imati barem PARTITE_MINIME odigranih utakmica."""
    ag = seasonstats.agg(M, season)
    played = {}
    for m in M['matches']:
        if m['played'] and m['season'] == season:
            for c_ in (m['home'], m['away']):
                played[c_] = played.get(c_, 0) + 1
    live = read_dump_any() or {}
    out = {}
    for c in aitransfers.load_clubs(s, rat, POS, my).values():
        tm = played.get(c['idx'], 0)
        if tm < revalue.PARTITE_MINIME:
            continue
        for p in c['players']:
            if not p['ovr']:
                continue
            x = ag.get(p['pid']) or dict(app=0, g=0, a=0, rs=0.0)
            a = (live.get(p['pid']) or {}).get('age') or p['age']
            mer, _v, _r = revalue.merit(x['app'], tm, x['rs'], x['g'], x['a'], a)
            # pc354: za AI igrace blaze nego za tvoje (svijet se ne smije napuhati): 60 % pomaka, najvise x1,6, najmanje x0,8
            mer = max(REVAL_WORLD_MIN, min(REVAL_WORLD_MAX, 1 + (mer - 1) * REVAL_WORLD_DAMP))
            out[p['pid']] = round(mer, 3)
    return out


def _revalue_world_rows(s, merits):
    """-> [dict(pid,name,ovr,age,merit,old,new)] za AI igrace (vrijednosti u EUR)."""
    vals = s.player_values(set(merits))
    live = read_dump_any() or {}
    rows = []
    for pid, mer in merits.items():
        cur = vals.get(pid) or 0
        o, a = rat(pid)
        if not cur or not o:
            continue
        a = (live.get(pid) or {}).get('age') or a
        fair = revalue.fair_units(o, a, negotiate.fair_value(o, a) if negotiate.VALUE_BASE else None)
        nv = revalue.new_value(cur, mer, fair)
        rows.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), ovr=o, age=a, merit=mer, old=cur * 100, new=nv * 100))
    rows.sort(key=lambda r: -(r['new'] - r['old']))
    return rows


def revalue_view(slot):
    s = mlwrite.Save(slot_folder(slot), ro=True)
    M = _season(slot, s)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    ms = [m for m in M['matches'] if my in (m['home'], m['away'])]
    if not ms:
        return dict(ok=True, ready=False, rows=[], why='no matches in the save')
    pl_ = [m for m in ms if m['played']]
    season = max(m['season'] for m in (pl_ or ms))   # zadnja sezona u kojoj je klub igrao (1.7.: nova jos nije pocela)
    mine = [m for m in ms if m['season'] == season]
    played = [m for m in mine if m['played']]
    left = [m for m in mine if not m['played']]
    try:
        done = (json.load(open(REVAL_FILE, encoding='utf-8')).get(slot) or {}).get(str(season))
    except Exception:
        done = None
    lg = [m for m in mine if m['tid'] in COMP_LEAGUES]
    ready = len(played) >= revalue.PARTITE_MINIME and bool(lg) and all(m['played'] for m in lg)
    ag = seasonstats.agg(M, season, club=my)
    sq = list(s.my_squad_tags())
    vals = s.player_values(set(sq))
    live = read_dump_any() or {}
    rows = []
    for pid in sq:
        o, a = rat(pid)
        lv = live.get(pid) or {}
        a = lv.get('age') or a
        x = ag.get(pid) or dict(app=0, g=0, a=0, rs=0.0)
        cur = vals.get(pid) or 0
        if not cur or not o:
            continue
        mer, vote, reg = revalue.merit(x['app'], len(played), x['rs'], x['g'], x['a'], a)
        fair = revalue.fair_units(o, a, negotiate.fair_value(o, a) if negotiate.VALUE_BASE else None)
        nv = revalue.new_value(cur, mer, fair)
        rows.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), ovr=o, age=a, app=x['app'], goals=x['g'], assists=x['a'],
                         rating=round(vote, 2) if vote else None, reg=round(reg, 2), merit=round(mer, 2), old=cur * 100, new=nv * 100))
    rows.sort(key=lambda r: -(r['new'] - r['old']))
    try:
        g = json.load(open(REVAL_FILE, encoding='utf-8'))
    except Exception:
        g = {}
    e = g.setdefault(slot, {})
    if ready and not done:
        # zapamti zasluge: ako 1. srpnja igra obrise utakmice stare sezone prije nego sto kliknes, revalorizacija ostaje
        e['pending'] = dict(season=season, merit={str(r['pid']): r['merit'] for r in rows}, matches=len(played))
        if REVAL_WORLD and not e['pending'].get('world'):
            try:
                e['pending']['world'] = {str(k): v for k, v in _revalue_world(s, M, season, my).items()}
            except Exception as ex:
                print('[revalue] world:', ex)
        _jdump(g, REVAL_FILE, indent=1)
    elif not played and e.get('pending') and not e.get(str(e['pending']['season'])):
        pend = e['pending']
        rows = []
        for pid in sq:
            mer = pend['merit'].get(str(pid))
            o, a = rat(pid)
            cur = vals.get(pid) or 0
            if mer is None or not cur or not o:
                continue
            a = (live.get(pid) or {}).get('age') or a
            fair = revalue.fair_units(o, a, negotiate.fair_value(o, a) if negotiate.VALUE_BASE else None)
            rows.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), ovr=o, age=a, merit=mer, old=cur * 100, new=revalue.new_value(cur, mer, fair) * 100))
        rows.sort(key=lambda r: -(r['new'] - r['old']))
        return dict(ok=True, ready=bool(rows), done=False, season=pend['season'], team_matches=pend.get('matches'), left=0, rows=rows, from_memory=True)
    return dict(ok=True, ready=ready and not done, done=bool(done), season=season, team_matches=len(played), left=len(left), rows=rows)


def revalue_apply(body):
    slot = body['slot']
    v = revalue_view(slot)
    if v.get('done'):
        raise ValueError('Your players were already revalued for this season.')
    if not v.get('ready') and not body.get('force'):
        raise ValueError('The season is not over yet (the league must be finished and at least %d matches played).' % revalue.PARTITE_MINIME)
    ch = {r['pid']: r['new'] // 100 for r in v['rows'] if r['new'] != r['old']}
    wrows = []
    if REVAL_WORLD:   # pc353: i cijeli svijet (zasluge zapamcene na kraju sezone ili izracunate sad)
        try:
            pend = ((json.load(open(REVAL_FILE, encoding='utf-8')).get(slot) or {}).get('pending') or {})
            wm = {int(k): x for k, x in (pend.get('world') or {}).items()} if pend.get('season') == v['season'] else {}
            s_ = mlwrite.Save(slot_folder(slot), ro=True)
            if not wm:
                wm = _revalue_world(s_, _season(slot, s_), v['season'], (s_.club_offset() - mlwrite.REC0) // mlwrite.STRIDE)
            wm = {k: x for k, x in wm.items() if k not in ch and k not in {r['pid'] for r in v['rows']}}
            wrows = _revalue_world_rows(s_, wm)
            for x in wrows:
                if x['new'] != x['old']:
                    ch[x['pid']] = x['new'] // 100
        except Exception as ex:
            print('[revalue] world apply:', ex)
            wrows = []
    r = _write_slot(slot, 'revalue', lambda sv: 'revalued %d players' % sv.set_values(ch))
    try:
        g = json.load(open(REVAL_FILE, encoding='utf-8'))
    except Exception:
        g = {}
    g.setdefault(slot, {})[str(v['season'])] = dict(when=time.strftime('%Y-%m-%d %H:%M'), n=len(ch))
    g[slot].pop('pending', None)
    _jdump(g, REVAL_FILE, indent=1)
    up = [x for x in v['rows'] if x['new'] > x['old']][:3]
    dn = sorted([x for x in v['rows'] if x['new'] < x['old']], key=lambda x: x['new'] - x['old'])[:3]
    fm = lambda x: '%s %s -> %s' % (x['name'], '{:,}'.format(x['old']), '{:,}'.format(x['new']))
    msg = 'Season review: %d market values updated.%s%s' % (len(ch), (' Up: ' + '; '.join(fm(x) for x in up) + '.') if up else '',
                                                           (' Down: ' + '; '.join(fm(x) for x in dn) + '.') if dn else '')
    if wrows:
        wu = [x for x in wrows if x['new'] > x['old']][:3]
        msg += ' Around the world: %d players revalued%s' % (sum(1 for x in wrows if x['new'] != x['old']), (' (biggest risers: ' + '; '.join(fm(x) for x in wu) + ').') if wu else '.')
        try:   # vijest u novinama: najveci skok vrijednosti u svijetu
            if wu:
                x = wu[0]
                _ev_add(slot, 'world_revalue', 0, _nofan=True, head='%s now worth %s EUR after a big season' % (x['name'], '{:,}'.format(x['new'])),
                        lead='End-of-season valuations: %s.' % '; '.join(fm(y) for y in wu))
        except Exception as ex:
            print('[revalue] news:', ex)
    return dict(ok=True, message=msg, detail=r, rows=v['rows'], world=len(wrows))


_WRITES = [0]
_REV = [0, '']   # pc413: broj upisa + tko je zadnji pisao (id kartice preglednika)
_ASC = {}


def assistant_cached(slot):
    """pc310: Assistant (~1 s) se trazi s vise stranica; isti odgovor dok se save, dump i podaci appa ne promijene (najvise 60 s)."""
    try:
        sv = os.path.join(CFG.get('save_dir', ''), slot)
        dp = CFG.get('dump') or ''
        key = (slot, os.path.getmtime(sv) if os.path.exists(sv) else 0, os.path.getmtime(dp) if dp and os.path.exists(dp) else 0, _WRITES[0])
    except Exception:
        return assistant_view(slot)
    c = _ASC.get(slot)
    if c and c[0] == key and time.time() - c[1] < 60:
        return c[2]
    r = assistant_view(slot)
    _ASC[slot] = (key, time.time(), r)
    return r


def assistant_view(slot):
    """Tjedni sazetak: sto menadzer treba napraviti (ugovori, ponude, nezadovoljni, ozljede, forma, mladi, prodaja, rupe u sastavu, trening)."""
    items = []

    def add(cat, prio, pid, name, t, d, go, extra=None):
        it = dict(cat=cat, prio=prio, pid=pid, name=name, t=t, d=d, go=go)
        if extra:
            it.update(extra)
        items.append(it)

    def safe(f, *a):
        try:
            return f(*a)
        except Exception:
            return None
    _rv = safe(revalue_view, slot) or {}
    if _rv.get('ready'):
        add('money', 1, None, None, ['Kraj sezone: nove vrijednosti igraca', 'Season review: new market values'],
            ['Vrijednosti igraca po sezoni (ocjena, golovi, minute). Klikni da se upisu u save.',
             'Market values from the season (ratings, goals, minutes). Click to write them into the save.'], 'revalue')
    _gv = safe(gate_view, slot) or {}
    if _gv.get('total'):
        add('money', 2, None, None, ['Prihod od utakmica: %s EUR' % '{:,}'.format(_gv['total']), 'Match-day income: %s EUR' % '{:,}'.format(_gv['total'])],
            ['%d domacih utakmica od zadnje naplate. Klikni da se upise u transfer budzet.' % len(_gv['rows']),
             '%d home matches since the last collection. Click to add it to the transfer budget.' % len(_gv['rows'])], 'gate')
    ct = safe(contract_view, slot) or {}
    gr = safe(growth_state, slot) or {}
    sv = safe(sell_view, slot) or {}
    rq = safe(player_requests, slot) or {}
    yd = safe(youth_data, slot) or {}
    nx = safe(next_match, slot) or {}
    db = safe(debrief_view, slot) or {}
    due = safe(growth_due, slot) or {}
    G = {r['id']: r for r in (gr.get('rows') or [])}
    C = {r['pid']: r for r in (ct.get('players') or [])}
    role = {pid: r.get('role') for pid, r in C.items()}
    # stvarne minute: nastupi u zadnjih (do) 10 utakmica kluba ove sezone + trenutna prva postava iz savea
    sapps, played, xi_now = {}, 0, set()
    try:
        _s = mlwrite.Save(slot_folder(slot), ro=True)
        _M = _season(slot, _s)
        _my = (_s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
        _ms = sorted([m for m in _M['matches'] if m['played'] and _my in (m['home'], m['away'])], key=seasonstats.sort_key)
        if _ms:
            _cs = _ms[-1]['season']
            _ms = [m for m in _ms if m['season'] == _cs][-10:]
        played = len(_ms)
        for m in _ms:
            for pid_, ci_, g_, a_, r_ in m['rows']:
                if ci_ == _my:
                    sapps[pid_] = sapps.get(pid_, 0) + 1
        _ids = _s.squad_ids() if hasattr(_s, 'squad_ids') else []
        _lu = _s.lineup()
        _i2 = {i: q for i, q in enumerate(_ids) if q}
        xi_now = {_i2.get(i) for i in _lu[:11] if _i2.get(i)}
    except Exception:
        pass
    played = max(1, played)
    for pid_, g_ in G.items():
        g_['apps'] = sapps.get(pid_, 0)
    regular = {pid for pid, r in role.items() if r in ('key', 'starter')} | xi_now | {pid_ for pid_, n_ in sapps.items() if n_ / played >= 0.5}

    # 0. skautska mreza: neplacena sezona, nova izvjesca
    try:
        _se = _sc_get(slot)
        if _se.get('scouts'):
            _sv = mlwrite.Save(slot_folder(slot), ro=True)
            _gd = _sv.game_date_code()
            if _sc_tick(slot, _se, _gd):
                _sc_put(slot, _se)
            _ssn = _sc_season(_gd)
            _due = sum((x.get('fee') or SC_TIERS[x['tier']]['fee']) for x in _se['scouts'] if x.get('paid', 0) < _ssn and x.get('until', x.get('paid', _ssn)) >= _ssn)
            if _due:
                add('scout', 2, None, '', ('Scouts are not paid for the new season', 'Scouts unpaid for the new season'),
                    ('Godisnja placa %s ide iz transfer budzeta. Dok ne platis, skauti ne idu na misije.' % _eur(_due), 'The yearly wage of %s comes from the transfer budget. Until paid, scouts cannot go on missions.' % _eur(_due)), 'scouting')
            _now = _sc_ord(_gd)
            for _r in _se.get('reports', [])[:3]:
                if _now - _r['mission']['end'] <= 7:
                    add('scout', 2, None, '', ('Scout report: %s' % (_r['mission'].get('region') or 'slobodni igraci'), 'Scout report: %s' % (_r['mission'].get('region') or 'free agents')),
                        ('%s screened %d players and shortlisted %d.' % (_r['scout_name'], _r['found'], len(_r['players'])), '%s screened %d players and picked %d.' % (_r['scout_name'], _r['found'], len(_r['players']))), 'scouting')
    except Exception:
        pass
    # 1. ponude za moje igrace
    for p in sv.get('players') or []:
        offs = [o for o in (p.get('offers') or []) if not o.get('gone')]
        loffs = [o for o in (p.get('loan_offers') or []) if not o.get('gone')]
        if offs:
            b = max(offs, key=lambda o: o.get('fee') or 0)
            add('offer', 1, p['pid'], p['name'],
                ('Offer for %s' % p['name'], 'Offer for %s' % p['name']),
                ('%s nudi %s%s. Vrijednost %s.' % (b.get('club', ''), _eur(b.get('fee')), (' (+%d drugih)' % (len(offs) - 1)) if len(offs) > 1 else '', _eur(p.get('mv'))),
                 '%s offers %s%s. Value %s.' % (b.get('club', ''), _eur(b.get('fee')), (' (+%d more)' % (len(offs) - 1)) if len(offs) > 1 else '', _eur(p.get('mv')))),
                'sales')
        elif loffs:
            add('offer', 2, p['pid'], p['name'], ('Loan enquiry: %s' % p['name'], 'Loan enquiry: %s' % p['name']),
                ('%d club(s) want him on loan.' % len(loffs), '%d club(s) want him on loan.' % len(loffs)), 'sales')
    # 2. nezadovoljni igraci
    for r in rq.get('items') or []:
        pid = r.get('pid')
        nm = r.get('name') or NAMES.get(pid, str(pid))
        why = r.get('reason') or r.get('kind') or ''
        add('mood', 1, pid, nm, ('%s is unhappy' % nm, '%s is unhappy' % nm),
            ({'bench': 'Wants more minutes.', 'ambition': 'Wants a bigger club or a bigger role.'}.get(why, 'Wants to talk to you.'),
             {'bench': 'Wants more minutes.', 'ambition': 'Wants a bigger club or role.'}.get(why, 'Wants to talk to you.')), 'inbox')
    # 3. ugovori
    for p in ct.get('players') or []:
        if p.get('loaned_in') or p.get('months') is None:
            continue
        mo, rl = p['months'], p.get('role')
        imp = rl in ('key', 'starter')
        if mo <= 0:
            add('contract', 1, p['pid'], p['name'], ('Contract expired: %s' % p['name'], 'Contract expired: %s' % p['name']),
                ('Extend or let go. Wage %s/yr.' % _eur(p.get('sal')), 'Renew or release. Wage %s/yr.' % _eur(p.get('sal'))), 'inbox')
        elif mo <= 6 or (mo <= 12 and imp):
            add('contract', 1 if (imp and mo <= 6) else 2, p['pid'], p['name'],
                ('Contract expires in %d mo.: %s' % (mo, p['name']), 'Contract ends in %d mo.: %s' % (mo, p['name'])),
                ('%s. Do %s; bez produljenja odlazi besplatno.' % ({'key': 'Key player', 'starter': 'Prva postava'}.get(rl, 'Rotacija'), p.get('until')),
                 '%s. Until %s; he leaves for free without a renewal.' % ({'key': 'Key player', 'starter': 'Starter'}.get(rl, 'Rotation'), p.get('until'))), 'inbox')
    # 4. ozljede (pc198: i iz Injuries For All dok igra radi, bez F7 dumpa)
    try:
        W_ = world_injuries()[0]
    except Exception:
        W_ = {}
    for pid, g in G.items():
        inj = max(g.get('inj') or 0, W_.get(pid, 0))
        if inj > 0:
            long_ = inj >= 180
            add('injury', 2 if (pid in regular or long_) else 3, pid, g['name'],
                ('Injured: %s' % g['name'], 'Injured: %s' % g['name']),
                (('Out for about %d days.' % inj) + (' Long-term injury: consider a replacement or a loan.' if long_ else ''),
                 ('Out for about %d days.' % inj) + (' Long-term: consider a replacement or a loan.' if long_ else '')), 'squad')
    # 5. forma i minute
    for pid, g in G.items():
        if g.get('inj'):
            continue
        share = (g.get('apps') or 0) / played
        fm = g.get('form')
        if pid in regular and fm is not None and fm <= 2:
            add('form', 3, pid, g['name'], ('Poor form: %s' % g['name'], 'Poor form: %s' % g['name']),
                ('Consider resting him or a bench spot for the next match.', 'Consider resting him for the next match.'), 'squad')
        elif pid not in regular and fm is not None and fm >= 6 and share < 0.5 and played >= 3:
            add('form', 3, pid, g['name'], ('In excellent form: %s' % g['name'], 'In great form: %s' % g['name']),
                ('Plays little, but his form is excellent. He deserves a chance.', 'Plays little but his form is excellent. He deserves a chance.'), 'squad')
        pot, ovr, age = g.get('pot') or 0, g.get('ovr') or 0, g.get('age') or 30
        if age <= 21 and pot - ovr >= 6 and share < 0.3 and played >= 3 and pid not in regular:
            add('dev', 3, pid, g['name'], ('Talent bez minuta: %s' % g['name'], 'Talent without minutes: %s' % g['name']),
                ('%d y, OVR %d, potential ~%d. Without games he grows slower: give him minutes or loan him out.' % (age, ovr, pot),
                 '%d yrs, OVR %d, potential ~%d. Without games he grows slower: give him minutes or loan him out.' % (age, ovr, pot)), 'growth')
        cp = C.get(pid) or {}
        if age >= growth.decl_start(pid, g.get('pos'), db_speed(pid)) + 1 and share < 0.3 and played >= 3 and (cp.get('sal') or 0) >= 2e6 and pid not in regular:
            add('sell', 3, pid, g['name'], ('Sale candidate: %s' % g['name'], 'Sale candidate: %s' % g['name']),
                ('%d y, plays little, earns %s/yr. His value will drop.' % (age, _eur(cp.get('sal'))),
                 '%d yrs, plays little, wage %s/yr. His value will keep falling.' % (age, _eur(cp.get('sal')))), 'sales')
    # 6. omladina spremna
    first = {}
    for pid, g in G.items():
        first.setdefault(growth.pos_group(g.get('pos')), []).append(g.get('ovr') or 0)
    for y_ in [r for r in (yd.get('rows') or []) if (r.get('age') or 99) <= 19][:40]:
        grp = growth.pos_group(_YPOS.index(y_['pos']) if y_.get('pos') in _YPOS else 5)
        arr = sorted(first.get(grp, []), reverse=True)
        bar = arr[min(len(arr) - 1, {'gk': 1, 'def': 5, 'mid': 5, 'fw': 3}[grp])] if arr else 0
        if (y_.get('ovr') or 0) >= bar - 2 and (y_.get('ovr') or 0) >= 65:
            add('youth', 2, y_['id'], y_['name'], ('Junior spreman: %s' % y_['name'], 'Youth ready: %s' % y_['name']),
                ('%s, %d y, OVR %d (potential ~%d). Ready for the first team.' % (y_['pos'], y_['age'], y_['ovr'], y_.get('pot') or 0),
                 '%s, %d yrs, OVR %d (potential ~%d). Ready for the first team.' % (y_['pos'], y_['age'], y_['ovr'], y_.get('pot') or 0)), 'youth')
    # 7. rupe u sastavu
    healthy = {}
    for pid, g in G.items():
        if (g.get('inj') or 0) < 14:
            healthy.setdefault(growth.pos_group(g.get('pos')), 0)
            healthy[growth.pos_group(g.get('pos'))] += 1
    for grp, mn in _GRP_MIN.items():
        n = healthy.get(grp, 0)
        if G and n < mn:
            add('squad', 2, None, '', ('Premalo %s' % _GRP_N[grp][0], 'Too few %s' % _GRP_N[grp][1]),
                ('Fit players: %d (recommended at least %d). Look for a signing or a loan.' % (n, mn), 'Fit: %d (at least %d advised). Look for a signing or a loan.' % (n, mn)), 'signings')
    # 8. trening
    if due.get('due') and gr.get('matches'):
        add('training', 2, None, '', ('Obradi mjesec treninga', 'Process the training month'),
            ('Matches since last update: %d. Player progress is waiting to be written.' % gr.get('matches'), '%d matches played since the last update. Player progress is waiting.' % gr.get('matches')), 'growth')
    # 9. proracun
    st = gr.get('staff') or {}
    bud = ct.get('budget')
    _CO = ['offer', 'mood', 'contract', 'injury', 'youth', 'squad', 'training', 'money', 'form', 'dev', 'sell', 'scout']
    items.sort(key=lambda i: (i['prio'], _CO.index(i['cat']) if i['cat'] in _CO else len(_CO)))   # pc205: 'money' (kraj sezone, prihod) je rusio pomocnika
    nxt = None
    if nx.get('next'):
        n_ = nx['next']
        nxt = dict(opp=n_.get('opp'), home=n_.get('home'), date=n_.get('date'), formation=(nx.get('opponent') or {}).get('formation'))
    last = None
    if db.get('opp'):
        last = dict(opp=db['opp'], gf=db.get('gf'), ga=db.get('ga'), res=db.get('res'), home=db.get('home'), date=db.get('date'), last5=db.get('last5'),
                    pos=(db.get('table') or {}).get('after'), pos0=(db.get('table') or {}).get('before'))
    return dict(date=ct.get('date'), club=nx.get('club'), next=nxt, last=last, budget=bud, wage_bill=st.get('wage_bill'), items=items,
                counts={k: sum(1 for i in items if i['prio'] == k) for k in (1, 2, 3)})


def form_view(slot):
    s, ms, t, st = _form_targets(slot)
    pids = list(t)
    live = None
    try:
        live = growth.read_live(CFG.get('dump') or '', pids)
    except Exception:
        live = None
    out = []
    for pid, v in t.items():
        out.append(dict(pid=pid, name=NAMES.get(pid, str(pid)), pos=POS.get(pid, 5), ovr=rat(pid)[0], target=v['target'], level=v['level'], bias=v['bias'],
                        f=v['f'], why=v['why'], n=v['n'], cur=((live or {}).get(pid) or {}).get('form')))
    out.sort(key=lambda r: (-r['target'], -r['ovr']))
    return dict(players=out, matches=len(ms), last=(ms[-1]['n'] if ms else None), live=bool(live), bridge=growth.enabled(CFG))



def _press_ctx(slot, s, conf):
    """Kontekst za pitanja: uprava, sljedeci protivnik, glasine, nezadovoljni, cilj sezone, prekrsena obecanja."""
    ctx = {}
    try:
        B = board_view(slot)
        ctx.update(board_level=B.get('level'), pos=B.get('pos'), target=B.get('target'), goal=B.get('goal'), goal_txt=B.get('goal_txt'),
                   pos_s=(('%d%s' % (B['pos'], {1: 'st', 2: 'nd', 3: 'rd'}.get(B['pos'] if B['pos'] < 20 else B['pos'] % 10, 'th'))) if B.get('pos') else ''))
    except Exception as ex:
        print('[press] board:', ex)
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    try:
        clubs = aitransfers.load_clubs(s, rat, POS, -1)
        ctx['my_str'] = (clubs.get(my) or {}).get('strength', 70)
        if conf.get('kind') == 'prematch':
            ctx['next'] = dict(opp=conf['opp'], n=conf.get('date'), opp_str=(clubs.get(conf.get('opp_idx')) or {}).get('strength', 70))
    except Exception:
        pass
    squad = set(s.my_squad_tags())
    try:
        gd = s.game_date_code()
        since = _add_days(gd, -30)
        evs = [e for e in _ev_all(slot) if e.get('kind') == 'interest' and int(e.get('pid') or 0) in squad]
        evs = [e for e in evs if _cmp_date(_parse_any_date(e.get('when')) or gd, since) >= 0] or evs[-1:]
        if evs:
            e = evs[-1]
            ctx['rumour'] = dict(pid=int(e['pid']), name=NAMES.get(int(e['pid']), str(e['pid'])), club=e.get('to'))
    except Exception as ex:
        print('[press] rumour:', ex)
    try:
        rq = [r for r in (player_requests(slot).get('items') or []) if r.get('pid') in squad]
        if rq:
            ctx['unhappy'] = dict(pid=rq[0]['pid'], name=rq[0].get('name') or NAMES.get(rq[0]['pid'], ''), why=rq[0].get('reason'))
    except Exception:
        pass
    try:
        if ctx.get('next'):
            A_ = _stories_all().get(_career_id(slot, s), {})
            for k_ in sorted(A_, reverse=True)[:1]:
                for x in A_[k_].get('stories', []):
                    if x['kind'] in ('return', 'revenge') and not x.get('closed') and conf['opp'] in (x.get('clubs') or []):
                        ctx['story'] = dict(kind=x['kind'], who=x.get('who'), name=NAMES.get(x.get('pid'), '') if x.get('pid') else '',
                                            why=(x.get('teaser') or '').replace('Last season they ', '').rstrip('.'))
    except Exception as ex:
        print('[press] story:', ex)
    st = _press_load().get(slot, {})
    br = [p for p in st.get('promises', []) if p.get('state') == 'broken' and not p.get('asked')]
    if br:
        ctx['broken'] = br[0]
    return ctx


def _parse_any_date(w):
    m = re.match(r'\s*(\d{1,2})[./](\d{1,2})[./](\d{4})', str(w or ''))
    return ((int(m.group(1)) << 24) | (int(m.group(2)) << 16) | int(m.group(3))) if m else None


def _ev_all(slot):
    try:
        return json.load(open(os.path.join(HERE, 'data', 'events.json'), encoding='utf-8')).get(slot, [])
    except Exception:
        return []


def _press_questions(slot, conf, s=None):
    st = _press_load().get(slot, {})
    op = (st.get('open') or {}).get(conf['id'])
    if op:
        return op
    if conf['kind'] == 'signing':
        qs = press.build_signing(slot, conf['pid'], conf['name'], conf['club'], 1)
    elif conf['kind'] == 'prematch':
        s = s or mlwrite.Save(slot_folder(slot), ro=True)
        ctx = _press_ctx(slot, s, conf)
        qs = press2.context_questions(slot, conf['id'], ctx, limit=4)
        if not any(q['key'] == 'next' for q in qs):
            qs = (qs[:3] + [q for q in [press2.q_next(ctx, press2.rng('pcn', slot, conf['id']))] if q])
    else:
        qs = press.build_match(slot, conf['n'], conf['res'], conf.get('star'), conf.get('weak'))
        s = s or mlwrite.Save(slot_folder(slot), ro=True)
        ctx = _press_ctx(slot, s, conf)
        extra = [q for q in press2.context_questions(slot, conf['id'], ctx, limit=3) if q['key'] in ('broken', 'board', 'rumour', 'unhappy')][:2]
        qs = qs[:3] + extra
    a = _press_load()
    a.setdefault(slot, {}).setdefault('open', {})[conf['id']] = qs
    _press_save(a)
    return qs


def _board_adjust(slot, s, delta, why):
    """Konferencija/obecanje mijenja povjerenje uprave u appu."""
    if not delta:
        return
    with BOARD_LOCK:
        try:
            ALL = json.load(open(BOARD_FILE, encoding='utf-8'))
        except Exception:
            return
        try:
            cid = _career_id(slot, s)
        except Exception:
            cid = slot
        B = ALL.get(cid) or {}
        cur = B.get('cur')
        if not cur:
            return
        cur['trust'] = max(0.0, min(100.0, cur.get('trust', 50) + delta))
        B.setdefault('msgs', []).append(dict(kind='press', d=_fmt_date(s.game_date_code()), club=cur.get('club'), delta=delta, why=why))
        del B['msgs'][:-40]
        _jdump(ALL, BOARD_FILE, ensure_ascii=False, indent=1)


def press_promises_check(slot, s=None):
    """Obecanja s konferencija: pobjeda protiv X, igrac nije na prodaju, vise od cilja. Ispunjeno/prekrseno -> uprava, navijaci, vijest."""
    a = _press_load()
    st = a.get(slot, {})
    pr = [p for p in st.get('promises', []) if p.get('state') == 'open']
    if not pr:
        return
    s = s or mlwrite.Save(slot_folder(slot), ro=True)
    gd = s.game_date_code()
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    squad = set(s.my_squad_tags())
    ch = False
    try:
        ms = club_matches(slot, s, my, None, 12, True)
    except Exception:
        ms = []
    for p in pr:
        d0 = _parse_any_date(p.get('d'))
        if p['kind'] == 'win':
            m = next((m for m in reversed(ms) if m.get('opp') == p.get('opp') and _cmp_date(_parse_any_date(m.get('date')) or 0, d0 or 0) >= 0), None)
            if m:
                p['state'] = 'kept' if m.get('res') == 'W' else 'broken'
                p['res'] = '%s-%s' % (m.get('gf'), m.get('ga'))
        elif p['kind'] == 'keep':
            if p['pid'] not in squad:
                p['state'] = 'broken'
            elif _win_ord(gd) > _win_ord(d0 or gd):
                p['state'] = 'kept'
        elif p['kind'] == 'goal_up':
            y, mth, _ = _date_tuple(gd)
            if mth in (6, 7):
                try:
                    B = board_view(slot)
                    if B.get('pos') and B.get('target'):
                        p['state'] = 'kept' if B['pos'] < B['target'] else 'broken'
                except Exception:
                    pass
        if p['state'] != 'open':
            ch = True
            p['done'] = _fmt_date(gd)
            good = p['state'] == 'kept'
            st['fans'] = max(-20, min(20, st.get('fans', 0) + (3 if good else -4)))
            _board_adjust(slot, s, 2 if good else -4, 'promise_' + p['state'])
            try:
                _ev_add(slot, 'press_promise', p.get('pid'), state=p['state'], what=p['kind'], opp=p.get('opp'), name=p.get('name'))
            except Exception:
                pass
    if ch:
        a[slot] = st
        _press_save(a)


def press_start(body):
    slot, cid = body['slot'], body['id']
    _, _, confs = _press_confs(slot)
    conf = next((c for c in confs if c['id'] == cid), None)
    if not conf:
        raise ValueError('press conference not available')
    return dict(conf=conf, questions=_press_questions(slot, conf))


def press_finish(body):
    slot, cid = body['slot'], body['id']
    s, club, confs = _press_confs(slot)
    conf = next((c for c in confs if c['id'] == cid), None)
    if not conf:
        raise ValueError('press conference not available')
    qs = _press_questions(slot, conf, s)
    pick = {int(k): int(v) for k, v in (body.get('picks') or {}).items()}
    texts = {int(k): str(v).strip()[:500] for k, v in (body.get('texts') or {}).items() if v and str(v).strip()}
    picks, shown, fxs = [], [], []
    for i, q in enumerate(qs):
        o = next((x for x in q['opts'] if x['id'] == pick.get(i)), None)
        if not o:
            raise ValueError('answer every question')
        if o.get('fx') is not None:
            fxs.append(o['fx'])
        else:
            picks.append(dict(topic=q['topic'], tone=o['tone'], pid=q.get('pid')))
        shown.append(dict(q=q['q'], a=o['t'], tone=o['tone'], topic=q['topic'], said=texts.get(i)))
    tot = press2.apply_fx(fxs)
    squad = [p for p in s.my_squad_tags()]
    sp = conf.get('pid')
    grp = growth.pos_group(POS.get(sp, 5)) if sp else None
    rivals = [p for p in squad if sp and p != sp and growth.pos_group(POS.get(p, 5)) == grp]
    rows = press.effects(conf['kind'], picks, sp, squad, rivals, conf.get('res'))
    for who, d_ in tot['aff'].items():
        for p_ in (squad if who == 'squad' else [int(who)]):
            rows.append((p_, 'Affection', d_))
    agg = {}
    for p_, f_, d_ in rows:
        agg[(p_, f_)] = agg.get((p_, f_), 0) + d_
    rows = [(p_, f_, max(-24, min(24, d_)) if f_ == 'Affection' else max(-1, min(1, d_))) for (p_, f_), d_ in agg.items() if d_]
    conseq = []
    gd_ = _fmt_date(s.game_date_code())
    if tot['board']:
        _board_adjust(slot, s, tot['board'], 'press')
        conseq.append(dict(k='board', d=tot['board']))
    for pr_ in tot['promises']:
        conseq.append(dict(k='promise', p=pr_))
    for opp_ in tot['wars']:
        conseq.append(dict(k='war', opp=opp_))
        try:
            _ev_add(slot, 'press_war', None, opp=opp_)
            d_w = worldlib.date_str(s.game_date_code())
            world(slot, s).add('press_war', d_w, 'war:%s:%s' % (opp_, d_w), clubs=[opp_], opp=opp_)
        except Exception:
            pass
    if tot['fans']:
        conseq.append(dict(k='fans', d=tot['fans']))
    queued = 0
    a0 = _press_load()
    fs0 = a0.setdefault(slot, {}).setdefault('form', {})
    nm_ = 0
    try:
        nm_ = len([m for m in _season(slot, s)['matches'] if m['played']])
    except Exception:
        pass
    for p_, f_, d_ in rows:
        if f_ == 'Form':
            fs0.setdefault('bias', {})[str(p_)] = dict(v=d_, c0=len(_form_targets(slot)[1]))
    _press_save(a0)
    arow = [r for r in rows if r[1] == 'Affection']
    for p_, f_, d_, n_ in press.chunks(arow):
        queued += growth.queue(CFG, [(p_, f_, d_)], 'pc%s-%d' % (cid, n_))
    try:
        queued += form_commit(slot).get('queued', 0)
    except Exception:
        pass
    net = sum({'pos': 1, 'neg': -1}.get(x['tone'], 0) for x in picks)
    nm = conf.get('name') or conf.get('club')
    net = sum({'pos': 1, 'neg': -1}.get(x['tone'], 0) for x in shown)
    if conf['kind'] == 'signing':
        react = press.reactions(net, conf['name'], club, cid)
    else:
        react = press.match_reactions(net, conf.get('res'), club, conf['opp'], cid)
    eff = {}
    for p_, f_, d_ in rows:
        e = eff.setdefault(p_, dict(pid=p_, name=NAMES.get(p_, str(p_)), aff=0, form=0))
        if f_ == 'Affection':
            e['aff'] += d_
        else:
            e['form'] += d_
    big = sorted(eff.values(), key=lambda e: -(abs(e['aff']) + 8 * abs(e['form'])))
    allp = len(squad)
    summary = dict(squad=sum(1 for e in big if e['pid'] not in ([sp] if sp else [])) , players=big[:6], total=len(big))
    a = _press_load()
    st = a.setdefault(slot, {})
    st.setdefault('done', {})[cid] = 1
    (st.get('open') or {}).pop(cid, None)
    if tot['fans']:
        st['fans'] = max(-20, min(20, st.get('fans', 0) + tot['fans']))
    for pr_ in tot['promises']:
        st.setdefault('promises', []).append(dict(pr_, state='open', d=gd_, conf=cid))
    for p_ in st.get('promises', []):
        if p_.get('state') == 'broken' and any(q['key'] == 'broken' for q in qs):
            p_['asked'] = True
    st['promises'] = st.get('promises', [])[-30:]
    gd = _fmt_date(s.game_date_code())
    title = ('Pre-match: %s' % conf['opp']) if conf['kind'] == 'prematch' else ('Predstavljanje: %s' % conf['name']) if conf['kind'] == 'signing' else ('%s %d–%d %s' % (club, conf['gf'], conf['ga'], conf['opp']) if conf['home'] else '%s %d–%d %s' % (conf['opp'], conf['ga'], conf['gf'], club))
    st.setdefault('hist', []).append(dict(id=cid, kind=conf['kind'], title=title, when=gd, net=net, shown=shown, effects=big[:8], total=len(big), react=react, queued=queued))
    del st['hist'][:-40]
    _press_save(a)
    try:
        qt = next((x for x in shown if x.get('said') and x['tone'] != 'neu'), None) or next((x for x in shown if x.get('said')), None)
        # pc316: novine citiraju konferenciju; bez upisanog teksta uzme se najjaci odgovor (ne neutralan)
        qa = qt or next((x for x in shown if x['tone'] != 'neu'), None) or (shown[0] if shown else None)
        _ev_add(slot, 'press', conf.get('pid'), net=net, title=title, quote=((qa.get('said') or qa.get('a') or '')[:180] if qa else None),
                q=((qa.get('q') or '')[:160] if qa else None), opp=conf.get('opp'), pkind=conf['kind'], manager=s.manager())
    except Exception:
        pass
    return dict(ok=True, queued=queued, bridge=growth.enabled(CFG), effects=big[:8], total=len(big), react=react, net=net, shown=shown, conseq=conseq)



def repair(body):
    def fn(sv):
        return 'clubs fixed: %d' % sv.fix_squad_counts()
    return _write_slot(body['slot'], 'repair', fn)


def lock_player(body):
    """Rucno oznaci igraca kao 'promijenio klub u ovom roku' (datum pocetka ugovora = danas u igri)."""
    pid = int(body['pid'])

    def fn(sv):
        sv.set_contract_start(pid, sv.game_date_code())
        return '%s is locked for this transfer window.' % NAMES.get(pid, pid)
    return _write_slot(body['slot'], 'lock', fn)


def open_app(url):
    """Otvara app u zasebnom prozoru bez adresne trake (Edge/Chrome --app), inace u obicnom pregledniku."""
    pf = [os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', ''), os.environ.get('LOCALAPPDATA', '')]
    rel = [r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe']
    for r in rel:
        for base in pf:
            exe = os.path.join(base, r) if base else ''
            if exe and os.path.isfile(exe):
                try:
                    subprocess.Popen([exe, '--app=' + url, '--window-size=1500,950'])
                    return
                except Exception:
                    pass
    webbrowser.open(url)


def _hotkey_loop(url):
    """Globalna tipka (Windows): Ctrl+F8 iz igre prebaci na prozor appa (ili ga otvori ako nije otvoren).
    Igra bi trebala biti u Borderless/Windowed modu; u pravom fullscreenu Windows je samo minimizira."""
    if os.name != 'nt' or CFG.get('hotkey') is False:
        return
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        MOD_CONTROL, MOD_NOREPEAT, VK_F8, WM_HOTKEY = 0x2, 0x4000, 0x77, 0x0312
        if not u32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_NOREPEAT, VK_F8):
            print('hotkey Ctrl+F8 not available (used by another program)')
            return
        EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def find():
            found = []

            def cb(h, _):
                if u32.IsWindowVisible(h):
                    n = u32.GetWindowTextLengthW(h)
                    if n:
                        b = ctypes.create_unicode_buffer(n + 1)
                        u32.GetWindowTextW(h, b, n + 1)
                        if b.value.startswith(('The Gaffer', 'Karijera 26')):
                            found.append(h)
                            return False
                return True
            u32.EnumWindows(EnumProc(cb), 0)
            return found[0] if found else None
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                # pc362: iz appa Ctrl+F8 vraca u igru (kao tipka na kontroleru)
                fg = u32.GetForegroundWindow()
                if fg and fg == find() and _PADFN.get('to_game'):
                    try:
                        _PADFN['to_game']()
                    except Exception:
                        pass
                    continue
                h = find()
                if h:
                    u32.ShowWindow(h, 9)  # SW_RESTORE
                    # Windows ne da fokus iz pozadine bez trika: kratko pritisni/otpusti Alt
                    u32.keybd_event(0x12, 0, 0, 0)
                    u32.keybd_event(0x12, 0, 2, 0)
                    u32.SetForegroundWindow(h)
                else:
                    open_app(url)
    except Exception as e:
        print('hotkey error:', e)


_PADFN = {}


def _pad_loop(url):
    """pc362: tipka na kontroleru (XInput): drzi Back + Start (Xbox: View + Menu, PlayStation: Share + Options) ~0,6 s
    -> prebaci na The Gaffer; ponovo iz appa -> natrag u igru. Radi neovisno o fokusu (XInput cita kontroler izravno),
    bez Sidera. Igra treba biti u Borderless/Windowed modu. Iskljuci: config "pad_switch": false."""
    if os.name != 'nt' or CFG.get('pad_switch') is False:
        return
    try:
        import ctypes
        from ctypes import wintypes
        xi = None
        for dll in ('xinput1_4', 'xinput1_3', 'xinput9_1_0'):
            try:
                xi = ctypes.WinDLL(dll)
                break
            except OSError:
                continue
        if xi is None:
            return

        class PAD(ctypes.Structure):
            _fields_ = [('wButtons', wintypes.WORD), ('bLeftTrigger', ctypes.c_ubyte), ('bRightTrigger', ctypes.c_ubyte),
                        ('sThumbLX', ctypes.c_short), ('sThumbLY', ctypes.c_short), ('sThumbRX', ctypes.c_short), ('sThumbRY', ctypes.c_short)]

        class STATE(ctypes.Structure):
            _fields_ = [('dwPacketNumber', wintypes.DWORD), ('Gamepad', PAD)]
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        COMBO = 0x0010 | 0x0020   # START | BACK

        def title(h):
            n = u32.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, b, n + 1)
            return b.value

        def exe_of(h):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            hp = k32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not hp:
                return ''
            try:
                b = ctypes.create_unicode_buffer(520)
                n = wintypes.DWORD(520)
                return os.path.basename(b.value).lower() if k32.QueryFullProcessImageNameW(hp, 0, b, ctypes.byref(n)) else ''
            finally:
                k32.CloseHandle(hp)

        def find(pred):
            found = []

            def cb(h, _):
                if u32.IsWindowVisible(h) and u32.GetWindowTextLengthW(h) and pred(h):
                    found.append(h)
                    return False
                return True
            u32.EnumWindows(EnumProc(cb), 0)
            return found[0] if found else None

        def focus(h):
            u32.ShowWindow(h, 9)
            u32.keybd_event(0x12, 0, 0, 0)
            u32.keybd_event(0x12, 0, 2, 0)
            u32.SetForegroundWindow(h)

        is_app = lambda h: title(h).startswith(('The Gaffer', 'Karijera 26'))
        game_exe = lambda: (str(CFG.get('pes_process') or 'FL_2026').lower().removesuffix('.exe') + '.exe')
        def to_game():
            g = find(lambda h: exe_of(h) == game_exe())
            if g:
                focus(g)
        _PADFN['to_game'] = to_game
        st = STATE()
        since, fired = None, False
        while True:
            pressed = False
            any_pad = False
            for i in range(4):
                if xi.XInputGetState(i, ctypes.byref(st)) == 0:
                    any_pad = True
                    if (st.Gamepad.wButtons & COMBO) == COMBO:
                        pressed = True
            if not any_pad:
                since, fired = None, False
                time.sleep(2.0)
                continue
            if pressed:
                since = since or time.time()
                if not fired and time.time() - since >= 0.6:
                    fired = True
                    fg = u32.GetForegroundWindow()
                    if fg and is_app(fg):
                        to_game()
                    else:
                        h = find(is_app)
                        if h:
                            focus(h)
                        else:
                            open_app(url)
            else:
                since, fired = None, False
            time.sleep(0.05)
    except Exception as e:
        print('controller switch error:', e)


def launch():
    if game_running():
        return dict(ok=True, message='The game is already running.')
    subprocess.Popen([CFG['pes_exe']], cwd=os.path.dirname(CFG['pes_exe']))
    return dict(ok=True, message='Launching the game.')


def assign(body):
    s = mlwrite.Save(slot_folder(body['slot']), ro=True)
    xi, bench = s.auto_lineup(body['preset'], POS, body['pool'])
    return dict(xi=xi, bench=bench)


_FACE = {}



_GF = {}


def _img_mime(b):
    if not b:
        return 'image/png'
    if b[:2] == b'\xff\xd8':
        return 'image/jpeg'
    if len(b) >= 12 and b[:4] == b'RIFF' and b[8:12] == b'WEBP':
        return 'image/webp'
    if b[:2] == b'BM':
        return 'image/bmp'
    return 'image/png'


def _clear_face_caches():
    _GF.clear()
    _GL.pop('kitidx', None)
    _GL.pop('roots', None)


def game_face(pid):
    """Lice iz igre (livecpk/*/common/render/symbol/player/<pid>.dds, npr. UML_Minifaces) kao PNG; kesira se u data/gface. Regeni se preskacu (datoteka je lice starog igraca).
    PES 2017: uvoz mini-lica je uklonjen, pa se cita samo vec spremljeni data/gface kes."""
    if _GAME['save'] == 'pes17':
        # r10: the PES 2017 mini-face importer was removed. Only portraits already
        # cached in data/gface are served; nothing is scanned in the game folder.
        if not pid or pid in _REGEN:
            return None
        try:
            with open(os.path.join(HERE, 'data', 'gface', '%d.png' % pid), 'rb') as f:
                return f.read()
        except Exception:
            return None
    if 'dirs' not in _GF:
        _gf_dirs()
    if not pid or pid in _REGEN:
        return None
    cd = os.path.join(HERE, 'data', 'gface')
    cp = os.path.join(cd, '%d.png' % pid)
    try:
        with open(cp, 'rb') as f:
            return f.read()
    except Exception:
        pass
    for pd_ in list(_GF['dirs']):
        for ext in ('.dds', '.png'):
            fp = _gf_find(pd_, '%d%s' % (pid, ext))
            if fp:
                try:
                    raw = open(fp, 'rb').read()
                    png = raw if ext == '.png' else dds.dds_to_png(raw)
                    if not png:
                        continue
                    os.makedirs(cd, exist_ok=True)
                    with open(cp, 'wb') as f:
                        f.write(png)
                    return png
                except Exception:
                    continue
    return None


def _ci_path(base, *parts):
    """pc413: Linux (Steam Deck / Proton) razlikuje velika i mala slova, a paketi lica znaju imati Common\\Render\\Symbol\\Player.
    Na Windowsu obican join."""
    p = os.path.join(base, *parts)
    if os.name == 'nt' or os.path.exists(p):
        return p
    cur = base
    for part in parts:
        nxt = os.path.join(cur, part)
        if not os.path.exists(nxt):
            try:
                hit = next((x for x in os.listdir(cur) if x.lower() == part.lower()), None)
            except Exception:
                hit = None
            if not hit:
                return p
            nxt = os.path.join(cur, hit)
        cur = nxt
    return cur


def _gf_find(pd_, name):
    """Datoteka u mapi lica; na Linuxu bez obzira na velika/mala slova (65707.DDS)."""
    fp = os.path.join(pd_, name)
    if os.name == 'nt' or os.path.isfile(fp):
        return fp if os.path.isfile(fp) else None
    ix = _GF.setdefault('ci', {})
    if pd_ not in ix:
        try:
            ix[pd_] = {x.lower(): x for x in os.listdir(pd_)}
        except Exception:
            ix[pd_] = {}
    hit = ix[pd_].get(name.lower())
    return os.path.join(pd_, hit) if hit else None


def _gf_dirs():
    if 'dirs' not in _GF:
        L = []
        try:
            for rt in _cpk_roots():
                pd_ = _ci_path(rt, 'common', 'render', 'symbol', 'player')
                if os.path.isdir(pd_):
                    L.append(pd_)
            # pc413: portreti menadzera-legendi (ML Manager Mod: symbol\coachML\<id igraca>.png, npr. Ronaldinho 65707) - iza pravih lica
            for rt in _cpk_roots():
                pd_ = _ci_path(rt, 'common', 'render', 'symbol', 'coachML')
                if os.path.isdir(pd_):
                    L.append(pd_)
        except Exception:
            pass
        _GF['dirs'] = L



# ---------------------------------------------------------------- Postavljanje (prvo pokretanje), Sider moduli, paket za dijeljenje
SETUP_SKIP = {'windows', '$recycle.bin', 'programdata', 'system volume information', 'appdata', 'node_modules', 'msocache', 'recovery', '$windows.~bt', 'perflogs', 'intel', 'amd', 'nvidia'}


def _drives():
    if os.name != 'nt':
        return ['/']
    return ['%s:\\' % c for c in 'CDEFGHIJKLMNOPQRSTUVWXYZ' if os.path.exists('%s:\\' % c)]


def _bfs(roots, want, depth=4, limit=40000):
    """Pretraga mapa u sirinu: vraca putanje datoteka/mapa za koje want(dirpath, name) vrati True."""
    out, seen, q = [], 0, [(r, 0) for r in roots if r and os.path.isdir(r)]
    while q and seen < limit:
        d_, lv = q.pop(0)
        seen += 1
        try:
            names = os.listdir(d_)
        except Exception:
            continue
        for n in names:
            fp = os.path.join(d_, n)
            try:
                if want(d_, n):
                    out.append(fp)
            except Exception:
                pass
            if lv < depth and n.lower() not in SETUP_SKIP and not n.startswith('.'):
                try:
                    if os.path.isdir(fp):
                        q.append((fp, lv + 1))
                except Exception:
                    pass
    return out


def _known_documents():
    """Prava mapa Dokumenti iz Windowsa (radi za svaki jezik i OneDrive preusmjeravanje, npr. OneDrive\\Documenti)."""
    if os.name != 'nt':
        return []
    try:
        import ctypes, ctypes.wintypes as wt
        class GUID(ctypes.Structure):
            _fields_ = [('a', wt.DWORD), ('b', wt.WORD), ('c', wt.WORD), ('d', ctypes.c_ubyte * 8)]
        g = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))  # FOLDERID_Documents
        pp = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(pp)) == 0:
            v = pp.value
            ctypes.windll.ole32.CoTaskMemFree(pp)
            return [v] if v else []
    except Exception:
        pass
    return []


def _home_dirs():
    up = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    L = [up] + _known_documents()
    od = [up]
    try:
        od += [os.path.join(up, n) for n in os.listdir(up) if n.lower().startswith('onedrive')]   # OneDrive, "OneDrive - Personal"...
    except Exception:
        pass
    for o in [os.environ.get('OneDrive') or '', os.environ.get('OneDriveConsumer') or '']:
        if o:
            od.append(o)
    for b in dict.fromkeys(od):
        for a in ('Documents', 'Documenti', 'Dokumenti', 'Dokumente', 'Documentos', 'Documenten', 'Dokumenty', 'Mes documents', 'Downloads', 'Desktop', 'Radna površina'):
            L.append(os.path.join(b, a))
    return [x for x in dict.fromkeys(L) if x and os.path.isdir(x)]


def setup_detect():
    """Pokusa sam naci mapu saveova, Sider, igru i PES File Crypter (decrypter21/encrypter21)."""
    found = {}
    # saveovi: ...\KONAMI\eFootball PES 2021 SEASON UPDATE\<godina>\save s ML datotekama
    sv = []
    for h in _home_dirs():
        # pc264: Football Life 2027 sprema u ...\SPGAME\Football Life\2027\save
        for k in (os.path.join(h, 'KONAMI'), os.path.join(h, 'SPGAME')):
            if os.path.isdir(k):
                sv += _bfs([k], lambda d_, n: n.lower() == 'save' and any(f.startswith('ML0') for f in os.listdir(os.path.join(d_, n))), depth=3, limit=500)
    sv.sort(key=lambda p: -max([os.path.getmtime(os.path.join(p, f)) for f in os.listdir(p) if f.startswith('ML0')] or [0]))
    found['save_dir'] = sv
    # Sider: mapa sa sider.ini koji sadrzi exe.name (uz sider.dll); kod Football Lifea najcesce <igra>\\SiderAddons
    def _is_sider(d_, n):
        if n.lower() != 'sider.ini':
            return False
        try:
            return 'exe.name' in open(os.path.join(d_, n), encoding='utf-8', errors='ignore').read(20000)
        except Exception:
            return False
    sd = _bfs(_home_dirs() + [r'C:\\pes_test'], _is_sider, depth=4, limit=20000) + _bfs(_drives(), _is_sider, depth=5, limit=80000)
    sd = list(dict.fromkeys(sd))
    def _exe_name(sdir):
        try:
            m = re.search(r'exe\.name\s*=\s*"\\?([^"]+)"', open(os.path.join(sdir, 'sider.ini'), encoding='utf-8', errors='ignore').read())
            return os.path.basename(m.group(1).strip().replace('/', '\\')) if m else ''
        except Exception:
            return ''

    def _sider_score(sdir):
        nm = _exe_name(sdir)
        game = any(nm and os.path.isfile(os.path.join(d_, nm)) for d_ in (os.path.dirname(sdir), sdir))
        return (2 if game else 0) + (1 if os.path.isdir(os.path.join(sdir, 'livecpk')) else 0) + (1 if os.path.isdir(os.path.join(sdir, 'modules')) else 0)
    sl = [os.path.dirname(x) for x in sd]
    found['sider'] = sorted(sl, key=lambda d_: -_sider_score(d_))      # prava instalacija (igra pored, livecpk, modules) prva
    # igra: samo exe iz exe.name i launcher u istoj mapi (ime sa start/launch/FL/PES); ne nudi ostale programe s diska
    ex = []
    for sdir in found['sider']:
        if _sider_score(sdir) < 2:
            continue
        nm = _exe_name(sdir)
        for par in (os.path.dirname(sdir), sdir):
            try:
                cand = sorted(f for f in os.listdir(par) if f.lower().endswith('.exe') and (f == nm or re.search(r'start|launch|^fl|pes', f, re.I)) and 'unins' not in f.lower() and 'sider' not in f.lower())
            except Exception:
                cand = []
            for c in cand:
                fp = os.path.join(par, c)
                if os.path.isfile(fp) and fp not in ex:
                    ex.append(fp)
    ex.sort(key=lambda x: 0 if re.search(r'start|launch', os.path.basename(x), re.I) else 1)   # launcher prvi (pokrece igru sa Siderom)
    found['pes_exe'] = ex
    # PES File Crypter
    roots = [HERE, os.path.join(HERE, 'tools')] + _home_dirs() + [r'C:\pes_test']
    dc = _bfs(roots, lambda d_, n: n.lower() == 'decrypter21.exe', depth=4, limit=20000)
    if not dc:
        dc = _bfs(_drives(), lambda d_, n: n.lower() == 'decrypter21.exe', depth=4, limit=60000)
    found['decrypter'] = dc
    enc = [os.path.join(os.path.dirname(x), 'encrypter21.exe') for x in dc if os.path.isfile(os.path.join(os.path.dirname(x), 'encrypter21.exe'))]
    if not enc:     # encrypter trazi se i sam za sebe (nije uvijek uz decrypter)
        isn = lambda d_, n: n.lower() == 'encrypter21.exe'
        enc = _bfs([HERE, os.path.join(HERE, 'tools')] + _home_dirs() + [r'C:\\pes_test'], isn, depth=4, limit=20000) or _bfs(_drives(), isn, depth=4, limit=60000)
    found['encrypter'] = list(dict.fromkeys(enc))
    try:
        import pes17_setup as _p17d
        _p17_sv = _p17d.candidates()  # candidates() returns paths, not dicts
        found['save_dir'] = list(dict.fromkeys(_p17_sv + (found.get('save_dir') or [])))
        _p17_ex = [_p17d._find_exe_in(g) or g
                   for g in _p17d.game_candidates(CFG.get('save_dir') or '')]
        found['pes_exe'] = list(dict.fromkeys(_p17_ex + (found.get('pes_exe') or [])))
    except Exception:
        pass
    return found


SIDER_MODS = ('PlayerDump.lua', 'GrowthBridge.lua')


def _lua_ver(fp):
    """'2.2' iz 'local m = { version = "2.2" }' (prvih 2 KB) ili None."""
    try:
        m_ = re.search(r'version\s*=\s*"([0-9.]+)"', open(fp, encoding='latin-1').read(2048))
        return m_.group(1) if m_ else None
    except Exception:
        return None


def _vtuple(v):
    try:
        return tuple(int(x) for x in (v or '0').split('.'))
    except Exception:
        return (0,)


def mods_check():
    """pc294: jesu li Sider moduli u igri (PlayerDump, GrowthBridge) stariji od onih koje app nosi u lua/.
    Stari GrowthBridge (<1.2) krivo upisuje moral; stari PlayerDump (<2.2) nema automatski F7 pred utakmicu."""
    sdir = _sider_root()
    out = dict(sider=bool(sdir and os.path.isfile(os.path.join(sdir, 'sider.ini'))), mods=[], outdated=[])
    if not out['sider']:
        return out
    st = _sider_mod_state(sdir)
    for m in SIDER_MODS:
        src = os.path.join(HERE, 'lua', m)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(sdir, 'modules', m)
        have, want = (_lua_ver(dst) if os.path.isfile(dst) else None), _lua_ver(src)
        old = (not os.path.isfile(dst)) or (not st.get(m, {}).get('ini')) or _vtuple(have) < _vtuple(want)
        r = dict(name=m, have=have, want=want, missing=not os.path.isfile(dst), ini=st.get(m, {}).get('ini', False), outdated=old)
        out['mods'].append(r)
        if old:
            out['outdated'].append(r)
    return out


def first_steps(slot):
    """pc299: kontrolna lista za nove korisnike (Home): mape, save, Sider moduli, povezana igra, upis treninga."""
    mc = mods_check()
    ds = dump_status(slot) if slot else {}
    has_save = False
    try:
        has_save = bool(slot) and os.path.isfile(os.path.join(CFG.get('save_dir') or '', slot))
    except Exception:
        pass
    return dict(save=has_save, sider=mc.get('sider', False), mods=bool(mc.get('sider')) and not mc.get('outdated'),
                connected=bool(ds.get('exists') and ds.get('career_ok')), live=growth.enabled(CFG) if CFG.get('dump') else False)


def _sider_mod_state(sdir):
    st = {}
    try:
        ini = open(os.path.join(sdir, 'sider.ini'), encoding='utf-8', errors='ignore').read()
    except Exception:
        ini = ''
    for m in SIDER_MODS:
        st[m] = dict(file=os.path.isfile(os.path.join(sdir, 'modules', m)),
                     ini=bool(re.search(r'^\s*lua\.module\s*=\s*"%s"' % re.escape(m), ini, re.M)))
    return st


def setup_check(key, val):
    """Provjera jedne putanje odmah (prije spremanja): ok + kratka napomena."""
    v = (val or '').strip().strip('"')
    v = os.path.expandvars(v)
    if key == 'save_dir':
        n = 0
        if os.path.isdir(v):
            try:
                n = sum(1 for f in os.listdir(v) if f.startswith('ML0'))
            except Exception:
                n = 0
        return dict(ok=n > 0, note=L_('%d karijera' % n, '%d careers' % n) if n else L_('no ML0 files', 'no ML0 files'))
    if key == 'sider':
        ini = os.path.isfile(os.path.join(v, 'sider.ini')) if v else False
        return dict(ok=ini, note='sider.ini' if ini else L_('no sider.ini', 'no sider.ini'))
    ok = bool(v) and os.path.isfile(v) and v.lower().endswith('.exe')
    return dict(ok=ok, note='' if ok else L_('datoteka ne postoji', 'file not found'))


def setup_pick(kind, start):
    """Nativni Windows dijalog za odabir datoteke (.exe) ili mape; vraca put ili '' ako je korisnik odustao. Izvan Windowsa: unsupported."""
    if os.name != 'nt':
        return dict(ok=False, unsupported=True)
    import base64
    start = (start or '').strip().strip('"')
    if start and not os.path.isdir(start):
        start = os.path.dirname(start)
    if not start or not os.path.isdir(start):
        start = os.environ.get('USERPROFILE') or ''
    if kind == 'dir':
        body = ("$o=New-Object System.Windows.Forms.OpenFileDialog;$o.Title='Select folder (open it, then click Open)';$o.ValidateNames=$false;$o.CheckFileExists=$false;$o.CheckPathExists=$true;$o.FileName='Select folder';"
                "$o.InitialDirectory=$env:KP_START;if($o.ShowDialog($f) -eq 'OK'){$p=$o.FileName;if(Test-Path -LiteralPath $p -PathType Container){$p}else{Split-Path -LiteralPath $p}}")
    else:
        body = ("$o=New-Object System.Windows.Forms.OpenFileDialog;$o.Title='Select file';$o.Filter='Programs (*.exe)|*.exe|All files (*.*)|*.*';$o.InitialDirectory=$env:KP_START;"
                "if($o.ShowDialog($f) -eq 'OK'){$o.FileName}")
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;Add-Type -AssemblyName System.Windows.Forms;"
          "$f=New-Object System.Windows.Forms.Form;$f.TopMost=$true;$f.ShowInTaskbar=$false;$f.Opacity=0;$f.StartPosition='CenterScreen';$f.Show();" + body + ";$f.Close()")
    enc = base64.b64encode(ps.encode('utf-16le')).decode()
    env = dict(os.environ, KP_START=start)
    try:
        r = _run(['powershell', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', enc], capture_output=True, timeout=600, env=env,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        out = (r.stdout or b'').decode('utf-8', 'ignore').strip().splitlines()
        return dict(ok=True, path=out[-1].strip() if out else '')
    except Exception as e:
        return dict(ok=False, error=str(e))


def setup_browse(path, files):
    """Jednostavan preglednik mapa/datoteka za Postavljanje (preglednik ne smije dati puni put iz dijalogu za datoteke)."""
    path = (path or '').strip().strip('"')
    out = dict(path=path, parent=None, entries=[], roots=[])
    up = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    quick = [(n, p) for n, p in (('Desktop', os.path.join(up, 'Desktop')), ('Documents', os.path.join(up, 'Documents')), ('Dokumenti', os.path.join(up, 'OneDrive', 'Dokumenti')),
                                 ('Documents (OneDrive)', os.path.join(up, 'OneDrive', 'Documents')), ('Downloads', os.path.join(up, 'Downloads')), ('Home', up)) if os.path.isdir(p)]
    out['roots'] = [dict(n=d.rstrip('\\'), p=d) for d in _drives()] + [dict(n=n, p=p) for n, p in quick]
    if not path or not os.path.isdir(path):
        if path and os.path.isfile(path):
            path = os.path.dirname(path)
            out['path'] = path
        else:
            out['path'] = ''
            return out
    par = os.path.dirname(path.rstrip('\\/'))
    out['parent'] = par if par and par != path.rstrip('\\/') else ''
    try:
        names = sorted(os.listdir(path), key=lambda x: x.lower())
    except Exception as e:
        out['error'] = str(e)
        return out
    for n in names[:2000]:
        fp = os.path.join(path, n)
        try:
            if os.path.isdir(fp):
                if not n.startswith(('$', '.')):
                    out['entries'].append(dict(n=n, dir=True))
            elif files and n.lower().endswith('.exe'):
                out['entries'].append(dict(n=n, dir=False))
        except Exception:
            pass
    out['entries'].sort(key=lambda e: (not e['dir'],))
    out['has_ini'] = os.path.isfile(os.path.join(path, 'sider.ini'))
    return out


def _vkey_name(v):
    v = int(v)
    if v == 0x20: return 'Space'
    if v == 0xC0: return '`'
    if 0x70 <= v <= 0x87: return 'F%d' % (v - 0x6F)
    if 0x30 <= v <= 0x5A: return chr(v)
    return '0x%X' % v


def _overlay_keys(sdir):
    k = dict(toggle='Space', next='1', prev='`')
    try:
        ini = open(os.path.join(sdir, 'sider.ini'), encoding='utf-8', errors='ignore').read()
        for key, nm in (('toggle', 'toggle'), ('next', 'next-module'), ('prev', 'prev-module')):
            m = re.search(r'^\s*overlay\.vkey\.%s\s*=\s*(0x[0-9a-fA-F]+|\d+)' % re.escape(nm), ini, re.M)
            if m:
                k[key] = _vkey_name(int(m.group(1), 0))
    except Exception:
        pass
    return k


def _live_on():
    try:
        return bool(growth.enabled(CFG))
    except Exception:
        return False


def _is_owner():
    """Dijeljenje (izrada paketa) je samo za vlasnika appa: oznaka data/.owner postoji samo na njegovom racunalu i nikad ne ide u paket."""
    return bool(DEV) or os.path.isfile(os.path.join(HERE, 'data', '.owner'))


CLOG_FILE = os.path.join(HERE, 'data', 'client_errors.log')
_CLOG_SEEN = {}


def client_log(body):
    """Greske iz preglednika (window.onerror / unhandledrejection): zadnjih ~400 redaka u data/client_errors.log, ide u datoteku podrske."""
    try:
        msg = str(body.get('msg') or '')[:400]
        key = msg + '|' + str(body.get('line'))
        now = time.time()
        if now - _CLOG_SEEN.get(key, 0) < 60:
            return dict(ok=True, dup=True)
        _CLOG_SEEN[key] = now
        row = '%s %s page=%s src=%s:%s:%s %s\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), APP_VERSION, str(body.get('page') or '')[:40], str(body.get('src') or '')[-80:],
                                             body.get('line'), body.get('col'), msg, str(body.get('stack') or '')[:1500])
        os.makedirs(os.path.dirname(CLOG_FILE), exist_ok=True)
        old = open(CLOG_FILE, encoding='utf-8', errors='replace').read() if os.path.isfile(CLOG_FILE) else ''
        txt = (old + row)[-120000:]
        open(CLOG_FILE, 'w', encoding='utf-8').write(txt)
    except Exception as ex:
        return dict(ok=False, error=str(ex))
    return dict(ok=True)


def setup_status():
    sdir = _sider_root() or ''
    items = []

    def add(key, label, val, ok, req, hint):
        items.append(dict(key=key, label=label, value=val or '', ok=bool(ok), required=req, hint=hint))
    sv = CFG.get('save_dir') or ''
    add('save_dir', L_('Mapa saveova', 'Save folder'), sv, os.path.isdir(sv) and any(f.startswith('ML0') for f in os.listdir(sv)) if os.path.isdir(sv) else False, True,
        L_('...\\KONAMI\\eFootball PES 2021 SEASON UPDATE\\<godina>\\save ili ...\\KONAMI\\Pro Evolution Soccer 2017\\save',
           '...\\KONAMI\\eFootball PES 2021 SEASON UPDATE\\<year>\\save or ...\\KONAMI\\Pro Evolution Soccer 2017\\save'))
    _tl = os.path.isdir(os.path.join(HERE, 'tools'))
    _av = L_(' The file is missing from the tools folder: your antivirus may have removed it, check quarantine.', ' The file is not in the tools folder: antivirus may have removed it, check quarantine.') if _tl else ''
    # pc361: decrypter21/encrypter21 vise ne trebaju (ugradjena enkripcija), pa ih Setup ne trazi
    add('sider', L_('Sider (mapa sa sider.ini)', 'Sider (folder with sider.ini)'), sdir, os.path.isfile(os.path.join(sdir, 'sider.ini')) if sdir else False, False,
        L_('needed for F7 dump, training, crests and faces from the game', 'needed for the F7 dump, training, crests and in-game faces'))
    add('pes_exe', L_('Game (exe)', 'Game (exe)'), CFG.get('pes_exe'), os.path.isfile(CFG.get('pes_exe') or ''), False, L_('for the "Save and launch game" button', 'for the "Save & launch game" button'))
    mods = _sider_mod_state(sdir) if sdir else {}
    ok_dump = os.path.exists(CFG.get('dump') or '')
    fmt = None
    try:
        sl = [x for x in list_slots() if isinstance(x, dict)]
    except Exception:
        sl = []
    # pc270: koraci za Football Life 2027 (Setup ih prikazuje kad je odabrana FL27 mapa saveova)
    g27 = 'spgame' in os.path.normcase(sv) or _GAME['save'] == 'fl27'
    _fcs = fc27db.summary()
    game = dict(v='fc27', name='EA SPORTS FC 27', save=_GAME['save'] or '',
                db=_fcs['players'], clubs=_fcs['clubs'], leagues=_fcs['leagues'],
                db_ok=_fcs['ok'])
    if g27:
        _pj = os.path.join(HERE, 'data', 'fl27', 'players.json')
        try:
            _n = len(json.load(open(_pj, encoding='utf-8'))) if os.path.exists(_pj) else 0
        except Exception:
            _n = 0
        _sd = sdir or ''
        game.update(save=os.path.isdir(sv) and any(f.startswith('ML0') for f in os.listdir(sv)), key=bool(_fl_key()),
                    sider=bool(_sd) and '2027' in _sd, mods=bool(mods) and all(v['file'] and v['ini'] for v in mods.values()),
                    dump=ok_dump, dump_time=_fmt_mtime(CFG.get('dump') or '') if ok_dump else '', db=_n)
    return dict(version=APP_VERSION, built=APP_BUILT, game=game, ok=bool(DEV) or all(i['ok'] for i in items if i['required']), items=items, mods=mods, mods_ok=bool(mods) and all(v['file'] and v['ini'] for v in mods.values()),
                dump=ok_dump, slots=len(sl), work=CFG.get('work'), keys=_overlay_keys(sdir), live=_live_on(), regen=_regen_state(sdir), michele=_mich_state(sdir), reg_rules=bool(CFG.get('reg_rules', True)), owner=_is_owner(), first=not os.path.exists(os.path.join(HERE, 'config.json')) and not os.path.exists(os.path.join(HERE, 'data', '.setup_seen')) and not DEV)


def _reload_cfg():
    newc = load_cfg()
    CFG.clear()
    CFG.update(newc)
    _GL.clear()
    _GF.clear()
    if pes17.looks_like_pes17_path(CFG.get('save_dir')):
        _GAME['save'] = 'pes17'
    _clear_face_caches()



def save_check():
    """Je li odabrana mapa saveova zastarjela? Ako igra sprema u drugu mapu (npr. druga godina ili OneDrive), vrati je."""
    if DEV:
        return dict(ok=True)
    cur = CFG.get('save_dir') or ''

    def newest(d_):
        try:
            return max([os.path.getmtime(os.path.join(d_, f)) for f in os.listdir(d_) if f.startswith('ML0')] or [0])
        except Exception:
            return 0
    mine = newest(cur)
    cands = []
    try:
        par = os.path.dirname(os.path.dirname(cur))
        for y in os.listdir(par):
            cands.append(os.path.join(par, y, 'save'))
    except Exception:
        pass
    for h in _home_dirs():
        k = os.path.join(h, 'KONAMI')
        if os.path.isdir(k):
            try:
                cands += _bfs([k], lambda d_, n: n.lower() == 'save' and any(f.startswith('ML0') for f in os.listdir(os.path.join(d_, n))), depth=3, limit=300)
            except Exception:
                pass
    best, bm = None, mine
    for c in dict.fromkeys(cands):
        if os.path.normcase(os.path.abspath(c)) == os.path.normcase(os.path.abspath(cur)) or not os.path.isdir(c):
            continue
        # pc267: druga igra (FL26 u KONAMI, Football Life 2027 u SPGAME) nije 'novija mapa iste igre': ne nudi prelazak
        if ('spgame' in os.path.normcase(c)) != ('spgame' in os.path.normcase(cur)):
            continue
        m = newest(c)
        if m > bm + 60:
            best, bm = c, m
    if not best:
        return dict(ok=True, dir=cur)
    n = len([f for f in os.listdir(best) if f.startswith('ML0')])
    return dict(ok=False, dir=cur, newer=best, slots=n, newer_mtime=int(bm), mine_mtime=int(mine))



def save_ops_check(slot):
    """Provjera 'na suho' (u memoriji, save se ne sprema): koje upise app moze napraviti na ovom saveu."""
    d = slot_folder(slot)
    base = mlwrite.Save(d)
    my = (base.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    c = base.game_date_code()
    y = c & 0xffff
    g27 = bool(base.ext and getattr(base, 'game27', False))
    fmt = (base.layout_note or 'Football Life 2027') if g27 else ('45 MB (extended)' + (' · ' + base.layout_note if base.layout_note else ''))
    info = dict(format=fmt if base.ext else '19.9 MB (classic)', layout_ok=bool(base.layout_ok), dx=base.dx,
                known=bool(base.known_format), date='%d.%d.%d' % (c >> 24, (c >> 16) & 0xff, y), size=len(base.d),
                window=win_state(c)[2] == 'in')
    try:
        info['s16'] = struct.unpack_from('<I', base.d, base.S16CNT)[0]
    except Exception:
        pass
    loaned = base.loaned_pids()
    other = None
    oc = None
    for ci in range(1, 600):
        if ci == my:
            continue
        try:
            ids = [p for p in base.club_squad_ids(ci) if p and p not in loaned]
        except Exception:
            continue
        if len(ids) >= 18:
            other, oc = ids[-1], ci
            break
    mine = [p for p in base.my_squad_tags() if p not in loaned]
    pm = mine[-1] if mine else None
    end = (30 << 24) | (6 << 16) | (y + 1)
    if g27:   # pc277: FL27 kupnja ide kao dogovor (add_deal), kao u appu
        _buy = lambda sv: sv.add_deal(other, 0, 1000000, release=0, end=(31 << 24) | (8 << 16) | (y + 2), level=2)
    else:
        _buy = lambda sv: sv.direct_sign(other, 0, 1000000, (31 << 24) | (8 << 16) | (y + 2), pos=POS)
    tests = [('transfer', 'Sign a player (transfer)', _buy),
             ('loan_in', 'Loan a player in', lambda sv: sv.loan_in_pending(other, 0, end)),
             ('contract', 'Extend a contract', lambda sv: sv.extend_contract(pm, 1000000, y + 3))]
    if base.ext:
        # za test posudbe van: igrac koji nije doveden u ovom roku (takve igra jos ne pusta van)
        pm_lo = next((p for p in reversed(mine) if not base.recently_joined(p)), pm)
        tests.append(('loan_out', 'Loan a player out', lambda sv: sv.loan_out_pending(pm_lo, mlwrite.REC0 + oc * mlwrite.STRIDE, 0, end)))
    out = []
    for key, label, fn in tests:
        r = dict(key=key, label=label)
        try:
            if other is None or pm is None:
                raise ValueError('no test player found')
            sv = mlwrite.Save(d)
            fn(sv)
            # regresija (Clyne, 27.10.): kupljen igrac ne smije ispasti 'posuden'
            if key == 'transfer' and not g27 and other in sv.loaned_in_pids():
                raise ValueError('signed player would show as "on loan" in the app')
            sv.write_guard()   # pc277: iste zastite kao pri pravom spremanju (prije su zakljucani upisi pokazivali kvacicu)
            r['ok'] = True
        except Exception as ex:
            r['ok'] = False
            r['error'] = str(ex)[:300]
        out.append(r)
    try:
        sc = layoutscan.scan(base.d, base.my_squad_tags(), base.dx if base.ext else 0) if base.ext else None
        if sc:
            info['scan'] = sc['summary']
            info['scan_ok'] = all(t['status'] == 'ok' for t in sc['tables'])
            info['scan_tables'] = sc['tables']
    except Exception as ex:
        info['scan'] = 'table scan failed: %s' % ex
    try:
        ls = loanscan.scan(base)
        ok2 = all(t['status'] == 'ok' for t in ls['tables'])
        info['scan'] = ((info.get('scan') + ' ') if info.get('scan') else '') + ls['summary']
        info['scan_ok'] = info.get('scan_ok', True) and ok2
        info['loan_tables'] = ls['tables']
    except Exception as ex:
        info['scan'] = ((info.get('scan') + ' ') if info.get('scan') else '') + 'loan table scan failed: %s' % ex
    return dict(slot=slot, info=info, ops=out)


def support_pack(slot, note='', page=''):
    """Zip za podrsku: originalni (kriptirani) save slota, podaci o formatu, rezultat provjere i zadnji log. Bez lozinki; putanje ostaju."""
    import zipfile
    od = os.path.join(HERE, 'support')
    os.makedirs(od, exist_ok=True)
    zp = os.path.join(od, 'support_%s_%s.zip' % (re.sub(r'[^A-Za-z0-9]', '', slot), time.strftime('%Y%m%d_%H%M%S')))
    import traceback
    try:
        chk = save_ops_check(slot) if slot else dict(error='no career loaded')
    except Exception as ex:
        chk = dict(error=str(ex), trace=traceback.format_exc()[-4000:])
    diag = dict(slot=slot)
    try:
        diag['setup'] = setup_status() if 'setup_status' in globals() else None
    except Exception as ex:
        diag['setup'] = 'ERR ' + str(ex)
    try:
        sd = CFG.get('save_dir') or ''
        diag['save_dir'] = sd
        diag['saves'] = sorted((f, os.path.getsize(os.path.join(sd, f))) for f in os.listdir(sd) if f.startswith('ML')) if os.path.isdir(sd) else 'missing'
    except Exception as ex:
        diag['saves'] = 'ERR ' + str(ex)
    if slot:
        try:
            sv_ = mlwrite.Save(slot_folder(slot), ro=True)
            diag['layout'] = dict(shift=sv_.sh, dx=sv_.dx, ok=sv_.layout_ok, note=sv_.layout_note, size=len(sv_.d))
            if sv_.ext:
                diag['table_scan'] = layoutscan.scan(sv_.d, sv_.my_squad_tags(), sv_.dx)
            try:
                diag['loan_tables'] = loanscan.scan(sv_)
            except Exception as ex:
                diag['loan_tables'] = dict(error=str(ex))
        except BaseException as ex:
            diag['layout'] = dict(error=str(ex))
        try:
            st_ = state(slot)
            diag['state'] = dict(ok=True, club=(st_.get('info') or {}).get('club'), date=(st_.get('info') or {}).get('date'), layout=st_.get('layout'))
        except BaseException as ex:
            diag['state'] = dict(ok=False, error=str(ex), trace=traceback.format_exc()[-4000:])
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('diag.json', json.dumps(diag, ensure_ascii=False, indent=1, default=str))
        if note or page:   # pc299: 'Report a problem': sto je korisnik opisao i na kojoj je stranici bio
            z.writestr('report.txt', ('Page: %s\r\nVersion: %s\r\n\r\n%s\r\n' % (page, APP_VERSION, note)).encode('utf-8'))
        try:
            z.writestr('config.json', json.dumps({k: v for k, v in CFG.items() if not re.search(r'key|token|pass', k, re.I)}, ensure_ascii=False, indent=1, default=str))
        except Exception:
            pass
        src = os.path.join(CFG['save_dir'], slot) if not DEV else os.path.join(DEV, 'data.dat')
        if os.path.isfile(src):
            z.write(src, slot)
        z.writestr('check.json', json.dumps(chk, ensure_ascii=False, indent=1))
        z.writestr('app.json', json.dumps(dict(version=APP_VERSION, built=APP_BUILT, when=time.strftime('%Y-%m-%d %H:%M:%S'), server_size=os.path.getsize(os.path.join(HERE, 'server.py')),
                                               pes_exe=CFG.get('pes_exe'), sider=CFG.get('sider'), platform=sys.platform), ensure_ascii=False, indent=1))
        try:
            if os.path.isdir(DR_DIR):
                for f_ in sorted(os.listdir(DR_DIR))[-6:]:
                    fp_ = os.path.join(DR_DIR, f_)
                    z.write(fp_, 'deal_reports/' + f_)
                    try:
                        bk_ = json.load(open(fp_, encoding='utf-8')).get('backup_before')
                        if bk_ and os.path.isfile(bk_) and os.path.getsize(bk_) < 60 * 1024 * 1024:
                            z.write(bk_, 'deal_reports/before_' + os.path.basename(bk_))
                    except Exception:
                        pass
        except Exception as ex:
            z.writestr('deal_reports/error.txt', str(ex))
        if os.path.isfile(CLOG_FILE):
            z.write(CLOG_FILE, 'client_errors.log')
        for lg in ('career.log', 'karijera.log'):
            lp = os.path.join(HERE, lg)
            if os.path.isfile(lp):
                z.writestr(lg, open(lp, 'rb').read()[-200000:])
    if os.name == 'nt':
        try:
            subprocess.Popen(['explorer', '/select,', zp])
        except Exception:
            pass
    return dict(ok=True, path=zp, size=os.path.getsize(zp))


_DBC = {}


def db_check(slot):
    """pc146: odgovara li baza u appu (data/players.json) bazi u igri? Dva znaka koji ne ovise o napretku karijere:
    igraci u save-u kojih app nema i (ako postoji F7 dump) igraci u dumpu s ID-em kojeg app nema. Promjena OVR-a se NE broji
    jer je u karijeri normalna (rast igraca), a regeni koriste stare ID-eve pa se ne broje kao novi."""
    pj = _dbf('players.json')
    dp = CFG.get('dump') or ''
    try:
        sf = slot_folder(slot)
        key = (slot, os.path.getmtime(pj), os.path.getmtime(dp) if dp and os.path.exists(dp) else 0, _mtime_any(sf))
    except Exception as e:
        return dict(ok=False, why=str(e))
    if _DBC.get('key') == key:
        return _DBC['v']
    ids = {p[0] for p in json.load(open(pj, encoding='utf-8'))}
    s = mlwrite.Save(sf)
    ap = mlsave.all_players(s.d)
    miss = [pid for pid in ap if pid not in ids]
    my = (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE
    miss_my = [pid for pid in miss if ap[pid][0] == my]
    out = dict(ok=True, save_players=len(ap), unknown=len(miss), unknown_mine=len(miss_my), dump=False, dump_new=0, dump_date='')
    if dp and os.path.exists(dp):
        try:
            raw = open(dp, 'rb').read()
            P = dbimport.players_from_dump(raw)
            out.update(dump=True, dump_new=sum(1 for k in P if k not in ids), dump_date=_fmt_mtime(dp),
                       dump_newer=os.path.getmtime(dp) > os.path.getmtime(pj))
        except Exception as e:
            out['dump_err'] = str(e)
    lim = max(25, int(0.004 * max(1, len(ap))))
    if out['dump_new'] >= 50:
        out['level'] = 'import'          # dump ima nove igrace: uvoz baze rjesava
    elif out['unknown'] >= lim or out['unknown_mine'] >= 3:
        out['level'] = 'dump' if not out['dump'] or not out.get('dump_newer') else 'import'
    else:
        out['level'] = 'ok'
    out['sig'] = '%d-%d' % (out['unknown'] // 10, out['dump_new'] // 25)
    _DBC.update(key=key, v=out)
    return out


def _mtime_any(p):
    if os.path.isdir(p):
        return max([os.path.getmtime(os.path.join(p, f)) for f in os.listdir(p)] or [0])
    return os.path.getmtime(p)


def save_folders():
    """Mape saveova koje igra koristi (KONAMI\\eFootball PES 2021 SEASON UPDATE\\<x>\\save) s ML karijerama, za brzi prelazak FL26 <-> vanilla."""
    cur = os.path.normpath(CFG.get('save_dir') or '')
    roots = set()
    if cur:
        roots.add(os.path.dirname(os.path.dirname(cur)))
    try:
        docs = os.path.join(os.path.expanduser('~'), 'Documents', 'KONAMI', 'eFootball PES 2021 SEASON UPDATE')
        roots.add(docs)
        od = os.environ.get('OneDrive')
        if od:
            for nm in ('Documents', 'Dokumenti'):
                roots.add(os.path.join(od, nm, 'KONAMI', 'eFootball PES 2021 SEASON UPDATE'))
        # pc265: Football Life 2027 sprema u <Dokumenti>\SPGAME\Football Life\<godina>\save
        for h in _home_dirs():
            roots.add(os.path.join(h, 'SPGAME', 'Football Life'))
    except Exception:
        pass
    out = []
    for rt in roots:
        try:
            subs = os.listdir(rt)
        except Exception:
            continue
        for sub in subs:
            sd = os.path.join(rt, sub, 'save')
            try:
                ml = [f for f in os.listdir(sd) if re.match(r'^ML[0-9A-F]{8}$', f)]
            except Exception:
                continue
            if not ml:
                continue
            newest = max(os.path.getmtime(os.path.join(sd, f)) for f in ml)
            kind = ('Football Life ' + sub) if re.match(r'^\d{4}$', sub) else ('PES 2021 (Steam)' if sub.isdigit() else sub)
            out.append(dict(path=sd, label=kind, n=len(ml), newest=time.strftime('%d.%m.%Y %H:%M', time.localtime(newest)),
                            current=os.path.normcase(os.path.normpath(sd)) == os.path.normcase(cur)))
    # PES 2017 compatibility: Documents\KONAMI\Pro Evolution Soccer 2017\save
    for h in _home_dirs():
        p17 = os.path.join(h, 'KONAMI', 'Pro Evolution Soccer 2017', 'save')
        if not os.path.isdir(p17):
            continue
        try:
            ml = [f for f in os.listdir(p17) if re.match(r'^ML[0-9A-F]{8}$', f)]
        except OSError:
            continue
        if not ml:
            continue
        newest = max(os.path.getmtime(os.path.join(p17, f)) for f in ml)
        out.append(dict(path=p17, label='PES 2017', n=len(ml),
                        newest=time.strftime('%d.%m.%Y %H:%M', time.localtime(newest)),
                        current=os.path.normcase(os.path.normpath(p17)) == os.path.normcase(cur)))
    seen, res = set(), []
    for x in sorted(out, key=lambda x: (not x['current'], x['label'])):
        k = os.path.normcase(os.path.normpath(x['path']))
        if k not in seen:
            seen.add(k)
            res.append(x)
    return dict(folders=res, current=cur)


GAME_KEYS = ('pes_exe', 'sider', 'pes_process', 'dump', 'telemetry', 'edit_dat', 'fl_key')


def _save_year(sd):
    """Godina igre iz mape saveova: ...\\2027\\save -> '2027' (FL27 je u SPGAME\\Football Life\\2027)."""
    m = re.findall(r'(20\d\d)', os.path.normpath(sd).replace('\\', '/'))
    return m[-1] if m else ''


def _detect_game_for(sd):
    """pc265: postavke igre (exe, Sider, proces, dump) za mapu saveova: Sider cija igra (exe.name) nosi istu godinu
    (FL_2027.exe za ...\\2027\\save). Trazi samo vrh diskova i jednu razinu ispod (brzo). -> dict ili {}"""
    if pes17.looks_like_pes17_path(sd):
        r = dict(pes_process='PES2017', auto_menu=False, pes17_date_order='dmy')
        exe = pes17.find_exe(sd)
        if exe:
            r['pes_exe'] = exe
        return r
    yr = _save_year(sd)
    if not yr:
        return {}
    cands = []
    for dr in _drives():
        try:
            subs = [os.path.join(dr, x) for x in os.listdir(dr)]
        except Exception:
            continue
        for g in [dr] + subs:
            for sdir in (os.path.join(g, 'SiderAddons'), g):
                ini = os.path.join(sdir, 'sider.ini')
                if os.path.isfile(ini):
                    cands.append(sdir)
    for sdir in cands:
        try:
            m = re.search(r'exe\.name\s*=\s*"\\?([^"]+)"', open(os.path.join(sdir, 'sider.ini'), encoding='utf-8', errors='ignore').read())
        except Exception:
            m = None
        exe = os.path.basename(m.group(1).strip().replace('/', '\\')) if m else ''
        if not exe or yr not in exe:
            continue
        gdir = os.path.dirname(sdir) if os.path.isfile(os.path.join(os.path.dirname(sdir), exe)) else sdir
        out = dict(sider=sdir, pes_process=os.path.splitext(exe)[0])
        try:
            st = sorted(f for f in os.listdir(gdir) if f.lower().endswith('.exe') and re.search(r'start|launch', f, re.I))
        except Exception:
            st = []
        out['pes_exe'] = os.path.join(gdir, st[0] if st else exe)
        b_ = os.path.join(sdir, 'content', 'ml-immersion', 'bridge')
        out['dump'] = os.path.join(b_, 'players_dump.bin')
        out['telemetry'] = os.path.join(b_, 'telemetry.json')
        for kp in (os.path.join(gdir, 'FL_key.bin'), os.path.join(sd, 'FL_key.bin')):
            if os.path.isfile(kp):
                out['fl_key'] = kp
        return out
    return {}


def setup_save(body):
    p = os.path.join(HERE, 'config.json')
    try:
        cur = json.load(open(p, encoding='utf-8'))
    except Exception:
        cur = {}
    if os.path.exists(p):
        shutil.copy2(p, p + '.bak-setup')
    # pc265: igra prati mapu saveova. Prelazak na drugu mapu (npr. FL26 -> Football Life 2027) zapamti postavke igre za staru
    # mapu (exe, Sider, proces, dump) i vrati/pronadje postavke igre nove mape, pa app cita i pise u pravu igru.
    new_sd = (body.get('save_dir') or '').strip().strip('"')
    old_sd = cur.get('save_dir') or CFG.get('save_dir') or ''
    if new_sd and os.path.normcase(os.path.normpath(new_sd)) != os.path.normcase(os.path.normpath(os.path.expandvars(old_sd))):
        prof = cur.setdefault('profiles', {})
        if old_sd:
            prof[os.path.normcase(os.path.normpath(os.path.expandvars(old_sd)))] = {k: cur.get(k, CFG.get(k)) for k in GAME_KEYS if cur.get(k, CFG.get(k))}
        got = prof.get(os.path.normcase(os.path.normpath(new_sd)))
        if not got:
            try:
                got = _detect_game_for(new_sd)
            except Exception as ex:
                print('[setup] igra za mapu:', ex)
                got = {}
        if got:   # nepoznata mapa (npr. PES 2021 Steam): postavke igre ostaju kakve jesu
            for k in GAME_KEYS:
                cur.pop(k, None)
            cur.update(got)
    for k in ('save_dir', 'decrypter', 'encrypter', 'pes_exe', 'sider'):
        v = (body.get(k) or '').strip().strip('"')
        if v:
            cur[k] = v
    if 'reg_rules' in body:
        cur['reg_rules'] = bool(body.get('reg_rules'))   # pc195: pravila registracije u appu
    if cur.get('sider'):
        b_ = os.path.join(cur['sider'], 'content', 'ml-immersion', 'bridge')
        cur['dump'] = os.path.join(b_, 'players_dump.bin')
        cur['telemetry'] = os.path.join(b_, 'telemetry.json')
        try:
            m = re.search(r'exe\.name\s*=\s*"\\?([^"]+)"', open(os.path.join(cur['sider'], 'sider.ini'), encoding='utf-8', errors='ignore').read())
            if m:
                cur['pes_process'] = os.path.splitext(os.path.basename(m.group(1).strip().replace('/', '\\')))[0]   # proces igre (za "igra je pokrenuta")
        except Exception:
            pass
    if not cur.get('work') or not os.path.isdir(os.path.dirname(os.path.expandvars(cur.get('work')))):
        cur['work'] = os.path.join(HERE, 'work')
    try:
        os.makedirs(os.path.expandvars(cur['work']), exist_ok=True)
        _jdump(cur, p, ensure_ascii=False, indent=1)
    except OSError as ex:
        return dict(ok=False, error=_blocked_write_msg(ex))
    _reload_cfg()
    return dict(ok=True, status=setup_status())


def _blocked_write_msg(ex):
    """pc366: Windows 'Controlled folder access' (zastita od ransomwarea) tiho blokira pisanje u Dokumente; Python tada
    dobije WinError 2 ili 5 za mapu koja postoji. Jasna uputa umjesto gole greske."""
    py = sys.executable or 'python.exe'
    return ('Windows blocked The Gaffer from writing in this folder (%s). This is usually Windows Security > Ransomware protection > '
            '"Controlled folder access", which protects Documents. Fix: Windows Security > Virus & threat protection > Manage ransomware protection > '
            'Allow an app through Controlled folder access > Add an allowed app > choose %s. (The game saves are in Documents too, so the app needs this to write them.) '
            'Alternatively move The Gaffer folder out of Documents, e.g. to C:\\Games\\TheGaffer.' % (ex, py))


def _grant_sider_access(sdir):
    """Igra u C:\\Program Files: Windows ne da pisati u Sider mapu bez administratora. Jednom (uz Windows UAC upit)
    damo grupi Users pravo izmjene na Sider mapi; dalje app i Sider moduli (dump, growth) pisu normalno."""
    if os.name != 'nt' or not sdir:
        return False
    import subprocess
    arg = '"%s" /grant *S-1-5-32-545:(OI)(CI)M /C /Q' % sdir.rstrip('\\/')
    ps = "Start-Process -FilePath icacls.exe -ArgumentList '%s' -Verb RunAs -Wait -WindowStyle Hidden" % arg.replace("'", "''")
    try:
        r = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, timeout=180,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode != 0:
            return False
        t = os.path.join(sdir, '.karijera_write_test')
        open(t, 'w').write('ok')
        os.remove(t)
        return True
    except Exception:
        return False


def _sider_denied_msg(sdir, e):
    return dict(ok=False, denied=True, message=L_(
        'Windows ne dopušta pisanje u mapu igre (%s): igra je u "Program Files". Klikni ponovo i prihvati Windows upit (Da), '
        'ili jednom pokreni The Gaffer.bat (ili Career.bat) desnim klikom → "Pokreni kao administrator", ili premjesti igru izvan Program Files. (%s)' % (sdir, e),
        'Windows does not allow writing to the game folder (%s) because the game is in "Program Files". Click again and accept the Windows prompt (Yes), '
        'or run The Gaffer.bat (or Career.bat) once with right-click > "Run as administrator", or move the game out of Program Files. (%s)' % (sdir, e)))


def _with_sider_access(fn):
    def w():
        try:
            return fn()
        except PermissionError as e:
            sdir = _sider_root()
            if _grant_sider_access(sdir):
                try:
                    return fn()
                except PermissionError as e2:
                    return _sider_denied_msg(sdir, e2)
            return _sider_denied_msg(sdir, e)
    return w


def _sider_retry(f):
    """Pisanje u bridge mapu (growth.csv i sl.) kad je igra u Program Files: jednom zatrazi pravo (UAC) pa ponovi."""
    def w(*a, **k):
        try:
            return f(*a, **k)
        except PermissionError as e:
            sdir = _sider_root()
            if _grant_sider_access(sdir):
                return f(*a, **k)
            raise PermissionError(_sider_denied_msg(sdir, e)['message'])
    return w


growth.queue = _sider_retry(growth.queue)
growth.set_enabled = _sider_retry(growth.set_enabled)


def setup_install_sider():
    """Kopira Sider module appa (lua/) u <Sider>\\modules i doda lua.module linije u sider.ini (uz kopiju sider.ini)."""
    sdir = _sider_root()
    if not sdir or not os.path.isfile(os.path.join(sdir, 'sider.ini')):
        return dict(ok=False, message=L_('Prvo postavi mapu Sidera.', 'Set the Sider folder first.'))
    src = os.path.join(HERE, 'lua')
    os.makedirs(os.path.join(sdir, 'modules'), exist_ok=True)
    os.makedirs(os.path.join(sdir, 'content', 'ml-immersion', 'bridge'), exist_ok=True)
    done = []
    for m in SIDER_MODS:
        s_ = os.path.join(src, m)
        d_ = os.path.join(sdir, 'modules', m)
        if not os.path.isfile(s_):
            continue
        if os.path.isfile(d_) and open(d_, 'rb').read() == open(s_, 'rb').read():
            continue
        if os.path.isfile(d_):
            shutil.copy2(d_, d_ + '.bak-gaffer')
        shutil.copy2(s_, d_)
        done.append(m)
    ini_p = os.path.join(sdir, 'sider.ini')
    ini = open(ini_p, encoding='utf-8', errors='ignore').read()
    add = [m for m in SIDER_MODS if not re.search(r'^\s*lua\.module\s*=\s*"%s"' % re.escape(m), ini, re.M)]
    if add:
        shutil.copy2(ini_p, ini_p + '.bak-gaffer-%s' % time.strftime('%Y%m%d_%H%M%S'))
        nl = '\r\n' if '\r\n' in ini else '\n'
        if not ini.endswith(('\n', '\r')):
            ini += nl
        ini += ''.join('lua.module = "%s"%s' % (m, nl) for m in add)
        open(ini_p, 'w', encoding='utf-8', newline='').write(ini)
    if not done and not add:
        return dict(ok=True, message=L_('Modules are already installed and up to date.', 'Modules are already installed and up to date.'), status=setup_status())
    return dict(ok=True, message=L_('Moduli kopirani: %s; dodano u sider.ini: %s. Ponovo pokreni igru.' % (', '.join(done) or '-', ', '.join(add) or '-'),
                                    'Modules copied: %s; added to sider.ini: %s. Restart the game.' % (', '.join(done) or '-', ', '.join(add) or '-')), status=setup_status())


# ---------------------------------------------------------------- Regen fix (mataodzanata (FL Mod Studio), fl26regen) - neobavezni dodatak
REGEN_MODS = ('fl26regen.dll', 'fl26regen.lua')
REGEN_OPT = ('fl26regen_faces.bin',)
REGEN_CPK = 'FL26 Regen Faces'


def _regen_src():
    """Mapa s datotekama regen fixa uz app (iz paketa): addons/regenfix/(modules, livecpk)."""
    d = os.path.join(HERE, 'addons', 'regenfix')
    return d if os.path.isfile(os.path.join(d, 'modules', 'fl26regen.dll')) else None


def _regen_state(sdir):
    st = dict(available=bool(_regen_src()) and not _is_fl27_setup(), fl27=_is_fl27_setup(), dll=False, lua=False, faces_bin=False, cpk_dir=False, ini_module=False, ini_cpk=False, luajit=False)
    if not sdir or not os.path.isfile(os.path.join(sdir, 'sider.ini')):
        return st
    md = os.path.join(sdir, 'modules')
    st['dll'] = os.path.isfile(os.path.join(md, 'fl26regen.dll'))
    st['lua'] = os.path.isfile(os.path.join(md, 'fl26regen.lua'))
    st['faces_bin'] = os.path.isfile(os.path.join(md, 'fl26regen_faces.bin'))
    st['cpk_dir'] = os.path.isdir(os.path.join(sdir, 'livecpk', REGEN_CPK))
    try:
        ini = open(os.path.join(sdir, 'sider.ini'), encoding='utf-8', errors='ignore').read()
    except Exception:
        ini = ''
    st['ini_module'] = bool(re.search(r'^\s*lua\.module\s*=\s*"fl26regen\.lua"', ini, re.M))
    st['ini_cpk'] = bool(re.search(r'^\s*cpk\.root\s*=\s*"[^"]*%s"' % re.escape(REGEN_CPK), ini, re.M | re.I))
    st['luajit'] = bool(re.search(r'^\s*luajit\.ext\.enabled\s*=\s*1', ini, re.M))
    st['installed'] = st['dll'] and st['lua'] and st['ini_module'] and st['luajit']
    st['faces'] = st['faces_bin'] and st['cpk_dir'] and st['ini_cpk']
    return st


def _is_fl27_setup():
    """pc283: je li odabrana igra Football Life 2027 (profil/exe/zadnji ucitani save). FL26 Sider moduli (Michele, regen fix,
    ozljede) nisu provjereni na FL27 i ne nude se tamo."""
    try:
        if _GAME.get('save') == 'fl27':
            return True
        return '2027' in (CFG.get('pes_exe') or '') or '2027' in (CFG.get('save_dir') or '')
    except Exception:
        return False


def setup_install_regen():
    """Instalira regen fix (mataodzanata, FL Mod Studio) iz addons/regenfix u Sider: modules + livecpk/FL26 Regen Faces + linije u sider.ini (uz kopije)."""
    if _is_fl27_setup():
        return dict(ok=False, message='The regen fix is made for FL26 and is not checked on Football Life 2027, so the app does not install it there.')
    sdir = _sider_root()
    if not sdir or not os.path.isfile(os.path.join(sdir, 'sider.ini')):
        return dict(ok=False, message=L_('Prvo postavi mapu Sidera.', 'Set the Sider folder first.'))
    src = _regen_src()
    if not src:
        st = _regen_state(sdir)
        if st.get('installed'):
            return dict(ok=True, message=L_('Regen fix je već instaliran.', 'The regen fix is already installed.'), status=setup_status())
        return dict(ok=False, message=L_('Datoteke regen fixa nisu uz app (mapa addons\\regenfix).', 'The regen fix files are not next to the app (folder addons\\regenfix).'))
    done = []
    md = os.path.join(sdir, 'modules')
    os.makedirs(md, exist_ok=True)
    for f in REGEN_MODS + REGEN_OPT:
        s_ = os.path.join(src, 'modules', f)
        d_ = os.path.join(md, f)
        if not os.path.isfile(s_):
            continue
        if os.path.isfile(d_) and open(d_, 'rb').read() == open(s_, 'rb').read():
            continue
        if os.path.isfile(d_):
            shutil.copy2(d_, d_ + '.bak-gaffer')
        shutil.copy2(s_, d_)
        done.append(f)
    cs = os.path.join(src, 'livecpk', REGEN_CPK)
    ncp = 0
    if os.path.isdir(cs):
        for root_, dirs_, files_ in os.walk(cs):
            rel = os.path.relpath(root_, cs)
            dd = os.path.join(sdir, 'livecpk', REGEN_CPK, rel) if rel != '.' else os.path.join(sdir, 'livecpk', REGEN_CPK)
            os.makedirs(dd, exist_ok=True)
            for f in files_:
                if not os.path.isfile(os.path.join(dd, f)):
                    shutil.copy2(os.path.join(root_, f), os.path.join(dd, f))
                    ncp += 1
    ini_p = os.path.join(sdir, 'sider.ini')
    ini = open(ini_p, encoding='utf-8', errors='ignore').read()
    nl = '\r\n' if '\r\n' in ini else '\n'
    new = ini
    added = []
    if re.search(r'^\s*luajit\.ext\.enabled\s*=\s*0', new, re.M):
        new = re.sub(r'^(\s*luajit\.ext\.enabled\s*=\s*)0', r'\g<1>1', new, count=1, flags=re.M)
        added.append('luajit.ext.enabled = 1')
    elif not re.search(r'^\s*luajit\.ext\.enabled\s*=', new, re.M):
        if not new.endswith(('\n', '\r')):
            new += nl
        new += 'luajit.ext.enabled = 1' + nl
        added.append('luajit.ext.enabled = 1')
    if os.path.isdir(os.path.join(sdir, 'livecpk', REGEN_CPK)) and not re.search(r'^\s*cpk\.root\s*=\s*"[^"]*%s"' % re.escape(REGEN_CPK), new, re.M | re.I):
        if not new.endswith(('\n', '\r')):
            new += nl
        new += 'cpk.root = ".\\livecpk\\%s"%s' % (REGEN_CPK, nl)
        added.append('cpk.root %s' % REGEN_CPK)
    if not re.search(r'^\s*lua\.module\s*=\s*"fl26regen\.lua"', new, re.M):
        if not new.endswith(('\n', '\r')):
            new += nl
        new += 'lua.module = "fl26regen.lua"' + nl
        added.append('lua.module fl26regen.lua')
    if new != ini:
        shutil.copy2(ini_p, ini_p + '.bak-gaffer-%s' % time.strftime('%Y%m%d_%H%M%S'))
        open(ini_p, 'w', encoding='utf-8', newline='').write(new)
    if not done and not added and not ncp:
        return dict(ok=True, message=L_('Regen fix je već instaliran i ažuran.', 'The regen fix is already installed and up to date.'), status=setup_status())
    return dict(ok=True, message=L_('Regen fix instaliran (datoteke: %s; lica: %d; sider.ini: %s). Ponovo pokreni igru.' % (', '.join(done) or '-', ncp, ', '.join(added) or '-'),
                                    'Regen fix installed (files: %s; faces: %d; sider.ini: %s). Restart the game.' % (', '.join(done) or '-', ncp, ', '.join(added) or '-')), status=setup_status())


MICH_FIRST = 'FL26 - Guardia rosa vuota.lua'
MICH_MODS = ('Economia Lunga - motore.lua', 'Regole di tesseramento.lua')


def _mich_src():
    """Moduli Michele & Claude uz app (iz paketa): addons/michele/modules."""
    d = os.path.join(HERE, 'addons', 'michele', 'modules')
    return d if os.path.isfile(os.path.join(d, MICH_FIRST)) else None


def _mich_state(sdir):
    st = dict(available=bool(_mich_src()) and not _is_fl27_setup(), files=False, ini=False, first=False, luajit=False, fl27=_is_fl27_setup())
    if not sdir or not os.path.isfile(os.path.join(sdir, 'sider.ini')):
        return st
    md = os.path.join(sdir, 'modules')
    st['files'] = all(os.path.isfile(os.path.join(md, f)) for f in (MICH_FIRST,) + MICH_MODS)
    try:
        ini = open(os.path.join(sdir, 'sider.ini'), encoding='utf-8', errors='ignore').read()
    except Exception:
        ini = ''
    mods = re.findall(r'^\s*lua\.module\s*=\s*"([^"]+)"', ini, re.M)
    st['ini'] = all(f in mods for f in (MICH_FIRST,) + MICH_MODS)
    st['first'] = bool(mods) and mods[0] == MICH_FIRST
    st['luajit'] = bool(re.search(r'^\s*luajit\.ext\.enabled\s*=\s*1', ini, re.M))
    st['guard'] = os.path.isfile(os.path.join(md, MICH_FIRST)) and MICH_FIRST in mods and st['first']
    st['rules'] = all(os.path.isfile(os.path.join(md, f)) for f in MICH_MODS) and all(f in mods for f in MICH_MODS)
    st['installed'] = st['guard']
    st['inj'] = os.path.isfile(os.path.join(md, MICH_INJ)) and MICH_INJ in mods
    st['inj_level'] = 'off'
    if st['inj']:
        st['inj_level'] = 'realistic'
        try:
            m_ = re.search(r'^\s*level\s*=\s*(\w+)', open(os.path.join(sdir, MICH_INJ_INI), encoding='utf-8', errors='ignore').read(), re.M)
            if m_ and m_.group(1).lower() in INJ_LEVELS:
                st['inj_level'] = m_.group(1).lower()
        except OSError:
            pass
    try:
        w_, src_ = world_injuries()
        st['inj_live'] = dict(source=src_, n=len(w_), long=sum(1 for v in w_.values() if v >= 45))
    except Exception:
        st['inj_live'] = None
    return st


MICH_INJ, MICH_INJ_INI = 'injuries_for_all.lua', 'injuries_for_all.ini'
INJ_LEVELS = ('light', 'realistic', 'heavy')


def setup_injuries(body=None):
    """pc198: Injuries For All (Michele & Claude, v1.0-gaffer1): prave duljine ozljeda i nove ozljede po kalendaru za sve klubove.
    level = off | light | realistic | heavy. Radi na svim formatima savea (trazi tablicu igraca u memoriji, ne tablicu klubova)."""
    if _is_fl27_setup():
        return dict(ok=False, message='Injuries For All is made for FL26 and is not checked on Football Life 2027, so the app does not install it there.')
    body = body or {}
    lv = (body.get('level') or 'realistic').lower()
    if lv not in INJ_LEVELS + ('off',):
        return dict(ok=False, message='Unknown level.')
    sdir = _sider_root()
    if not sdir or not os.path.isfile(os.path.join(sdir, 'sider.ini')):
        return dict(ok=False, message='Set the Sider folder first.')
    src = _mich_src()
    md = os.path.join(sdir, 'modules')
    ini_p = os.path.join(sdir, 'sider.ini')
    ini = open(ini_p, encoding='utf-8', errors='ignore').read()
    nl = '\r\n' if '\r\n' in ini else '\n'
    rx = re.compile(r'^\s*lua\.module\s*=\s*"([^"]+)"')
    lines = ini.splitlines()
    if lv == 'off':
        lines = [l for l in lines if not (rx.match(l) and rx.match(l).group(1) == MICH_INJ)]
        msg = 'Injuries For All is switched off (removed from sider.ini). Injuries already in your career stay until they heal. Restart the game.'
    else:
        if not src or not os.path.isfile(os.path.join(src, MICH_INJ)):
            return dict(ok=False, message='The module file is not next to the app (folder addons\\michele).')
        os.makedirs(md, exist_ok=True)
        s_, d_ = os.path.join(src, MICH_INJ), os.path.join(md, MICH_INJ)
        if not (os.path.isfile(d_) and open(d_, 'rb').read() == open(s_, 'rb').read()):
            if os.path.isfile(d_):
                shutil.copy2(d_, d_ + '.bak-gaffer')
            shutil.copy2(s_, d_)
        open(os.path.join(sdir, MICH_INJ_INI), 'w', encoding='utf-8').write(
            '; Injuries For All (Michele & Claude) - written by The Gaffer Setup\n; level = light | realistic | heavy\nlevel = %s\n' % lv)
        if not any(rx.match(l) and rx.match(l).group(1) == MICH_INJ for l in lines):
            idx = [i for i, l in enumerate(lines) if rx.match(l)]
            if idx:
                lines.insert(idx[-1] + 1, 'lua.module = "%s"' % MICH_INJ)
            else:
                lines.append('lua.module = "%s"' % MICH_INJ)
        if not any(re.match(r'^\s*luajit\.ext\.enabled\s*=\s*1', l) for l in lines):
            lines = [re.sub(r'^(\s*luajit\.ext\.enabled\s*=\s*)0', r'\g<1>1', l) for l in lines]
            if not any(re.match(r'^\s*luajit\.ext\.enabled\s*=\s*1', l) for l in lines):
                lines.append('luajit.ext.enabled = 1')
        msg = ('Injuries For All installed, level "%s". Restart the game. It works in Master League on every save format: '
               'the lengths of new injuries become realistic and every calendar day a few healthy players get injured, for you and the CPU. '
               'sider.log shows its lines as "INJURIES FOR ALL".' % lv)
    new = nl.join(lines) + nl
    if new.strip() != ini.strip():
        shutil.copy2(ini_p, ini_p + '.bak-gaffer-%s' % time.strftime('%Y%m%d_%H%M%S'))
        open(ini_p, 'w', encoding='utf-8', newline='').write(new)
    return dict(ok=True, message=msg, status=setup_status())


def _mich_rules_ok(slot):
    """pc196: modul s pravilima (i motor) pisan je za tablice od 1.600 klubova (fl26caps / Mod Studio 0.2.0-0.2.1 = nas 45 MB).
    Na klasicnom (750) i 60 MB (2.400) formatu bi citao krive klubove, pa se tamo ne nudi. -> (ok, opis formata)"""
    try:
        sv = mlwrite.Save(slot_folder(slot), ro=True)
    except Exception:
        return False, 'unknown (load a career first)'
    if not sv.ext:
        return False, 'classic 19.9 MB save'
    if sv.fmt60:
        return False, '60 MB save (FL Mod Studio 0.2.2+)'
    return True, '45 MB save'


def setup_install_michele(body=None):
    """Instalira module Michele & Claude (FL26 Master League Realism Mods): popravak pada 1. srpnja (Guardia rosa vuota, PRVI modul),
    Economia Lunga - motore i Regole di tesseramento (motor prije pravila). Uz kopije; moduli sami provjere bajtove igre.
    pc196: motor i pravila samo na formatu za koji su pisani (45 MB); na ostalima samo popravak pada."""
    if _is_fl27_setup():
        return dict(ok=False, message='The Michele & Claude modules is made for FL26 and is not checked on Football Life 2027, so the app does not install it there.')
    body = body or {}
    rules_ok, fmt = _mich_rules_ok(body.get('slot') or '')
    sdir = _sider_root()
    if not sdir or not os.path.isfile(os.path.join(sdir, 'sider.ini')):
        return dict(ok=False, message='Set the Sider folder first.')
    src = _mich_src()
    if not src:
        return dict(ok=False, message='The module files are not next to the app (folder addons\\michele).')
    md = os.path.join(sdir, 'modules')
    os.makedirs(md, exist_ok=True)
    done = []
    mods = MICH_MODS if rules_ok else ()
    for f in (MICH_FIRST,) + mods:
        s_, d_ = os.path.join(src, f), os.path.join(md, f)
        if os.path.isfile(d_) and open(d_, 'rb').read() == open(s_, 'rb').read():
            continue
        if os.path.isfile(d_):
            shutil.copy2(d_, d_ + '.bak-gaffer')
        shutil.copy2(s_, d_)
        done.append(f)
    ini_p = os.path.join(sdir, 'sider.ini')
    ini = open(ini_p, encoding='utf-8', errors='ignore').read()
    nl = '\r\n' if '\r\n' in ini else '\n'
    lines = ini.splitlines()
    added = []
    rx = re.compile(r'^\s*lua\.module\s*=\s*"([^"]+)"')
    # Guardia rosa vuota mora biti PRVI lua.module
    lines = [l for l in lines if not (rx.match(l) and rx.match(l).group(1) == MICH_FIRST)]
    first_mod = next((i for i, l in enumerate(lines) if rx.match(l)), None)
    ins = 'lua.module = "%s"' % MICH_FIRST
    if first_mod is None:
        lines.append(ins)
    else:
        lines.insert(first_mod, ins)
    if ins not in ini:
        added.append(MICH_FIRST)
    have = [rx.match(l).group(1) for l in lines if rx.match(l)]
    last_mod = max(i for i, l in enumerate(lines) if rx.match(l))
    for f in mods:
        if f not in have:
            last_mod += 1
            lines.insert(last_mod, 'lua.module = "%s"' % f)
            added.append(f)
    if not any(re.match(r'^\s*luajit\.ext\.enabled\s*=\s*1', l) for l in lines):
        lines = [re.sub(r'^(\s*luajit\.ext\.enabled\s*=\s*)0', r'\g<1>1', l) for l in lines]
        if not any(re.match(r'^\s*luajit\.ext\.enabled\s*=\s*1', l) for l in lines):
            lines.append('luajit.ext.enabled = 1')
        added.append('luajit.ext.enabled = 1')
    new = nl.join(lines) + nl
    if new.strip() != ini.strip():
        shutil.copy2(ini_p, ini_p + '.bak-gaffer-%s' % time.strftime('%Y%m%d_%H%M%S'))
        open(ini_p, 'w', encoding='utf-8', newline='').write(new)
    note = '' if rules_ok else (' The in-game registration rules were NOT installed: they are written for 45 MB saves (1,600 clubs) and your career is a %s. '
                                'The rules still apply to the app\'s negotiations and AI transfers.' % fmt)
    if not done and not added:
        return dict(ok=True, message='The modules by Michele & Claude are already installed and up to date.' + note, status=setup_status())
    return dict(ok=True, message='Installed (files: %s; sider.ini: %s). Restart the game. If your game build is different, the modules change nothing and say so in sider.log.%s'
                % (', '.join(done) or '-', ', '.join(added) or '-', note), status=setup_status())


# The player database lives in data/fc27 (shipped via PKG_DATA_DIRS below), not
# at the data/ root. put() silently skips missing files, so listing the old root
# paths here would produce a package with no players at all.
# data/teamids.json + venue_metadata.json stay: they are a matched FL26 pair used
# only by the name-keyed venue lookup, which verifies ids between those two files.
PKG_DATA = ('teamids.json', 'fm_text.json', 'owners.json', 'club_identity.json',
            'venue_metadata.json', 'fl26_installed_league_counts.json')
PKG_DATA_DIRS = ('fc27', 'art', 'stadiums', 'myscenes', 'i18n')   # fc27 = the game database; i18n = translations; myscenes = office/press scenes


PY_EMBED = ('https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip',)


def _portable_python():
    """Prijenosni (embeddable) Python za Windows: skine se jednom s python.org i kesira u paket\\_kes."""
    import urllib.request, zipfile, io
    kd = os.path.join(HERE, 'paket', '_kes')
    os.makedirs(kd, exist_ok=True)
    zp = os.path.join(kd, 'python-embed-amd64.zip')
    err = None
    if not os.path.isfile(zp):
        for u in PY_EMBED:
            try:
                data = urllib.request.urlopen(u, timeout=120).read()
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    if 'python.exe' not in z.namelist():
                        raise ValueError('neocekivan sadrzaj')
                open(zp, 'wb').write(data)
                err = None
                break
            except Exception as e:
                err = str(e)
    return zp if os.path.isfile(zp) else None, err


def make_package(opt=None):
    """Cisti zip za dijeljenje (mapa careerFL): kod, sucelje, Sider moduli, alati za save (tools) i prijenosni Python; bez osobnih podataka, FM slika, kopija i postavki."""
    import zipfile
    opt = opt or {}
    TOP = 'TheGaffer/'
    out_dir = os.path.join(HERE, 'paket')
    os.makedirs(out_dir, exist_ok=True)
    zp = os.path.join(out_dir, 'TheGaffer_%s_%s.zip' % (APP_VERSION, time.strftime('%Y%m%d')))
    sdir = _sider_root()
    bak = re.compile(r'\.(bak|tmp|pyc|log|orig|rar)$|\.(bak|tmp|pyc|log|orig)|\.bak-|\.star|\.stari', re.I)   # pc355: i .orig (stare kopije index.html)
    n = 0
    notes = []
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        def wr(arc, data):
            # vrijeme upisujemo sami: neke datoteke imaju neispravan datum izmjene (Errno 22 u zipfile.write)
            zi = zipfile.ZipInfo(arc, time.localtime()[:6])
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)

        def put(fp, arc):
            nonlocal n
            if os.path.isfile(fp) and not bak.search(os.path.basename(fp)):
                wr(arc, open(fp, 'rb').read())
                n += 1
        put(os.path.join(HERE, 'server.py'), TOP + 'server.py')
        wr(TOP + 'VERSION.txt', ('%s (%s)\n' % (APP_VERSION, APP_BUILT)).encode())
        put(os.path.join(HERE, 'TheGaffer.ico') if os.path.isfile(os.path.join(HERE, 'TheGaffer.ico')) else os.path.join(HERE, 'Karijera.ico'), TOP + 'TheGaffer.ico')
        # pc270: kljuc saveova Football Life 2027 (od SP tima) ide uz app; za FL26 / PES 2021 se ne koristi
        if os.path.isfile(os.path.join(HERE, 'FL_key.bin')):
            put(os.path.join(HERE, 'FL_key.bin'), TOP + 'FL_key.bin')
            wr(TOP + 'FL_key_README.txt', ('FL_key.bin = save key for Football Life 2027 (provided by the SP Football Life team).\r\n'
                                           'The Gaffer needs it only to open FL27 saves. Leave it next to server.py. FL26 / PES 2021 saves do not use it.\r\n').encode())
        for f, arc in (('Career.bat', 'The Gaffer.bat'), ('Career.vbs', 'The Gaffer.vbs'), ('README.txt', 'README.txt')):     # start skripte i upute (mapa share), pod imenom The Gaffer
            fp_ = os.path.join(HERE, 'share', f)
            if os.path.isfile(fp_):
                raw_ = open(fp_, 'rb').read()
                if f != 'README.txt':
                    raw_ = raw_.replace(b'Career.bat', b'The Gaffer.bat').replace(b'Karijera 26', b'The Gaffer')
                wr(TOP + arc, raw_)
                n += 1
        for f in os.listdir(os.path.join(HERE, 'lib')):
            if f.endswith(('.py', '.json')):
                put(os.path.join(HERE, 'lib', f), TOP + 'lib/' + f)
        for root_, dirs_, files_ in os.walk(os.path.join(HERE, 'static')):
            rel = os.path.relpath(root_, os.path.join(HERE, 'static'))
            if rel.split(os.sep)[0] in ('faces',):
                continue
            for f in files_:
                if rel == '.' and f == 'lab.html':
                    continue
                put(os.path.join(root_, f), TOP + 'static/' + (f if rel == '.' else rel.replace(os.sep, '/') + '/' + f))
        for f in PKG_DATA:
            put(os.path.join(HERE, 'data', f), TOP + 'data/' + f)
        if real_moves_ready():   # pc379: stvarni transferi u paketu, korisnik ne ovisi o Wikipediji pri prvom pokretanju
            put(REALMOVES_FILE, TOP + 'data/realmoves.json')
        for dn in PKG_DATA_DIRS:
            for root_, dirs_, files_ in os.walk(os.path.join(HERE, 'data', dn)):
                for f in files_:
                    rel = os.path.relpath(os.path.join(root_, f), os.path.join(HERE, 'data'))
                    put(os.path.join(root_, f), TOP + 'data/' + rel.replace(os.sep, '/'))
        for m in SIDER_MODS:
            # pc188: izvor je mapa lua/ appa (najnovija verzija); instalirani Sider modul samo ako nje nema (prije je ulazio stari 1.4)
            src = os.path.join(HERE, 'lua', m)
            if not os.path.isfile(src) and sdir:
                src = os.path.join(sdir, 'modules', m)
            put(src, TOP + 'lua/' + m)
        if opt.get('tools', False):   # pc361: exe alati ne idu u paket (antivirusi ih prijavljuju), app ih ne treba
            for f in ('decrypter21.exe', 'encrypter21.exe'):
                tp = os.path.join(HERE, 'tools', f)
                if not os.path.isfile(tp):
                    tp = os.path.join(os.path.dirname(CFG.get('decrypter') or ''), f)
                if os.path.isfile(tp):
                    put(tp, TOP + 'tools/' + f)
                else:
                    notes.append(L_('%s not found, not in the package' % f, '%s not found, not in the package' % f))
        if opt.get('regen', True):
            # regen fix (mataodzanata (FL Mod Studio), uz njegovo dopustenje): iz Sidera ovog racunala ili iz addons uz app
            rs = _regen_src()
            mdirs = [os.path.join(rs, 'modules')] if rs else []
            if sdir:
                mdirs.append(os.path.join(sdir, 'modules'))
            got = 0
            for f in REGEN_MODS + REGEN_OPT:
                fp = next((os.path.join(d_, f) for d_ in mdirs if os.path.isfile(os.path.join(d_, f))), None)
                if fp:
                    put(fp, TOP + 'addons/regenfix/modules/' + f)
                    got += 1
            cdirs = ([os.path.join(rs, 'livecpk', REGEN_CPK)] if rs else []) + ([os.path.join(sdir, 'livecpk', REGEN_CPK)] if sdir else [])
            cd_ = next((d_ for d_ in cdirs if os.path.isdir(d_)), None)
            if cd_:
                for root_, dirs_, files_ in os.walk(cd_):
                    for f in files_:
                        rel = os.path.relpath(os.path.join(root_, f), cd_).replace(os.sep, '/')
                        put(os.path.join(root_, f), TOP + 'addons/regenfix/livecpk/' + REGEN_CPK + '/' + rel)
            if got >= 2:
                wr(TOP + 'addons/regenfix/README.txt', ('Regen fix for Football Life 26 by mataodzanata (FL Mod Studio) (included with his permission).\r\n'
                   'Regens become new players: new name, new potential, and a generic or face-pack face instead of the retired player\'s.\r\n'
                   'Install it from the app: Setup > Regen fix > Install. The app copies the files into Sider\\modules and livecpk and adds the lines to sider.ini (with a backup).\r\n'
                   'All credit to mataodzanata (FL Mod Studio).\r\n').encode('utf-8'))
            else:
                notes.append(L_('Regen fix nije nađen u Sideru, nije u paketu.', 'Regen fix not found in Sider, not in the package.'))
        # pc195: moduli Michele & Claude (uz njihovo dopustenje)
        _ms = os.path.join(HERE, 'addons', 'michele')
        if os.path.isdir(_ms):
            for root_, dirs_, files_ in os.walk(_ms):
                for f in files_:
                    if '.bak' in f:
                        continue
                    rel = os.path.relpath(os.path.join(root_, f), _ms).replace(os.sep, '/')
                    put(os.path.join(root_, f), TOP + 'addons/michele/' + rel)
        if opt.get('python', True):
            pz, perr = _portable_python()
            if pz:
                with zipfile.ZipFile(pz) as pzf:
                    for nm in pzf.namelist():
                        if nm.endswith('/'):
                            continue
                        wr(TOP + 'python/' + nm, pzf.read(nm))
                        n += 1
            else:
                notes.append(L_('Portable Python could not be downloaded (%s); The Gaffer.bat will offer the user an install.' % perr, 'Portable Python could not be downloaded (%s); The Gaffer.bat will offer to install it.' % perr))
    mb = os.path.getsize(zp) / 1e6
    return dict(ok=True, path=zp, files=n, size=os.path.getsize(zp), notes=notes,
                message=L_('Package is ready: %s (%d files, %.1f MB).' % (zp, n, mb), 'Package ready: %s (%d files, %.1f MB).' % (zp, n, mb)) + (' ' + ' '.join(notes) if notes else ''))



def _edit_data():
    """Dekriptirana EDIT datoteka (klubovi s ID-evima): CFG['edit_dat'] ili dekripcija EDIT00000000 iz mape saveova."""
    p = CFG.get('edit_dat')
    if p and os.path.exists(p):
        return open(p, 'rb').read(), p
    src = os.path.join(CFG.get('save_dir') or '', 'EDIT00000000')
    if not os.path.isfile(src):
        return None, None
    d = os.path.join(CFG['work'], 'cache', 'EDIT_%d' % int(os.path.getmtime(src)))
    if not os.path.exists(os.path.join(d, 'data.dat')):
        decrypt(src, d)
    return open(os.path.join(d, 'data.dat'), 'rb').read(), src



def official_comp_name(tid, app_name):
    """Pravo (sluzbeno) ime natjecanja za prikaz: COMP_WIKI po ID-u ili LEAGUE_WIKI po imenu iz appa."""
    if app_name == 'Ostale europske lige':
        return L_('Ostale europske lige (FL)', 'Other European leagues (FL)')
    # COMP_WIKI is keyed by FL26 competition ids; FC 27 reuses those numbers for
    # different competitions, so only the name lookup is safe here.
    return LEAGUE_WIKI.get(app_name or '') or app_name


def _lc_norm():
    """pc411: LEAGUE_CLUBS s normaliziranim imenima (bez FC/AC/..., dijakritika), da se prepoznaju i baze s drugacijim imenima
    klubova ("Bayern München" / "FC Bayern München")."""
    if 'lcn' not in _GL:
        _GL['lcn'] = {ln: {_norm_club(c) for c in lc} for ln, lc in LEAGUE_CLUBS.items()}
    return _GL['lcn']


def _ov(cs, lc):
    """Koliko se dva skupa (normaliziranih) klubova poklapaju; djelomicno poklapanje imena ('bayern munchen' u 'fc bayern munchen')."""
    n = 0
    for c in cs:
        if c in lc or any(len(c) >= 5 and (c in x or x in c) for x in lc if len(x) >= 5):
            n += 1
    return n


TIER1_BY_LAND = {}


def guess_comp(tid, clubs, kind, maxg):
    """-> (ime, izvor, opis). izvor: 'app' (app ga vec zna), 'clubs' (prepoznat po klubovima), 'guess' (procjena po drzavi/konfederaciji), None."""
    try:
        saved = json.load(open(_dbf('comps.json'), encoding='utf-8'))
    except Exception:
        saved = {}
    cs = {_norm_club(c) for c in clubs}
    LCN = _lc_norm()

    def by_clubs():
        best = None
        for ln, lc in LCN.items():
            inter = _ov(cs, lc)
            if inter >= 0.6 * len(cs) and inter >= 0.6 * len(lc) and (best is None or inter > best[1]):
                best = (ln, inter)
        return best[0] if best else None

    nm = (saved.get(str(tid)) or {}).get('name')
    if nm:
        lc = LCN.get(nm)
        if lc and kind == 'league' and _ov(cs, lc) < 0.2 * min(len(cs), len(lc)):
            # pc411: spremljeno ime poznate lige, a klubovi su potpuno drugi (ime spremljeno iz krivog zadanog imena po broju)
            ln = by_clubs()
            if ln:
                return ln, 'clubs', None
            return nm, 'guess', L_('the clubs in it do not match %s, check the name' % nm, 'the clubs in it do not match %s, check the name' % nm)
        return nm, 'app', None   # ime koje je korisnik upisao (ili potvrdio) kod uvoza
    nm = COMP_LEAGUES.get(tid) or (COMP_GROUPS.get(tid) or [None])[0]
    if nm:
        # pc411: zadano ime po broju natjecanja vrijedi samo ako klubovi odgovaraju. S prosirenom bazom (FL Mod Studio) brojevi
        # su drugaciji: broj 'Bundeslige' je imao francuske klubove (pc11gamer, 2.11.), pa ga app nije smio zvati Bundesliga
        lc = LCN.get(nm)
        if not lc or kind != 'league' or _ov(cs, lc) >= 0.4 * min(len(cs), len(lc)):
            return nm, 'app', None
    ln = by_clubs()
    if ln:
        return ln, 'clubs', None
    land, conf = {}, {}
    known = 0
    for c in cs:
        for ln, lc in LCN.items():
            if ln in LEAGUE_LAND and _ov({c}, lc):
                hr, en, cf = LEAGUE_LAND[ln]
                known += 1
                if en:
                    land[en] = land.get(en, 0) + 1
                conf[cf] = conf.get(cf, 0) + 1
                break
    if known < 4:
        return None, None, None
    top_land = max(land.items(), key=lambda kv: kv[1]) if land else (None, 0)
    top_conf = max(conf.items(), key=lambda kv: kv[1])
    if top_land[0] and top_land[1] >= 0.7 * known:
        if kind == 'league':
            # pc411: liga (svatko sa svakim) s klubovima jedne drzave je liga te drzave, ne kup
            return None, 'guess', L_('all clubs are from %s: type the name of this league' % top_land[0], 'all clubs are from %s: type the name of this league' % top_land[0])
        return CUP_BY_LAND.get(top_land[0], top_land[0] + ' Cup'), 'guess', L_('all clubs are from the same country (%s), so it is probably a national cup' % top_land[0],
                                                                              'all clubs are from one country (%s), so it is probably the national cup' % top_land[0])
    if top_conf[1] >= 0.5 * known:
        if top_conf[0] == 'UEFA' and maxg <= 2:
            return 'UEFA qualifiers', 'guess', L_('European clubs playing two-legged ties (qualifiers / play-offs)', 'European clubs playing two matches each (qualifiers / play-offs)')
        return CONF_CUP[top_conf[0]], 'guess', L_('clubs from several countries of the same confederation (%s)' % top_conf[0], 'clubs from several countries of one confederation (%s)' % top_conf[0])
    return None, None, None

def dbimport_preview(slot):
    # The FC 27 database is generated at build time by tools/import_fc27.mjs.
    # A PES F7 dump has different player ids and a different attribute scale, so
    # importing one here would corrupt it. Rebuild with the importer instead.
    return dict(ok=False, why=L_('FC 27 baza se gradi sa tools/import_fc27.mjs; PES F7 dump se ne moze uvesti u nju.',
                                 'The FC 27 database is built with tools/import_fc27.mjs; a PES F7 dump cannot be imported into it.'))


def _fmt_mtime(p):
    try:
        return time.strftime('%d.%m.%Y %H:%M', time.localtime(os.path.getmtime(p)))
    except Exception:
        return ''


def L_(hr, en):
    return hr if (CFG.get('lang') or 'hr') == 'hr' else en


BAT_TPL = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set ARC={ARC}
set DEST={DEST}
set RAR=
if exist "C:\\Program Files\\WinRAR\\UnRAR.exe" set RAR=C:\\Program Files\\WinRAR\\UnRAR.exe
if "%RAR%"=="" if exist "C:\\Program Files\\WinRAR\\WinRAR.exe" set RAR=C:\\Program Files\\WinRAR\\WinRAR.exe
if "%RAR%"=="" if exist "C:\\Program Files (x86)\\WinRAR\\UnRAR.exe" set RAR=C:\\Program Files (x86)\\WinRAR\\UnRAR.exe
if "%RAR%"=="" (echo WinRAR not found. & pause & exit /b)
if not exist "%ARC%" (echo Archive missing: %ARC% & pause & exit /b)
if not exist "%DEST%" mkdir "%DEST%"
echo Extracting new FM faces (do not close this window)...
"%RAR%" x -ep -o- -y "-n@%~dp0face_list_novo.txt" "%ARC%" "%DEST%\\"
echo DONE.
pause
"""


def dbimport_apply(body):
    return dict(ok=False, message='The FC 27 database is built with tools/import_fc27.mjs, not imported from a PES dump.')


def fm_face(pid):
    """FM cutout lice (static/faces/face_<UID>.png) ako imamo par PES id -> FM UID i datoteku."""
    if 'map' not in _FACE:
        try:
            _FACE['map'] = json.load(open(os.path.join(HERE, 'data', 'face_map.json'), encoding='utf-8'))
        except Exception:
            _FACE['map'] = {}
    uid = _FACE['map'].get(str(pid))
    if not uid:
        return None
    fp = os.path.join(HERE, 'static', 'faces', 'face_%s.png' % uid)
    try:
        with open(fp, 'rb') as f:
            return f.read()
    except Exception:
        return None


# ---------------------------------------------------------------- pc363: mobitel / tablet preko kucne mreze
# Drugi server na 0.0.0.0:(port+1) samo kad je ukljuceno u Setupu. Glavni ostaje na 127.0.0.1 (PC). Pristup s drugih
# uredjaja uz PIN (kolacic); admin radnje (Setup, paket, gasenje) samo s PC-a.
LAN_GET_BLOCK = ('/api/setup/browse', '/api/setup/detect', '/api/show', '/api/dev/', '/api/lan')
LAN_POST_BLOCK = ('/api/setup/save', '/api/setup/pick', '/api/setup/sider', '/api/setup/michele', '/api/setup/injuries',
                  '/api/setup/regen', '/api/setup/check', '/api/package', '/api/quit', '/api/lan/set',
                  '/api/backups/keep', '/api/backups/clean', '/api/dev/',
                  '/api/pes17/setup/savefolder')
_LAN = dict(srv=None, port=None, err=None, fails={})


def _cfg_update(**kv):
    p_ = os.path.join(HERE, 'config.json')
    try:
        cur_ = json.load(open(p_, encoding='utf-8'))
    except Exception:
        cur_ = {}
    cur_.update(kv)
    _jdump(cur_, p_, ensure_ascii=False, indent=1)
    CFG.update(kv)


def _lan_token():
    import hmac
    sec = CFG.get('lan_secret') or ''
    return hmac.new(sec.encode(), ('pin:%s' % CFG.get('lan_pin', '')).encode(), hashlib.sha256).hexdigest()[:40] if sec else ''


def _lan_ips():
    ips = []
    try:
        s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_.connect(('10.255.255.255', 1))   # ne salje nista, samo odabere mreznu karticu
        ips.append(s_.getsockname()[0])
        s_.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    priv = lambda ip: ip.startswith(('192.168.', '10.')) or (ip.startswith('172.') and 16 <= int(ip.split('.')[1]) <= 31)
    return [ip for ip in ips if priv(ip) and not ip.startswith('127.')] or [ip for ip in ips if not ip.startswith('127.')]


def lan_start():
    if _LAN['srv']:
        return True
    port = (CFG.get('_port') or 8766) + 1
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
        threading.Thread(target=lambda: (srv_.shutdown(), srv_.server_close()), daemon=True).start()


def lan_view():
    on = bool(CFG.get('lan_on')) and bool(_LAN['srv'])
    port = _LAN.get('port') or (CFG.get('_port') or 8766) + 1
    urls = ['http://%s:%d/' % (ip, port) for ip in _lan_ips()]
    qr = None
    if on and urls:
        try:
            import qrmini
            qr = qrmini.svg(urls[0], scale=5)
        except Exception as ex:
            print('[lan] qr:', ex)
    return dict(ok=True, on=on, want=bool(CFG.get('lan_on')), port=port, pin=CFG.get('lan_pin') or '', urls=urls, qr=qr, err=_LAN.get('err'))


def lan_set(body):
    import secrets
    kv = {}
    if body.get('new_pin') or not CFG.get('lan_pin'):
        kv['lan_pin'] = '%06d' % secrets.randbelow(1000000)
        kv['lan_secret'] = secrets.token_hex(16)   # novi PIN odjavi sve uredjaje
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


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if len(a) > 1 and str(a[1]) not in ('200', '204') and not (str(a[1]) == '404' and '/api/wiki/' in str(a[0])):
            print('HTTP', *a)

    def _remote(self):
        try:
            return self.client_address[0] not in ('127.0.0.1', '::1', '::ffff:127.0.0.1')
        except Exception:
            return True

    def _lan_guard(self, post=False):
        """pc363: zahtjev s drugog uredjaja: True = smije dalje. Inace je odgovor vec poslan (PIN stranica / 401 / 403)."""
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
        # pc371: mobitel/tablet preko Wi-Fija: veliki tekstualni odgovori (stranica 2,8 MB, popis igraca 4-5 MB) idu sazeti (~6x manje)
        try:
            if (len(data) > 16384 and (ctype.startswith('text') or ctype in ('application/json', 'image/svg+xml')) and self._remote()
                    and 'gzip' in (self.headers.get('Accept-Encoding') or '')):
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
        # pc369: slike (lica, grbovi, logotipi, dresovi) preglednik smije cuvati sat vremena; prije se sve skidalo iznova
        # pri svakom osvjezavanju popisa (na mobitelu preko Wi-Fija i do 4-5 s za Inbox)
        self.send_header('Cache-Control', 'private, max-age=3600' if (code == 200 and ctype.startswith('image/') and not any(k in self.path for k in ('/api/kitimg', '/api/coach/custom', '/api/wiki/img', '/api/wiki/photo', 'spon', '/api/kit?'))) else 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if not self._lan_guard():
            return
        try:
            if u.path == '/api/lan':
                return self.send(200, lan_view())
            if u.path == '/api/dbcheck':
                return self.send(200, db_check(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/savefolders':
                return self.send(200, save_folders())
            if u.path == '/api/menustate':   # pc392: lagano stanje za gumb 'I am on the main menu' (bez ucitavanja savea)
                return self.send(200, dict(ok=True, game_running=game_running(), menu_ok=menu_ok(), auto=_MEMST.get('state')))
            if u.path == '/api/pes17/info':
                _slot = parse_qs(u.query).get('slot', [''])[0]
                try:
                    return self.send(200, pes17_tools_info(_slot))
                except Exception as _ex:
                    import pes17_setup
                    return self.send(200, pes17_setup.unavailable(CFG, _slot, _ex, HERE))
            if u.path == '/api/pes17/mode':
                return self.send(200, dict(pes17=(_GAME['save'] == 'pes17'), game='fc27', only=False,
                                          offline=not bool(CFG.get('wiki_web', False))))
            # --- FC 27 database (read-only) ---------------------------------
            # Pure-stdlib reads of data/fc27, generated by tools/import_fc27.mjs.
            if u.path == '/api/fc27/status':
                return self.send(200, fc27db.summary())
            if u.path == '/api/fc27/attrs':
                # Schema for the engine: EA's 34 raw attributes plus the lossy
                # PES-25 projection the older algorithms still read.
                _m = fc27db.meta()
                return self.send(200, dict(ok=True, ea=fc27db.ea_ab(),
                                           pes=_m.get('ab', []), pesSource=_m.get('abSource', []),
                                           dropped=_m.get('pesProjectionDrops', []),
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
            if u.path == '/api/pes17/setup':
                import pes17_setup
                return self.send(200, pes17_setup.status(CFG, HERE))
            if u.path == '/api/pes17/offers':
                r = pes17_tools_info(parse_qs(u.query).get('slot', [''])[0])
                return self.send(200, dict(ok=True, offers=r['offers'], teams=r['teams']))
            if u.path == '/api/state':
                slot = parse_qs(u.query).get('slot', [''])[0]
                return self.send(200, state(slot))
            if u.path == '/api/teamsquad':
                q = parse_qs(u.query)
                return self.send(200, team_squad(q.get('slot', [''])[0], q.get('team', ['nation'])[0]))
            if u.path == '/api/dev/mix':
                q = parse_qs(u.query)
                slot = q.get('slot', [''])[0]
                parts = q.get('parts', [''])[0]
                nat = q.get('nat', [r'C:\pes_test\ml_work\restore\B_s_Dowmanom_prije_Valdimarssona\ML00000001'])[0]
                work = CFG['work']
                basedir = os.path.join(work, 'lab_base')
                natdir = os.path.join(work, 'lab_nat')
                if q.get('fresh', ['0'])[0] == '1' or not os.path.exists(basedir):
                    if os.path.exists(basedir):
                        shutil.rmtree(basedir)
                    decrypt(os.path.join(CFG['save_dir'], slot), basedir)
                if q.get('fresh', ['0'])[0] == '1' or not os.path.exists(natdir):
                    if os.path.exists(natdir):
                        shutil.rmtree(natdir)
                    decrypt(nat, natdir)
                def _m(sv):
                    sb = mlwrite.Save(basedir)
                    sn = mlwrite.Save(natdir)
                    if len(sb.d) != len(sv.d):
                        raise RuntimeError('database and slot are not the same size')
                    sv.d[:] = sb.d
                    eb = sb._chunks()[1]
                    en = sn._chunks()[1]
                    n = 0
                    import re as _re
                    rr = []
                    for kind, lo, hi in _re.findall(r'([htr]):(\d+)-(\d+)', parts):
                        lo, hi = int(lo), int(hi)
                        if kind == 'h':
                            sv.d[lo:hi] = sn.d[lo:hi]
                        elif kind == 't':
                            sv.d[eb + lo:eb + hi] = sn.d[en + lo:en + hi]
                        else:
                            rr.append((lo, hi))
                        n += hi - lo
                    if rr:
                        chunks, e_ = sv._chunks()
                        big = bytearray(b''.join(chunks))
                        nbig = b''.join(sn._chunks()[0])
                        for lo, hi in rr:
                            big[lo:hi] = nbig[lo:hi]
                        new_, pos_ = [], 0
                        for c in chunks:
                            new_.append(bytes(big[pos_:pos_ + len(c)]))
                            pos_ += len(c)
                        sv._rebuild(new_, e_)
                    return 'preslikano %d B' % n
                return self.send(200, _write_slot(slot, 'mix', _m))
            if u.path == '/api/dev/lab':
                q = parse_qs(u.query)
                slot = q.get('slot', [''])[0]
                pid = int(q.get('pid', ['178082'])[0])
                mask = int(q.get('mask', ['0'])[0], 16)
                info = {}
                def _f(sv):
                    offs, done = sv.lab_blank(pid, mask)
                    if int(q.get('rec', ['0'])[0], 16):
                        sv.lab_rec(pid, int(q.get('rec', ['0'])[0], 16))
                    info['offs'] = offs
                    return 'prazno %d od %d' % (len(done), len(offs))
                if q.get('dry', ['0'])[0] == '1':
                    sv = mlwrite.Save(os.path.join(CFG['work'], 'apply_dec'))
                    return self.send(200, dict(offs=sv.lab_offsets(pid)))
                r = _write_slot(slot, 'lab', _f)
                r['offs'] = info.get('offs')
                return self.send(200, r)
            if u.path == '/api/auto':
                return self.send(200, auto_status(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/history':
                q = parse_qs(u.query)
                se = q.get('season', [None])[0]
                return self.send(200, history_view(q.get('slot', [''])[0], int(se) if se else None, full=bool(q.get('full'))))
            if u.path == '/api/history/club':
                q = parse_qs(u.query)
                return self.send(200, history_club(q.get('slot', [''])[0], q.get('name', [''])[0]))
            if u.path == '/api/history/legends':
                return self.send(200, history_legends(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/history/h2h':
                q = parse_qs(u.query)
                return self.send(200, history_h2h(q.get('slot', [''])[0], q.get('opp', [''])[0]))
            if u.path == '/api/history/news':
                return self.send(200, history_news(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/history/player':
                q = parse_qs(u.query)
                return self.send(200, history_player(q.get('slot', [''])[0], int(q.get('pid', ['0'])[0])))
            if u.path == '/api/records':
                try:
                    return self.send(200, records_view(parse_qs(u.query).get('slot', [''])[0]))
                except Exception as ex:
                    return self.send(200, dict(error=str(ex)[:200], records=[], milestones=[], leaders=[]))
            if u.path == '/api/revalue':
                return self.send(200, revalue_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/gate':
                return self.send(200, gate_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/kitsp/files':
                return self.send(200, kitsp_files(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/kitsp/region':
                _q = parse_qs(u.query)
                return self.send(200, kitsp_region(_q.get('slot', [''])[0], _q.get('rel', [''])[0], _q.get('part', ['chest'])[0]))
            if u.path == '/api/stops':
                return self.send(200, stops_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/sponsor/custom':
                return self.send(200, dict(ok=True, items=_spon_custom()))
            if u.path == '/api/kitsp/logo':
                _q = parse_qs(u.query)
                _cu = re.sub(r'[^0-9a-f]', '', _q.get('custom', [''])[0])[:16]
                if _cu:
                    _fp = os.path.join(KS_LOGO_DIR, 'custom_%s.png' % _cu)
                    b = open(_fp, 'rb').read() if os.path.isfile(_fp) else None
                else:
                    b = kitsp_logo(int(_q.get('tid', ['0'])[0] or 0), _q.get('part', ['chest'])[0])
                return self.send(200, b, 'image/png') if b else self.send(404, b'', 'image/png')
            if u.path == '/api/sponsor':
                return self.send(200, sponsor_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/inbox/extra':
                return self.send(200, inbox_extra(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/invest':
                return self.send(200, invest_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/precon':
                return self.send(200, precon_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/finance':
                return self.send(200, finance_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/gate/report':
                return self.send(200, gate_report(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/board':
                return self.send(200, board_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/auto/history':
                return self.send(200, auto_history(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/ai/plan':
                q = parse_qs(u.query)
                return self.send(200, ai_plan(q.get('slot', [''])[0], float(q.get('scale', ['1'])[0]), int(q.get('seed', ['1'])[0])))
            if u.path == '/api/tactics/opp':
                return self.send(200, opp_squad(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/players':
                slot = parse_qs(u.query).get('slot', [''])[0]
                return self.send(200, players_data(slot))
            if u.path == '/api/youth/terms':
                _q = parse_qs(u.query)
                return self.send(200, youth_terms(_q.get('slot', [''])[0], int(_q.get('pid', ['0'])[0])))
            if u.path == '/api/youth':
                return self.send(200, youth_data(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/traits':
                T = traits_all()
                ids = [int(x) for x in parse_qs(u.query).get('ids', [''])[0].split(',') if x.strip().isdigit()]
                return self.send(200, {str(i): dict(sk=T[i][0], com=T[i][1]) for i in ids if i in T})
            if u.path == '/api/attrs':
                # atributi svih igraca za filtere u transferima: po igracu niz dvoznamenkastih vrijednosti (redoslijed = ab)
                return self.send(200, dict(ab=RATAB, p={str(k): ''.join('%02d' % max(0, min(99, int(x or 0))) for x in v[10]) for k, v in RAT.items() if len(v) > 10 and isinstance(v[10], list)}))
            if u.path == '/api/styles':
                return self.send(200, {str(k): v[5] for k, v in RAT.items() if len(v) > 5})
            if u.path == '/api/pdetail':
                return self.send(200, player_detail(int(parse_qs(u.query).get('id', ['0'])[0])))
            if u.path == '/api/poll':
                slot = parse_qs(u.query).get('slot', [''])[0]
                if DEV:
                    mt, sz = 0, 0
                else:
                    p = os.path.join(CFG['save_dir'], slot)
                    mt, sz = (int(os.path.getmtime(p)), os.path.getsize(p)) if slot.startswith('ML0') and os.path.isfile(p) else (0, 0)
                return self.send(200, dict(mtime=mt, size=sz, game_running=game_running(), menu_ok=menu_ok(), rev=_REV[0], by=_REV[1]))
            if u.path == '/api/deals':
                return self.send(200, deals_info(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/table/ghosts':
                return self.send(200, table_ghosts(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/morale/newjob':
                q_ = parse_qs(u.query)
                try:
                    return self.send(200, newjob_morale(q_.get('slot', [''])[0], q_.get('force', [''])[0] == '1'))
                except Exception as ex:
                    return self.send(200, dict(ok=False, queued=0, why=str(ex)[:200]))
            if u.path == '/api/squad/tailcheck':
                return self.send(200, squad_tail_check(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/news/world':
                return self.send(200, news_world(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/comps':
                return self.send(200, league_places_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/awards':
                _q = parse_qs(u.query)
                return self.send(200, awards_view(_q.get('slot', [''])[0], _q.get('season', [None])[0]))
            if u.path == '/api/stats':
                q = parse_qs(u.query)
                return self.send(200, stats_view(q.get('slot', [''])[0], q.get('season', [None])[0], q.get('tid', [None])[0], q.get('club', [None])[0]))
            if u.path == '/api/club/matches':
                q = parse_qs(u.query)
                sl = q.get('slot', [''])[0]
                se = q.get('season', [None])[0]
                return self.send(200, club_matches(sl, mlwrite.Save(slot_folder(sl)), int(q.get('club', ['0'])[0]), int(se) if se else None, None, True))
            if u.path == '/api/scout/deep':
                try:
                    return self.send(200, scout_deep(parse_qs(u.query).get('slot', [''])[0]))
                except Exception as e:
                    return self.send(200, dict(error=str(e)))
            if u.path == '/api/next':
                return self.send(200, next_match(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/club/lineup':
                q = parse_qs(u.query)
                return self.send(200, club_lineup_info(q.get('slot', [''])[0], int(q.get('idx', ['0'])[0])))
            if u.path == '/api/club/formations':
                return self.send(200, club_formations(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/contract/view':
                return self.send(200, contract_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/version':
                return self.send(200, dict(version=APP_VERSION, built=APP_BUILT, app='thegaffer', code=_code_stamp(), pid=os.getpid()))
            if u.path == '/api/i18n':
                # pc317: prijevod sucelja (data/i18n/<lang>.json, engleski tekst -> prijevod); prazno = engleski
                lg = re.sub(r'[^a-z]', '', parse_qs(u.query).get('lang', [''])[0])[:5]
                try:
                    d = json.load(open(os.path.join(HERE, 'data', 'i18n', lg + '.json'), encoding='utf-8')) if lg else {}
                except Exception:
                    d = {}
                return self.send(200, dict(lang=lg, strings={k: v for k, v in d.items() if isinstance(v, str) and v.strip()}))
            if u.path == '/api/encrypter':
                return self.send(200, encrypter_status())
            if u.path == '/api/show':
                # pc186: drugo pokretanje precaca samo otvori prozor ovog appa (umjesto gasenja procesa na portu)
                threading.Thread(target=open_app, args=('http://127.0.0.1:%d/' % self.server.server_address[1],), daemon=True).start()
                return self.send(200, dict(ok=True, version=APP_VERSION, app='thegaffer'))
            if u.path == '/api/setup/status':
                CFG['lang'] = parse_qs(u.query).get('lang', ['hr'])[0]
                return self.send(200, setup_status())
            if u.path == '/api/setup/browse':
                q_ = parse_qs(u.query)
                return self.send(200, setup_browse(q_.get('path', [''])[0], q_.get('files', ['0'])[0] == '1'))
            if u.path == '/api/setup/detect':
                return self.send(200, setup_detect())
            if u.path == '/api/dbimport/preview':
                CFG['lang'] = parse_qs(u.query).get('lang', ['hr'])[0]
                return self.send(200, dbimport_preview(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/formnews':
                return self.send(200, form_news(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/assistant':
                return self.send(200, assistant_cached(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/form':
                return self.send(200, form_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/debrief':
                return self.send(200, debrief_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/totw':
                q_ = parse_qs(u.query)
                _award_grants_safe(q_.get('slot', [''])[0])
                return self.send(200, totw_view(q_.get('slot', [''])[0], q_.get('tid', [None])[0], q_.get('week', [None])[0]))
            if u.path == '/api/ballon':
                q_ = parse_qs(u.query)
                _award_grants_safe(q_.get('slot', [''])[0])
                return self.send(200, ballon_view(q_.get('slot', [''])[0], q_.get('season', [None])[0]))
            if u.path == '/api/stories':
                return self.send(200, stories_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/honours':
                return self.send(200, honours_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/realhonours':
                r_, c_, k_ = _real_honours(parse_qs(u.query).get('club', [''])[0])
                return self.send(200, dict(real=r_, cutoff=c_, country=k_))
            if u.path == '/api/journal':
                return self.send(200, journal_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/career':
                q = parse_qs(u.query)
                return self.send(200, career_view(q.get('slot', [''])[0], int(q.get('pid', ['0'])[0])))
            if u.path == '/api/story':
                return self.send(200, story_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/talks':
                return self.send(200, talks_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/press':
                return self.send(200, press_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/sell/view':
                return self.send(200, sell_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/wiki':
                q = parse_qs(u.query)
                return self.send(200, wiki_info(q.get('slot', [''])[0], int(q.get('pid', ['0'])[0])))
            if u.path == '/api/backups':
                return self.send(200, backups_info())
            if u.path == '/api/firststeps':
                return self.send(200, first_steps(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/mods/check':
                return self.send(200, mods_check())
            if u.path == '/api/growth/due':
                return self.send(200, growth_due(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/growth/player':
                q = parse_qs(u.query)
                return self.send(200, growth_player(q.get('slot', [''])[0], int(q.get('pid', ['0'])[0])))
            if u.path == '/api/growth':
                q = parse_qs(u.query)
                return self.send(200, growth_state(q.get('slot', [''])[0]))
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
            if u.path == '/api/kit':
                try:
                    return self.send(200, venue_kit_info(parse_qs(u.query).get('club', [''])[0]))
                except Exception as e:
                    return self.send(200, dict(kits=[], error=str(e)[:120]))
            if u.path == '/api/scene':
                b = scene_img(parse_qs(u.query).get('k', [''])[0])
                if b is None:
                    return self.send(404, b'', 'image/jpeg')
                return self.send(200, b, 'image/jpeg')
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
            if u.path == '/api/kitimg':
                _q = parse_qs(u.query)
                try:
                    b = kit_img(_q.get('club', [''])[0], int(_q.get('k', ['1'])[0]))
                except Exception:
                    b = None
                if b is None:
                    return self.send(404, b'', 'image/png')
                return self.send(200, b, 'image/png')
            if u.path == '/api/coach/custom':
                b = coach_custom_img(parse_qs(u.query).get('career', [''])[0])
                if b is None:
                    return self.send(404, b'', 'image/jpeg')
                return self.send(200, b, 'image/jpeg')
            if u.path == '/api/coach/img':
                try:
                    _i = int(parse_qs(u.query).get('id', ['0'])[0])
                    b = coach_img(_i)
                except Exception:
                    b = None
                if b is None:
                    return self.send(404, b'', 'image/png')
                return self.send(200, b, 'image/png')
            if u.path == '/api/dumpstatus':
                return self.send(200, dump_status(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/calendar':
                return self.send(200, calendar_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/intro':
                return self.send(200, intro_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/job/intro':
                return self.send(200, job_intro(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/player/terms':
                _q = parse_qs(u.query)
                return self.send(200, player_terms_view(_q.get('slot', [''])[0], _q.get('pid', ['0'])[0]))
            if u.path == '/api/coach':
                _q = parse_qs(u.query)
                return self.send(200, coach_info(_q.get('slot', [''])[0], _q.get('club', [''])[0] or None))
            if u.path == '/api/coach/list':
                return self.send(200, coach_list(parse_qs(u.query).get('q', [''])[0]))
            if u.path == '/api/wiki/img':
                _pq = int(parse_qs(u.query).get('pid', ['0'])[0])
                _old = parse_qs(u.query).get('old', [''])[0] == '1'   # pc245: slika umirovljenog igraca (Hall of Fame) iako je ID sad regen
                if _pq in _REGEN and not _old:
                    return self.send(404, b'', 'image/png')   # regen: sve slike (FM, igra, Wikipedia) pripadaju starom igracu
                if _old and _pq in _REGEN:
                    _REGEN.discard(_pq)
                    try:
                        _fb = game_face(_pq) or fm_face(_pq)
                    finally:
                        _REGEN.add(_pq)
                else:
                    _fb = game_face(_pq) or fm_face(_pq)   # pc284: lice iz igre ima prednost (imaju ga svi), FM lice je rezerva
                if _fb:
                    return self.send(200, _fb, _img_mime(_fb))
            if u.path == '/api/wiki/img':
                b = wiki_img(int(parse_qs(u.query).get('pid', ['0'])[0]))
                if b is None:
                    return self.send(404, b'', 'image/jpeg')
                return self.send(200, b, 'image/jpeg')
            if u.path == '/api/wiki/photo':
                _pp = int((parse_qs(u.query).get('pid', ['0'])[0] or '0')
                          if (parse_qs(u.query).get('pid', ['0'])[0] or '0').lstrip('-').isdigit() else 0)
                b = wiki_photo(_pp)
                if b is None and _GAME['save'] == 'pes17':
                    b = game_face(_pp)
                if b is None:
                    return self.send(404, b'', 'image/jpeg')
                return self.send(200, b, _img_mime(b))
            if u.path == '/api/form':
                return self.send(200, form_news(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/interest':
                q = parse_qs(u.query)
                return self.send(200, interest_view(q.get('slot', [''])[0], int(q.get('pid', ['0'])[0])))
            if u.path == '/api/loan/options':
                return self.send(200, loan_options(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/events':
                return self.send(200, events_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/requests':
                return self.send(200, player_requests(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/tlist/world':
                return self.send(200, tlist_world(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/scouting/reports':
                return self.send(200, scouting_reports(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/scouting':
                return self.send(200, scouting_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/freeagents':
                qq = parse_qs(u.query)
                g = lambda k, dflt='': qq.get(k, [dflt])[0]
                return self.send(200, freeagents_view(g('slot'), g('q'), g('pos'), int(g('min', '0') or 0), int(g('maxage', '0') or 0), g('nat'), int(g('lim', '120') or 120)))
            if u.path == '/api/tlist':
                return self.send(200, tlist_view(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/neg/list':
                return self.send(200, neg_list(parse_qs(u.query).get('slot', [''])[0]))
            if u.path.startswith('/api/world/'):
                q = parse_qs(u.query)
                sl = q.get('slot', [''])[0]
                if u.path == '/api/world/feed':
                    return self.send(200, world_feed(sl, q.get('limit', ['200'])[0], q.get('kind', [''])[0] or None, q.get('season', [''])[0] or None))
                if u.path == '/api/world/player':
                    return self.send(200, world_player(sl, q.get('id', ['0'])[0]))
                if u.path == '/api/world/club':
                    return self.send(200, world_club(sl, q.get('name', [''])[0]))
                if u.path == '/api/world/season':
                    return self.send(200, world_season(sl, q.get('season', [''])[0] or None))
            if u.path == '/api/savecheck/ops':
                return self.send(200, save_ops_check(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/savecheck':
                return self.send(200, save_check())
            if u.path == '/api/slots':
                return self.send(200, list_slots())
            if u.path == '/favicon.ico':
                return self.send(204, b'', 'image/x-icon')
            name = 'index.html' if u.path in ('/', '') else u.path.lstrip('/').replace('\\', '/')
            if '..' in name.split('/') or name.startswith('/'):
                return self.send(404, {'error': 'nema'})
            p = os.path.join(HERE, 'static', *name.split('/'))
            if not os.path.isfile(p):
                print('404:', u.path, '->', p)
                return self.send(404, {'error': 'missing: ' + u.path})
            ct = {'html': 'text/html', 'css': 'text/css', 'js': 'text/javascript', 'svg': 'image/svg+xml', 'png': 'image/png', 'jpg': 'image/jpeg',
                  'jpeg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif', 'mp3': 'audio/mpeg', 'mp4': 'video/mp4'}.get(p.rsplit('.', 1)[-1].lower(), 'application/octet-stream')
            return self.send(200, open(p, 'rb').read(), ct)
        except Exception as e:
            return self.send(500, {'error': str(e)})

    def do_POST(self):
        if not self._lan_guard(post=True):
            return
        try:
            n = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(n) or b'{}')
            if self.path == '/api/lan/login':
                return self._lan_login(body)
            if self.path == '/api/lan/set':
                return self.send(200, lan_set(body))
            if self.path == '/api/pes17/setup/savefolder':
                import pes17_setup
                try:
                    _sd = pes17_setup.validate_save_dir(body.get('save_dir'))
                except ValueError as _ex:
                    return self.send(400, dict(ok=False, error=str(_ex)))
                _kw = dict(save_dir=_sd)
                if pes17_setup.needs_game_discovery(CFG.get('pes_exe')):
                    _exe = pes17_setup.autodetect_exe(_sd)
                    if _exe:
                        _kw['pes_exe'] = _exe
                _cfg_update(**_kw)
                _GAME['save'] = 'pes17'
                try:
                    pes17.ensure_teamids(CFG, os.path.join(HERE, 'data', 'pes17'), force=True)
                except Exception:
                    pass
                _clear_face_caches()
                return self.send(200, pes17_setup.status(CFG, HERE))
            if self.path == '/api/pes17/write':
                lc = body.get('layout', True)
                if lc not in (True, False, 'auto', 'report'):
                    lc = True
                return self.send(200, pes17_tools_apply(body.get('slot'),
                                                        body.get('ops') or [],
                                                        bool(body.get('dry')),
                                                        lc))
            if self.path not in ('/api/clientlog',):
                _WRITES[0] += 1   # pc310: svaki upis ponisti kesirane poglede
                if not self.path.startswith(('/api/setup', '/api/support', '/api/wiki/prefetch')):
                    # pc413: drugi preglednici (mobitel preko LAN-a) vide da se nesto promijenilo i osvjeze se
                    _REV[0] += 1
                    _REV[1] = (self.headers.get('X-Gaffer-Client') or '')[:40]
            if self.path == '/api/clientlog':
                return self.send(200, client_log(body))
            if self.path == '/api/setup/check':
                CFG['lang'] = body.get('lang') or CFG.get('lang', 'hr')
                return self.send(200, setup_check(body.get('key'), body.get('value')))
            if self.path == '/api/setup/pick':
                return self.send(200, setup_pick(body.get('kind'), body.get('start')))
            if self.path == '/api/support/pack':
                return self.send(200, support_pack(body.get('slot', ''), body.get('note', '')[:4000], body.get('page', '')[:60]))
            if self.path == '/api/setup/seen':
                # Setup se sam otvara samo pri prvom pokretanju (oznaka u mapi appa, ne u pregledniku)
                os.makedirs(os.path.join(HERE, 'data'), exist_ok=True)
                open(os.path.join(HERE, 'data', '.setup_seen'), 'w').write(time.strftime('%Y-%m-%d %H:%M:%S'))
                return self.send(200, dict(ok=True))
            if self.path == '/api/setup/save':
                CFG['lang'] = body.get('lang') or 'hr'
                return self.send(200, setup_save(body))
            if self.path == '/api/setup/sider':
                CFG['lang'] = body.get('lang') or 'hr'
                return self.send(200, _with_sider_access(setup_install_sider)())
            if self.path == '/api/table/fix':
                return self.send(200, table_fix(body))
            if self.path == '/api/squad/tailfix':
                return self.send(200, squad_tail_fix(body))
            if self.path == '/api/revalue/apply':
                return self.send(200, revalue_apply(body))
            if self.path == '/api/budgetset':
                return self.send(200, budget_settings_set(body))
            if self.path == '/api/stop/add':
                return self.send(200, stop_add(body))
            if self.path == '/api/stop/remove':
                return self.send(200, stop_remove(body))
            if self.path == '/api/sponsor/end':
                return self.send(200, sponsor_end(body))
            if self.path == '/api/sponsor/custom/add':
                return self.send(200, spon_custom_add(body))
            if self.path == '/api/sponsor/custom/del':
                return self.send(200, spon_custom_del(body))
            if self.path == '/api/kitsp/apply':
                return self.send(200, kitsp_apply(body))
            if self.path == '/api/kitsp/restore':
                return self.send(200, kitsp_restore(body))
            if self.path == '/api/sponsor/sign':
                return self.send(200, sponsor_sign(body))
            if self.path == '/api/invest/buy':
                return self.send(200, invest_buy(body))
            if self.path == '/api/invest/event':
                return self.send(200, invest_event(body))
            if self.path == '/api/precon/complete':
                return self.send(200, precon_complete(body))
            if self.path == '/api/precon/cancel':
                return self.send(200, precon_cancel(body))
            if self.path == '/api/board/collect':
                return self.send(200, board_money_collect(body.get('slot', '')))
            if self.path == '/api/gate/collect':
                return self.send(200, gate_collect(body))
            if self.path == '/api/agent/deadline':
                return self.send(200, agent_deadline(body))
            if self.path == '/api/setup/michele':
                return self.send(200, _with_sider_access(lambda: setup_install_michele(body))())
            if self.path == '/api/setup/injuries':
                return self.send(200, _with_sider_access(lambda: setup_injuries(body))())
            if self.path == '/api/setup/regen':
                CFG['lang'] = body.get('lang') or 'hr'
                return self.send(200, _with_sider_access(setup_install_regen)())
            if self.path == '/api/package':
                CFG['lang'] = body.get('lang') or 'hr'
                if not _is_owner():
                    return self.send(403, dict(error='Sharing is only available to the app owner.'))
                return self.send(200, make_package(body))
            if self.path == '/api/dbimport/apply':
                CFG['lang'] = body.get('lang') or 'hr'
                return self.send(200, dbimport_apply(body))
            if self.path == '/api/growth/apply':
                return self.send(200, growth_apply(body))
            if self.path == '/api/growth/focus':
                return self.send(200, growth_focus(body))
            if self.path == '/api/growth/staff':
                return self.send(200, growth_staff(body))
            if self.path == '/api/backups/clean':
                r_ = prune_backups(int(body['keep']) if body.get('keep') is not None else None)
                return self.send(200, dict(r_, **backups_info()))
            if self.path == '/api/backups/keep':   # pc356: koliko kopija po karijeri (0 = iskljuceno)
                k_ = max(0, min(50, int(body.get('keep', 3))))
                p_ = os.path.join(HERE, 'config.json')
                try:
                    cur_ = json.load(open(p_, encoding='utf-8'))
                except Exception:
                    cur_ = {}
                cur_['backup_keep'] = k_
                _jdump(cur_, p_, ensure_ascii=False, indent=1)
                CFG['backup_keep'] = k_
                r_ = prune_backups()
                return self.send(200, dict(r_, **backups_info()))
            if self.path == '/api/growth/auto':
                return self.send(200, growth_auto_set(body))
            if self.path == '/api/growth/enable':
                growth.set_enabled(CFG, bool(body.get('on')))
                return self.send(200, dict(ok=True, enabled=growth.enabled(CFG)))
            if self.path == '/api/apply':
                return self.send(200, apply(body))
            if self.path == '/api/assign':
                return self.send(200, assign(body))
            if self.path == '/api/quit':
                # pc186: launcher gasi STARU verziju appa nakon nadogradnje (samo uz zaglavlje koje preglednik s druge stranice ne moze poslati)
                if self.headers.get('X-Gaffer') != '1':
                    return self.send(403, dict(error='forbidden'))
                threading.Timer(0.4, lambda: os._exit(0)).start()
                return self.send(200, dict(ok=True, version=APP_VERSION))
            if self.path == '/api/club/fluid_test':
                return self.send(200, club_fluid_test(body))
            if self.path == '/api/club/formation_test':
                return self.send(200, club_formation_test(body))
            if self.path == '/api/tactics/club':
                return self.send(200, set_club_tac(body))
            if self.path == '/api/auto/set':
                return self.send(200, auto_set(body))
            if self.path == '/api/auto/run':
                r = auto_run_slot(body['slot'], force=True)
                if body.get('tac'):
                    r['tac'] = auto_tac_slot(body['slot'], force=True)
                r['auto'] = auto_status(body['slot'])
                return self.send(200, r)
            if self.path == '/api/ai/move':
                return self.send(200, ai_moves(body))
            if self.path == '/api/wiki/prefetch':
                return self.send(200, wiki_prefetch((body.get('pids') or [])[:40]))
            if self.path == '/api/requests/act':
                return self.send(200, player_request_act(body))
            if self.path == '/api/coach/upload':
                return self.send(200, coach_upload(body))
            if self.path == '/api/coach/set':
                return self.send(200, coach_set(body))
            if self.path == '/api/scouting/act':
                return self.send(200, scouting_act(body))
            if self.path == '/api/freeagents/offer':
                return self.send(200, freeagent_offer(body))
            if self.path == '/api/freeagents/sign':
                return self.send(200, freeagent_sign(body))
            if self.path == '/api/tlist/set':
                return self.send(200, tlist_set(body))
            if self.path == '/api/list':
                return self.send(200, list_players(body))
            if self.path == '/api/sbase':
                return self.send(200, sbase_set(body))
            if self.path == '/api/history/shown':
                return self.send(200, history_shown(body))
            if self.path == '/api/job/intro/seen':
                return self.send(200, job_intro(body.get('slot', ''), seen=True))
            if self.path == '/api/neg/start':
                return self.send(200, neg_start(body))
            if self.path == '/api/neg/offer':
                return self.send(200, neg_offer(body))
            if self.path == '/api/neg/terms':
                return self.send(200, neg_terms(body))
            if self.path == '/api/neg/quiet':
                return self.send(200, neg_quiet(body))
            if self.path == '/api/neg/end':
                return self.send(200, neg_end(body))
            if self.path == '/api/neg/hurry':
                return self.send(200, neg_hurry(body))
            if self.path == '/api/neg/agent':
                return self.send(200, neg_agent(body))
            if self.path == '/api/neg/medical':
                return self.send(200, neg_medical(body))
            if self.path == '/api/neg/finish':
                return self.send(200, neg_finish(body))
            if self.path == '/api/contract/offer':
                return self.send(200, contract_offer(body))
            if self.path == '/api/youth/sign':
                return self.send(200, youth_sign(body))
            if self.path == '/api/youth/broken':
                return self.send(200, broken_set(body))
            if self.path == '/api/contract/sign':
                return self.send(200, contract_sign(body))
            if self.path == '/api/drama/choice':
                return self.send(200, drama_choice(body))
            if self.path == '/api/contract/sync':
                return self.send(200, contract_sync(body))
            if self.path == '/api/form/commit':
                return self.send(200, form_commit(body['slot']))
            if self.path == '/api/talks/start':
                return self.send(200, talk_start(body))
            if self.path == '/api/talks/reply':
                return self.send(200, talk_reply(body))
            if self.path == '/api/talks/say':
                return self.send(200, say_talk(body))
            if self.path == '/api/press/say':
                return self.send(200, say_press(body))
            if self.path == '/api/press/start':
                return self.send(200, press_start(body))
            if self.path == '/api/press/finish':
                return self.send(200, press_finish(body))
            if self.path == '/api/lock':
                return self.send(200, lock_player(body))
            if self.path == '/api/repair':
                return self.send(200, repair(body))
            if self.path == '/api/sell/open':
                return self.send(200, sell_open(body))
            if self.path == '/api/sell/agree':
                return self.send(200, sell_agree(body))
            if self.path == '/api/sell/bonus':
                return self.send(200, sell_bonus(body))
            if self.path == '/api/sell/tactic':
                return self.send(200, sell_tactic(body))
            if self.path == '/api/sell/counter':
                return self.send(200, sell_counter(body))
            if self.path == '/api/honours/manual':
                return self.send(200, honours_manual(body))
            if self.path == '/api/sell/nfs':
                return self.send(200, sell_nfs(body))
            if self.path == '/api/sell/dismiss':
                return self.send(200, sell_dismiss(body))
            if self.path == '/api/sell/do':
                return self.send(200, sell_do(body))
            if self.path == '/api/lab/restore':
                return self.send(200, lab_restore(body))
            if self.path == '/api/loan/do':
                return self.send(200, loan_do(body))
            if self.path == '/api/lneg/start':
                return self.send(200, lneg_start(body))
            if self.path == '/api/lneg/offer':
                return self.send(200, lneg_offer(body))
            if self.path == '/api/lneg/terms':
                return self.send(200, lneg_terms(body))
            if self.path == '/api/lneg/finish':
                return self.send(200, lneg_finish(body))
            if self.path == '/api/loan/in/terms':
                return self.send(200, loan_in_terms(body))
            if self.path == '/api/loan/in':
                return self.send(200, loan_in_do(body))
            if self.path == '/api/loan/queue/run':
                return self.send(200, loan_queue_run(body))
            if self.path == '/api/loan/queue/drop':
                return self.send(200, loan_queue_drop(body))
            if self.path == '/api/loan/refund':
                return self.send(200, loan_refund(body))
            if self.path == '/api/loan/fixdate':
                return self.send(200, loan_fixdate(body))
            if self.path == '/api/swap':
                return self.send(200, swap_deal(body))
            if self.path == '/api/menumode':
                return self.send(200, set_menu(bool(body.get('on'))))
            if self.path == '/api/launch':
                return self.send(200, launch())
            return self.send(404, {'error': 'nema'})
        except Exception as e:
            return self.send(400, {'ok': False, 'error': str(e)})


def reload_db():
    """pc236: nakon uvoza baze ponovno ucitaj imena, pozicije i ocjene (bez restarta appa) i ocisti cacheve."""
    global NAMES, POS, RAT, RATAB, PLAYPOS
    NAMES = mlwrite.load_names(_dbf('players.json'))
    POS = mlwrite.load_positions(_dbf('positions.json'))
    try:
        PLAYPOS = {int(k): v for k, v in json.load(open(_dbf('playpos.json'))).items()}
    except Exception:
        PLAYPOS = {}
    rp = _dbf('ratings.json')
    if os.path.exists(rp):
        _r = json.load(open(rp, encoding='utf-8'))
        RAT = {int(k): v for k, v in _r['p'].items()}
        RATAB = _r['ab']
    for c in (PCACHE, FA_CACHE, _RDC, _YDC, _OWN_CACHE, _DBC):
        try:
            c.clear()
        except Exception:
            pass


_CODE_STAMP = {}


def _code_stamp():
    """pc316: otisak koda na disku (velicina + vrijeme izmjene server.py, lib/*.py, static/index.html). Drugo pokretanje
    usporedi otisak s vec pokrenutim appom: isti = samo otvori prozor, drugaciji = stari app se ugasi (inace ostaje stari kod)."""
    if 'v' in _CODE_STAMP:
        return _CODE_STAMP['v']
    import hashlib
    h = hashlib.sha1()
    files = [os.path.join(HERE, 'server.py'), os.path.join(HERE, 'static', 'index.html')] + sorted(glob.glob(os.path.join(HERE, 'lib', '*.py')))
    for f in files:
        try:
            st = os.stat(f)
            h.update(('%s|%d|%d;' % (os.path.basename(f), st.st_size, int(st.st_mtime))).encode())
        except OSError:
            pass
    _CODE_STAMP['v'] = h.hexdigest()[:12]
    return _CODE_STAMP['v']


def _port_busy(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def _kill_stuck(port):
    """pc379: zaglavljena kopija appa na portu (slusa, ne odgovara): nadji PID (netstat) i ugasi ga, samo ako je python."""
    if os.name != 'nt':
        return
    import subprocess
    try:
        cf = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        out = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, timeout=10, creationflags=cf).stdout
        pids = set()
        for line in out.splitlines():
            p_ = line.split()
            if len(p_) >= 5 and p_[1].endswith(':%d' % port) and p_[3].upper() == 'LISTENING':
                pids.add(p_[4])
        for pid in pids:
            if pid == str(os.getpid()):
                continue
            img = subprocess.run(['tasklist', '/FI', 'PID eq %s' % pid, '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                                 timeout=10, creationflags=cf).stdout.lower()
            if 'python' in img:
                print('A stuck copy of The Gaffer (PID %s) was not responding: closing it.' % pid)
                subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=10, creationflags=cf)
        for _ in range(20):
            if not _port_busy(port):
                break
            time.sleep(0.25)
    except Exception as ex:
        print('[instance] stuck check:', ex)


def _single_instance(port, show=True):
    """pc316: jedan app na portu. Isti kod vec radi -> otvori njegov prozor i izadji. Stari kod -> zamoli ga da se ugasi."""
    import urllib.request
    def call(method, path, to=2):
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path), data=(b'{}' if method == 'POST' else None), method=method,
                                     headers={'X-Gaffer': '1', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=to) as r:
            return json.loads(r.read().decode('utf-8', 'replace') or '{}')
    try:
        v = call('GET', '/api/version')
    except Exception:
        # pc379: nesto slusa na portu, ali ne odgovara (zaglavljena stara kopija) -> 'Failed to fetch' u pregledniku.
        # Ako je to Python, ugasi ga (prije je korisnik morao u Task Manager).
        if _port_busy(port):
            try:
                v = call('GET', '/api/version', 12)   # zauzeta kopija (npr. upravo pise save) stigne odgovoriti; ne gasimo je usred posla
            except Exception:
                _kill_stuck(port)
                return True
        else:
            return True   # nista ne radi na portu
    if v.get('app') != 'thegaffer':
        print('Port %d is used by another program.' % port)
        return True   # bind ce javiti gresku
    if v.get('code') == _code_stamp():
        if show:
            try:
                call('GET', '/api/show')
            except Exception:
                pass
        print('The Gaffer is already running (same code): opened its window.')
        return False
    print('An older copy of The Gaffer is running (%s): closing it.' % v.get('version'))
    try:
        call('POST', '/api/quit')
    except Exception:
        pass
    for _ in range(40):
        time.sleep(0.25)
        try:
            call('GET', '/api/version')
        except Exception:
            return True
    return True


class _Srv(ThreadingHTTPServer):
    # pc316: na Windowsu SO_REUSEADDR dopusta da DVA procesa slusaju isti port (dva appa odjednom); ekskluzivno vezanje
    allow_reuse_address = (os.name != 'nt')

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


def main():
    global CFG, DEV, NAMES, POS, RAT, RATAB, PLAYPOS
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev-folder')
    ap.add_argument('--port', type=int)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--host', default='127.0.0.1',
                    help='bind address (default 127.0.0.1; 0.0.0.0 for LAN/preview)')
    a = ap.parse_args()
    CFG = load_cfg()
    if pes17.looks_like_pes17_path(CFG.get('save_dir')):
        _GAME['save'] = 'pes17'
    if not fc27db.available():
        print('[fc27] data/fc27/players.json is missing - rebuild it with: node tools/import_fc27.mjs')
    else:
        _fcs = fc27db.summary()
        print('[fc27] database: %d players, %d clubs, %d leagues' % (_fcs['players'], _fcs['clubs'], _fcs['leagues']))
    if not a.dev_folder and not _single_instance(a.port or CFG['port'], show=not a.no_browser):
        return
    DEV = a.dev_folder
    if DEV:
        CFG['work'] = os.path.join(HERE, '_dev_work')
    NAMES = mlwrite.load_names(_dbf('players.json'))
    POS = mlwrite.load_positions(_dbf('positions.json'))
    try:
        PLAYPOS = {int(k): v for k, v in json.load(open(_dbf('playpos.json'))).items()}
    except Exception:
        PLAYPOS = {}
    rp = _dbf('ratings.json')
    if os.path.exists(rp):
        _r = json.load(open(rp, encoding='utf-8'))
        RAT = {int(k): v for k, v in _r['p'].items()}
        RATAB = _r['ab']
    port = a.port or CFG['port']
    try:
        _career_job_restore()
    except Exception as ex:
        print('[career] restore:', ex)
    threading.Thread(target=auto_loop, daemon=True).start()
    try:
        srv = _Srv((a.host, port), H)
        CFG['_port'] = port
        if CFG.get('lan_on') and CFG.get('lan_pin'):
            lan_start()
    except OSError as ex:
        print('Cannot start on port %d (%s). Is The Gaffer or another program already using it?' % (port, ex))
        return
    _code_stamp()
    try:
        _es = encrypter_status()
        if not _es['ok']:
            print('[encrypter]', _es['why'])
    except Exception:
        pass
    url = 'http://127.0.0.1:%d/' % port
    print('The Gaffer running at', url, '(Ctrl+C to exit)')
    if not a.no_browser:
        threading.Timer(0.8, lambda: open_app(url)).start()
    threading.Thread(target=_hotkey_loop, args=(url,), daemon=True).start()
    threading.Thread(target=_pad_loop, args=(url,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
