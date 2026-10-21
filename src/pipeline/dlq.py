"""Antrean surat mati (DLQ) in-memori dan kebijakan retry bersama."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Jeda retry terkunci (AGENTS.md): 3x percobaan ulang pada 5/30/300 detik, lalu DLQ.
JEDA_RETRY_DETIK = (5, 30, 300)


@dataclass
class SuratMati:
    """Satu entri DLQ: event yang gagal beserta alasannya."""

    event: Any
    alasan: str
    tujuan: str
    percobaan: int
    waktu: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


class AntreanSuratMati:
    """DLQ memori-lokal (sesuai `antrean: memori-lokal` di config/pipeline.yaml)."""

    def __init__(self) -> None:
        self.entri: list[SuratMati] = []

    def tambah(self, event: Any, alasan: str, tujuan: str, percobaan: int = 0) -> SuratMati:
        item = SuratMati(event=event, alasan=alasan, tujuan=tujuan, percobaan=percobaan)
        self.entri.append(item)
        return item

    def __len__(self) -> int:
        return len(self.entri)
