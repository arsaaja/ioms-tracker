// --- FITUR NAVBAR / TABS ---
function switchTab(tabId) {
  // Sembunyiin semua section
  document.querySelectorAll(".view-section").forEach((el) => {
    el.style.display = "none";
  });

  // Matiin highlight di semua tombol navbar
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.remove("active");
  });

  // Nyalain section dan highlight tombol yang dipilih
  document.getElementById("view-" + tabId).style.display = "block";
  document.getElementById("nav-" + tabId).classList.add("active");
}

// Pastikan tab default (Tracker) nyala pas web pertama kali diload
window.onload = () => {
  switchTab("tracker");
};

// --- FITUR PENCARIAN & TRACKING ---
async function executeSearch() {
  const inputIds = document.getElementById("searchInput").value;
  const resultsDiv = document.getElementById("searchResults");

  if (!inputIds.trim()) {
    alert("Masukkan minimal 1 SOW ID");
    return;
  }

  resultsDiv.innerHTML =
    '<p class="loading"><i class="fas fa-spinner fa-spin"></i> Memuat data dari database...</p>';

  try {
    const response = await fetch("/api/bulk_search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sow_ids: inputIds }),
    });

    const result = await response.json();

    if (!response.ok) {
      resultsDiv.innerHTML = `<p class="error"><i class="fas fa-exclamation-triangle"></i> ${result.error}</p>`;
      return;
    }

    renderSearchResults(result, resultsDiv);
  } catch (error) {
    console.error("Error:", error);
    resultsDiv.innerHTML =
      '<p class="error"><i class="fas fa-times-circle"></i> Gagal melakukan pencarian server.</p>';
  }
}

function renderSearchResults(result, container) {
  let html = `<div class="summary-box">
        <strong>Hasil:</strong> ${result.total_found} ditemukan | ${result.total_not_found} tidak ditemukan.
    </div>`;

  if (result.not_found_list.length > 0) {
    // Ganti ❌ dengan icon warning
    html += `<p class="warning"><i class="fas fa-exclamation-triangle"></i> Tidak ada di DB: ${result.not_found_list.join(", ")}</p>`;
  }

  if (result.total_found > 0) {
    html += `<div class="table-responsive"><table class="milestone-table">
            <thead>
                <tr>
                    <th>SOW ID</th>
                    ${result.milestones.map((m) => `<th>${m.replace(" Date", "")}</th>`).join("")}
                </tr>
            </thead>
            <tbody>`;

    result.data.forEach((item) => {
      const sowId = item.sow_id;
      const mData = item.milestones;

      html += `<tr><td class="sticky-col">${sowId}</td>`;

      result.milestones.forEach((m) => {
        const dateVal = mData[m];
        if (dateVal && dateVal !== "None" && dateVal !== "null") {
          html += `<td class="dot-cell"><span class="dot filled" title="${dateVal}">●</span></td>`;
        } else {
          html += `<td class="dot-cell"><span class="dot empty" title="Belum update">○</span></td>`;
        }
      });
      html += `</tr>`;
    });

    html += `</tbody></table></div>`;
  }

  container.innerHTML = html;
}

// --- FITUR UPDATE & UPSERT ---
async function uploadExcel() {
  const fileInput = document.getElementById("excelFile");
  if (fileInput.files.length === 0) {
    alert("Pilih file excel terlebih dahulu!");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  showLogContainer("Memproses file Excel...");

  try {
    const response = await fetch("/api/upload_excel", {
      method: "POST",
      body: formData,
    });
    const result = await response.json();
    renderUpdateLog(result);
  } catch (error) {
    document.getElementById("summaryStats").innerHTML =
      `<p class="error"><i class="fas fa-times-circle"></i> Error upload: ${error}</p>`;
  }
}

async function submitManualInput() {
  const textData = document.getElementById("manualInput").value;
  if (!textData.trim()) {
    alert("Paste data dari excel terlebih dahulu!");
    return;
  }

  showLogContainer("Memproses teks input...");

  try {
    const response = await fetch("/api/input_manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text_data: textData }),
    });
    const result = await response.json();

    if (!response.ok) {
      document.getElementById("summaryStats").innerHTML =
        `<p class="error"><i class="fas fa-exclamation-circle"></i> ${result.error}</p>`;
      return;
    }

    renderUpdateLog(result);
  } catch (error) {
    document.getElementById("summaryStats").innerHTML =
      `<p class="error"><i class="fas fa-times-circle"></i> Error input manual: ${error}</p>`;
  }
}

// --- HELPER UI ---
function showLogContainer(msg) {
  const logContainer = document.getElementById("updateLog");
  logContainer.style.display = "block";
  document.getElementById("summaryStats").innerHTML =
    `<p class="loading"><i class="fas fa-spinner fa-spin"></i> ${msg}</p>`;
  document.getElementById("logDetails").value = "";
}

function renderUpdateLog(result) {
  if (result.error) {
    document.getElementById("summaryStats").innerHTML =
      `<p class="error"><i class="fas fa-times-circle"></i> ${result.error}</p>`;
    return;
  }

  const s = result.summary;

  document.getElementById("summaryStats").innerHTML = `
        <p>
            <i class="fas fa-check-circle" style="color: #2ea043;"></i> <strong>Insert baru:</strong> ${s.inserted} | 
            <i class="fas fa-sync-alt" style="color: #3b82f6;"></i> <strong>Update milestone:</strong> ${s.updated} | 
            <i class="fas fa-forward" style="color: #8b949e;"></i> <strong>Dilewati (sudah terisi/kosong):</strong> ${s.unchanged}
        </p>
    `;

  document.getElementById("logDetails").value =
    result.logs.length > 0
      ? result.logs.join("\n")
      : "Tidak ada data baru yang di-update ke database.";
}

// --- FITUR TAMBAHAN: PIVOT PREVIEW & DOWNLOAD ---
async function previewPivot() {
  const fileInput = document.getElementById("pivotExcel");
  const sowInput = document.getElementById("pivotSowids").value;

  if (fileInput.files.length === 0 || !sowInput.trim()) {
    alert("File Excel sama SOW ID wajib diisi bos!");
    return;
  }

  const formData = new FormData();
  for (let i = 0; i < fileInput.files.length; i++) {
    formData.append("files", fileInput.files[i]);
  }
  formData.append("sowids", sowInput);

  const btn = document.getElementById("btnPreview");
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';

  try {
    const response = await fetch("/api/preview-pivot", {
      method: "POST",
      body: formData,
    });
    const result = await response.json();

    if (!response.ok) throw new Error(result.error);

    // Render tabel HTML pakai data JSON dari Flask
    let tableHtml = `<thead><tr>`;
    result.columns.forEach((col) => {
      tableHtml += `<th>${col.replace(" Date", "")}</th>`;
    });
    tableHtml += `</tr></thead><tbody>`;

    result.data.forEach((row) => {
      tableHtml += `<tr>`;
      result.columns.forEach((col, index) => {
        let val = row[col];
        // Styling biar kece, kalau Project SOW ID di-bold, Done dikasih dot ijo
        if (index === 0) {
          tableHtml += `<td class="sticky-col">${val}</td>`;
        } else if (val === "Done") {
          tableHtml += `<td class="dot-cell"><span class="dot filled">●</span></td>`;
        } else {
          tableHtml += `<td class="dot-cell"><span class="dot empty">○</span></td>`;
        }
      });
      tableHtml += `</tr>`;
    });
    tableHtml += `</tbody>`;

    document.getElementById("pivotTableResult").innerHTML = tableHtml;
    document.getElementById("pivotPreviewContainer").style.display = "block";
  } catch (error) {
    alert("Waduh error: " + error.message);
    document.getElementById("pivotPreviewContainer").style.display = "none";
  } finally {
    btn.innerHTML = '<i class="fas fa-table"></i> Generate Preview';
  }
}

async function downloadPivot() {
  const fileInput = document.getElementById("pivotExcel");
  const sowInput = document.getElementById("pivotSowids").value;

  const formData = new FormData();
  for (let i = 0; i < fileInput.files.length; i++) {
    formData.append("files", fileInput.files[i]);
  }
  formData.append("sowids", sowInput);

  try {
    const response = await fetch("/api/download-pivot", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.error);
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "Report_IOMS_Pivot.xlsx";
    a.click();
  } catch (error) {
    alert("Gagal download pivot: " + error.message);
  }
}

async function compressPdf() {
  const fileInput = document.getElementById("pdfFiles");
  const quality = document.getElementById("pdfQuality").value;

  if (fileInput.files.length === 0) {
    alert("Upload PDF-nya dulu!");
    return;
  }

  const formData = new FormData();
  for (let i = 0; i < fileInput.files.length; i++) {
    formData.append("files", fileInput.files[i]);
  }
  formData.append("quality", quality);

  const btn = document.getElementById("btnCompress");
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Compressing...';
  btn.disabled = true;

  try {
    const response = await fetch("/api/compress-pdf", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) throw new Error(await response.text());

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    if (fileInput.files.length > 1) {
      a.download = "Hasil_Compress_Bulk.zip";
    } else {
      // Ambil nama file aslinya, terus selipin '_compressed' sebelum '.pdf'
      const oriName = fileInput.files[0].name;
      a.download = oriName.replace(/\.pdf$/i, "_compressed.pdf");
    }
    a.click();
  } catch (error) {
    alert("Gagal compress: " + error.message);
  } finally {
    btn.innerHTML = "Compress";
    btn.disabled = false;
  }
}
