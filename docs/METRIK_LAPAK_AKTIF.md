# Metrik Lapak Aktif dan Sumber Data Dasbor (PSR-DATA-003)

Rujukan: `metrik/10-lapak-aktif.md` (Pasaree-TownHall). Kode: `src/pipeline/metrik.py`.

Pemakaian lokal: `python -m pipeline.metrik snapshot.json [sekarang ISO-8601 UTC]` -> JSON dasbor di stdout.

## Format snapshot masukan

```json
{"lapak": [{
  "id": "<ULID>", "status": "AKTIF|BEKU|TUTUP",
  "produk": [{"status": "TAYANG", "stok": 5, "hari_stok_nol": 0}],
  "pesanan_selesai": 4, "subpesanan_total": 10, "subpesanan_tepat_waktu": 9,
  "pelanggaran_terbuka": 0, "penjualan_terakhir": "2026-01-25T00:00:00Z",
  "durasi_kurasi_jam": [12.0]
}]}
```

Angka `pesanan_selesai`, `subpesanan_*` adalah rangkuman jendela 30 hari dari hulu; modul ini tidak memotong jendela sendiri.

## Aturan

- Lapak aktif: status `AKTIF`, >=3 produk `TAYANG` dengan stok total >0, >=1 pesanan `SELESAI`, konfirmasi tepat waktu (<=2 jam) >=80%, tanpa pelanggaran terbuka.
- Turunan agregat (lapak berstatus `AKTIF`): % lapak aktif (target >=60%), waktu kurasi median (<=36 jam), konfirmasi tepat waktu (>=90%), stok-0 kronis (<=15%).
- Lapak berisiko: konfirmasi <80%, rasio stok-0 kronis >15%, atau tanpa penjualan >21 hari.

Keluaran `ekspor_dasbor`: `dihitung_pada`, `ringkasan` (nilai, target, tercapai per metrik), `lapak_aktif_id`, `lapak_berisiko` (dengan `sebab`).
