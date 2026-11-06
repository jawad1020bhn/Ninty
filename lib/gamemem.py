"""pc391: je li igra u Master Ligi ili na pocetnom zaslonu, iz memorije igre (samo citanje).

Lanac pokazivaca (izmjerio tester, isti u FL26 mod exeu 63707cf3 / 9ee0c306 i FL27 327c6df6):
  obj  = u64 [exe_base + 0x3705E10]       (0 prije prvog ucitavanja karijere)
  tbl  = u64 [obj + 0x48]                  (pocetak tablice igraca)
  date = [tbl + 0x1642A24]: u16 godina, u8 mjesec (+2), u8 dan (+3)
U Master Ligi datum je valjan; na pocetnom zaslonu FL27 pise 65535-00-00.

Nista se ne pise u igru. Ako bilo sto ne uspije (drugi exe, 32-bitni Python, prava pristupa) -> None i app radi kao prije."""
import os
import struct

OFF_OBJ = 0x3705E10
OFF_TBL = 0x48
OFF_DATE = 0x1642A24


def _valid_date(y, m, d):
    return 2000 <= y <= 2200 and 1 <= m <= 12 and 1 <= d <= 31


def classify(read_u64, read_bytes, base):
    """-> ('null'|'home'|'ml'|'unknown', (y, m, d) ili None). read_* vracaju None kad citanje ne uspije."""
    obj = read_u64(base + OFF_OBJ)
    if obj is None:
        return 'unknown', None
    if obj == 0:
        return 'null', None
    tbl = read_u64(obj + OFF_TBL)
    if not tbl:
        return 'unknown', None
    raw = read_bytes(tbl + OFF_DATE, 4)
    if not raw or len(raw) < 4:
        return 'unknown', None
    y = struct.unpack_from('<H', raw, 0)[0]
    m, d = raw[2], raw[3]
    if _valid_date(y, m, d):
        return 'ml', (y, m, d)
    if y == 0xFFFF and m == 0 and d == 0:
        return 'home', None
    return 'unknown', (y, m, d)


# ---------------------------------------------------------------- Windows
def _win_pid(exe_name):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class PE(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD),
                    ('szExeFile', ctypes.c_wchar * 260)]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return None
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        want = exe_name.lower()
        while ok:
            if e.szExeFile.lower() == want:
                return int(e.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None


class _WinReader:
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k32.OpenProcess.restype = wintypes.HANDLE
        self.k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.h = self.k32.OpenProcess(0x0410, False, pid)   # QUERY_INFORMATION | VM_READ
        if not self.h:
            self.h = self.k32.OpenProcess(0x1010, False, pid)   # QUERY_LIMITED_INFORMATION | VM_READ
        if not self.h:
            raise OSError('OpenProcess failed')
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        mods = (ctypes.c_void_p * 1)()
        need = wintypes.DWORD()
        if not psapi.EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x03):
            self.close()
            raise OSError('EnumProcessModulesEx failed')
        self.base = mods[0] or 0x140000000

    def read_bytes(self, addr, n):
        buf = self.ct.create_string_buffer(n)
        got = self.ct.c_size_t()
        try:
            if not self.k32.ReadProcessMemory(self.h, self.ct.c_void_p(addr), buf, n, self.ct.byref(got)) or got.value != n:
                return None
        except Exception:
            return None
        return buf.raw

    def read_u64(self, addr):
        b = self.read_bytes(addr, 8)
        return struct.unpack('<Q', b)[0] if b else None

    def close(self):
        try:
            if self.h:
                self.k32.CloseHandle(self.h)
        except Exception:
            pass
        self.h = None


# ---------------------------------------------------------------- Linux (Wine / Proton)
def _linux_pid(exe_name):
    want = exe_name.lower()
    for p in os.listdir('/proc'):
        if not p.isdigit() or int(p) == os.getpid():
            continue
        try:
            cl = open('/proc/%s/cmdline' % p, 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace').lower().replace('\\', '/')
        except Exception:
            continue
        if want in cl:
            return int(p)
    return None


class _LinuxReader:
    def __init__(self, pid):
        self.f = open('/proc/%d/mem' % pid, 'rb', buffering=0)
        self.base = 0x140000000

    def read_bytes(self, addr, n):
        try:
            self.f.seek(addr)
            b = self.f.read(n)
            return b if len(b) == n else None
        except Exception:
            return None

    def read_u64(self, addr):
        b = self.read_bytes(addr, 8)
        return struct.unpack('<Q', b)[0] if b else None

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


class Probe:
    """Drzi otvoren proces igre izmedju citanja. probe() -> (pid, stanje, datum) ili None."""
    def __init__(self, exe_name):
        self.exe = exe_name if exe_name.lower().endswith('.exe') else exe_name + '.exe'
        self.pid = None
        self.r = None
        self.err = ''

    def probe(self):
        import time as _t
        # pc413: popis procesa najvise svakih 5 s dok je proces otvoren (citanje ne uspije -> odmah novi popis)
        if self.r is not None and self.pid and _t.time() - getattr(self, '_lt', 0) < 5:
            st, dt = classify(self.r.read_u64, self.r.read_bytes, self.r.base)
            if st != 'unknown':
                self.err = ''
                return self.pid, st, dt
        self._lt = _t.time()
        try:
            pid = _win_pid(self.exe) if os.name == 'nt' else _linux_pid(self.exe)
        except Exception as ex:
            pid = None
            self.err = 'process list: %s' % ex
        if not pid:
            self.err = self.err or 'process %s not found' % self.exe
            self.close()
            return None
        if pid != self.pid or self.r is None:
            self.close()
            try:
                self.r = _WinReader(pid) if os.name == 'nt' else _LinuxReader(pid)
                self.pid = pid
            except Exception as ex:
                self.r, self.pid = None, None
                self.err = 'open process %d: %s (WinError %s)' % (pid, ex, getattr(ex, 'winerror', '') or self._lasterr())
                return None
        st, dt = classify(self.r.read_u64, self.r.read_bytes, self.r.base)
        if st == 'unknown':
            try:
                obj = self.r.read_u64(self.r.base + OFF_OBJ)
                self.err = 'base 0x%x obj %s date %s' % (self.r.base, hex(obj) if obj is not None else 'unreadable', dt)
            except Exception as ex:
                self.err = 'read: %s' % ex
        else:
            self.err = ''
        return self.pid, st, dt

    @staticmethod
    def _lasterr():
        try:
            import ctypes
            return ctypes.get_last_error()
        except Exception:
            return ''

    def close(self):
        if self.r is not None:
            self.r.close()
        self.r, self.pid = None, None
