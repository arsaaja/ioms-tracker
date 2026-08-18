# SOW Milestone Tracker

Web app kecil buat search & update status 11 milestone (MOS, INSTALL, CONNECTED,
OA, QC, BAUTEQP, BASOEQP, BAPAEQP, SOAC, BAST, ATP) berdasarkan **Project SOW ID**.

## Cara jalanin (lokal dulu buat coba-coba)

```bash
cd sow_tracker
pip install -r requirements.txt
python app.py
```

Buka browser: **http://localhost:5000**

Database otomatis dibikin di `sow_tracker.db` (SQLite) pas pertama kali dijalankan.

## Fitur

1. **Cari SOW ID** — ketik SOW ID, langsung kelihatan status 11 milestone-nya
   (dot terisi teal = sudah ada tanggalnya, dot kosong = belum).
2. **Input Banyak Baris** — paste langsung dari excel (tab-separated) atau
   pisah pakai koma, 1 baris = 1 SOW. Klik "lihat format" buat lihat urutan
   kolom yang diharapkan. Kolom yang dikosongin di baris paste-an **tidak**
   akan menimpa data yang sudah ada di database — cuma isi yang kosong.
3. **Upload Excel** — buat update massal langsung dari file yang didownload
   dari website kantor. Kolom yang dikenali otomatis: `Project SOW ID`
   (atau `SOW ID`), `Infra Vendor`, dan 11 kolom milestone di atas (nama
   kolom harus sama persis, misal `MOS Date`, `INSTALL Date`, dst).

Semua tiga cara input (search hasil, bulk paste, upload excel) pakai logic
yang sama: **insert kalau SOW ID baru, isi kolom kosong kalau SOW ID sudah
ada** — jadi data yang udah bener gak akan ketimpa.

## Supaya bisa dipakai bareng-bareng tim kantor

Ini masih mode development (`app.run(debug=True)`), buat production perlu:

1. Ganti server dev Flask dengan **gunicorn** atau **waitress**:
   ```bash
   pip install waitress
   waitress-serve --host=0.0.0.0 --port=5000 app:app
   ```
2. Taruh di server/VM internal kantor (yang bisa diakses dari jaringan
   kantor), atau minta tim IT hosting-in di intranet.
3. Kasih tau tim link internal-nya, misal `http://10.x.x.x:5000` atau
   domain internal kalau ada (`http://sow-tracker.internal`).
4. **Backup rutin** file `sow_tracker.db` (tinggal copy file-nya, SQLite
   itu single-file database).
5. Kalau nanti butuh multi-user beneran rame (banyak yang edit bersamaan
   terus-terusan), tinggal migrasi dari SQLite ke PostgreSQL — struktur
   kode Python-nya gak banyak berubah, cuma ganti koneksi DB-nya.

## Struktur file

```
sow_tracker/
├── app.py              # backend Flask + logic upsert
├── requirements.txt
├── templates/
│   └── index.html      # halaman utama
├── static/
│   ├── style.css
│   └── app.js
└── sow_tracker.db      # dibuat otomatis saat pertama run
```
