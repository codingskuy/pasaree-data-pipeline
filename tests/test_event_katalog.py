import pytest

from pipeline.event_katalog import validasi_event

BASE = {
    "id": "01J00000000000000000000001",
    "jenis": "harga.berubah",
    "waktu": "2026-01-01T00:00:00Z",
    "lapak_id": "01J00000000000000000000000",
    "produk_id": "01J00000000000000000000002",
    "harga_idr": 25000,
}


def tanpa(*kunci):
    return {k: v for k, v in BASE.items() if k not in kunci}


def test_event_valid():
    assert validasi_event(BASE) == []


@pytest.mark.parametrize("ubah,pesan", [
    ({"jenis": "x.y"}, "jenis"),
    ({"id": "01J0000000000000000000001"}, "ULID"),          # 25 karakter
    ({"id": "01J0000000000000000000000I"}, "ULID"),         # huruf terlarang I
    ({"produk_id": "abc"}, "produk_id"),
    ({"waktu": "2026-01-01 00:00:00"}, "waktu"),
    ({"waktu": "2026-01-01T07:00:00+07:00"}, "waktu"),
    ({"waktu": "2026-13-45T00:00:00Z"}, "waktu"),
    ({"harga_idr": 25000.5}, "harga_idr"),
    ({"harga_idr": "25000"}, "harga_idr"),
    ({"harga_idr": True}, "harga_idr"),
    ({"harga_idr": -1}, "harga_idr"),
    ({"stok": -3}, "stok"),
])
def test_event_rusak(ubah, pesan):
    assert any(pesan in g for g in validasi_event({**BASE, **ubah}))


@pytest.mark.parametrize("kunci", ["id", "waktu", "lapak_id", "produk_id"])
def test_medan_wajib(kunci):
    assert any(kunci in g for g in validasi_event(tanpa(kunci)))


def test_bukan_objek():
    assert validasi_event("bukan dict") != []
