import json

from pipeline.amplop import PembuatEventId, bungkus
from pipeline.dlq import AntreanSuratMati
from pipeline.ingest import PATH_INGEST, PengirimEvent


def amplop(eid_ulid="01J00000000000000000000001"):
    e = {"id": eid_ulid, "jenis": "tayang.berubah", "waktu": "2026-01-01T00:00:00Z",
         "lapak_id": "01J00000000000000000000000", "produk_id": "01J00000000000000000000009",
         "lapak_status": "AKTIF"}
    return bungkus(e, PembuatEventId(), "bat_1", received_at="2026-01-01T00:00:05Z")


class Palsu:
    def __init__(self, *respons):
        self.respons = list(respons)
        self.panggilan = []

    def __call__(self, url, headers, body):
        self.panggilan.append((url, headers, json.loads(body)))
        r = self.respons.pop(0) if len(self.respons) > 1 else self.respons[0]
        if isinstance(r, Exception):
            raise r
        return r


def pengirim(transport):
    tidur = []
    dlq = AntreanSuratMati()
    return PengirimEvent("http://titeny.lokal/", transport, dlq, tidur.append), tidur, dlq


def test_kirim_sukses_memakai_header_idempotensi_dan_path():
    t = Palsu((200, {}))
    p, tidur, dlq = pengirim(t)
    a = amplop()
    assert p.kirim(a) == "terkirim"
    url, headers, body = t.panggilan[0]
    assert url == "http://titeny.lokal" + PATH_INGEST
    assert headers["X-Idempotency-Key"] == a["event_id"]
    assert body["event_id"] == a["event_id"]
    assert tidur == [] and len(dlq) == 0


def test_duplikat_event_id_diabaikan_tanpa_kirim_ulang():
    t = Palsu((200, {}))
    p, _, _ = pengirim(t)
    a = amplop()
    p.kirim(a)
    assert p.kirim(a) == "duplikat"
    assert len(t.panggilan) == 1


def test_respons_duplikat_dari_server_dianggap_sukses():
    t = Palsu((200, {"status": "duplikat_diabaikan"}))
    p, _, dlq = pengirim(t)
    assert p.kirim(amplop()) == "duplikat"
    assert len(dlq) == 0


def test_retry_5_30_300_lalu_dlq():
    t = Palsu((503, {}))
    p, tidur, dlq = pengirim(t)
    assert p.kirim(amplop()) == "dlq"
    assert len(t.panggilan) == 4  # 1 + 3 retry
    assert tidur == [5, 30, 300]
    assert len(dlq) == 1 and dlq.entri[0].percobaan == 4 and dlq.entri[0].tujuan == "titeny"


def test_pulih_di_retry_kedua():
    t = Palsu((500, {}), (500, {}), (200, {}))
    p, tidur, dlq = pengirim(t)
    assert p.kirim(amplop()) == "terkirim"
    assert tidur == [5, 30] and len(dlq) == 0


def test_galat_jaringan_diulang():
    t = Palsu(ConnectionError("putus"), (200, {}))
    p, tidur, _ = pengirim(t)
    assert p.kirim(amplop()) == "terkirim"
    assert tidur == [5]


def test_4xx_permanen_langsung_dlq_tanpa_retry():
    t = Palsu((422, {}))
    p, tidur, dlq = pengirim(t)
    assert p.kirim(amplop()) == "dlq"
    assert len(t.panggilan) == 1 and tidur == [] and len(dlq) == 1


def test_amplop_rusak_tidak_dikirim():
    t = Palsu((200, {}))
    p, _, dlq = pengirim(t)
    a = amplop()
    del a["batch_id"]
    assert p.kirim(a) == "dlq"
    assert t.panggilan == [] and "batch_id" in dlq.entri[0].alasan
