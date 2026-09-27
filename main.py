# -*- coding: utf-8 -*-
import os, io, re, json, base64, hashlib, struct, time, html, threading, traceback
import urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ============================================================
#  الإعدادات
# ============================================================
BOT_TOKEN = "8789296809:AAGj_sVv3b2gOev9SVDW82v3bLGXk1pSErQ"
BOT_IMAGE_URL ="https://ibb.co/Fk4NSJQC"
DEV_ID = 7093004518
DEV_USERNAME = "@MRDPY"
DEV_TITLE = "المطور"
DEPUTY_USERNAME = "@Zero_Vib"
DEPUTY_TITLE = "نائب المطور"

if not BOT_TOKEN or ":" not in BOT_TOKEN:
    print("FATAL: BOT_TOKEN missing or malformed.")
    raise SystemExit(1)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

DATA_FILE = Path(__file__).parent / "data.json"
DATA_LOCK = threading.Lock()

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_TEXT_LEN = 8192
MAX_JSON_DEPTH = 64
RATE_LIMIT = 10
RATE_WINDOW = 60

# ============================================================
#  المكتبات الاختيارية
# ============================================================
try:
    from Crypto.Cipher import AES, ChaCha20_Poly1305
    from Crypto.Hash import SHA1
    from Crypto.Util.Padding import unpad
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

try:
    from argon2.low_level import hash_secret_raw, Type
    HAVE_ARGON2 = True
except ImportError:
    HAVE_ARGON2 = False


# ============================================================
#  أدوات أمنية + logging
# ============================================================
def _mask(s):
    if not s or len(s) < 8:
        return "***"
    return s[:4] + "…" + s[-4:]


_SECRETS = []


def _register_secret(v):
    if isinstance(v, str) and len(v) >= 8:
        _SECRETS.append(v)


def _scrub(msg):
    if not isinstance(msg, str):
        msg = str(msg)
    for s in _SECRETS:
        if s and s in msg:
            msg = msg.replace(s, _mask(s))
    return msg


def log_info(msg):
    print(f"[INFO ] {_scrub(msg)}", flush=True)


def log_ok(msg):
    print(f"[ OK  ] {_scrub(msg)}", flush=True)


def log_warn(msg):
    print(f"[WARN ] {_scrub(msg)}", flush=True)


def log_err(msg):
    print(f"[FAIL ] {_scrub(msg)}", flush=True)


def log_exc(prefix, exc):
    tb = traceback.format_exc()
    lines = tb.strip().splitlines()
    short = lines[-1] if lines else repr(exc)
    print(f"[FAIL ] {_scrub(prefix)}: {type(exc).__name__}: {_scrub(str(exc))}", flush=True)
    print(f"[FAIL ] {_scrub(short)}", flush=True)


def _safe_name(name):
    if not isinstance(name, str):
        return "config"
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)
    if not name or name in (".", ".."):
        return "config"
    return name[:128]


def _check_depth(obj, depth=0):
    if depth > MAX_JSON_DEPTH:
        raise ValueError("depth")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_depth(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _check_depth(v, depth + 1)
    return True


_RATE = defaultdict(list)
_RATE_LOCK = threading.Lock()


def _rate_ok(user_id):
    now = time.time()
    with _RATE_LOCK:
        bucket = _RATE[user_id]
        bucket[:] = [t for t in bucket if now - t < RATE_WINDOW]
        if len(bucket) >= RATE_LIMIT:
            return False
        bucket.append(now)
        return True


def _esc(s):
    return html.escape(str(s), quote=False)[:512]


_register_secret(BOT_TOKEN)


# ============================================================
#  تخزين البيانات
# ============================================================
def _load_data():
    if DATA_FILE.exists():
        try:
            raw = DATA_FILE.read_bytes()
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError("data too big")
            d = json.loads(raw.decode("utf-8"))
            if not isinstance(d, dict):
                raise ValueError("bad shape")
            log_ok(f"data loaded: {len(d)} keys")
            return d
        except Exception as e:
            log_exc("data load failed", e)
    return {
        "force_sub": False,
        "channels": [],
        "users": [],
        "pending": {},
        "groups": [],
        "active_group": None,
    }


def _save_data(d):
    with DATA_LOCK:
        try:
            tmp = DATA_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(DATA_FILE)
        except Exception as e:
            log_exc("data save failed", e)


DATA = _load_data()

# ============================================================
#  EHI
# ============================================================
L1Key = bytes([0x7e,0x12,0x10,0xf7,0xaa,0xb9,0x56,0xf7,0xa6,0x68,0xbd,0xa6,
               0xe5,0x7f,0xed,0xdb,0x7f,0x84,0xad,0x84,0x0a,0xef,0x8d,0x27,
               0xb1,0xb9,0x69,0x95,0x9b,0xe3,0xab,0x6c])
L2KeyStatic = bytes([0xb2,0xbc,0x61,0x7c,0x32,0xd8,0xb9,0xeb,0x19,0x43,0xa5,
                     0xff,0xa8,0x05,0x1e,0xea])
EooMasterKey = b"null=V5kU5+FFrY\x00"
SideIvs = [
    bytes([0x22,0x1d,0x57,0x23,0x49,0x55,0x5f,0x1d,0x11,0x21,0x33,0x23,0x6b,0x1f,0x4a,0x3f]),
    bytes([0x55,0x43,0x49,0x4c,0x53,0x44,0x3e,0x3f,0x4a,0x6a,0x45,0x39,0x38,0x4e,0x77,0x6a]),
    bytes([0x37,0x4c,0x25,0x41,0x57,0x5e,0x4d,0x53,0x1a,0x3c,0x32,0x7b,0x75,0x43,0x1e,0x5f]),
]
StandardIvs = [
    bytes([0x2c,0x5d,0x11,0x47,0xbb,0xad,0x42,0x2b,0x3b,0x33,0x4d,0x4d,0x23,0x5f,0x1a,0x53]),
    bytes([0x52,0x2b,0x01,0x43,0x3a,0x5e,0x8b,0x2f,0xc7,0x54,0x9e,0x1a,0xd3,0x68,0xe5,0x41]),
    bytes([0x33,0x7a,0x10,0x35,0xaa,0xed,0xf3,0x45,0x8c,0xa1,0x67,0xe9,0x2d,0x74,0xb8,0x39]),
]
ALL_IVS = SideIvs + StandardIvs
CustomAlphabet = "RkLC2QaVMPYgGJW/A4f7qzDb9e+t6Hr0Zp8OlNyjuxKcTw1o5EIimhBn3UvdSFXs"
_STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_TRANS = str.maketrans(CustomAlphabet, _STD)


def _custom_b64_decode(s):
    s = s.replace("?", "").translate(_TRANS)
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _xor_layer(cipher_str, key):
    if not cipher_str.strip():
        return cipher_str
    hex_bytes = _custom_b64_decode(cipher_str[::-1])
    hex_str = hex_bytes.decode("latin-1")
    if len(hex_str) % 2:
        hex_str = "0" + hex_str
    raw = bytes.fromhex(hex_str)
    kl = len(key)
    out = bytearray()
    for i, b in enumerate(raw):
        x = b ^ ord(key[i % kl])
        if x != 0:
            out.append(x)
    return out.decode("utf-8", errors="replace")


def _decode_config_message(s):
    if not s.strip():
        return s
    s2 = s + "=" * (-len(s) % 4)
    raw = base64.b64decode(s2)
    text = raw.decode("utf-16-le", errors="replace")
    kc = ['E', 'H', 'I', 'M', 'S', 'G']
    return "".join(chr(ord(c) ^ ord(kc[i % 6])) for i, c in enumerate(text))


def _xxtea_decrypt(data, key):
    if not data:
        return b""
    if len(data) % 4:
        data += b"\x00" * (4 - len(data) % 4)
    k = list(struct.unpack("<4I", key[:16].ljust(16, b"\x00")))
    n = len(data) // 4
    v = list(struct.unpack(f"<{n}I", data))
    delta = 0x9E3779B9
    rounds = 6 + 52 // n
    s = (rounds * delta) & 0xFFFFFFFF
    y = v[0]
    while s != 0:
        e = (s >> 2) & 3
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((s ^ y) + (k[(p & 3) ^ e] ^ z))
            v[p] = (v[p] - mx) & 0xFFFFFFFF
            y = v[p]
        z = v[n - 1]
        mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((s ^ y) + (k[(0 & 3) ^ e] ^ z))
        v[0] = (v[0] - mx) & 0xFFFFFFFF
        y = v[0]
        s = (s - delta) & 0xFFFFFFFF
    out = struct.pack(f"<{n}I", *v)
    length = v[-1]
    if 0 < length <= n * 4:
        return out[:length]
    return out.rstrip(b"\x00")


def _parse_ehi(file_bytes):
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError("file too big")
    r = io.BytesIO(file_bytes)
    def read_utf():
        b = r.read(2)
        if len(b) < 2:
            raise ValueError("trunc")
        l = struct.unpack(">H", b)[0]
        if l > 4096:
            raise ValueError("utf too long")
        return r.read(l)
    read_utf(); r.seek(8, 1)
    read_utf(); r.seek(8, 1)
    b = r.read(4)
    if len(b) < 4:
        raise ValueError("trunc")
    p_len = struct.unpack(">I", b)[0]
    if p_len > MAX_FILE_BYTES:
        raise ValueError("payload too big")
    r.seek(8, 1)
    return r.read(p_len)


def _aes_cbc_dec(ct, key, iv):
    return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ct), 16)


_PY_FIELDS = ["configAesKey", "configIdentifier", "configSalt", "configTimestamp",
              "configExpiryTimestamp", "lockModes", "lockModesHash", "configHwid",
              "configLockMobileOperatorId"]
_ALWAYS_STR = {"configTimestamp", "configExpiryTimestamp"}


def _py_str(v):
    if v is None: return ""
    if isinstance(v, bool): return "True" if v else "False"
    if isinstance(v, float) and v == int(v): return str(int(v))
    return str(v)


def _truthy(v):
    if v is None: return False
    if isinstance(v, str): return v != ""
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return v != 0
    return True


def _master_key(cfg):
    sb = []
    for f in _PY_FIELDS:
        v = cfg.get(f)
        if f in _ALWAYS_STR:
            sb.append(_py_str(0 if v is None else v)); continue
        if v is None: v = ""
        if _truthy(v): sb.append(_py_str(v))
    return hashlib.sha256("".join(sb).encode()).digest()


def _clean_inner(cfg, salt_key):
    out = {}
    for k, v in cfg.items():
        if not isinstance(v, str) or not v.strip():
            out[k] = v
            continue
        if len(v) > MAX_TEXT_LEN:
            out[k] = v
            out[f"_undecoded_{k}"] = True
            continue
        decrypted = None
        method = None
        if k == "configMessage":
            try:
                decrypted = _decode_config_message(v)
                method = "utf16-xor"
            except Exception:
                pass
        if decrypted is None or decrypted == v:
            try:
                candidate = _xor_layer(v, salt_key)
                if candidate and candidate != v:
                    decrypted = candidate
                    method = "xor-layer"
            except Exception:
                pass
        if decrypted is None or decrypted == v:
            try:
                padded = v + "=" * (-len(v) % 4)
                raw = base64.b64decode(padded, validate=False)
                txt = raw.decode("utf-8", errors="ignore")
                if txt and txt != v and any(c.isprintable() and ord(c) < 128 for c in txt):
                    decrypted = txt
                    method = "base64"
            except Exception:
                pass
        if decrypted is None or decrypted == v:
            try:
                raw = _custom_b64_decode(v)
                txt = raw.decode("utf-8", errors="ignore")
                if txt and txt != v:
                    decrypted = txt
                    method = "custom-b64"
            except Exception:
                pass
        if decrypted and decrypted != v and method:
            out[k] = decrypted
            out[f"_decoded_{k}"] = method
        else:
            out[k] = v
            if k != "overwriteServerData":
                out[f"_undecoded_{k}"] = True
    return out


def decrypt_ehi(file_bytes):
    if not (HAVE_CRYPTO and HAVE_ARGON2):
        raise ValueError("deps")
    payload = _parse_ehi(file_bytes)
    if not payload:
        raise ValueError("bad")
    config = None
    is_bypass = False
    for idx, iv in enumerate(ALL_IVS):
        try:
            l1 = _aes_cbc_dec(payload, L1Key, iv)
        except Exception:
            continue
        parts = l1.decode("latin-1").split(":")
        if len(parts) < 3:
            continue
        try:
            iv2 = base64.b64decode(parts[0])
            garbage = _aes_cbc_dec(base64.b64decode(parts[2]), L2KeyStatic, iv2)
        except Exception:
            continue
        final = _xxtea_decrypt(garbage, EooMasterKey)
        i = final.find(b"{")
        if i < 0:
            continue
        try:
            config = json.loads(final[i:].decode("utf-8", errors="replace"))
            is_bypass = idx < len(SideIvs)
            log_info(f"EHI layer1 ok at iv#{idx} bypass={is_bypass}")
            break
        except Exception:
            continue
    if config is None:
        raise ValueError("ehi")
    salt = config.get("configSalt") or "EVZJNI"
    if is_bypass:
        parsed = config
    else:
        aaa = _xor_layer(config.get("configData", ""), salt)
        raw = base64.b64decode(aaa)
        if len(raw) <= 50 or len(raw) > MAX_FILE_BYTES:
            raise ValueError("short/long")
        tc = struct.unpack("<I", raw[1:5])[0]
        mc = struct.unpack("<I", raw[5:9])[0]
        par = raw[9]
        if tc > 100 or mc > 2_000_000 or par > 64:
            raise ValueError("argon bounds")
        salt_b = raw[0x0a:0x1a]
        nonce = raw[0x1a:0x32]
        aad = raw[:0x1a]
        argon = hash_secret_raw(_master_key(config), salt_b, time_cost=tc,
                                memory_cost=mc, parallelism=par,
                                hash_len=32, type=Type.ID)
        cipher = ChaCha20_Poly1305.new(key=argon, nonce=nonce)
        cipher.update(aad)
        plain = cipher.decrypt_and_verify(raw[0x32:-16], raw[-16:])
        parsed = json.loads(plain)
        log_info("EHI argon+chacha ok")
    parsed = _clean_inner(parsed, salt)
    for f in ("v2rRawJson", "overwriteServerData"):
        if isinstance(parsed.get(f), str):
            s = parsed[f]
            if len(s) > MAX_JSON_BYTES:
                continue
            i, j = s.find("{"), s.rfind("}")
            if i >= 0 and j > i:
                try:
                    parsed[f] = json.loads(s[i:j + 1])
                except Exception:
                    pass
    _check_depth(parsed)
    return parsed


# ============================================================
#  DARK
# ============================================================
DARK_KEY_256 = b"$B&E)H@McQfThWmZq4t7w!z%C*F-JaNd"
DARK_KEY_192 = b"F)J@NcRfUjXn2r4u7x!A%D*G"
DARK_IV = bytes.fromhex("232e39185523184a5723586242200e05")


def _clean(s):
    return "".join(c for c in s if ord(c) < 128)


def _b64d(s):
    s = _clean(s)
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.replace("-", "+").replace("_", "/")
    s = re.sub(r"\s", "", s)
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _dark_dec(d, k):
    return AES.new(k, AES.MODE_CFB, iv=DARK_IV, segment_size=128).decrypt(d)


def _unpack(data, depth=0):
    if depth > MAX_JSON_DEPTH:
        raise ValueError("depth")
    pos = 0
    def read(n):
        nonlocal pos
        r = data[pos:pos + n]; pos += n; return r
    def up():
        nonlocal pos
        if pos >= len(data): return None
        b = data[pos]; pos += 1
        if b <= 0x7f: return b
        if b >= 0xe0: return b - 256
        if 0x80 <= b <= 0x8f: return {up(): up() for _ in range(b & 0x0f)}
        if 0x90 <= b <= 0x9f: return [up() for _ in range(b & 0x0f)]
        if 0xa0 <= b <= 0xbf: return read(b & 0x1f).decode(errors="ignore")
        if b == 0xc0: return None
        if b == 0xd9:
            n = data[pos]; pos += 1
            return read(n).decode(errors="ignore")
        if b == 0xda:
            n = int.from_bytes(read(2), "big")
            return read(n).decode(errors="ignore")
        if b == 0xc4:
            n = data[pos]; pos += 1
            return read(n)
        if b == 0xc5:
            n = int.from_bytes(read(2), "big")
            return read(n)
        if b == 0xde:
            n = int.from_bytes(read(2), "big")
            return {up(): up() for _ in range(n)}
        return None
    return up()


def _fix(o):
    if isinstance(o, dict):
        n = {}
        for k, v in o.items():
            if k == "Password": continue
            nk = k.replace("Encrypted", "") if k.startswith("Encrypted") else k
            if isinstance(v, bytes):
                try: n[nk] = _dark_dec(v, DARK_KEY_192).decode(errors="ignore")
                except Exception: n[nk] = v
            elif isinstance(v, list) and v and isinstance(v[0], int):
                try: n[nk] = _dark_dec(bytes(v), DARK_KEY_192).decode(errors="ignore")
                except Exception: n[nk] = v
            else: n[nk] = _fix(v)
        return n
    if isinstance(o, list): return [_fix(x) for x in o]
    return o


def decrypt_dark(link):
    if not HAVE_CRYPTO:
        raise ValueError("deps")
    outer = json.loads(_b64d(link))
    dec1 = _dark_dec(_b64d(outer["encryptedLockedConfig"]), DARK_KEY_256)
    un1 = _unpack(dec1)
    if not un1 or "EncryptedLockedConfig" not in un1:
        raise ValueError("dark protected")
    return _fix(_unpack(_dark_dec(un1["EncryptedLockedConfig"], DARK_KEY_192)))


# ============================================================
#  SLIPNET
# ============================================================
SLIP_KEY = bytes.fromhex("214F052025B2F949605A5429EC3D5FA80C2022C168AD946E68852D447214DBD3")
SLIP_LABELS = {
    0: "Version", 1: "Type", 2: "Remark/Name", 3: "SNI/Host", 7: "Congestion Control",
    8: "Socks Port", 9: "Local Host", 11: "DNSTT PubKey", 15: "SSH Username",
    16: "SSH Password", 17: "SSH Port", 19: "SSH Real Host", 22: "UDP Mode",
    23: "Auth Mode", 28: "TLS Port", 32: "V2Ray UUID:Key", 37: "DNS Server", 53: "HTTP Port",
}


def decrypt_slip(link):
    if not HAVE_CRYPTO:
        raise ValueError("deps")
    d = _b64d(link)
    c = AES.new(SLIP_KEY, AES.MODE_GCM, nonce=d[1:13])
    pt = c.decrypt_and_verify(d[13:-16], d[-16:]).decode()
    fields = pt.rstrip("|").split("|")
    out = {}
    for i, v in enumerate(fields):
        if str(v).strip() == "": continue
        out[SLIP_LABELS.get(i, f"Field_{i:02d}")] = v
    return out


# ============================================================
#  NETMOD / HAT
# ============================================================
def decrypt_netmod(text):
    if not HAVE_CRYPTO:
        raise ValueError("deps")
    txt = _clean(text.strip())
    if "://" in txt: txt = txt.split("://", 1)[1]
    txt = re.sub(r"\s", "", txt).replace("-", "+").replace("_", "/")
    txt += "=" * (-len(txt) % 4)
    data = base64.b64decode(txt)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("big")
    for k in [b"<n3t5yn4^n3tm0d>", b"_netsyna_netmod_", b"nicetrybuddygoon"]:
        try:
            pt = AES.new(k, AES.MODE_ECB).decrypt(data)
            try: pt = unpad(pt, 16)
            except Exception:
                l = pt[-1]
                if l < 16: pt = pt[:-l]
            return json.loads(pt)
        except Exception:
            continue
    raise ValueError("netmod")


def decrypt_hat(text):
    if not HAVE_CRYPTO:
        raise ValueError("deps")
    txt = _clean(text.strip())
    if "://" in txt: txt = txt.split("://", 1)[1]
    txt = re.sub(r"\s", "", txt)
    txt += "=" * (-len(txt) % 4)
    data = base64.b64decode(txt)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("big")
    key = hashlib.sha1(b"8515D40BD04D8C97").digest()[:16]
    pt = AES.new(key, AES.MODE_ECB).decrypt(data)
    try: pt = unpad(pt, 16)
    except Exception: pt = pt.rstrip(b"\x00 \n\r")
    return json.loads(pt)


# ============================================================
#  NPVT / DNS
# ============================================================
def decrypt_npvt(text):
    txt = _clean(text)
    raw = txt.split("://", 1)[1] if "://" in txt else txt
    raw = re.sub(r"\s", "", raw)
    raw += "=" * (-len(raw) % 4)
    j = json.loads(base64.b64decode(raw).decode())
    out = {}
    for k, v in j.items():
        if isinstance(v, str) and v.startswith("npvs1:"):
            b = v[6:]; b += "=" * (-len(b) % 4)
            try: out[k] = base64.b64decode(b).decode()
            except Exception: out[k] = b
        else: out[k] = v
    return out


def decrypt_dns(text):
    txt = _clean(text)
    raw = txt.split("://", 1)[1]
    raw += "=" * (-len(raw) % 4)
    return json.loads(base64.b64decode(raw).decode())


# ============================================================
#  DISPATCH
# ============================================================
EXT_MAP = {".ehi": "ehi", ".dark": "dark", ".npvt": "npvt", ".dns": "dns"}


def _detect(filename, raw):
    ext = Path(filename or "").suffix.lower()
    if ext in EXT_MAP:
        return EXT_MAP[ext]
    text = raw.decode("utf-8", errors="ignore")
    low = text.lower()
    if "darktunnel://" in low: return "dark"
    if "slipnet-enc://" in low: return "slipnet"
    if low.startswith("npvt-"): return "npvt"
    if low.startswith("dns://"): return "dns"
    return "auto"


def _decrypt(kind, raw, filename=""):
    if kind == "ehi":
        return {"_type": "EHI", "data": decrypt_ehi(raw)}
    text = raw.decode("utf-8", errors="ignore").strip()
    low = text.lower()
    if kind == "dark" or "darktunnel://" in low:
        m = re.search(r"darktunnel://[A-Za-z0-9+/=_-]+", text, re.IGNORECASE)
        return {"_type": "DARKTUNNEL", "data": decrypt_dark(m.group(0))}
    if kind == "slipnet" or "slipnet-enc://" in low:
        m = re.search(r"slipnet-enc://[A-Za-z0-9+/=_-]+", text, re.IGNORECASE)
        return {"_type": "SLIPNET", "data": decrypt_slip(m.group(0))}
    if kind == "npvt" or low.startswith("npvt-"):
        return {"_type": "NPVT", "data": decrypt_npvt(text)}
    if kind == "dns" or low.startswith("dns://"):
        return {"_type": "DNS", "data": decrypt_dns(text)}
    try:
        return {"_type": "HAT", "data": decrypt_hat(text)}
    except Exception as e:
        log_info(f"HAT failed: {type(e).__name__}")
    try:
        return {"_type": "NETMOD", "data": decrypt_netmod(text)}
    except Exception as e:
        log_info(f"NETMOD failed: {type(e).__name__}")
    raise ValueError("unknown")


# ============================================================
#  TELEGRAM API
# ============================================================
def _api(method, params=None, files=None):
    if not re.fullmatch(r"[A-Za-z]+", method):
        return {"ok": False}
    url = f"{API}/{method}"
    if files:
        boundary = "----WebKitFormBoundary" + hashlib.md5(str(time.time()).encode()).hexdigest()
        body = b""
        for k, v in (params or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, (fname, fdata) in files.items():
            fname = _safe_name(fname)
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            body += fdata + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        data = urllib.parse.urlencode(params or {}).encode()
        req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False}
    except Exception as e:
        log_info(f"api {method} net: {type(e).__name__}")
        return {"ok": False}


def _send_photo(chat_id, reply_to=None):
    if not BOT_IMAGE_URL:
        return
    if not re.match(r"^https://", BOT_IMAGE_URL):
        return
    p = {"chat_id": chat_id, "photo": BOT_IMAGE_URL}
    if reply_to:
        p["reply_to_message_id"] = reply_to
    return _api("sendPhoto", p)


def _send(chat_id, text, reply_to=None, markup=None, with_photo=True):
    if with_photo:
        _send_photo(chat_id, reply_to)
    p = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"}
    if reply_to:
        p["reply_to_message_id"] = reply_to
    if markup:
        p["reply_markup"] = json.dumps(markup, ensure_ascii=False)
    return _api("sendMessage", p)


def _edit(chat_id, msg_id, text, markup=None):
    p = {"chat_id": chat_id, "message_id": msg_id, "text": text[:4096], "parse_mode": "HTML"}
    if markup:
        p["reply_markup"] = json.dumps(markup, ensure_ascii=False)
    return _api("editMessageText", p)


def _answer_cb(cb_id, text=""):
    return _api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:200]})


def _send_doc(chat_id, fname, fdata, caption=None, reply_to=None, markup=None, with_photo=True):
    if with_photo:
        _send_photo(chat_id, reply_to)
    fname = _safe_name(fname)
    p = {"chat_id": chat_id, "caption": (caption or "")[:1024], "parse_mode": "HTML"}
    if reply_to:
        p["reply_to_message_id"] = reply_to
    if markup:
        p["reply_markup"] = json.dumps(markup, ensure_ascii=False)
    return _api("sendDocument", p, files={"document": (fname, fdata)})


def _get_file(file_id):
    if not isinstance(file_id, str) or len(file_id) > 256:
        return None
    r = _api("getFile", {"file_id": file_id})
    if not r.get("ok"):
        return None
    path = r["result"]["file_path"]
    if ".." in path or path.startswith("/"):
        return None
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                return None
            return data
    except Exception as e:
        log_info(f"file fetch: {type(e).__name__}")
        return None


def _get_chat_member(chat_id, user_id):
    r = _api("getChatMember", {"chat_id": chat_id, "user_id": user_id})
    if not r.get("ok"):
        return None
    return r["result"].get("status")


# ============================================================
#  الاشتراك الإجباري
# ============================================================
def _check_sub(user_id):
    if not DATA.get("force_sub"):
        return True, []
    missing = []
    for ch in DATA.get("channels", []):
        cid = ch.get("chat_id") or ch.get("url")
        if not cid:
            continue
        status = _get_chat_member(cid, user_id)
        if status not in ("member", "administrator", "creator"):
            missing.append(ch)
    return len(missing) == 0, missing


def _sub_markup(missing):
    rows = []
    for ch in missing:
        rows.append([{"text": f"📢 {_esc(ch.get('title', 'قناة'))}", "url": ch.get("url", "")}])
    rows.append([{"text": "✅ تحقق", "callback_data": "check_sub"}])
    return {"inline_keyboard": rows}


def _sub_text():
    return (
        "🔒 <b>الاشتراك الإجباري</b>\n\n"
        "للاستخدام البوت، يجب الاشتراك في القنوات التالية:\n"
        "بعد الاشتراك اضغط <b>✅ تحقق</b>."
    )


# ============================================================
#  المجموعات
# ============================================================
def _is_group_allowed(chat_id):
    cid = str(chat_id)
    if cid == str(DEV_ID):
        return True
    for g in DATA.get("groups", []):
        if str(g.get("chat_id")) == cid and g.get("active", True):
            return True
    return False


def _active_group_url():
    url = DATA.get("active_group")
    if url and re.match(r"^https?://", url):
        return url
    for g in DATA.get("groups", []):
        if g.get("active", True):
            u = g.get("url", "")
            if re.match(r"^https?://", u):
                return u
    return ""


# ============================================================
#  لوحة تحكم المطور
# ============================================================
def _is_dev(user_id):
    try:
        return int(user_id) == DEV_ID
    except Exception:
        return False


def _panel_main():
    fs = "🟢 مفعل" if DATA.get("force_sub") else "🔴 معطل"
    groups = DATA.get("groups", [])
    active_url = _esc(DATA.get("active_group") or "—")
    text = (
        "⚙️ <b>لوحة تحكم المطور</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 المطور: <code>{DEV_ID}</code>\n"
        f"📢 قنوات الاشتراك: <b>{len(DATA.get('channels', []))}</b>\n"
        f"👥 المجموعات: <b>{len(groups)}</b>\n"
        f"🔗 الرابط النشط: <code>{active_url}</code>\n"
        f"👤 المستخدمون: <b>{len(DATA.get('users', []))}</b>\n"
        f"🔐 الاشتراك الإجباري: <b>{fs}</b>\n"
        f"🖼️ الصورة: <b>{'مفعلة' if BOT_IMAGE_URL else 'معطلة'}</b>\n\n"
        "اختر إجراءً:"
    )
    kb = {"inline_keyboard": [
        [{"text": f"🔐 الاشتراك الإجباري: {fs}", "callback_data": "toggle_fs"}],
        [{"text": "➕ إضافة قناة اشتراك", "callback_data": "add_ch"}],
        [{"text": "📋 عرض قنوات الاشتراك", "callback_data": "list_ch"}],
        [{"text": "🗑️ حذف قناة اشتراك", "callback_data": "del_ch"}],
        [{"text": "➕ إضافة مجموعة تفكيك", "callback_data": "add_grp"}],
        [{"text": "📋 عرض المجموعات", "callback_data": "list_grp"}],
        [{"text": "🔗 تعيين الرابط النشط", "callback_data": "set_active"}],
        [{"text": "🗑️ حذف مجموعة", "callback_data": "del_grp"}],
        [{"text": "📊 إحصائيات", "callback_data": "stats"}],
        [{"text": "🔄 تحديث", "callback_data": "refresh"}],
    ]}
    return text, kb


def _panel_channels():
    chs = DATA.get("channels", [])
    if not chs:
        text = "📋 <b>لا توجد قنوات اشتراك مضافة.</b>"
    else:
        lines = ["📋 <b>قنوات الاشتراك:</b>\n"]
        for i, ch in enumerate(chs, 1):
            lines.append(f"{i}. <b>{_esc(ch.get('title', '—'))}</b>\n   <code>{_esc(ch.get('chat_id', '—'))}</code>\n   {_esc(ch.get('url', ''))}")
        text = "\n".join(lines)
    kb = {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "panel"}]]}
    return text, kb


def _panel_groups():
    grps = DATA.get("groups", [])
    if not grps:
        text = "📋 <b>لا توجد مجموعات مضافة.</b>"
    else:
        lines = ["📋 <b>مجموعات التفكيك:</b>\n"]
        active = DATA.get("active_group")
        for i, g in enumerate(grps, 1):
            mark = "🟢" if g.get("active", True) else "🔴"
            star = " ⭐" if g.get("url") == active else ""
            lines.append(f"{mark} <b>{_esc(g.get('title', '—'))}</b>{star}\n   <code>{_esc(g.get('chat_id', '—'))}</code>\n   {_esc(g.get('url', ''))}")
        text = "\n".join(lines)
    kb = {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "panel"}]]}
    return text, kb


# ============================================================
#  بناء المخرجات
# ============================================================
def _strip_meta(obj):
    if isinstance(obj, dict):
        if set(obj.keys()) == {"_type", "data"}:
            return _strip_meta(obj["data"])

        has_markers = any(
            k.startswith("_undecoded_") or k.startswith("_decoded_")
            for k in obj.keys()
        )
        if has_markers:
            out = {}
            for k, v in obj.items():
                if k.startswith("_undecoded_"):
                    field = k[len("_undecoded_"):]
                    if field in {
                        'payload', 'payloadProxyURL', 'sshAddress', 'vpnAddress',
                        'sslSni', 'udpgwPort', 'hwid', 'password', 'enablePassword',
                        'unlockUserAndPassword', 'lockPayload', 'lockPayloadAndServers',
                        'expiryDate',
                    }:
                        out[field] = obj.get(field, v)
                    continue
                if k.startswith("_decoded_"):
                    continue
                out[k] = _strip_meta(v)
            return out

        return {k: _strip_meta(v) for k, v in obj.items()
                if not (k.startswith("_undecoded_")
                        or k.startswith("_decoded_")
                        or k == "_type")}
    if isinstance(obj, list):
        return [_strip_meta(x) for x in obj]
    return obj


def _build_file(result, strip_undecoded=False):
    clean = _strip_meta(result) if strip_undecoded else result
    body = json.dumps(clean, indent=2, ensure_ascii=False)
    return body.encode("utf-8")


def _build_caption(user_id, username, kind, orig_name, is_file, undecoded_count=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uname = f"@{username}" if username else "—"
    warn = f"\n⚠️ <b>UNDECODED</b>  : <b>{undecoded_count}</b>" if undecoded_count else ""
    return (
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID</b>       : <code>{_esc(user_id)}</code>\n"
        f"👤 <b>USERNAME</b> : {_esc(uname)}\n"
        f"📦 <b>TYPE</b>     : <b>{_esc(kind.upper())}</b>\n"
        f"📁 <b>FILE</b>     : <code>{_esc(orig_name if is_file else 'TEXT')}</code>\n"
        f"🕒 <b>DATE</b>     : <code>{now}</code>{warn}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )


def _buttons():
    return {"inline_keyboard": [[
        {"text": DEV_TITLE, "url": f"https://t.me/{DEV_USERNAME.lstrip('@')}"},
        {"text": DEPUTY_TITLE, "url": f"https://t.me/{DEPUTY_USERNAME.lstrip('@')}"},
    ]]}


# ============================================================
#  معالجة الرسائل
# ============================================================
def _handle_start(msg):
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    uid = msg["from"]["id"]
    DATA.setdefault("users", [])
    if uid not in DATA["users"]:
        DATA["users"].append(uid)
        if len(DATA["users"]) > 100000:
            DATA["users"] = DATA["users"][-50000:]
        _save_data(DATA)
    ok, missing = _check_sub(uid)
    if not ok:
        _send(chat_id, _sub_text(), reply_to=msg_id, markup=_sub_markup(missing))
        return
    text = (
        "👋 <b>أهلاً بك</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📥 أرسل <b>ملف</b> التطبيق أو <b>الصق الرابط</b> المشفر.\n\n"
        "الصيغ المدعومة:\n"
        "• <code>.ehi</code> — HTTP Injector\n"
        "• <code>.dark</code> / <code>darktunnel://</code>\n"
        "• <code>slipnet-enc://</code>\n"
        "• <code>npvt-</code>\n"
        "• <code>dns://</code>\n"
        "• HAT / NetMod"
    )
    if _is_dev(uid):
        kb = {"inline_keyboard": [[{"text": "⚙️ لوحة التحكم", "callback_data": "panel"}]]}
        _send(chat_id, text, reply_to=msg_id, markup=kb)
    else:
        _send(chat_id, text, reply_to=msg_id)
    log_ok(f"/start uid={uid}")


def _handle_doc(msg):
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    uid = msg["from"]["id"]
    username = msg["from"].get("username", "")

    if not _rate_ok(uid):
        log_warn(f"rate limited uid={uid}")
        return
    in_registered_group = chat_id < 0 and _is_group_allowed(chat_id)
    if chat_id < 0 and not in_registered_group:
        log_warn(f"group not registered chat={chat_id}")
        return
    if chat_id > 0:
        ok, missing = _check_sub(uid)
        if not ok:
            _send(chat_id, _sub_text(), reply_to=msg_id, markup=_sub_markup(missing))
            return

    doc = msg["document"]
    fname = _safe_name(doc.get("file_name", "config"))
    size = doc.get("file_size", 0)
    log_info(f"doc uid={uid} name={fname} size={size}")
    if size and size > MAX_FILE_BYTES:
        log_err(f"file too big: {size}")
        _send(chat_id, "❌ حدث خطأ", reply_to=msg_id)
        return
    raw = _get_file(doc["file_id"])
    if raw is None:
        log_err("file fetch failed")
        _send(chat_id, "❌ حدث خطأ", reply_to=msg_id)
        return
    log_info(f"file fetched {len(raw)} bytes")
    try:
        kind = _detect(fname, raw)
        log_info(f"detected kind={kind}")
        result = _decrypt(kind, raw, fname)
        out = _build_file(result, strip_undecoded=True)
        caption = _build_caption(uid, username, kind, fname, True, 0)
        stem = Path(fname).stem
        r = _send_doc(chat_id, f"{stem}_decrypted.txt", out,
                      caption=caption, reply_to=msg_id, markup=_buttons())
        if r.get("ok"):
            log_ok(f"sent {kind} uid={uid} out={len(out)}B")
        else:
            log_err(f"send failed: {r.get('description', 'unknown')}")
    except Exception as e:
        log_exc(f"decrypt failed kind={kind if 'kind' in dir() else '?'} name={fname}", e)
        _send(chat_id, "❌ حدث خطأ", reply_to=msg_id)


DEV_PENDING = {"add_channel", "add_group", "set_active"}


def _looks_like_cipher(text):
    low = text.lower()
    return (
        "darktunnel://" in low
        or "slipnet-enc://" in low
        or low.startswith("npvt-")
        or low.startswith("dns://")
        or low.startswith("hat://")
        or low.startswith("netmod://")
        or (len(text) > 40 and re.fullmatch(r"[A-Za-z0-9+/=_\-|\s]+", text) is not None)
    )


def _handle_text(msg):
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    uid = msg["from"]["id"]
    username = msg["from"].get("username", "")
    text = msg["text"].strip()[:MAX_TEXT_LEN]

    if text.startswith("/start"):
        _handle_start(msg)
        return
    if text.startswith("/panel"):
        if _is_dev(uid):
            t, kb = _panel_main()
            _send(chat_id, t, reply_to=msg_id, markup=kb)
        return

    if _is_dev(uid):
        pending = DATA.get("pending", {}).get(str(uid))
        if pending in DEV_PENDING:
            if _looks_like_cipher(text):
                DATA["pending"].pop(str(uid), None)
                _save_data(DATA)
                log_info(f"pending cancelled (cipher text detected) uid={uid}")
            else:
                parts = [p.strip()[:256] for p in text.split("|")]
                if pending == "add_channel":
                    if len(parts) < 3 or not re.match(r"^https?://", parts[1]):
                        _send(chat_id, "❌ الصيغة:\n<code>العنوان | الرابط | chat_id</code>", reply_to=msg_id)
                        return
                    DATA.setdefault("channels", []).append(
                        {"title": parts[0], "url": parts[1], "chat_id": parts[2]})
                    DATA["pending"].pop(str(uid), None)
                    _save_data(DATA)
                    _send(chat_id, f"✅ أُضيفت قناة الاشتراك:\n<b>{_esc(parts[0])}</b>", reply_to=msg_id)
                    log_ok(f"channel added: {parts[0]}")
                    return
                if pending == "add_group":
                    if len(parts) < 3 or not re.match(r"^https?://", parts[1]):
                        _send(chat_id, "❌ الصيغة:\n<code>العنوان | الرابط | chat_id</code>", reply_to=msg_id)
                        return
                    DATA.setdefault("groups", []).append(
                        {"title": parts[0], "url": parts[1], "chat_id": parts[2], "active": True})
                    if not DATA.get("active_group"):
                        DATA["active_group"] = parts[1]
                    DATA["pending"].pop(str(uid), None)
                    _save_data(DATA)
                    _send(chat_id, f"✅ أُضيفت المجموعة:\n<b>{_esc(parts[0])}</b>", reply_to=msg_id)
                    log_ok(f"group added: {parts[0]}")
                    return
                if pending == "set_active":
                    if not re.match(r"^https?://", text):
                        _send(chat_id, "❌ رابط غير صالح", reply_to=msg_id)
                        return
                    DATA["active_group"] = text
                    DATA["pending"].pop(str(uid), None)
                    _save_data(DATA)
                    _send(chat_id, f"✅ تم تعيين الرابط النشط:\n<code>{_esc(text)}</code>", reply_to=msg_id)
                    log_ok("active url set")
                    return

    if not _rate_ok(uid):
        log_warn(f"rate limited uid={uid}")
        return

    in_registered_group = chat_id < 0 and _is_group_allowed(chat_id)
    if chat_id < 0 and not in_registered_group:
        log_warn(f"group not registered chat={chat_id}")
        return
    if chat_id > 0:
        ok, missing = _check_sub(uid)
        if not ok:
            _send(chat_id, _sub_text(), reply_to=msg_id, markup=_sub_markup(missing))
            return

    if not _looks_like_cipher(text):
        if _is_dev(uid):
            _send(chat_id, "ℹ️ ليس نصاً مشفراً معروفاً. /panel للوحة التحكم.", reply_to=msg_id)
        return

    raw = text.encode()
    try:
        kind = _detect("", raw)
        log_info(f"text kind={kind}")
        result = _decrypt(kind, raw)
        out = _build_file(result, strip_undecoded=True)
        caption = _build_caption(uid, username, kind, "", False, 0)
        r = _send_doc(chat_id, "decrypted.txt", out,
                      caption=caption, reply_to=msg_id, markup=_buttons())
        if r.get("ok"):
            log_ok(f"sent {kind} uid={uid} out={len(out)}B")
        else:
            log_err(f"send failed: {r.get('description', 'unknown')}")
    except Exception as e:
        log_exc(f"text decrypt failed uid={uid}", e)
        _send(chat_id, "❌ حدث خطأ", reply_to=msg_id)


def _handle_callback(cb):
    cb_id = cb["id"]
    uid = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb.get("data", "")

    if not isinstance(data, str) or len(data) > 64:
        _answer_cb(cb_id, "❌")
        return

    if data == "check_sub":
        ok, missing = _check_sub(uid)
        if ok:
            _answer_cb(cb_id, "✅ تم التحقق")
            _edit(chat_id, msg_id, "✅ <b>تم التحقق بنجاح.</b>\nأرسل ملفك الآن.")
        else:
            _answer_cb(cb_id, "❌ لم تشترك بعد")
        return

    if not _is_dev(uid):
        _answer_cb(cb_id, "❌")
        return

    if data in ("panel", "refresh"):
        t, kb = _panel_main()
        _edit(chat_id, msg_id, t, kb)
        _answer_cb(cb_id)
    elif data == "toggle_fs":
        DATA["force_sub"] = not DATA.get("force_sub", False)
        _save_data(DATA)
        t, kb = _panel_main()
        _edit(chat_id, msg_id, t, kb)
        _answer_cb(cb_id, "تم")
        log_ok(f"force_sub={DATA['force_sub']}")
    elif data == "add_ch":
        DATA.setdefault("pending", {})[str(uid)] = "add_channel"
        _save_data(DATA)
        _edit(chat_id, msg_id,
              "➕ <b>إضافة قناة اشتراك</b>\n\nأرسل:\n<code>العنوان | الرابط | chat_id</code>",
              {"inline_keyboard": [[{"text": "🔙 إلغاء", "callback_data": "panel"}]]})
        _answer_cb(cb_id)
    elif data == "list_ch":
        t, kb = _panel_channels()
        _edit(chat_id, msg_id, t, kb)
        _answer_cb(cb_id)
    elif data == "del_ch":
        chs = DATA.get("channels", [])
        if not chs:
            _answer_cb(cb_id, "لا توجد قنوات")
            return
        rows = [[{"text": f"🗑️ {_esc(ch.get('title', '—'))}", "callback_data": f"delch_{i}"}] for i, ch in enumerate(chs)]
        rows.append([{"text": "🔙 رجوع", "callback_data": "panel"}])
        _edit(chat_id, msg_id, "🗑️ <b>اختر قناة للحذف:</b>", {"inline_keyboard": rows})
        _answer_cb(cb_id)
    elif data.startswith("delch_"):
        try:
            i = int(data.split("_")[1])
        except Exception:
            _answer_cb(cb_id, "❌")
            return
        chs = DATA.get("channels", [])
        if 0 <= i < len(chs):
            removed = chs.pop(i)
            _save_data(DATA)
            _answer_cb(cb_id, f"حُذفت: {removed.get('title', '')[:30]}")
            log_ok(f"channel removed idx={i}")
        t, kb = _panel_main()
        _edit(chat_id, msg_id, t, kb)
    elif data == "add_grp":
        DATA.setdefault("pending", {})[str(uid)] = "add_group"
        _save_data(DATA)
        _edit(chat_id, msg_id,
              "➕ <b>إضافة مجموعة تفكيك</b>\n\nأرسل:\n<code>العنوان | الرابط | chat_id</code>",
              {"inline_keyboard": [[{"text": "🔙 إلغاء", "callback_data": "panel"}]]})
        _answer_cb(cb_id)
    elif data == "list_grp":
        t, kb = _panel_groups()
        _edit(chat_id, msg_id, t, kb)
        _answer_cb(cb_id)
    elif data == "set_active":
        DATA.setdefault("pending", {})[str(uid)] = "set_active"
        _save_data(DATA)
        _edit(chat_id, msg_id,
              "🔗 <b>تعيين الرابط النشط</b>\n\nأرسل الرابط الذي سيظهر أسفل كل ملف مفكوك:",
              {"inline_keyboard": [[{"text": "🔙 إلغاء", "callback_data": "panel"}]]})
        _answer_cb(cb_id)
    elif data == "del_grp":
        grps = DATA.get("groups", [])
        if not grps:
            _answer_cb(cb_id, "لا توجد مجموعات")
            return
        rows = [[{"text": f"🗑️ {_esc(g.get('title', '—'))}", "callback_data": f"delgrp_{i}"}] for i, g in enumerate(grps)]
        rows.append([{"text": "🔙 رجوع", "callback_data": "panel"}])
        _edit(chat_id, msg_id, "🗑️ <b>اختر مجموعة للحذف:</b>", {"inline_keyboard": rows})
        _answer_cb(cb_id)
    elif data.startswith("delgrp_"):
        try:
            i = int(data.split("_")[1])
        except Exception:
            _answer_cb(cb_id, "❌")
            return
        grps = DATA.get("groups", [])
        if 0 <= i < len(grps):
            removed = grps.pop(i)
            if DATA.get("active_group") == removed.get("url"):
                DATA["active_group"] = grps[0]["url"] if grps else None
            _save_data(DATA)
            _answer_cb(cb_id, f"حُذفت: {removed.get('title', '')[:30]}")
            log_ok(f"group removed idx={i}")
        t, kb = _panel_main()
        _edit(chat_id, msg_id, t, kb)
    elif data == "stats":
        text = (
            "📊 <b>إحصائيات</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 المستخدمون: <b>{len(DATA.get('users', []))}</b>\n"
            f"📢 قنوات الاشتراك: <b>{len(DATA.get('channels', []))}</b>\n"
            f"👥 المجموعات: <b>{len(DATA.get('groups', []))}</b>\n"
            f"🔗 الرابط النشط: <code>{_esc(DATA.get('active_group') or '—')}</code>\n"
            f"🔐 الاشتراك: <b>{'مفعل' if DATA.get('force_sub') else 'معطل'}</b>"
        )
        _edit(chat_id, msg_id, text, {"inline_keyboard": [[{"text": "🔙 رجوع", "callback_data": "panel"}]]})
        _answer_cb(cb_id)


# ============================================================
#  الحلقة الرئيسية
# ============================================================
def main():
    log_info(f"Bot started. Dev ID: {DEV_ID}")
    log_info(f"Crypto: {'OK' if HAVE_CRYPTO else 'MISSING'}  Argon2: {'OK' if HAVE_ARGON2 else 'MISSING'}")
    log_info(f"Image URL: {'set' if BOT_IMAGE_URL else 'none'}")
    offset = 0
    while True:
        try:
            r = _api("getUpdates", {"offset": offset, "timeout": 30})
            if r.get("ok"):
                for upd in r["result"]:
                    offset = upd["update_id"] + 1
                    if "message" in upd:
                        m = upd["message"]
                        if "document" in m:
                            _handle_doc(m)
                        elif "text" in m:
                            _handle_text(m)
                    elif "callback_query" in upd:
                        _handle_callback(upd["callback_query"])
            else:
                desc = r.get("description", "")
                if desc:
                    log_warn(f"getUpdates: {desc}")
                time.sleep(3)
        except KeyboardInterrupt:
            log_info("stopping")
            break
        except Exception as e:
            log_exc("main loop", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
