# IOMS Tracker (SOW Milestone Tracker)

IOMS Tracker adalah aplikasi web-based dashboard untuk memonitoring dan mengelola data pencapaian (milestone) pada proyek Telco Site Rollout.

## Fitur Utama
* Bulk Search & Tracking (Chunking SQLite)
* Update Massal via Excel
* Update Manual (Copy-Paste TSV)
* Smart Upsert Logic (Hanya mengisi kolom NULL, tidak overwrite)
* Indikator Visual Intuitif (Grid dot)

## Teknologi
* Backend: Python 3, Flask, Pandas, SQLite3
* Frontend: HTML5, Vanilla JavaScript, CSS3, FontAwesome 6

## Instalasi & Menjalankan Aplikasi

```bash
# Clone repository
git clone [https://github.com/arsaaja/ioms-tracker.git](https://github.com/arsaaja/ioms-tracker.git)
cd ioms-tracker

# Setup Virtual Environment (Windows)
python -m venv venv
venv\Scripts\activate

# Instal dependensi dan jalankan
pip install -r requirements.txt
python app.py
