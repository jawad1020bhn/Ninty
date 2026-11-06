"""PES 2016-2021 / Football Life save container (de)kripcija u Pythonu (pc264).

Algoritam: javni pesXdecrypter (the4chancup, public domain), prema Rust portu pes21-ml-editor (felipemikeias, MIT/Apache).
Master kljuc je 64 B: PES 2021 ugradjen; Football Life 2027 koristi vlastiti (FL_key.bin, 64 B) pa se moze zadati.
Izlaz je isti kao decrypter21.exe: encryptHeader.dat, header.dat, description.dat, logo.png, data.dat, version.txt.
"""
import os
import random
import struct
import sys


ENC_HDR = 320
FILE_HDR = 208
FILE_HDR_PES17 = 176   # PES 2017 has no gameVersionString in header.dat
KEY_PES21 = bytes([
    0x90, 0x61, 0xD8, 0x66, 0x43, 0x77, 0x24, 0xF8, 0x92, 0xBA, 0xB8, 0x71, 0x21, 0xC7, 0x60, 0x63,
    0xF0, 0x91, 0x9A, 0x7D, 0xED, 0x47, 0x80, 0xDE, 0x51, 0xF5, 0xDD, 0xD1, 0x08, 0xFE, 0x32, 0x84,
    0xF5, 0x09, 0x92, 0x00, 0xB2, 0x3E, 0x88, 0x9F, 0xEB, 0x24, 0x43, 0x05, 0x58, 0x76, 0x00, 0x22,
    0x9B, 0xFE, 0xEC, 0xF6, 0x50, 0x00, 0x29, 0xD3, 0x42, 0x75, 0x50, 0xB9, 0xEC, 0xD2, 0xF6, 0x75])
M32 = 0xffffffff

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
    """Ordered (name, 64 B key) pairs to try on an unknown save container.

    A wrong key produces garbage block sizes, so decrypt_bytes() rejects it.
    """
    return [('pes21', KEY_PES21), ('fl', fl_key), ('pes17', KEY_PES17)]


def key_for(name, fl_key=None):
    """Resolve a key name written in the decrypted folder's gaffer_key.txt."""
    return {k: v for k, v in key_candidates(fl_key) if v}.get(name)



def _mt_from_key(words):
    N = 624
    mt = [0] * N
    mt[0] = 19650218
    for i in range(1, N):
        mt[i] = (1812433253 * (mt[i - 1] ^ (mt[i - 1] >> 30)) + i) & M32
    i, j = 1, 0
    for _ in range(max(N, len(words))):
        mt[i] = ((mt[i] ^ (((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1664525) & M32)) + words[j] + j) & M32
        i += 1
        j += 1
        if i >= N:
            mt[0] = mt[N - 1]
            i = 1
        if j >= len(words):
            j = 0
    for _ in range(N - 1):
        mt[i] = ((mt[i] ^ (((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1566083941) & M32)) - i) & M32
        i += 1
        if i >= N:
            mt[0] = mt[N - 1]
            i = 1
    mt[0] = 0x80000000
    r = random.Random()
    r.setstate((3, tuple(mt) + (624,), None))
    return r


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & M32


def _rotl(x, n):
    return ((x << n) | (x >> (32 - n))) & M32


def crypt(key, buf):
    """XOR tok iz MT19937 (kljuc 64 B); simetricno. -> bytes"""
    words = struct.unpack('<16I', key)
    rng = _mt_from_key(words)
    n = len(buf) // 4
    rest = len(buf) - 4 * n
    cnt = 4 + n + (1 if rest else 0)
    raw = rng.getrandbits(32 * cnt).to_bytes(4 * cnt, 'little')
    if n >= 64:
        return _crypt_bigint(buf, raw, n, rest)
    r = struct.unpack('<%dI' % cnt, raw)
    if True:
        out = bytearray(buf)
        c0, c1, c2, c3 = r[0], r[1], r[2], r[3]
        for k in range(n):
            c4 = r[4 + k]
            v = struct.unpack_from('<I', buf, 4 * k)[0] ^ c4 ^ c3 ^ c2 ^ c1 ^ c0
            struct.pack_into('<I', out, 4 * k, v)
            c0, c1, c2, c3 = _rotr(c1, 15), _rotl(c2, 11), _rotl(c3, 7), _rotr(c4, 13)
        if rest:
            t = bytes(buf[4 * n:]) + b'\0' * (4 - rest)
            v = struct.unpack('<I', t)[0] ^ r[4 + n] ^ c3 ^ c2 ^ c1 ^ c0
            out[4 * n:] = struct.pack('<I', v)[:rest]
        return bytes(out)


def _lanes_rot(X, nbytes, s, right):
    """Rotacija svake 32-bitne trake u velikom cijelom broju (little-endian niz u32) za s bitova."""
    if not right:
        s = 32 - s
    lanes = nbytes // 4
    lo = int.from_bytes(struct.pack('<I', (1 << (32 - s)) - 1) * lanes, 'little')
    hi = int.from_bytes(struct.pack('<I', (M32 ^ ((1 << (32 - s)) - 1))) * lanes, 'little')
    return ((X >> s) & lo) | ((X << (32 - s)) & hi)


def _crypt_bigint(buf, raw, n, rest):
    """Bez numpyja: tok kljuca za blokove 4.. preko velikih cijelih brojeva (C brzina), prva 4 bloka i rep petljom."""
    r = struct.unpack_from('<8I', raw, 0)
    out = bytearray(buf)
    c0, c1, c2, c3 = r[0], r[1], r[2], r[3]
    for k in range(4):
        c4 = r[4 + k]
        v = struct.unpack_from('<I', buf, 4 * k)[0] ^ c4 ^ c3 ^ c2 ^ c1 ^ c0
        struct.pack_into('<I', out, 4 * k, v)
        c0, c1, c2, c3 = _rotr(c1, 15), _rotl(c2, 11), _rotl(c3, 7), _rotr(c4, 13)
    m = n - 4
    nb = 4 * m
    seg = lambda j: int.from_bytes(raw[4 * (4 + j):4 * (4 + j) + nb], 'little')   # R[k + j] za k = 4..n-1
    ks = seg(4) ^ _lanes_rot(seg(3), nb, 13, True) ^ _lanes_rot(seg(2), nb, 6, True) ^ _lanes_rot(seg(1), nb, 5, False) ^ _lanes_rot(seg(0), nb, 10, True)
    d = int.from_bytes(bytes(buf[16:16 + nb]), 'little') ^ ks
    out[16:16 + nb] = d.to_bytes(nb, 'little')
    if rest:
        R = lambda i: struct.unpack_from('<I', raw, 4 * i)[0]
        k = n - 1
        c0, c1, c2, c3 = _rotr(R(k + 1), 10), _rotl(R(k + 2), 5), _rotr(R(k + 3), 6), _rotr(R(k + 4), 13)
        t = bytes(buf[4 * n:]) + b'\0' * (4 - rest)
        v = struct.unpack('<I', t)[0] ^ R(4 + n) ^ c3 ^ c2 ^ c1 ^ c0
        out[4 * n:] = struct.pack('<I', v)[:rest]
    return bytes(out)


def _shuffle(master):
    return b''.join(master[i:i + 8][::-1] for i in range(0, 64, 8))


def _crypt_enc_header(hdr, master):
    sh = _shuffle(master)
    key = bytes(a ^ b for a, b in zip(hdr[256:320], sh))
    out = bytearray(crypt(key, hdr))
    out[256:320] = hdr[256:320]
    return bytes(out)


def _rolling(plain):
    k = bytearray(plain[:64])
    for i, b in enumerate(plain[64:]):
        k[i & 63] ^= b
    return bytes(k)


def _bkey(rolling, param):
    return b''.join(struct.pack('<Q', struct.unpack_from('<Q', rolling, i)[0] ^ param) for i in range(0, 64, 8))


def _decrypt_bytes(f, master, file_hdr):
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
    raise ValueError(str(last))


def encrypt_parts(parts, master=KEY_PES21):
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
    return b''.join(out)


def decrypt_file(src, outdir, master=KEY_PES21):
    parts = decrypt_bytes(open(src, 'rb').read(), master)
    os.makedirs(outdir, exist_ok=True)
    for k, v in parts.items():
        with open(os.path.join(outdir, k), 'wb') as fh:
            fh.write(v)
    return parts


def encrypt_dir(indir, dst, master=KEY_PES21):
    parts = {k: open(os.path.join(indir, k), 'rb').read() for k in ('encryptHeader.dat', 'header.dat', 'description.dat', 'logo.png', 'data.dat', 'version.txt')}
    with open(dst, 'wb') as fh:
        fh.write(encrypt_parts(parts, master))


if __name__ == '__main__':
    mode, a, b = sys.argv[1:4]
    key = open(sys.argv[4], 'rb').read() if len(sys.argv) > 4 else KEY_PES21
    (decrypt_file if mode == 'dec' else encrypt_dir)(a, b, key)
