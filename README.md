# IOMS Tracker: SOW Milestone Management System

IOMS Tracker merupakan aplikasi dashboard interaktif berbasis web yang dirancang untuk memantau, mengelola, dan mendokumentasikan data pencapaian (milestone) pada proyek Telkominfra. Sistem ini memfasilitasi pelacakan status proyek secara efisien dan akurat.

## Fitur Utama
* Optimized Bulk Search: Fitur pencarian dan pelacakan data berskala besar yang mengimplementasikan metode chunking pada SQLite untuk menjaga stabilitas performa sistem.
* Mass Data Synchronization: Fasilitas pembaruan data secara massal yang terintegrasi langsung dengan unggahan dokumen raw Excel.
* Manual TSV Integration: Pembaruan data sekunder melalui metode salin-tempel berbasis Tab-Separated Values (TSV) untuk fleksibilitas operasional.
* Intelligent Upsert Logic: Algoritma pembaruan data presisi yang menjamin integritas database (sistem secara otomatis hanya mengisi kolom NULL tanpa menimpa data historis yang sudah tervalidasi).
* Visual Milestone Indicators: Representasi status proyek menggunakan sistem antarmuka grid-dot intuitif guna mempercepat proses evaluasi dan eskalasi pengawasan.

## Teknologi
* Backend Environment: Python 3, Flask, Pandas, SQLite3
* Frontend Interface: HTML5, Vanilla JavaScript, CSS3, FontAwesome 6

## Instalasi & Menjalankan Aplikasi

```bash
# 1. Mengkloning repositori ke mesin lokal
git clone https://github.com/arsaaja/ioms-tracker.git
cd ioms-tracker

# 2. Mengonfigurasi Virtual Environment (Khusus lingkungan Windows)
python -m venv venv
venv\Scripts\activate

# 3. Menginstal dependensi sistem dan mengeksekusi aplikasi
pip install -r requirements.txt
python app.py
