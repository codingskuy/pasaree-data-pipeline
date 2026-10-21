"""Amplop idempoten event Pasaree dan pemetaan ke registry 11 event Titeny.

Sumber kontrak: KONTEKS-LINTAS-DIVISI.md §3 dan ADR-0001. Modul ini TIDAK menambah
`event_type` di luar registry Titeny.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .event_katalog import validasi_event

SCHEMA_VERSION = "1.0.0"
SOURCE = "pasaree"

# Registry terkunci Titeny V1 (11 event_type). Read-only: repo ini hanya memproduksi.
REGISTRY_TITENY = frozenset(
    {
        "harga.diperbarui",
        "stok.berubah",
        "stok.snapshot_harian",
        "transaksi.dibuat",
        "lapak.status_berubah",
        "panen.dicatat",
        "logistik.biaya_diperbarui",
        "vendor.status_berubah",
        "cuaca.diperbarui",
        "kalender.dikunci",
        "keuangan.ringkasan_harian",
    }
)

# Event_type yang diproduksi Pasaree ke Titeny (ADR-0001 butir 2).
JENIS_DIPRODUKSI_PASAREE = frozenset(
    {"transaksi.dibuat", "lapak.status_berubah", "logistik.biaya_diperbarui", "vendor.status_berubah"}
)

# Pemetaan event katalog lokal -> registry Titeny. None = internal Pasaree (hanya untuk
# pencarian-katalog / metrik-lapak-aktif), tidak diteruskan ke Titeny.
PEMETAAN_LOKAL = {
    "produk.dibuat": None,
    "harga.berubah": None,
    "stok.berubah": None,
    # Diteruskan sebagai lapak.status_berubah hanya bila payload memuat `lapak_status`.
    "tayang.berubah": "lapak.status_berubah",
}

RE_EVENT_ID = re.compile(r"^evt_(\d{8})_(\d{6})$")
RE_WAKTU_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

MEDAN_AMPLOP = ("event_id", "event_type", "schema_version", "source", "occurred_at", "received_at", "batch_id", "payload")


class AmplopTidakValid(ValueError):
    """Amplop/event gagal validasi; `galat` memuat daftar alasan."""

    def __init__(self, galat: list[str]):
        super().__init__("; ".join(galat))
        self.galat = galat


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PembuatEventId:
    """Pembuat `event_id` `evt_YYYYMMDD_NNNNNN`.

    Nomor urut per hari (tanggal UTC dari `occurred_at`). Idempoten: kunci sumber yang
    sama (mis. ULID event lokal) selalu mendapat `event_id` yang sama, sehingga retry
    produsen tidak melahirkan event baru.
    """

    BATAS = 999_999

    def __init__(self) -> None:
        self._urut: dict[str, int] = {}
        self._peta: dict[str, str] = {}

    def buat(self, kunci_sumber: str, occurred_at: str) -> str:
        if kunci_sumber in self._peta:
            return self._peta[kunci_sumber]
        hari = _parse_utc(occurred_at).strftime("%Y%m%d")
        n = self._urut.get(hari, 0) + 1
        if n > self.BATAS:
            raise OverflowError(f"nomor urut event habis untuk {hari}")
        self._urut[hari] = n
        event_id = f"evt_{hari}_{n:06d}"
        self._peta[kunci_sumber] = event_id
        return event_id


def validasi_amplop(a: dict) -> list[str]:
    """Kembalikan daftar kesalahan amplop. Kosong berarti valid."""
    galat: list[str] = []
    for k in MEDAN_AMPLOP:
        if k not in a or a[k] in (None, ""):
            galat.append(f"{k} wajib ada")
    if galat:
        return galat
    if not RE_EVENT_ID.match(a["event_id"]):
        galat.append("event_id harus berformat evt_YYYYMMDD_NNNNNN")
    if a["event_type"] not in REGISTRY_TITENY:
        galat.append("event_type di luar registry Titeny")
    if a["source"] != SOURCE:
        galat.append(f"source harus '{SOURCE}'")
    for k in ("occurred_at", "received_at"):
        if not RE_WAKTU_UTC.match(str(a[k])):
            galat.append(f"{k} harus ISO-8601 UTC (akhiran Z)")
    if not isinstance(a["payload"], dict):
        galat.append("payload harus objek")
    return galat


def bungkus(
    event: dict,
    pembuat_id: PembuatEventId,
    batch_id: str,
    received_at: str | None = None,
) -> dict | None:
    """Bungkus event katalog lokal jadi amplop registry Titeny.

    Mengembalikan None bila event bersifat internal (tidak dipetakan ke Titeny).
    Melempar AmplopTidakValid bila event sumber tidak valid.
    """
    galat = validasi_event(event)
    if galat:
        raise AmplopTidakValid(galat)
    tipe = PEMETAAN_LOKAL[event["jenis"]]
    if tipe is None or (event["jenis"] == "tayang.berubah" and "lapak_status" not in event):
        return None
    amplop = {
        "event_id": pembuat_id.buat(event["id"], event["waktu"]),
        "event_type": tipe,
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "occurred_at": event["waktu"],
        "received_at": received_at or _fmt_utc(datetime.now(timezone.utc)),
        "batch_id": batch_id,
        "payload": {k: v for k, v in event.items() if k not in ("id", "jenis", "waktu")},
    }
    galat = validasi_amplop(amplop)
    if galat:
        raise AmplopTidakValid(galat)
    return amplop
