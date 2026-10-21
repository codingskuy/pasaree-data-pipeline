"""Alur event katalog -> konsumen (pencarian-katalog, metrik-lapak-aktif, titeny).

Urutan: validasi skema -> buang duplikat -> buang event usang (urutan terbalik) ->
salurkan ke tiap konsumen terdaftar dengan retry 5/30/300 dtk lalu DLQ.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import yaml

from .dlq import JEDA_RETRY_DETIK, AntreanSuratMati
from .event_katalog import JENIS_WAJIB, validasi_event

TUJUAN_WAJIB = ("pencarian-katalog", "metrik-lapak-aktif")
TUJUAN_VALIDASI = "validasi"

Handler = Callable[[dict], None]


class KonfigurasiTidakValid(ValueError):
    pass


def muat_konfigurasi(path: str | Path) -> dict:
    """Muat config/pipeline.yaml dan pastikan konsumen tercatat lengkap."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    konsumen = cfg.get("konsumen")
    if not isinstance(konsumen, list) or not konsumen:
        raise KonfigurasiTidakValid("konsumen wajib tercatat")
    nama = [k.get("nama") for k in konsumen]
    if len(set(nama)) != len(nama):
        raise KonfigurasiTidakValid("nama konsumen duplikat")
    for t in list(TUJUAN_WAJIB) + list(cfg.get("tujuan", [])):
        if t not in nama:
            raise KonfigurasiTidakValid(f"tujuan '{t}' belum terdaftar sebagai konsumen")
    for k in konsumen:
        tak_dikenal = set(k.get("jenis_event", [])) - JENIS_WAJIB
        if tak_dikenal:
            raise KonfigurasiTidakValid(f"{k['nama']}: jenis_event tak dikenal {sorted(tak_dikenal)}")
    return cfg


class AlurEvent:
    def __init__(
        self,
        konfigurasi: dict,
        handler: dict[str, Handler],
        dlq: AntreanSuratMati | None = None,
        tidur: Callable[[float], None] = time.sleep,
    ) -> None:
        self.konsumen = {k["nama"]: set(k.get("jenis_event", [])) for k in konfigurasi["konsumen"]}
        tanpa_handler = set(self.konsumen) - set(handler)
        tak_tercatat = set(handler) - set(self.konsumen)
        if tanpa_handler or tak_tercatat:
            raise KonfigurasiTidakValid(
                f"handler tidak cocok dengan konsumen tercatat: tanpa handler={sorted(tanpa_handler)}, "
                f"tak tercatat={sorted(tak_tercatat)}"
            )
        self.handler = handler
        self.jeda = tuple(konfigurasi.get("retry_detik", JEDA_RETRY_DETIK))
        self.dlq = dlq if dlq is not None else AntreanSuratMati()
        self.tidur = tidur
        self._terlihat: set[str] = set()
        self._terakhir: dict[tuple[str, str], tuple[str, str]] = {}

    def proses(self, event: dict) -> str:
        """Hasil: 'ditolak' | 'duplikat' | 'usang' | 'disalurkan'."""
        galat = validasi_event(event)
        if galat:
            self.dlq.tambah(event, "skema tidak valid: " + "; ".join(galat), TUJUAN_VALIDASI)
            return "ditolak"
        if event["id"] in self._terlihat:
            return "duplikat"
        self._terlihat.add(event["id"])
        kunci = (event["produk_id"], event["jenis"])
        urutan = (event["waktu"], event["id"])
        if kunci in self._terakhir and urutan < self._terakhir[kunci]:
            return "usang"  # event lebih lama tiba setelah yang lebih baru
        self._terakhir[kunci] = urutan
        for nama, jenis in self.konsumen.items():
            if event["jenis"] in jenis:
                self._salurkan(nama, event)
        return "disalurkan"

    def _salurkan(self, nama: str, event: dict) -> None:
        percobaan = 0
        alasan = ""
        for i in range(len(self.jeda) + 1):
            percobaan += 1
            try:
                self.handler[nama](event)
                return
            except Exception as e:  # handler pihak ketiga: apa pun galatnya diulang lalu DLQ
                alasan = f"{type(e).__name__}: {e}"
            if i < len(self.jeda):
                self.tidur(self.jeda[i])
        self.dlq.tambah(event, alasan, nama, percobaan)


class IndeksPencarianMemori:
    """Konsumen contoh `pencarian-katalog`: dokumen per produk di memori."""

    def __init__(self) -> None:
        self.dokumen: dict[str, dict] = {}

    def __call__(self, e: dict) -> None:
        d = self.dokumen.setdefault(e["produk_id"], {"produk_id": e["produk_id"], "lapak_id": e["lapak_id"]})
        for k, v in e.items():
            if k not in ("id", "jenis", "waktu"):
                d[k] = v
        d["diperbarui_pada"] = e["waktu"]
