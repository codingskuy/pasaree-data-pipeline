from pathlib import Path

import pytest

from pipeline.alur import AlurEvent, IndeksPencarianMemori, KonfigurasiTidakValid, muat_konfigurasi
from pipeline.dlq import AntreanSuratMati

CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "pipeline.yaml"
PROD = "01J00000000000000000000009"


def ev(n, waktu="2026-01-01T00:00:00Z", jenis="harga.berubah", **kw):
    e = {"id": f"01J0000000000000000000{n:04d}", "jenis": jenis, "waktu": waktu,
         "lapak_id": "01J00000000000000000000000", "produk_id": PROD}
    if jenis == "harga.berubah":
        e["harga_idr"] = 25000
    e.update(kw)
    return e


class Rekam:
    def __init__(self, gagal_kali=0):
        self.diterima, self.gagal_kali = [], gagal_kali

    def __call__(self, e):
        if self.gagal_kali > 0:
            self.gagal_kali -= 1
            raise RuntimeError("tujuan mati")
        self.diterima.append(e)


def alur(**gagal):
    cfg = muat_konfigurasi(CFG_PATH)
    h = {k["nama"]: Rekam(gagal.get(k["nama"], 0)) for k in cfg["konsumen"]}
    tidur = []
    dlq = AntreanSuratMati()
    return AlurEvent(cfg, h, dlq, tidur.append), h, dlq, tidur


# --- konfigurasi / konsumen tercatat
def test_konsumen_tercatat_di_config():
    cfg = muat_konfigurasi(CFG_PATH)
    nama = {k["nama"] for k in cfg["konsumen"]}
    assert {"pencarian-katalog", "metrik-lapak-aktif", "titeny"} <= nama
    assert cfg["retry_detik"] == [5, 30, 300]


def test_config_tanpa_konsumen_wajib_ditolak(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("tujuan: [pencarian-katalog, metrik-lapak-aktif]\nkonsumen:\n  - nama: pencarian-katalog\n")
    with pytest.raises(KonfigurasiTidakValid):
        muat_konfigurasi(p)


def test_handler_harus_cocok_dengan_konsumen_tercatat():
    cfg = muat_konfigurasi(CFG_PATH)
    with pytest.raises(KonfigurasiTidakValid):
        AlurEvent(cfg, {"pencarian-katalog": Rekam(), "liar": Rekam()})


# --- skema rusak
def test_skema_rusak_masuk_dlq_dan_tidak_disalurkan():
    a, h, dlq, _ = alur()
    assert a.proses(ev(1, harga_idr=1.5)) == "ditolak"
    assert a.proses(ev(2, waktu="kemarin")) == "ditolak"
    assert a.proses({"jenis": "harga.berubah"}) == "ditolak"
    assert len(dlq) == 3 and all(d.tujuan == "validasi" for d in dlq.entri)
    assert all(not r.diterima for r in h.values())


# --- duplikat
def test_event_duplikat_disalurkan_sekali():
    a, h, dlq, _ = alur()
    assert a.proses(ev(1)) == "disalurkan"
    assert a.proses(ev(1)) == "duplikat"
    assert len(h["pencarian-katalog"].diterima) == 1 and len(dlq) == 0


# --- urutan terbalik
def test_urutan_terbalik_event_lama_tidak_menimpa_yang_baru():
    cfg = muat_konfigurasi(CFG_PATH)
    indeks = IndeksPencarianMemori()
    h = {k["nama"]: Rekam() for k in cfg["konsumen"]}
    h["pencarian-katalog"] = indeks
    a = AlurEvent(cfg, h, AntreanSuratMati(), lambda s: None)
    assert a.proses(ev(2, waktu="2026-01-01T10:00:00Z", harga_idr=30000)) == "disalurkan"
    assert a.proses(ev(1, waktu="2026-01-01T09:00:00Z", harga_idr=25000)) == "usang"
    assert indeks.dokumen[PROD]["harga_idr"] == 30000
    assert indeks.dokumen[PROD]["diperbarui_pada"] == "2026-01-01T10:00:00Z"


def test_urutan_terbalik_berlaku_per_jenis_dan_produk():
    a, h, _, _ = alur()
    a.proses(ev(2, waktu="2026-01-01T10:00:00Z", jenis="stok.berubah", stok=5))
    # jenis berbeda dengan waktu lebih lama tetap diproses
    assert a.proses(ev(1, waktu="2026-01-01T09:00:00Z")) == "disalurkan"


# --- penyaluran per konsumen
def test_filter_jenis_event_per_konsumen():
    a, h, _, _ = alur()
    a.proses(ev(1))  # harga.berubah: hanya pencarian
    assert len(h["pencarian-katalog"].diterima) == 1
    assert h["metrik-lapak-aktif"].diterima == [] and h["titeny"].diterima == []


# --- retry + DLQ
def test_retry_5_30_300_lalu_dlq_tanpa_menghalangi_konsumen_lain():
    a, h, dlq, tidur = alur(**{"metrik-lapak-aktif": 99})
    e = ev(1, jenis="stok.berubah", stok=3)
    assert a.proses(e) == "disalurkan"
    assert tidur == [5, 30, 300]
    assert len(dlq) == 1 and dlq.entri[0].tujuan == "metrik-lapak-aktif" and dlq.entri[0].percobaan == 4
    assert len(h["pencarian-katalog"].diterima) == 1


def test_pulih_sebelum_retry_habis():
    a, h, dlq, tidur = alur(**{"pencarian-katalog": 2})
    a.proses(ev(1))
    assert tidur == [5, 30] and len(dlq) == 0 and len(h["pencarian-katalog"].diterima) == 1


def test_indeks_pencarian_memori_memuat_event_berurutan():
    i = IndeksPencarianMemori()
    i(ev(1))
    i(ev(2, jenis="stok.berubah", stok=7, waktu="2026-01-01T01:00:00Z"))
    d = i.dokumen[PROD]
    assert d["harga_idr"] == 25000 and d["stok"] == 7
