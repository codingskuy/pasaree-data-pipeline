"""Klien `POST /api/v1/event/masuk` dengan X-Idempotency-Key, retry 3x lalu DLQ."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from .amplop import validasi_amplop
from .dlq import JEDA_RETRY_DETIK, AntreanSuratMati

PATH_INGEST = "/api/v1/event/masuk"
TUJUAN_TITENY = "titeny"

# Transport: (url, headers, body_bytes) -> (status_http, body_dict). Boleh melempar OSError.
Transport = Callable[[str, dict, bytes], "tuple[int, dict]"]


def transport_http(url: str, headers: dict, body: bytes, timeout: float = 10.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL dari konfigurasi)
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, {}


def _bisa_diulang(status: int) -> bool:
    return status >= 500 or status in (408, 429)


class PengirimEvent:
    """Mengirim amplop ke Titeny. Duplikat `event_id` tidak dikirim ulang (idempoten)."""

    def __init__(
        self,
        base_url: str,
        transport: Transport = transport_http,
        dlq: AntreanSuratMati | None = None,
        tidur: Callable[[float], None] = time.sleep,
        jeda: tuple[int, ...] = JEDA_RETRY_DETIK,
    ) -> None:
        self.url = base_url.rstrip("/") + PATH_INGEST
        self.transport = transport
        self.dlq = dlq if dlq is not None else AntreanSuratMati()
        self.tidur = tidur
        self.jeda = jeda
        self.terkirim: set[str] = set()

    def kirim(self, amplop: dict) -> str:
        """Hasil: 'terkirim' | 'duplikat' | 'dlq'."""
        galat = validasi_amplop(amplop)
        if galat:
            self.dlq.tambah(amplop, "amplop tidak valid: " + "; ".join(galat), TUJUAN_TITENY)
            return "dlq"
        eid = amplop["event_id"]
        if eid in self.terkirim:
            return "duplikat"
        headers = {"Content-Type": "application/json", "X-Idempotency-Key": eid}
        body = json.dumps(amplop, ensure_ascii=False).encode()
        percobaan = 0
        alasan = ""
        for i in range(len(self.jeda) + 1):
            percobaan += 1
            try:
                status, resp = self.transport(self.url, headers, body)
            except OSError as e:
                status, resp, alasan = 0, {}, f"galat jaringan: {e}"
            else:
                if 200 <= status < 300:
                    self.terkirim.add(eid)
                    return "duplikat" if resp.get("status") == "duplikat_diabaikan" else "terkirim"
                alasan = f"HTTP {status}"
                if not _bisa_diulang(status):
                    break  # 4xx permanen: retry tak ada gunanya
            if i < len(self.jeda):
                self.tidur(self.jeda[i])
        self.dlq.tambah(amplop, alasan, TUJUAN_TITENY, percobaan)
        return "dlq"
