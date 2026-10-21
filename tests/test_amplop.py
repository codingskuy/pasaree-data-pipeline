import pytest

from pipeline.amplop import (
    JENIS_DIPRODUKSI_PASAREE,
    PEMETAAN_LOKAL,
    REGISTRY_TITENY,
    AmplopTidakValid,
    PembuatEventId,
    bungkus,
    validasi_amplop,
)

ULID_A = "01J0000000000000000000001"
ULID_B = "01J0000000000000000000002"


def ev(**kw):
    e = {"id": ULID_A, "jenis": "tayang.berubah", "waktu": "2026-01-01T00:00:00Z",
         "lapak_id": "01J0000000000000000000000", "produk_id": "01J0000000000000000000009",
         "lapak_status": "BEKU"}
    e.update(kw)
    return e


def test_registry_terkunci_11_event():
    assert len(REGISTRY_TITENY) == 11


def test_jenis_diproduksi_pasaree_subset_registry():
    assert JENIS_DIPRODUKSI_PASAREE <= REGISTRY_TITENY
    assert JENIS_DIPRODUKSI_PASAREE == {
        "transaksi.dibuat", "lapak.status_berubah", "logistik.biaya_diperbarui", "vendor.status_berubah"}


def test_pemetaan_tidak_menambah_event_type_di_luar_registry():
    for tujuan in PEMETAAN_LOKAL.values():
        assert tujuan is None or tujuan in REGISTRY_TITENY


def test_bungkus_amplop_lengkap():
    a = bungkus(ev(), PembuatEventId(), "bat_001", received_at="2026-01-01T00:00:05Z")
    assert a["event_id"] == "evt_20260101_000001"
    assert a["event_type"] == "lapak.status_berubah"
    assert a["source"] == "pasaree"
    assert a["schema_version"]
    assert a["occurred_at"] == "2026-01-01T00:00:00Z"
    assert a["received_at"] == "2026-01-01T00:00:05Z"
    assert a["batch_id"] == "bat_001"
    assert a["payload"]["lapak_status"] == "BEKU"
    assert validasi_amplop(a) == []


def test_event_internal_tidak_diteruskan_ke_titeny():
    for jenis in ("produk.dibuat", "harga.berubah", "stok.berubah"):
        assert bungkus(ev(jenis=jenis), PembuatEventId(), "b") is None
    tanpa_status = {k: v for k, v in ev().items() if k != "lapak_status"}
    assert bungkus(tanpa_status, PembuatEventId(), "b") is None


def test_event_id_idempoten_per_ulid_dan_urut_per_hari():
    p = PembuatEventId()
    a1 = bungkus(ev(id=ULID_A), p, "b")
    a1b = bungkus(ev(id=ULID_A), p, "b")  # retry produsen
    a2 = bungkus(ev(id=ULID_B), p, "b")
    hari_lain = bungkus(ev(id="01J0000000000000000000003", waktu="2026-01-02T01:00:00Z"), p, "b")
    assert a1["event_id"] == a1b["event_id"] == "evt_20260101_000001"
    assert a2["event_id"] == "evt_20260101_000002"
    assert hari_lain["event_id"] == "evt_20260102_000001"


def test_event_id_overflow():
    p = PembuatEventId()
    p._urut["20260101"] = PembuatEventId.BATAS
    with pytest.raises(OverflowError):
        p.buat("x", "2026-01-01T00:00:00Z")


def test_event_sumber_tidak_valid_ditolak():
    with pytest.raises(AmplopTidakValid):
        bungkus(ev(jenis="tidak.dikenal"), PembuatEventId(), "b")


@pytest.mark.parametrize("ubah,pesan", [
    ({"event_id": "evt_2026_1"}, "event_id"),
    ({"event_type": "produk.dibuat"}, "registry"),
    ({"source": "lumbung"}, "source"),
    ({"occurred_at": "2026-01-01T07:00:00+07:00"}, "occurred_at"),
    ({"received_at": ""}, "received_at"),
    ({"batch_id": None}, "batch_id"),
    ({"schema_version": ""}, "schema_version"),
])
def test_validasi_amplop_menolak(ubah, pesan):
    a = bungkus(ev(), PembuatEventId(), "b", received_at="2026-01-01T00:00:05Z")
    a.update(ubah)
    assert any(pesan in g for g in validasi_amplop(a))
