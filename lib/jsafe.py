"""pc251: sigurno spremanje JSON-a (privremena datoteka + zamjena). Ako pisanje pukne, stara datoteka ostaje cijela."""
import json, os, threading, time

_LOCK = threading.Lock()


def jdump(obj, path, **kw):
    tmp = '%s.%d.%d.tmp' % (path, os.getpid(), threading.get_ident())
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, **kw)
        with _LOCK:
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
