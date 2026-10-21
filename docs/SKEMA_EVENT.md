# Skema Event Katalog Pasaree

Jenis: `produk.dibuat`, `harga.berubah`, `stok.berubah`, `tayang.berubah`.

Medan wajib: `id` ULID string, `jenis`, `waktu` ISO-8601 UTC, `lapak_id`, `produk_id`.

Contoh harga berubah:

```json
{
  "id": "01J00000000000000000000001",
  "jenis": "harga.berubah",
  "waktu": "2026-01-01T00:00:00Z",
  "lapak_id": "01J00000000000000000000000",
  "produk_id": "01J00000000000000000000002",
  "harga_idr": 25000
}
```

Uang selalu integer IDR. Paginasi cursor mengikuti kontrak TownHall.

## Amplop idempoten dan pemetaan ke registry Titeny (PSR-DATA-002)

Rujukan: KONTEKS-LINTAS-DIVISI §3, ADR-0001 butir 1-2. Kode: `src/pipeline/amplop.py`, `src/pipeline/ingest.py`.

Amplop wajib untuk setiap event yang dikirim ke Titeny:

| Medan | Aturan |
|---|---|
| `event_id` | `evt_YYYYMMDD_NNNNNN` (tanggal UTC `occurred_at`, urut per hari); duplikat diabaikan |
| `event_type` | salah satu dari 11 event registry Titeny; tidak ada jenis baru |
| `schema_version` | semver kontrak (saat ini `1.0.0`) |
| `source` | selalu `pasaree` |
| `occurred_at` / `received_at` | ISO-8601 UTC, akhiran `Z` |
| `batch_id` | pengelompok pengiriman |
| `payload` | objek; isi event lokal tanpa `id`/`jenis`/`waktu` |

Pemetaan event katalog lokal ke registry:

| Event lokal | Registry Titeny | Catatan |
|---|---|---|
| `produk.dibuat` | (internal) | hanya pencarian-katalog dan metrik-lapak-aktif |
| `harga.berubah` | (internal) | registry `harga.diperbarui` bukan milik Pasaree |
| `stok.berubah` | (internal) | registry `stok.berubah` bersumber Lumbung |
| `tayang.berubah` | `lapak.status_berubah` | hanya bila payload memuat `lapak_status` |

Event yang diproduksi Pasaree ke Titeny: `transaksi.dibuat`, `lapak.status_berubah`, `logistik.biaya_diperbarui`, `vendor.status_berubah`.

Pengiriman: `POST /api/v1/event/masuk`, header `X-Idempotency-Key` = `event_id`. Retry 3x (5/30/300 detik) untuk 5xx/408/429/galat jaringan, lalu DLQ; 4xx lain langsung DLQ. Respons `duplikat_diabaikan` dianggap sukses.

## Alur ke konsumen (PSR-DATA-004)

Kode: `src/pipeline/alur.py`; konsumen tercatat di `config/pipeline.yaml` (`pencarian-katalog`, `metrik-lapak-aktif`, `titeny`).

1. Validasi skema (ULID, waktu ISO-8601 UTC, uang integer IDR); tidak valid -> DLQ (`tujuan: validasi`).
2. Duplikat `id` diabaikan.
3. Urutan terbalik: event lebih lama dari yang sudah diterima untuk (`produk_id`, `jenis`) dibuang (`usang`).
4. Penyaluran per konsumen sesuai `jenis_event`; gagal -> retry 5/30/300 detik lalu DLQ per konsumen.
