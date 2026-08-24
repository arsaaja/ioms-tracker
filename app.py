import os
import sqlite3
import re
import pandas as pd
from flask import Flask, render_template, request, jsonify
from flask import send_file
import tempfile
import subprocess
import os
from io import BytesIO
import zipfile

app = Flask(__name__)
DB_FILE = 'sow_tracker.db'

# Daftar 11 Milestone yang difokuskan sesuai kebutuhan
MILESTONES = [
    'MOS Date', 'INSTALL Date', 'CONNECTED Date', 'OA Date', 'QC Date',
    'BAUTEQP Date', 'BASOEQP Date', 'BAPAEQP Date', 'SOAC Date', 'BAST Date', 'ATP'
]

def init_db():
    """Inisialisasi database SQLite dengan skema yang disederhanakan untuk web app."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Tabel Induk SOW
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS PROJECT_SOW (
            project_sow_id TEXT PRIMARY KEY,
            infra_vendor TEXT
        )
    ''')
    
    # Tabel Milestone (Format Long - 1 Baris per SOW dan Tipe Milestone)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS MILESTONE_DATE (
            project_sow_id TEXT,
            milestone_type TEXT,
            milestone_date TEXT,
            PRIMARY KEY (project_sow_id, milestone_type),
            FOREIGN KEY(project_sow_id) REFERENCES PROJECT_SOW(project_sow_id)
        )
    ''')

    # Tabel Mitra (dari file excel terpisah: kolom Project SOW ID + MITRA ACTUAL)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS MITRA_DATA (
            project_sow_id TEXT PRIMARY KEY,
            mitra TEXT
        )
    ''')
    conn.commit()
    conn.close()

def upsert_sow_data(data_list):
    """
    Logika Upsert: 
    1. Ambil Project SOW ID secara dinamis (mengabaikan puluhan kolom lain yang tidak perlu).
    2. Insert SOW ID jika belum ada di database.
    3. Insert/Update Milestone hanya jika di DB masih kosong dan input baru ada isinya.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    summary = {'inserted': 0, 'updated': 0, 'unchanged': 0}
    logs = []

    for row in data_list:
        # Deteksi otomatis apakah namanya "Project SOW ID" atau "SOW ID"
        sow_id = row.get('Project SOW ID') or row.get('SOW ID')
        
        # Skip baris jika ID kosong atau NaN
        if not sow_id or pd.isna(sow_id) or str(sow_id).strip() == '':
            continue
            
        sow_id = str(sow_id).strip()
        
        # Ambil Vendor Infra jika ada, amankan dari tipe data Float NaN
        infra_vendor = str(row.get('Infra Vendor', '')).strip() if not pd.isna(row.get('Infra Vendor')) else ""
        
        # 1. Cek apakah SOW ID sudah ada di tabel Induk
        cursor.execute("SELECT project_sow_id FROM PROJECT_SOW WHERE project_sow_id = ?", (sow_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO PROJECT_SOW (project_sow_id, infra_vendor) VALUES (?, ?)", (sow_id, infra_vendor))
            summary['inserted'] += 1
        
        # 2. Proses 11 Milestone
        is_updated = False
        for m_type in MILESTONES:
            # Ambil nilai tanggal milestone (misal: 'MOS Date')
            new_val = row.get(m_type)
            
            # Jika kolom tidak ada di input, isinya NaN dari Excel, atau kosong -> skip
            if new_val is None or pd.isna(new_val) or str(new_val).strip() == '' or str(new_val).strip() == 'nan':
                continue 
                
            new_val = str(new_val).strip()

            # Cek status milestone saat ini di database
            cursor.execute("SELECT milestone_date FROM MILESTONE_DATE WHERE project_sow_id = ? AND milestone_type = ?", (sow_id, m_type))
            existing_row = cursor.fetchone()

            if not existing_row:
                # Belum ada record milestone ini sama sekali, insert baru
                cursor.execute("INSERT INTO MILESTONE_DATE (project_sow_id, milestone_type, milestone_date) VALUES (?, ?, ?)", 
                               (sow_id, m_type, new_val))
                is_updated = True
                logs.append(f"[{sow_id}] Menambahkan {m_type}: {new_val}")
            else:
                existing_val = existing_row[0]
                # Update HANYA JIKA di DB masih kosong / null (aturan main dari PM)
                if not existing_val or existing_val.lower() == 'nan' or existing_val.strip() == '':
                    cursor.execute("UPDATE MILESTONE_DATE SET milestone_date = ? WHERE project_sow_id = ? AND milestone_type = ?", 
                                   (new_val, sow_id, m_type))
                    is_updated = True
                    logs.append(f"[{sow_id}] Memperbarui {m_type}: (kosong) -> {new_val}")
        
        if is_updated:
            summary['updated'] += 1
        else:
            summary['unchanged'] += 1

    conn.commit()
    conn.close()
    return summary, logs

def find_column(df_columns, candidates):
    """
    Cari nama kolom asli di df_columns yang cocok (case-insensitive, spasi
    diabaikan) dengan salah satu nama di `candidates` (urutan = prioritas).
    Return nama kolom asli kalau ketemu, None kalau tidak ada.
    """
    lookup = {str(c).strip().lower(): c for c in df_columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in lookup:
            return lookup[key]
    return None


def upsert_mitra_data(data_list, sow_col, mitra_actual_col, old_mitra_col):
    """
    Upsert khusus kolom Mitra dari file excel yang punya struktur kolom beda
    (Project SOW ID, ..., old Mitra, MITRA ACTUAL, ...).
    Prioritas ambil dari kolom MITRA ACTUAL, fallback ke old Mitra kalau kosong.
    Selalu ditimpa ke nilai terbaru (bukan cuma isi-kalau-kosong), karena
    mitra pelaksana bisa berganti dari waktu ke waktu.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    summary = {'inserted': 0, 'updated': 0, 'unchanged': 0}
    logs = []
    skipped_no_id = 0
    skipped_no_mitra = 0

    for row in data_list:
        sow_id = row.get(sow_col)
        if not sow_id or pd.isna(sow_id) or str(sow_id).strip() == '':
            skipped_no_id += 1
            continue
        sow_id = str(sow_id).strip()

        mitra_val = row.get(mitra_actual_col) if mitra_actual_col else None
        if mitra_val is None or pd.isna(mitra_val) or str(mitra_val).strip() == '':
            mitra_val = row.get(old_mitra_col) if old_mitra_col else None
        if mitra_val is None or pd.isna(mitra_val) or str(mitra_val).strip() == '':
            skipped_no_mitra += 1
            continue
        mitra_val = str(mitra_val).strip()

        cursor.execute("SELECT mitra FROM MITRA_DATA WHERE project_sow_id = ?", (sow_id,))
        existing = cursor.fetchone()

        if not existing:
            cursor.execute("INSERT INTO MITRA_DATA (project_sow_id, mitra) VALUES (?, ?)", (sow_id, mitra_val))
            summary['inserted'] += 1
            logs.append(f"[{sow_id}] Menambahkan Mitra: {mitra_val}")
        elif existing[0] != mitra_val:
            cursor.execute("UPDATE MITRA_DATA SET mitra = ? WHERE project_sow_id = ?", (mitra_val, sow_id))
            summary['updated'] += 1
            logs.append(f"[{sow_id}] Mitra berubah: ({existing[0] or '-'}) -> {mitra_val}")
        else:
            summary['unchanged'] += 1

    conn.commit()
    conn.close()

    if skipped_no_id or skipped_no_mitra:
        logs.append(f"[INFO] Dilewati: {skipped_no_id} baris tanpa SOW ID, {skipped_no_mitra} baris tanpa nilai Mitra.")

    return summary, logs


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/bulk_search', methods=['POST'])
def bulk_search():
    data = request.json
    raw_sow_ids = data.get('sow_ids', '')
    
    # Bersihkan input dan pisah berdasarkan koma, enter, atau tab.
    raw_list = [s.strip() for s in re.split(r'[,\n\t]+', raw_sow_ids) if s.strip()]
    
    # Hapus duplikat TETAPI pertahankan urutan aslinya dari atas ke bawah
    sow_ids = list(dict.fromkeys(raw_list))
    
    if not sow_ids:
        return jsonify({'error': 'Tidak ada SOW ID yang valid.'}), 400

    # Inisialisasi struktur result
    grouped_results = {sow_id: {m: None for m in MILESTONES} for sow_id in sow_ids}
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Chunking 500 ID agar tidak terkena limit 999 variabel SQLite
    chunk_size = 500 
    for i in range(0, len(sow_ids), chunk_size):
        chunk = sow_ids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        
        query = f"SELECT project_sow_id, milestone_type, milestone_date FROM MILESTONE_DATE WHERE project_sow_id IN ({placeholders})"
        cursor.execute(query, chunk)
        
        for row in cursor.fetchall():
            s_id = row['project_sow_id']
            m_type = row['milestone_type']
            m_date = row['milestone_date']
            
            if s_id in grouped_results and m_type in grouped_results[s_id]:
                grouped_results[s_id][m_type] = m_date
                
    # Cek SOW ID yang benar-benar ada di tabel master PROJECT_SOW
    valid_ids = []
    for i in range(0, len(sow_ids), chunk_size):
        chunk = sow_ids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        cursor.execute(f"SELECT project_sow_id FROM PROJECT_SOW WHERE project_sow_id IN ({placeholders})", chunk)
        valid_ids.extend([row['project_sow_id'] for row in cursor.fetchall()])

    # Ambil data Mitra (dari tabel terpisah MITRA_DATA) untuk SOW ID yang dicari
    mitra_map = {}
    for i in range(0, len(sow_ids), chunk_size):
        chunk = sow_ids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        cursor.execute(f"SELECT project_sow_id, mitra FROM MITRA_DATA WHERE project_sow_id IN ({placeholders})", chunk)
        for row in cursor.fetchall():
            mitra_map[row['project_sow_id']] = row['mitra']

    conn.close()

    # Pisahkan hasil yang ketemu dan tidak ketemu
    found_list = []
    for k in sow_ids:
        if k in valid_ids:
            found_list.append({
                'sow_id': k,
                'milestones': grouped_results[k],
                'mitra': mitra_map.get(k, '')
            })
            
    not_found = [k for k in sow_ids if k not in valid_ids]

    return jsonify({
        'total_searched': len(sow_ids),
        'total_found': len(found_list),
        'total_not_found': len(not_found),
        'data': found_list,  # <--- Sekarang dikirim sebagai Array
        'not_found_list': not_found,
        'milestones': MILESTONES
    })

@app.route('/api/upload_mitra', methods=['POST'])
def upload_mitra():
    if 'file' not in request.files:
        return jsonify({'error': 'Tidak ada file yang diunggah'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nama file kosong'}), 400

    try:
        # 1. Baca keseluruhan struktur file Excel
        xl = pd.ExcelFile(file)
        df = None
        header_idx = -1
        target_sheet = ""
        
        # 2. Cari sheet yang bernama 'site list all' (case-insensitive)
        sheet_to_process = None
        for sheet in xl.sheet_names:
            if sheet.strip().lower() == 'site list all':
                sheet_to_process = sheet
                break
        
        # Jika sheet spesifik ketemu, fokus ke sana. Jika tidak, jadikan semua sheet sebagai cadangan.
        sheets_to_scan = [sheet_to_process] if sheet_to_process else xl.sheet_names

        # 3. Loop ke sheet yang sudah ditentukan dan cari baris header
        for sheet in sheets_to_scan:
            temp_df = xl.parse(sheet, header=None)
            
            # Scan maksimal 30 baris pertama untuk mencari keberadaan teks SOW
            for i in range(min(30, len(temp_df))):
                row_str = " ".join([str(x).lower() for x in temp_df.iloc[i].tolist()])
                
                if 'sow' in row_str and ('project' in row_str or 'id' in row_str):
                    df = temp_df
                    header_idx = i
                    target_sheet = sheet
                    break
                    
            if df is not None:
                break
                
        # 4. Validasi jika benar-benar tidak ada yang cocok
        if header_idx == -1:
            return jsonify({
                'error': f"Gagal deteksi header SOW ID. Pastikan sheet 'site list all' ada di dalam file tersebut."
            }), 400

        # 5. Timpa nama kolom dengan baris yang berhasil ditemukan
        raw_columns = df.iloc[header_idx].tolist()
        cleaned_columns = []
        for col_idx, c in enumerate(raw_columns):
            if pd.isna(c) or str(c).strip() == '' or str(c).strip().lower() == 'nan':
                cleaned_columns.append(f"Unnamed_{col_idx}")
            else:
                # Ganti Alt+Enter jadi spasi biasa
                c_str = str(c).replace('\n', ' ').replace('\r', '').strip()
                cleaned_columns.append(c_str)
                
        df.columns = cleaned_columns
        
        # 6. Potong baris header dan baris-baris kosong di atasnya
        df = df.iloc[header_idx + 1:].reset_index(drop=True)
        
        # 7. Cari kolom pakai fungsi find_column yang sudah ada
        sow_candidates = ['Project SOW ID', 'SOW ID', 'SOWID', 'SOW No']
        mitra_candidates = ['MITRA ACTUAL', 'Mitra Actual', 'Mitra']
        old_mitra_candidates = ['old Mitra', 'Old Mitra']
        
        sow_col = find_column(df.columns, sow_candidates)
        mitra_actual_col = find_column(df.columns, mitra_candidates)
        old_mitra_col = find_column(df.columns, old_mitra_candidates)
        
        # 8. Validasi kolom akhir
        if not sow_col:
            detected = ", ".join(df.columns.tolist())
            return jsonify({
                'error': f"Header ketemu di Sheet '{target_sheet}' Baris {header_idx + 1}, tapi SOW ID beda nama. Terdeteksi: {detected}"
            }), 400
            
        if not mitra_actual_col and not old_mitra_col:
            detected = ", ".join(df.columns.tolist())
            return jsonify({
                'error': f"Header ketemu di Sheet '{target_sheet}' Baris {header_idx + 1}, tapi Mitra tidak ada. Terdeteksi: {detected}"
            }), 400

        # 9. Eksekusi Upsert
        data_list = df.to_dict('records')
        summary, logs = upsert_mitra_data(data_list, sow_col, mitra_actual_col, old_mitra_col)
        
        summary['detected_columns'] = {
            'sow_id': sow_col,
            'mitra_actual': mitra_actual_col,
            'old_mitra': old_mitra_col
        }
        
        return jsonify({'summary': summary, 'logs': logs})

    except Exception as e:
        return jsonify({'error': f"Sistem error: {str(e)}"}), 500

@app.route('/api/upload_excel', methods=['POST'])
def upload_excel():
    if 'files' not in request.files:
        return jsonify({'error': 'Tidak ada file yang diunggah'}), 400
    
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': 'Nama file kosong'}), 400

    try:
        total_summary = {'inserted': 0, 'updated': 0, 'unchanged': 0}
        all_logs = []
        
        for file in files:
            # Baca Excel dengan Pandas
            df = pd.read_excel(file)
                
            # Konversi dataframe ke list of dictionaries (untuk dikirim ke upsert logic)
            data_list = df.to_dict('records')
            summary, logs = upsert_sow_data(data_list)
            
            total_summary['inserted'] += summary['inserted']
            total_summary['updated'] += summary['updated']
            total_summary['unchanged'] += summary['unchanged']
            all_logs.extend(logs)
            
        return jsonify({'summary': total_summary, 'logs': all_logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download_tracker_excel', methods=['POST'])
def download_tracker_excel():
    data = request.json if request.is_json else request.form
    raw_sow_ids = data.get('sow_ids', '')
    
    raw_list = [s.strip() for s in re.split(r'[,\n\t]+', raw_sow_ids) if s.strip()]
    sow_ids = list(dict.fromkeys(raw_list))
    
    if not sow_ids:
        return jsonify({'error': 'Tidak ada SOW ID yang valid.'}), 400

    grouped_results = {sow_id: {m: None for m in MILESTONES} for sow_id in sow_ids}
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    chunk_size = 500 
    for i in range(0, len(sow_ids), chunk_size):
        chunk = sow_ids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        
        cursor.execute(f"SELECT project_sow_id, milestone_type, milestone_date FROM MILESTONE_DATE WHERE project_sow_id IN ({placeholders})", chunk)
        for row in cursor.fetchall():
            grouped_results[row['project_sow_id']][row['milestone_type']] = row['milestone_date']
            
    valid_ids = []
    for i in range(0, len(sow_ids), chunk_size):
        chunk = sow_ids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        cursor.execute(f"SELECT project_sow_id FROM PROJECT_SOW WHERE project_sow_id IN ({placeholders})", chunk)
        valid_ids.extend([row['project_sow_id'] for row in cursor.fetchall()])

    mitra_map = {}
    for i in range(0, len(sow_ids), chunk_size):
        chunk = sow_ids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        cursor.execute(f"SELECT project_sow_id, mitra FROM MITRA_DATA WHERE project_sow_id IN ({placeholders})", chunk)
        for row in cursor.fetchall():
            mitra_map[row['project_sow_id']] = row['mitra']

    conn.close()

    report_data = []
    for k in sow_ids:
        if k in valid_ids:
            row_data = {"Project SOW ID": k}
            for m in MILESTONES:
                val = grouped_results[k][m]
                row_data[m] = "Done" if (val and val not in ["None", "null"]) else "Pending"
            row_data["Mitra"] = mitra_map.get(k, "")
            report_data.append(row_data)
            
    if not report_data:
        return jsonify({'error': 'SOW ID tidak ditemukan di database.'}), 404

    df_report = pd.DataFrame(report_data)
    cols = ["Project SOW ID"] + MILESTONES + ["Mitra"]
    df_report = df_report[cols]
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    df_report.to_excel(temp_file.name, index=False)
    temp_file.close()
    
    return send_file(temp_file.name, as_attachment=True, download_name="SOW_Tracker_Report.xlsx")
# ==========================================
# FITUR TAMBAHAN: COMPRESS PDF (BULK)
# ==========================================
@app.route('/api/compress-pdf', methods=['POST'])
def api_compress_pdf():
    if 'files' not in request.files:
        return jsonify({'error': 'Upload PDF-nya dulu!'}), 400
        
    files = request.files.getlist('files')
    quality = request.form.get('quality', '/ebook')
    
    try:
        if len(files) == 1:
            file = files[0]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_in:
                file.save(temp_in.name)
                input_path = temp_in.name
                
            output_path = input_path.replace(".pdf", "_compressed.pdf")
            gs_cmd = [
                "gswin64c", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={quality}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={output_path}", input_path
            ]
            subprocess.run(gs_cmd, check=True)
            return send_file(output_path, as_attachment=True, download_name=f"compressed_{file.filename}")
            
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for file in files:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_in:
                        file.save(temp_in.name)
                        input_path = temp_in.name
                        
                    output_path = input_path.replace(".pdf", "_compressed.pdf")
                    gs_cmd = [
                        "gswin64c", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                        f"-dPDFSETTINGS={quality}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                        f"-sOutputFile={output_path}", input_path
                    ]
                    subprocess.run(gs_cmd, check=True)
                    zip_file.write(output_path, arcname=f"compressed_{file.filename}")
                    os.remove(input_path)
                    os.remove(output_path)
                    
            zip_buffer.seek(0)
            return send_file(zip_buffer, as_attachment=True, download_name="Hasil_Compress_Bulk.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Paksa inisialisasi database setiap kali server nyala.
    # Sangat aman karena pakai 'CREATE TABLE IF NOT EXISTS'
    init_db()
    print("Mengecek dan menyiapkan tabel database...")
    
    app.run(debug=True)