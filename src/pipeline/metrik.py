"""Metrik lapak aktif dan sumber data dasbor admin (PSR-DATA-003).

Rujukan: metrik/10-lapak-aktif.md (Pasaree-TownHall). Murni fungsi atas snapshot;
tidak membaca/menulis DB sumber. Snapshot sudah dirangkum per jendela 30 hari oleh hulu.
"""
from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Ambang definisi lapak aktif (butir 1-4)
MIN_PRODUK_TAYANG = 3
MIN_PESANAN_SELESAI = 1
AMBANG_KONFIRMASI_LAPAK = 0.80
# Ambang daftar berisiko
HARI_TANPA_PENJUALAN = 21
HARI_STOK0_KRONIS = 14
# Target metrik turunan (Varian 1)
TARGET = {
    "persen_lapak_aktif": ("min", 0.60),
    "waktu_kurasi_median_jam": ("max", 36.0),
    "konfirmasi_tepat_waktu": ("min", 0.90),
    "stok0_kronis": ("max", 0.15),
}
STATUS_KATALOG = ("TAYANG", "NONAKTIF_STOK_0")


@dataclass
class ProdukSnap:
    status: str
    stok: int = 0
    hari_stok_nol: int = 0  # hari berturut-turut stok 0 per snapshot harian


@dataclass
class LapakSnap:
    id: str
    status: str
    produk: list[ProdukSnap] = field(default_factory=list)
    pesanan_selesai: int = 0  # 30 hari
    subpesanan_total: int = 0  # 30 hari
    subpesanan_tepat_waktu: int = 0  # dikonfirmasi <= 2 jam
    pelanggaran_terbuka: int = 0
    penjualan_terakhir: datetime | None = None
    durasi_kurasi_jam: list[float] = field(default_factory=list)  # ajukan -> tayang


def _rasio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def konfirmasi_lapak(l: LapakSnap) -> float | None:
    return _rasio(l.subpesanan_tepat_waktu, l.subpesanan_total)


def rasio_stok0_kronis(l: LapakSnap) -> float | None:
    """Produk stok-0 >= 14 hari / total produk di katalog (TAYANG + NONAKTIF_STOK_0)."""
    katalog = [p for p in l.produk if p.status in STATUS_KATALOG]
    return _rasio(sum(1 for p in katalog if p.hari_stok_nol >= HARI_STOK0_KRONIS), len(katalog))


def alasan_tidak_aktif(l: LapakSnap) -> list[str]:
    """Daftar syarat lapak aktif yang gagal. Kosong berarti lapak aktif."""
    if l.status != "AKTIF":
        return ["status_bukan_aktif"]
    alasan = []
    tayang = [p for p in l.produk if p.status == "TAYANG"]
    if len(tayang) < MIN_PRODUK_TAYANG or sum(p.stok for p in tayang) <= 0:
        alasan.append("produk_tayang_kurang")
    if l.pesanan_selesai < MIN_PESANAN_SELESAI:
        alasan.append("tanpa_pesanan_selesai")
    k = konfirmasi_lapak(l)
    if k is None or k < AMBANG_KONFIRMASI_LAPAK:
        alasan.append("konfirmasi_di_bawah_80")
    if l.pelanggaran_terbuka > 0:
        alasan.append("pelanggaran_terbuka")
    return alasan


def lapak_aktif(l: LapakSnap) -> bool:
    return not alasan_tidak_aktif(l)


def daftar_berisiko(lapak: list[LapakSnap], sekarang: datetime) -> list[dict]:
    """Lapak AKTIF berisiko: konfirmasi < 80%, stok-0 kronis, atau tanpa penjualan 21 hari."""
    hasil = []
    batas = sekarang - timedelta(days=HARI_TANPA_PENJUALAN)
    for l in sorted((x for x in lapak if x.status == "AKTIF"), key=lambda x: x.id):
        sebab = []
        k = konfirmasi_lapak(l)
        if k is not None and k < AMBANG_KONFIRMASI_LAPAK:
            sebab.append("konfirmasi_di_bawah_80")
        r = rasio_stok0_kronis(l)
        if r is not None and r > TARGET["stok0_kronis"][1]:
            sebab.append("stok0_kronis")
        if l.penjualan_terakhir is None or l.penjualan_terakhir < batas:
            sebab.append("tanpa_penjualan_21_hari")
        if sebab:
            hasil.append({"lapak_id": l.id, "sebab": sebab, "konfirmasi_tepat_waktu": k, "rasio_stok0_kronis": r})
    return hasil


def hitung_metrik(lapak: list[LapakSnap]) -> dict:
    """Metrik turunan agregat + status terhadap target."""
    aktif_status = [l for l in lapak if l.status == "AKTIF"]
    n_aktif = sum(1 for l in aktif_status if lapak_aktif(l))
    kurasi = [d for l in aktif_status for d in l.durasi_kurasi_jam]
    katalog = [p for l in aktif_status for p in l.produk if p.status in STATUS_KATALOG]
    nilai = {
        "persen_lapak_aktif": _rasio(n_aktif, len(aktif_status)),
        "waktu_kurasi_median_jam": statistics.median(kurasi) if kurasi else None,
        "konfirmasi_tepat_waktu": _rasio(
            sum(l.subpesanan_tepat_waktu for l in aktif_status), sum(l.subpesanan_total for l in aktif_status)
        ),
        "stok0_kronis": _rasio(sum(1 for p in katalog if p.hari_stok_nol >= HARI_STOK0_KRONIS), len(katalog)),
    }
    hasil = {}
    for nama, v in nilai.items():
        arah, ambang = TARGET[nama]
        tercapai = None if v is None else (v >= ambang if arah == "min" else v <= ambang)
        hasil[nama] = {"nilai": v, "target": ambang, "arah": arah, "tercapai": tercapai}
    return {"total_lapak_aktif_status": len(aktif_status), "lapak_aktif": n_aktif, "metrik": hasil}


def ekspor_dasbor(lapak: list[LapakSnap], sekarang: datetime) -> dict:
    """Sumber data dasbor admin web: ringkasan, daftar lapak aktif, dan lapak berisiko."""
    return {
        "dihitung_pada": sekarang.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ringkasan": hitung_metrik(lapak),
        "lapak_aktif_id": sorted(l.id for l in lapak if lapak_aktif(l)),
        "lapak_berisiko": daftar_berisiko(lapak, sekarang),
    }


def _waktu(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def lapak_dari_dict(d: dict) -> LapakSnap:
    return LapakSnap(
        id=d["id"],
        status=d["status"],
        produk=[ProdukSnap(**p) for p in d.get("produk", [])],
        pesanan_selesai=d.get("pesanan_selesai", 0),
        subpesanan_total=d.get("subpesanan_total", 0),
        subpesanan_tepat_waktu=d.get("subpesanan_tepat_waktu", 0),
        pelanggaran_terbuka=d.get("pelanggaran_terbuka", 0),
        penjualan_terakhir=_waktu(d.get("penjualan_terakhir")),
        durasi_kurasi_jam=list(d.get("durasi_kurasi_jam", [])),
    )


def main(argv: list[str]) -> int:
    """`python -m pipeline.metrik snapshot.json [sekarang-ISO]` -> JSON dasbor ke stdout."""
    if not argv:
        print("pemakaian: python -m pipeline.metrik snapshot.json [sekarang ISO-8601 UTC]", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        lapak = [lapak_dari_dict(x) for x in json.load(f)["lapak"]]
    sekarang = _waktu(argv[1]) if len(argv) > 1 else datetime.now(timezone.utc)
    print(json.dumps(ekspor_dasbor(lapak, sekarang), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
