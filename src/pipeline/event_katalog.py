"""Validasi event katalog Pasaree (PSR-DATA-004).

Aturan (katalog/10-model-data.md + docs/SKEMA_EVENT.md): ID ULID, waktu ISO-8601 UTC,
uang integer IDR (medan berakhiran `_idr`), stok integer >= 0.
"""
import re
from datetime import datetime

JENIS_WAJIB = {"produk.dibuat", "harga.berubah", "stok.berubah", "tayang.berubah"}

# ULID: 26 karakter Crockford base32 (tanpa I, L, O, U); karakter pertama maks 7.
RE_ULID = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
RE_WAKTU_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
MEDAN_ID = ("id", "lapak_id", "produk_id")


def _int_murni(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def waktu_valid(w) -> bool:
    if not isinstance(w, str) or not RE_WAKTU_UTC.match(w):
        return False
    try:
        datetime.fromisoformat(w.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validasi_event(e: dict) -> list:
    """Kembalikan daftar kesalahan. Kosong berarti valid."""
    if not isinstance(e, dict):
        return ["event harus objek"]
    galat = []
    if e.get("jenis") not in JENIS_WAJIB:
        galat.append("jenis tidak dikenal")
    for k in MEDAN_ID:
        v = e.get(k)
        if not v:
            galat.append(f"{k} wajib ada")
        elif not isinstance(v, str) or not RE_ULID.match(v):
            galat.append(f"{k} harus ULID 26 karakter")
    if not e.get("waktu"):
        galat.append("waktu ISO-8601 UTC wajib ada")
    elif not waktu_valid(e["waktu"]):
        galat.append("waktu harus ISO-8601 UTC (akhiran Z)")
    for k, v in e.items():
        if k.endswith("_idr") and (not _int_murni(v) or v < 0):
            galat.append(f"{k} harus integer nol atau lebih")
    if "stok" in e and (not _int_murni(e["stok"]) or e["stok"] < 0):
        galat.append("stok harus integer nol atau lebih")
    return galat


if __name__ == "__main__":
    contoh = {
        "jenis": "harga.berubah",
        "id": "01J00000000000000000000001",
        "waktu": "2026-01-01T00:00:00Z",
        "lapak_id": "01J00000000000000000000000",
        "produk_id": "01J00000000000000000000002",
        "harga_idr": 25000,
    }
    print(validasi_event(contoh))
