#!/usr/bin/env python3
"""Apply the PES 2017 compatibility patch to an extracted TheGaffer folder.

Usage:  python pes2017/patch.py /path/to/TheGaffer

The patch is intentionally written as a set of exact, asserted text
substitutions: if the upstream pc414 source drifts, patch.py fails loudly
instead of silently producing a broken program.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.join(ROOT, 'overlay')

KEY_PES17_LINES = """M32 = 0xffffffff

# pesXdecrypter/src/masterkey.c: MasterKeyPes17 (public domain).  PES 2017 uses
# exactly the same container algorithm as PES 2021 but a different master key.
KEY_PES17 = bytes([
    0x9B, 0xC7, 0x13, 0x28, 0x2D, 0xE8, 0x47, 0x75,
    0x4D, 0x52, 0x9E, 0x35, 0x90, 0xAA, 0x6A, 0x7A,
    0x5C, 0xFA, 0x60, 0x9F, 0x6A, 0x32, 0x04, 0x57,
    0xB8, 0x9F, 0x59, 0xA5, 0x5F, 0xAC, 0x7D, 0x62,
    0xFE, 0x10, 0x2A, 0xD6, 0x95, 0xFA, 0xDF, 0xA0,
    0x68, 0xBD, 0x40, 0x95, 0x47, 0x9C, 0xBB, 0x40,
    0xF2, 0x94, 0x49, 0x3C, 0xC8, 0xE0, 0x94, 0x9D,
    0x7B, 0x01, 0x6F, 0xF2, 0xC5, 0x3A, 0x2C, 0xE5,
])


def key_candidates(fl_key=None):
    \"\"\"Ordered (name, 64 B key) pairs to try on an unknown save container.

    A wrong key produces garbage block sizes, so decrypt_bytes() rejects it.
    \"\"\"
    return [('pes21', KEY_PES21), ('fl', fl_key), ('pes17', KEY_PES17)]


def key_for(name, fl_key=None):
    \"\"\"Resolve a key name written in the decrypted folder's gaffer_key.txt.\"\"\"
    return {k: v for k, v in key_candidates(fl_key) if v}.get(name)
"""

# (file, old text, new text, expected occurrences)
PATCHES = [
    # ---------------------------------------------------------------- crypto
    ('lib/pescrypt.py', "M32 = 0xffffffff", KEY_PES17_LINES, 1),

    # A REAL t99p17v20 save proved PES 2017 uses a 176-byte file header
    # (no gameVersionString), not the 208-byte PES 2021 header.  Without this
    # the app cannot open any real PES 2017 save at all.
    ('lib/pescrypt.py',
     "ENC_HDR = 320\nFILE_HDR = 208",
     """ENC_HDR = 320
FILE_HDR = 208
FILE_HDR_PES17 = 176   # PES 2017 has no gameVersionString in header.dat""", 1),

    ('lib/pescrypt.py',
     """def decrypt_bytes(f, master=KEY_PES21):
    if len(f) < ENC_HDR + FILE_HDR:
        raise ValueError('file too small')
    eh = _crypt_enc_header(f[:ENC_HDR], master)
    rk = _rolling(eh)
    pos = ENC_HDR
    fh = crypt(_bkey(rk, FILE_HDR), f[pos:pos + FILE_HDR])
    pos += FILE_HDR
    ds, ls, dsc, ss = struct.unpack_from('<4I', fh, 64)
    ss *= 2
    if pos + ds + ls + dsc + ss != len(f):
        raise ValueError('wrong key or not a save (block sizes do not match)')
    out = {'encryptHeader.dat': eh, 'header.dat': fh}
    for name, ln, p in (('description.dat', dsc, 0), ('logo.png', ls, 1), ('data.dat', ds, 2), ('version.txt', ss, 3)):
        out[name] = crypt(_bkey(rk, p), f[pos:pos + ln])
        pos += ln
    return out""",
     """def _decrypt_bytes(f, master, file_hdr):
    if len(f) < ENC_HDR + file_hdr:
        raise ValueError('file too small')
    eh = _crypt_enc_header(f[:ENC_HDR], master)
    rk = _rolling(eh)
    pos = ENC_HDR
    fh = crypt(_bkey(rk, file_hdr), f[pos:pos + file_hdr])
    pos += file_hdr
    ds, ls, dsc, ss = struct.unpack_from('<4I', fh, 64)
    ss *= 2
    # A wrong key + wrong header size can coincidentally add up to len(f).
    # Reject implausible block sizes before touching any large payload.
    if not (0 < ds < 200000000 and 0 <= ls < 5000000 and 0 <= dsc < 1000000
            and 0 < ss < 1000):
        raise ValueError('wrong key or not a save (implausible block sizes)')
    if pos + ds + ls + dsc + ss != len(f):
        raise ValueError('wrong key or not a save (block sizes do not match)')
    out = {'encryptHeader.dat': eh, 'header.dat': fh}
    for name, ln, p in (('description.dat', dsc, 0), ('logo.png', ls, 1), ('data.dat', ds, 2), ('version.txt', ss, 3)):
        out[name] = crypt(_bkey(rk, p), f[pos:pos + ln])
        pos += ln
    return out


def decrypt_bytes(f, master=KEY_PES21):
    # Try both file-header sizes: 208 B (PES 2021 / FL) and 176 B (PES 2017).
    last = None
    for hdr in (FILE_HDR, FILE_HDR_PES17):
        try:
            return _decrypt_bytes(f, master, hdr)
        except ValueError as e:
            last = e
    raise ValueError(str(last))""", 1),

    ('lib/pescrypt.py',
     """def encrypt_parts(parts, master=KEY_PES21):
    fh = bytearray(parts['header.dat'])
    struct.pack_into('<4I', fh, 64, len(parts['data.dat']), len(parts['logo.png']), len(parts['description.dat']), len(parts['version.txt']) // 2)
    eh = parts['encryptHeader.dat']
    rk = _rolling(eh)
    out = [_crypt_enc_header(eh, master), crypt(_bkey(rk, FILE_HDR), bytes(fh))]
    for name, p in (('description.dat', 0), ('logo.png', 1), ('data.dat', 2), ('version.txt', 3)):
        out.append(crypt(_bkey(rk, p), parts[name]))
    return b''.join(out)""",
     """def encrypt_parts(parts, master=KEY_PES21):
    fh = bytearray(parts['header.dat'])
    # PES 2017 stores a 176 B file header.  The header length itself tells us
    # which key-derivation param to use, so a decrypted PES 2017 folder
    # re-encrypts correctly with no extra marker file.
    if len(fh) not in (FILE_HDR, FILE_HDR_PES17):
        fh = bytearray((bytes(fh) + bytes(FILE_HDR))[:FILE_HDR])
    file_hdr = len(fh)
    struct.pack_into('<4I', fh, 64, len(parts['data.dat']), len(parts['logo.png']), len(parts['description.dat']), len(parts['version.txt']) // 2)
    eh = parts['encryptHeader.dat']
    rk = _rolling(eh)
    out = [_crypt_enc_header(eh, master), crypt(_bkey(rk, file_hdr), bytes(fh))]
    for name, p in (('description.dat', 0), ('logo.png', 1), ('data.dat', 2), ('version.txt', 3)):
        out.append(crypt(_bkey(rk, p), parts[name]))
    return b''.join(out)""", 1),

    # ------------------------------------------------------------ Save factory
    ('lib/mlwrite.py',
     "class Save:\n    _RO_CACHE = {}\n\n    def __init__(self, folder, ro=False):",
     """class Save:
    _RO_CACHE = {}

    def __new__(cls, *args, **kwargs):
        # PES 2017 compatibility: every mlwrite.Save(...) call on a PES 2017
        # save transparently returns the read-only adapter.  Python skips
        # __init__ when __new__ returns an object that is not an instance of
        # cls, so no FL26 layout code ever runs on a PES 2017 save.
        try:
            folder = args[0] if args else kwargs.get('folder')
            ro = kwargs.get('ro', args[1] if len(args) > 1 else False)
            if folder:
                import pes17
                if pes17.is_pes17(folder):
                    return pes17.open_save(folder, ro=ro)
        except Exception:
            pass
        return super(Save, cls).__new__(cls)

    def __init__(self, folder, ro=False):""", 1),

    # -------------------------------------------------------------- server.py
    ('server.py',
     "import layoutscan  # noqa: E402",
     "import layoutscan  # noqa: E402\nimport pes17  # noqa: E402  (PES 2017 compatibility, read-only)", 1),

    ('server.py', "    'port': 8765,",
     "    'port': 8765,\n    'pes17_date_order': 'dmy',       # PES 2017 writes D/M/YYYY; set 'mdy' for US locales\n    'pes17_allow_writes': False,     # safety: PES 2017 save writing is not mapped yet", 1),

    ('server.py',
     """    import pescrypt
    raw = open(src, 'rb').read()
    for name, key in (('pes21', pescrypt.KEY_PES21), ('fl', _fl_key())):
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
        if name == 'fl':
            with open(os.path.join(outdir, KEY_MARK), 'w') as fh:
                fh.write('fl')
        return""",
     """    import pescrypt
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
        return""", 1),

    ('server.py',
     """    if _fl_key() is None and os.path.basename(src).upper().startswith(('ML', 'EDIT')):
        raise RuntimeError('decryption failed (%s). Football Life 2027 saves need FL_key.bin: put it in the app folder.' % err)
    raise RuntimeError('decryption failed (%s)' % err)""",
     """    raise RuntimeError('decryption failed (%s). Tried the PES 2021, Football Life 2027 and PES 2017 save keys. '
                       'FL27 saves need FL_key.bin in the app folder.' % err)""", 1),

    ('server.py',
     """    if os.path.exists(os.path.join(new_dec, KEY_MARK)):
        import pescrypt
        key = _fl_key()
        if not key:
            raise RuntimeError('FL_key.bin is missing: cannot encrypt a Football Life 2027 save')
        parts = {}
        for k_ in ('encryptHeader.dat', 'header.dat', 'description.dat', 'logo.png', 'data.dat', 'version.txt'):
            p_ = os.path.join(new_dec, k_)
            parts[k_] = open(p_, 'rb').read() if os.path.exists(p_) else b''
        out = pescrypt.encrypt_parts(parts, key)
        pescrypt.decrypt_bytes(out, key)   # provjera prije upisa
        with open(newfile + '.tmp', 'wb') as fh:
            fh.write(out)
        os.replace(newfile + '.tmp', newfile)
        return type('R', (), dict(returncode=0, stdout='', stderr=''))()""",
     """    key_name = ''
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
        return type('R', (), dict(returncode=0, stdout='', stderr=''))()""", 1),

    ('server.py',
     """def _game_of(folder):
    \"\"\"'fl27' ako je save iz Football Life 2027 (header.dat: verzija igre), inace 'fl26'.\"\"\"
    try:
        p_ = os.path.join(folder, 'header.dat')""",
     """def _game_of(folder):
    \"\"\"'fl27' / 'pes17' / 'fl26'. PES 2017 is detected by its decrypted save.\"\"\"
    try:
        if pes17.is_pes17(folder):
            return 'pes17'
    except Exception:
        pass
    try:
        p_ = os.path.join(folder, 'header.dat')""", 1),

    ('server.py',
     """def _detect_game_for(sd):
    \"\"\"pc265: postavke igre (exe, Sider, proces, dump) za mapu saveova: Sider cija igra (exe.name) nosi istu godinu
    (FL_2027.exe za ...\\\\2027\\\\save). Trazi samo vrh diskova i jednu razinu ispod (brzo). -> dict ili {}\"\"\"
    yr = _save_year(sd)""",
     """def _detect_game_for(sd):
    \"\"\"pc265: postavke igre (exe, Sider, proces, dump) za mapu saveova: Sider cija igra (exe.name) nosi istu godinu
    (FL_2027.exe za ...\\\\2027\\\\save). Trazi samo vrh diskova i jednu razinu ispod (brzo). -> dict ili {}\"\"\"
    if pes17.looks_like_pes17_path(sd):
        r = dict(pes_process='PES2017', auto_menu=False, pes17_date_order='dmy')
        exe = pes17.find_exe(sd)
        if exe:
            r['pes_exe'] = exe
        return r
    yr = _save_year(sd)""", 1),

    ('server.py',
     """    def _sider_score(sdir):""",
     """    def _sider_score(sdir):""", 0),   # placeholder, no-op

    ('server.py',
     """def rows_json(save, k):
    rows = []""",
     """def rows_json(save, k):
    if getattr(save, 'pes17', False):
        return save.formation_rows(k)
    rows = []""", 1),

    ('server.py',
     """    fp = dict(club=int((s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE), mgr=mgr)""",
     """    fp = dict(club=int((s.club_offset() - getattr(s, 'REC0', mlwrite.REC0)) //
                       getattr(s, 'STRIDE', mlwrite.STRIDE)), mgr=mgr)""", 1),

    ('server.py',
     """def state(slot):
    _CUR_SLOT['slot'] = slot""",
     """def pes17_readonly(slot=None):
    \"\"\"Early, friendly refusal for every endpoint that writes into the save.\"\"\"
    if _GAME['v'] == 'pes17':
        raise ValueError(pes17.READ_ONLY_MSG)


def pes17_auto_db(folder):
    \"\"\"First PES 2017 load: build data/pes17/*.json from EDIT00000000.

    The FL26 player database has different player IDs, so without this the
    squad would show FL26 names (or just numbers).  Sider/F7 dumps do not
    exist for PES 2017 in this build, so the EDIT file is the source.
    \"\"\"
    if _GAME['v'] != 'pes17':
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


def state(slot):
    _CUR_SLOT['slot'] = slot""", 1),

    ('server.py',
     """def state(slot):
    _CUR_SLOT['slot'] = slot""",
     """def pes17_tools_info(slot):
    # Real-save PES 2017 info (read side), independent of the FL26 views.
    import pes17_write
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
    _CUR_SLOT['slot'] = slot""", 1),

    ('server.py',
     """            if u.path == '/api/state':
                slot = parse_qs(u.query).get('slot', [''])[0]
                return self.send(200, state(slot))""",
     """            if u.path == '/api/pes17/info':
                return self.send(200, pes17_tools_info(parse_qs(u.query).get('slot', [''])[0]))
            if u.path == '/api/pes17/offers':
                r = pes17_tools_info(parse_qs(u.query).get('slot', [''])[0])
                return self.send(200, dict(ok=True, offers=r['offers'], teams=r['teams']))
            if u.path == '/api/state':
                slot = parse_qs(u.query).get('slot', [''])[0]
                return self.send(200, state(slot))""", 1),

    ('server.py',
     """            if self.path == '/api/lan/set':
                return self.send(200, lan_set(body))""",
     """            if self.path == '/api/lan/set':
                return self.send(200, lan_set(body))
            if self.path == '/api/pes17/write':
                lc = body.get('layout', True)
                if lc not in (True, False, 'auto', 'report'):
                    lc = True
                return self.send(200, pes17_tools_apply(body.get('slot'),
                                                        body.get('ops') or [],
                                                        bool(body.get('dry')),
                                                        lc))""", 1),

    ('server.py',
     """    r = mlsave.read_save(d, None)
    s = mlwrite.Save(d)""",
     """    if pes17.is_pes17(d):
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
    s = mlwrite.Save(d)""", 1),

    ('server.py',
     """        layout=dict(ok=bool(s.known_format), note=s.layout_note, dx=s.dx,""",
     """        layout=dict(ok=bool(s.known_format), note=s.layout_note, dx=s.dx,
                   pes17=bool(getattr(s, 'pes17', False)),""", 1),

    ('server.py',
     """def _write_slot(slot, label, fn, pid=None):
    \"\"\"Dekriptira slot, primjeni fn(Save), spremi s TOCNOM duljinom, enkriptira i upise natrag (uz backup).\"\"\"
    if game_blocks():""",
     """def _write_slot(slot, label, fn, pid=None):
    \"\"\"Dekriptira slot, primjeni fn(Save), spremi s TOCNOM duljinom, enkriptira i upise natrag (uz backup).\"\"\"
    pes17_readonly(slot)
    if game_blocks():""", 1),

    ('server.py',
     """def apply(body):
    slot = body['slot']""",
     """def apply(body):
    pes17_readonly(body.get('slot'))
    slot = body['slot']""", 1),

    ('server.py',
     """def lab_restore(body):
    \"\"\"LAB: vrati dekriptirani save iz mape (data.dat + description.dat) u slot (uz backup). Samo za testove.\"\"\"
    if game_running():""",
     """def lab_restore(body):
    \"\"\"LAB: vrati dekriptirani save iz mape (data.dat + description.dat) u slot (uz backup). Samo za testove.\"\"\"
    pes17_readonly(body.get('slot'))
    if game_running():""", 1),

    ('server.py',
     """    Vraca (primijenjeni, preskoceni, backup).\"\"\"
    work = CFG['work']""",
     """    Vraca (primijenjeni, preskoceni, backup).\"\"\"
    pes17_readonly(slot)
    work = CFG['work']""", 1),

    ('server.py',
     """    \"\"\"Backup, dekriptiraj, upisi taktike klubova, provjeri citanjem, enkriptiraj, upisi. Vraca (backup).\"\"\"
    work = CFG['work']""",
     """    \"\"\"Backup, dekriptiraj, upisi taktike klubova, provjeri citanjem, enkriptiraj, upisi. Vraca (backup).\"\"\"
    pes17_readonly(slot)
    work = CFG['work']""", 1),

    ('server.py',
     """    \"\"\"Ručno namjesti taktiku AI klubu (test): body {slot, club (ime ili indeks, ili 'next'), tactics:{...}}.\"\"\"
    slot = body['slot']""",
     """    \"\"\"Ručno namjesti taktiku AI klubu (test): body {slot, club (ime ili indeks, ili 'next'), tactics:{...}}.\"\"\"
    pes17_readonly(body.get('slot'))
    slot = body['slot']""", 1),

    ('server.py',
     """        import gamemem
        v = bool(gamemem._win_pid(CFG['pes_process'] + '.exe'))""",
     """        import gamemem
        _pnames = [CFG['pes_process'] + '.exe']
        if _GAME['v'] == 'pes17' and 'PES2017.exe' not in _pnames:
            _pnames.append('PES2017.exe')
        v = any(gamemem._win_pid(n) for n in _pnames)""", 1),

    ('server.py',
     """            want = (CFG['pes_process'] + '.exe').lower()""",
     """            want = (CFG['pes_process'] + '.exe').lower()
            want17 = 'pes2017.exe' if _GAME['v'] == 'pes17' else ''""", 1),

    ('server.py',
     """                if want in cl.replace('\\\\', '/'):""",
     """                if want in cl.replace('\\\\', '/') or (want17 and want17 in cl.replace('\\\\', '/')):""", 1),

    ('server.py',
     """            if CFG.get('auto_menu', True) and not DEV and game_running():""",
     """            if (CFG.get('auto_menu', True) and not DEV and _GAME['v'] != 'pes17'
                    and game_running()):""", 1),

    ('server.py',
     """        L_('...\\\\KONAMI\\\\eFootball PES 2021 SEASON UPDATE\\\\<godina>\\\\save', '...\\\\KONAMI\\\\eFootball PES 2021 SEASON UPDATE\\\\<year>\\\\save'))""",
     """        L_('...\\\\KONAMI\\\\eFootball PES 2021 SEASON UPDATE\\\\<godina>\\\\save ili ...\\\\KONAMI\\\\Pro Evolution Soccer 2017\\\\save',
           '...\\\\KONAMI\\\\eFootball PES 2021 SEASON UPDATE\\\\<year>\\\\save or ...\\\\KONAMI\\\\Pro Evolution Soccer 2017\\\\save'))""", 1),

    ('server.py',
     """    seen, res = set(), []
    for x in sorted(out, key=lambda x: (not x['current'], x['label'])):""",
     """    # PES 2017 compatibility: Documents\\KONAMI\\Pro Evolution Soccer 2017\\save
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
    for x in sorted(out, key=lambda x: (not x['current'], x['label'])):""", 1),

    ('server.py',
     """    ap.add_argument('--no-browser', action='store_true')""",
     """    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--host', default='127.0.0.1',
                    help='bind address (default 127.0.0.1; 0.0.0.0 for LAN/preview)')""", 1),

    ('server.py',
     """        srv = _Srv(('127.0.0.1', port), H)""",
     """        srv = _Srv((a.host, port), H)""", 1),

    ('server.py',
     """def _my_club_name(s):
    try:
        return seasonstats.club_name(s.d, (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE)
    except Exception:
        return ''""",
     """def _my_club_name(s):
    if getattr(s, 'pes17', False):
        return s.team_name()
    try:
        return seasonstats.club_name(s.d, (s.club_offset() - mlwrite.REC0) // mlwrite.STRIDE)
    except Exception:
        return ''""", 1),

    ('server.py',
     """    _GAME['v'] = g
    dbimport.USE_GAME_OVR = (g == 'fl27')""",
     """    _GAME['v'] = g
    if g == 'pes17':
        try:
            pes17_auto_db(folder)   # build data/pes17/*.json from EDIT00000000
        except Exception as ex:
            print('[pes17] database:', ex)
    dbimport.USE_GAME_OVR = (g == 'fl27')""", 1),

    # ------------------------------------------------- FL26-only read helpers
    ('lib/mlwrite.py',
     """    @staticmethod
    def flag_map(data):
        \"\"\"{pid: (na_transfer_listi, na_listi_posudbi)} iz spremljenih zapisa igraca.\"\"\"
        d = bytes(data)""",
     """    @staticmethod
    def flag_map(data):
        \"\"\"{pid: (na_transfer_listi, na_listi_posudbi)} iz spremljenih zapisa igraca.\"\"\"
        # PES 2017: no FL26 zlib player-record chain in this save.
        try:
            import pes17
            if pes17._looks_pes17(bytes(data[:pes17.TEAM0 + 3 * pes17.TEAM_STRIDE]), len(data)):
                return {}
        except Exception:
            pass
        d = bytes(data)""", 1),

    ('server.py',
     """def players_data(slot):
    d = slot_folder(slot)   # pc289: prvo slot (prepozna igru FL26/FL27), pa zivi OVR""",
     """def pes17_players(slot):
    \"\"\"Player search for PES 2017: from EDIT00000000 + the ML club table.\"\"\"
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
    d = slot_folder(slot)   # pc289: prvo slot (prepozna igru FL26/FL27), pa zivi OVR""", 1),

    ('server.py',
     """    game = dict(v='fl27' if g27 else 'fl26')""",
     """    game = dict(v='pes17' if _GAME['v'] == 'pes17' else ('fl27' if g27 else 'fl26'))""", 1),

    # ------------------------------------------------------------------- UI
    ('static/index.html',
     """if(S.layout&&S.layout.game27){let seen=false;""",
     """if(S.layout&&S.layout.pes17){banner('<b>PES 2017 save.</b> The app reads your club, squad, players, shirt numbers, league table and negotiations from your real Master League + EDIT files. FL26-style writes stay blocked; measured formation, tactics, XI and budget write tools are here: <a href="/pes17.html" style="color:#fff;text-decoration:underline">PES 2017 tools</a>. The &euro; figure in the app is a RAW save word, not confirmed EUR (PES 2017 currency scale is not verified in game). The tools page labels it as raw and checks the save layout before any write. Always keep a backup.',false);}else if(S.layout&&S.layout.game27){let seen=false;""", 1),

    # ------------------------------------------------------------- GAME UI
    # Loaded LAST in <head> / at the very end of <body> so the skin wins over
    # the app's inline styles and sees the DOM after the app's own scripts.
    ('static/index.html',
     """</head>""",
     """<link rel="stylesheet" href="/game-skin.css">
</head>""", 1),

    ('static/index.html',
     """</body>""",
     """<script src="/game-skin.js"></script>
</body>""", 1),
]


def apply(target):
    # Keep one in-memory copy per file: all replacements must be cumulative.
    changes = {}
    for fn, old, new, count in PATCHES:
        if count == 0:
            continue
        if fn not in changes:
            with open(os.path.join(target, fn), encoding='utf-8') as f:
                changes[fn] = f.read()
        data = changes[fn]
        n = data.count(old)
        if n != count:
            raise RuntimeError('%s: expected %d occurrence(s) of %r, found %d' %
                               (fn, count, old[:90], n))
        changes[fn] = data.replace(old, new, count)
    for fn, data in changes.items():
        with open(os.path.join(target, fn), 'w', encoding='utf-8', newline='') as f:
            f.write(data)

    # New files
    for rel, dest in (
        ('lib/pes17.py', 'lib/pes17.py'),
        ('lib/pes17_layout.py', 'lib/pes17_layout.py'),
        ('lib/pes17_write.py', 'lib/pes17_write.py'),
        ('lib/pes17_pairs.py', 'lib/pes17_pairs.py'),
        ('static/pes17.html', 'static/pes17.html'),
        ('static/game-skin.css', 'static/game-skin.css'),
        ('static/game-skin.js', 'static/game-skin.js'),
        ('README_PES2017.txt', 'README_PES2017.txt'),
        ('config_pes2017.example.json', 'config_pes2017.example.json'),
    ):
        src = os.path.join(OVERLAY, rel)
        dst = os.path.join(target, dest)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    with open(os.path.join(target, 'VERSION.txt'), 'w', encoding='utf-8') as f:
        f.write('pc414-pes17-gameui-r5 (2026-11-04)\n')

    # Syntax-check all patched Python files in memory (no __pycache__ in the
    # shipped package, no execution of the app).
    for fn in ('server.py', 'lib/pescrypt.py', 'lib/mlwrite.py',
               'lib/pes17.py', 'lib/pes17_layout.py', 'lib/pes17_write.py',
               'lib/pes17_pairs.py'):
        with open(os.path.join(target, fn), encoding='utf-8') as f:
            compile(f.read(), fn, 'exec')
    print('PES 2017 patch applied to', target, '(%d replacements)' %
          sum(1 for p in PATCHES if p[3]))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    apply(sys.argv[1])
