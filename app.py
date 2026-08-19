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
        
    conn.close()

    # Pisahkan hasil yang ketemu dan tidak ketemu
    found_list = []
    for k in sow_ids:
        if k in valid_ids:
            found_list.append({
                'sow_id': k,
                'milestones': grouped_results[k]
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

@app.route('/api/upload_excel', methods=['POST'])
def upload_excel():
    if 'file' not in request.files:
        return jsonify({'error': 'Tidak ada file yang diunggah'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nama file kosong'}), 400

    try:
        # Baca Excel dengan Pandas
        df = pd.read_excel(file)
            
        # Konversi dataframe ke list of dictionaries (untuk dikirim ke upsert logic)
        data_list = df.to_dict('records')
        summary, logs = upsert_sow_data(data_list)
        return jsonify({'summary': summary, 'logs': logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/input_manual', methods=['POST'])
def input_manual():
    data = request.json
    raw_text = data.get('text_data', '')
    
    # Parsing Tab-Separated Values (TSV) dari copy-paste Excel
    lines = raw_text.strip().split('\n')
    if len(lines) < 2:
        return jsonify({'error': 'Data tidak lengkap. Pastikan Anda meng-copy baris header dan datanya.'}), 400
        
    headers = [h.strip() for h in lines[0].split('\t')]
    
    data_list = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split('\t')]
        
        # Pastikan jumlah kolom sama dengan header untuk menghindari index error
        # Jika kurang, tambahkan string kosong. Jika lebih, potong.
        while len(values) < len(headers):
            values.append("")
        values = values[:len(headers)]
            
        row_dict = dict(zip(headers, values))
        data_list.append(row_dict)

    summary, logs = upsert_sow_data(data_list)
    return jsonify({'summary': summary, 'logs': logs})

# ==========================================
# FITUR PIVOT 1: GENERATE PREVIEW (JSON)
# ==========================================
@app.route('/api/preview-pivot', methods=['POST'])
def api_preview_pivot():
    if 'files' not in request.files:
        return jsonify({'error': 'Mana file Excelnya?'}), 400
    
    files = request.files.getlist('files')
    sowid_input = request.form.get('sowids', '')
    
    try:
        df_list = [pd.read_excel(file) for file in files]
        df_all = pd.concat(df_list, ignore_index=True)
        sowid_list = [x.strip() for x in sowid_input.replace('\n', ',').split(',') if x.strip()]
        df_target = df_all[df_all['Project SOW ID'].isin(sowid_list)].copy()
        
        if df_target.empty:
            return jsonify({'error': 'SOWID lu kagak nemu di file Excel mana pun.'}), 404
            
        milestones = ['MOS Date', 'INSTALL Date', 'CONNECTED Date', 'OA Date', 'QC Date', 'BAUTEQP Date', 'BASOEQP Date', 'BAPAEQP Date', 'SOAC Date', 'BAST Date', 'ATP']
        report_data = []
        for _, row in df_target.iterrows():
            for col in milestones:
                if col in df_target.columns:
                    status = "Done" if pd.notna(row[col]) else "Pending"
                    report_data.append({"Project SOW ID": row['Project SOW ID'], "Milestone": col, "Status": status})
                    
        # Bikin pivot dan reset_index biar SOW ID jadi kolom biasa (gampang di-JSON-in)
        pivot_report = pd.DataFrame(report_data).pivot_table(index="Project SOW ID", columns="Milestone", values="Status", aggfunc='first').reset_index()
        
        # Rapihin urutan kolom
        available_cols = ["Project SOW ID"] + [c for c in milestones if c in pivot_report.columns]
        pivot_report = pivot_report[available_cols].fillna("Pending")
        
        # Balikin data berupa JSON buat di-render Frontend
        return jsonify({
            "columns": available_cols,
            "data": pivot_report.to_dict(orient="records")
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==========================================
# FITUR PIVOT 2: DOWNLOAD EXCEL
# ==========================================
@app.route('/api/download-pivot', methods=['POST'])
def api_download_pivot():
    # Sama kayak preview, tapi outputnya dilempar ke tempfile Excel
    files = request.files.getlist('files')
    sowid_input = request.form.get('sowids', '')
    
    try:
        df_list = [pd.read_excel(file) for file in files]
        df_all = pd.concat(df_list, ignore_index=True)
        sowid_list = [x.strip() for x in sowid_input.replace('\n', ',').split(',') if x.strip()]
        df_target = df_all[df_all['Project SOW ID'].isin(sowid_list)].copy()
        
        milestones = ['MOS Date', 'INSTALL Date', 'CONNECTED Date', 'OA Date', 'QC Date', 'BAUTEQP Date', 'BASOEQP Date', 'BAPAEQP Date', 'SOAC Date', 'BAST Date', 'ATP']
        report_data = []
        for _, row in df_target.iterrows():
            for col in milestones:
                if col in df_target.columns:
                    status = "Done" if pd.notna(row[col]) else "Pending"
                    report_data.append({"Project SOW ID": row['Project SOW ID'], "Milestone": col, "Status": status})
                    
        pivot_report = pd.DataFrame(report_data).pivot_table(index="Project SOW ID", columns="Milestone", values="Status", aggfunc='first')
        available_cols = [c for c in milestones if c in pivot_report.columns]
        pivot_report = pivot_report[available_cols]
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        pivot_report.to_excel(temp_file.name)
        temp_file.close()
        
        return send_file(temp_file.name, as_attachment=True, download_name="Report_IOMS_Pivot.xlsx")
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# ==========================================
# FITUR TAMBAHAN: COMPRESS PDF (BULK)
# ==========================================
@app.route('/api/compress-pdf', methods=['POST'])
def api_compress_pdf():
    if 'files' not in request.files:
        return jsonify({'error': 'Upload PDF-nya dulu bos!'}), 400
        
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