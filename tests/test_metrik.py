import json
from datetime import datetime, timezone

import pytest

from pipeline import metrik
from pipeline.metrik import LapakSnap, ProdukSnap, alasan_tidak_aktif, daftar_berisiko, ekspor_dasbor, hitung_metrik, lapak_aktif

NOW = datetime(2026, 2, 1, tzinfo=timezone.utc)
RECENT = datetime(2026, 1, 25, tzinfo=timezone.utc)


def sehat(id="L1", **kw):
    d = dict(id=id, status="AKTIF",
             produk=[ProdukSnap("TAYANG", stok=5) for _ in range(3)],
             pesanan_selesai=4, subpesanan_total=10, subpesanan_tepat_waktu=10,
             pelanggaran_terbuka=0, penjualan_terakhir=RECENT, durasi_kurasi_jam=[10.0])
    d.update(kw)
    return LapakSnap(**d)


def test_lapak_sehat_aktif():
    assert lapak_aktif(sehat()) and alasan_tidak_aktif(sehat()) == []


@pytest.mark.parametrize("ubah,alasan", [
    ({"status": "BEKU"}, "status_bukan_aktif"),
    ({"produk": [ProdukSnap("TAYANG", 5), ProdukSnap("TAYANG", 5)]}, "produk_tayang_kurang"),  # hanya 2
    ({"produk": [ProdukSnap("TAYANG", 0)] * 3}, "produk_tayang_kurang"),  # stok total 0
    ({"produk": [ProdukSnap("TAYANG", 5)] * 2 + [ProdukSnap("DRAF", 9)]}, "produk_tayang_kurang"),
    ({"pesanan_selesai": 0}, "tanpa_pesanan_selesai"),
    ({"subpesanan_tepat_waktu": 7}, "konfirmasi_di_bawah_80"),
    ({"subpesanan_total": 0, "subpesanan_tepat_waktu": 0}, "konfirmasi_di_bawah_80"),
    ({"pelanggaran_terbuka": 1}, "pelanggaran_terbuka"),
])
def test_syarat_gagal(ubah, alasan):
    assert alasan in alasan_tidak_aktif(sehat(**ubah))
    assert not lapak_aktif(sehat(**ubah))


def test_batas_tepat_konfirmasi_80_persen_lolos():
    assert lapak_aktif(sehat(subpesanan_tepat_waktu=8))


def test_metrik_turunan_dan_target():
    lapak = [sehat("A"), sehat("B"), sehat("C", pesanan_selesai=0), sehat("D", status="BEKU")]
    m = hitung_metrik(lapak)
    assert m["total_lapak_aktif_status"] == 3 and m["lapak_aktif"] == 2
    p = m["metrik"]["persen_lapak_aktif"]
    assert p["nilai"] == pytest.approx(2 / 3) and p["tercapai"] is True
    sepi = hitung_metrik([sehat("A"), sehat("B", pesanan_selesai=0), sehat("C", pesanan_selesai=0)])
    assert sepi["metrik"]["persen_lapak_aktif"]["tercapai"] is False  # 1/3 < 60%


def test_median_kurasi_dan_target_36_jam():
    lapak = [sehat("A", durasi_kurasi_jam=[10, 20]), sehat("B", durasi_kurasi_jam=[40])]
    m = hitung_metrik(lapak)["metrik"]["waktu_kurasi_median_jam"]
    assert m["nilai"] == 20 and m["tercapai"] is True
    lambat = hitung_metrik([sehat("A", durasi_kurasi_jam=[50, 60])])["metrik"]["waktu_kurasi_median_jam"]
    assert lambat["nilai"] == 55 and lambat["tercapai"] is False


def test_konfirmasi_agregat_target_90():
    lapak = [sehat("A", subpesanan_total=10, subpesanan_tepat_waktu=9), sehat("B", subpesanan_total=10, subpesanan_tepat_waktu=9)]
    assert hitung_metrik(lapak)["metrik"]["konfirmasi_tepat_waktu"]["tercapai"] is True
    lapak2 = [sehat("A", subpesanan_total=10, subpesanan_tepat_waktu=8)]
    assert hitung_metrik(lapak2)["metrik"]["konfirmasi_tepat_waktu"]["tercapai"] is False


def test_stok0_kronis_target_15():
    ok = [sehat("A", produk=[ProdukSnap("TAYANG", 5)] * 9 + [ProdukSnap("NONAKTIF_STOK_0", 0, 20)])]  # 10%
    bad = [sehat("A", produk=[ProdukSnap("TAYANG", 5)] * 3 + [ProdukSnap("NONAKTIF_STOK_0", 0, 14)])]  # 25%
    assert hitung_metrik(ok)["metrik"]["stok0_kronis"] == {"nilai": 0.1, "target": 0.15, "arah": "max", "tercapai": True}
    assert hitung_metrik(bad)["metrik"]["stok0_kronis"]["tercapai"] is False


def test_data_kosong_tidak_meledak():
    m = hitung_metrik([])["metrik"]
    assert all(v["nilai"] is None and v["tercapai"] is None for v in m.values())


def test_daftar_berisiko():
    lapak = [
        sehat("OK"),
        sehat("KONF", subpesanan_tepat_waktu=7),
        sehat("STOK0", produk=[ProdukSnap("TAYANG", 5)] * 3 + [ProdukSnap("NONAKTIF_STOK_0", 0, 30)]),
        sehat("SEPI", penjualan_terakhir=datetime(2026, 1, 10, tzinfo=timezone.utc)),  # 22 hari
        sehat("BATAS", penjualan_terakhir=datetime(2026, 1, 11, tzinfo=timezone.utc)),  # tepat 21 hari: aman
        sehat("NOL", penjualan_terakhir=None),
        sehat("BEKU", status="BEKU", penjualan_terakhir=None),  # bukan AKTIF: tidak dinilai
    ]
    r = {x["lapak_id"]: x["sebab"] for x in daftar_berisiko(lapak, NOW)}
    assert r == {
        "KONF": ["konfirmasi_di_bawah_80"],
        "STOK0": ["stok0_kronis"],
        "SEPI": ["tanpa_penjualan_21_hari"],
        "NOL": ["tanpa_penjualan_21_hari"],
    }


def test_ekspor_dasbor_serializable_json():
    out = ekspor_dasbor([sehat("A"), sehat("B", subpesanan_tepat_waktu=1)], NOW)
    d = json.loads(json.dumps(out))
    assert d["dihitung_pada"] == "2026-02-01T00:00:00Z"
    assert d["lapak_aktif_id"] == ["A"]
    assert d["lapak_berisiko"][0]["lapak_id"] == "B"


def test_cli_dari_snapshot_json(tmp_path, capsys):
    snap = {"lapak": [{"id": "A", "status": "AKTIF",
                       "produk": [{"status": "TAYANG", "stok": 3}] * 3,
                       "pesanan_selesai": 2, "subpesanan_total": 4, "subpesanan_tepat_waktu": 4,
                       "penjualan_terakhir": "2026-01-30T00:00:00Z", "durasi_kurasi_jam": [12]}]}
    f = tmp_path / "s.json"
    f.write_text(json.dumps(snap))
    assert metrik.main([str(f), "2026-02-01T00:00:00Z"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["lapak_aktif_id"] == ["A"] and out["lapak_berisiko"] == []
    assert metrik.main([]) == 2
