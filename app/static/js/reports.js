const PAGE_SIZE = 10;

let troubleshootingReportsCache = [];
let excelReportsCache = [];
let monthlyReportsCache = [];

let troubleshootingReportsSearchTerm = "";
let excelReportsSearchTerm = "";
let monthlyReportsSearchTerm = "";

function escapeHtml(value) {
  if (value === null || value === undefined) return "";

  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function buildSearchText(row) {
  if (row === null || row === undefined) return "";

  if (typeof row === "object") {
    return Object.values(row)
      .map((value) => buildSearchText(value))
      .join(" ")
      .toLowerCase();
  }

  return String(row).toLowerCase();
}

function filterRows(rows, searchTerm) {
  const safeRows = asArray(rows);
  const term = String(searchTerm || "").trim().toLowerCase();

  if (!term) {
    return safeRows;
  }

  return safeRows.filter((row) => buildSearchText(row).includes(term));
}

function renderResultsInfo(containerId, totalRows, currentPage, pageSize = PAGE_SIZE) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!totalRows || totalRows <= 0) {
    container.textContent = "Showing 0-0 of 0 results";
    return;
  }

  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalRows);
  container.textContent = `Showing ${start}-${end} of ${totalRows} results`;
}

function renderPagination(containerId, pageInfo, onPageClick) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = "";

  const totalPages = pageInfo?.total_pages || 0;
  const currentPage = pageInfo?.page || 1;

  if (totalPages <= 1) return;

  const addButton = (label, page, { disabled = false, active = false } = {}) => {
    const li = document.createElement("li");
    li.className = `page-item${disabled ? " disabled" : ""}${active ? " active" : ""}`;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "page-link";
    btn.innerHTML = label;

    if (disabled) {
      btn.disabled = true;
    } else if (!active) {
      btn.addEventListener("click", () => onPageClick(page));
    }

    li.appendChild(btn);
    container.appendChild(li);
  };

  const addEllipsis = () => {
    const li = document.createElement("li");
    li.className = "page-item disabled";

    const span = document.createElement("span");
    span.className = "page-ellipsis";
    span.textContent = "...";

    li.appendChild(span);
    container.appendChild(li);
  };

  const buildPages = () => {
    const pages = [];

    if (totalPages <= 0) return pages;

    if (totalPages <= 4) {
      for (let p = 1; p <= totalPages; p++) {
        pages.push(p);
      }
      return pages;
    }

    const visiblePages = new Set();
    visiblePages.add(1);
    visiblePages.add(totalPages);
    visiblePages.add(currentPage);
    visiblePages.add(currentPage - 1);
    visiblePages.add(currentPage + 1);

    if (currentPage <= 3) {
      visiblePages.add(2);
      visiblePages.add(3);
      visiblePages.add(4);
    }

    if (currentPage >= totalPages - 2) {
      visiblePages.add(totalPages - 1);
      visiblePages.add(totalPages - 2);
      visiblePages.add(totalPages - 3);
    }

    const sortedPages = [...visiblePages]
      .filter((page) => page >= 1 && page <= totalPages)
      .sort((a, b) => a - b);

    for (let i = 0; i < sortedPages.length; i++) {
      const page = sortedPages[i];
      const previousPage = sortedPages[i - 1];

      if (i > 0 && page - previousPage > 1) {
        pages.push("...");
      }

      pages.push(page);
    }

    return pages;
  };

  addButton("&laquo;", 1, { disabled: currentPage === 1 });
  addButton("&lsaquo;", currentPage - 1, { disabled: currentPage === 1 });

  for (const item of buildPages()) {
    if (item === "...") {
      addEllipsis();
    } else {
      addButton(String(item), item, { active: item === currentPage });
    }
  }

  addButton("&rsaquo;", currentPage + 1, { disabled: currentPage === totalPages });
  addButton("&raquo;", totalPages, { disabled: currentPage === totalPages });
}

function paginateRows(rows, currentPage) {
  const safeRows = asArray(rows);
  const start = (currentPage - 1) * PAGE_SIZE;
  const end = start + PAGE_SIZE;

  return safeRows.slice(start, end);
}

function renderReportRows({
  rows,
  currentPage = 1,
  tableBodyId,
  paginationId,
  resultsInfoId,
  emptyMessage,
  rerender,
}) {
  const tbody = document.getElementById(tableBodyId);
  const pagination = document.getElementById(paginationId);

  if (!tbody || !pagination) return;

  const safeRows = asArray(rows);

  tbody.innerHTML = "";
  pagination.innerHTML = "";

  if (safeRows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="2" class="text-center text-muted py-3">
          ${escapeHtml(emptyMessage)}
        </td>
      </tr>
    `;

    renderResultsInfo(resultsInfoId, 0, 1);
    return;
  }

  const totalPages = Math.ceil(safeRows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(safeRows, safePage);

  pageRows.forEach((row) => {
    const fileName = row.file_name || "-";
    const fileUrl = row.file_url || row.download_url || "";

    const linkHtml = fileUrl
      ? `<a href="${escapeHtml(fileUrl)}" target="_blank" class="btn btn-sm btn-outline-primary">Open</a>`
      : `<span class="text-muted">No link</span>`;

    tbody.innerHTML += `
      <tr>
        <td>
          <div class="px-3">${escapeHtml(fileName)}</div>
        </td>
        <td class="text-center">${linkHtml}</td>
      </tr>
    `;
  });

  renderResultsInfo(resultsInfoId, safeRows.length, safePage);
  renderPagination(
    paginationId,
    {
      page: safePage,
      total_pages: totalPages,
    },
    (page) => rerender(page)
  );
}

function renderTroubleshootingReports(currentPage = 1) {
  const rows = filterRows(troubleshootingReportsCache, troubleshootingReportsSearchTerm);

  renderReportRows({
    rows,
    currentPage,
    tableBodyId: "troubleshootingReportsTable",
    paginationId: "troubleshootingReportsPagination",
    resultsInfoId: "troubleshootingReportsResultsInfo",
    emptyMessage: "No troubleshooting reports found in TigerData.",
    rerender: (page) => renderTroubleshootingReports(page),
  });
}

function renderExcelReports(currentPage = 1) {
  const rows = filterRows(excelReportsCache, excelReportsSearchTerm);

  renderReportRows({
    rows,
    currentPage,
    tableBodyId: "csvReportsTable",
    paginationId: "csvReportsPagination",
    resultsInfoId: "csvReportsResultsInfo",
    emptyMessage: "No Excel reports found in TigerData.",
    rerender: (page) => renderExcelReports(page),
  });
}

function renderMonthlyReports(currentPage = 1) {
  const rows = filterRows(monthlyReportsCache, monthlyReportsSearchTerm);

  renderReportRows({
    rows,
    currentPage,
    tableBodyId: "monthlyReportsTable",
    paginationId: "monthlyReportsPagination",
    resultsInfoId: "monthlyReportsResultsInfo",
    emptyMessage: "No monthly reports found in TigerData.",
    rerender: (page) => renderMonthlyReports(page),
  });
}

function updateReportsSummary(summary) {
  const generatedReportsCount = document.getElementById("generatedReportsCount");
  const troubleshootingReportsCount = document.getElementById("troubleshootingReportsCount");
  const csvReportsCount = document.getElementById("csvReportsCount");
  const monthlyReportsCount = document.getElementById("monthlyReportsCount");
  const onedriveReportsInfo = document.getElementById("onedriveReportsInfo");

  if (generatedReportsCount) {
    generatedReportsCount.textContent = summary.generated_reports_count ?? 0;
  }

  if (troubleshootingReportsCount) {
    troubleshootingReportsCount.textContent = summary.troubleshooting_reports_count ?? 0;
  }

  if (csvReportsCount) {
    csvReportsCount.textContent = summary.csv_reports_count ?? 0;
  }

  if (monthlyReportsCount) {
    monthlyReportsCount.textContent = summary.monthly_reports_count ?? 0;
  }

  if (onedriveReportsInfo) {
    onedriveReportsInfo.className = "alert alert-info small mb-4";
    onedriveReportsInfo.textContent =
      `Displaying reports from ${summary.primary_storage || "TigerData"}. ` +
      `OneDrive remains the backup storage.`;
  }
}

function setupReportSearchInputs() {
  const troubleshootingInput = document.getElementById("troubleshootingReportsSearch");
  const excelInput = document.getElementById("excelReportsSearch");
  const monthlyInput = document.getElementById("monthlyReportsSearch");

  if (troubleshootingInput) {
    troubleshootingInput.addEventListener("input", (event) => {
      troubleshootingReportsSearchTerm = event.target.value;
      renderTroubleshootingReports(1);
    });
  }

  if (excelInput) {
    excelInput.addEventListener("input", (event) => {
      excelReportsSearchTerm = event.target.value;
      renderExcelReports(1);
    });
  }

  if (monthlyInput) {
    monthlyInput.addEventListener("input", (event) => {
      monthlyReportsSearchTerm = event.target.value;
      renderMonthlyReports(1);
    });
  }
}

async function loadReports() {
  try {
    if (window.showLoading) {
      window.showLoading();
    }

    const res = await fetch("/api/reports/overview");

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();

    updateReportsSummary(data.summary || {});

    troubleshootingReportsCache = asArray(data.troubleshooting_reports);
    excelReportsCache = asArray(data.csv_reports);
    monthlyReportsCache = asArray(data.monthly_reports);

    renderTroubleshootingReports(1);
    renderExcelReports(1);
    renderMonthlyReports(1);
  } catch (error) {
    console.error("Failed to load reports:", error);

    const onedriveReportsInfo = document.getElementById("onedriveReportsInfo");
    if (onedriveReportsInfo) {
      onedriveReportsInfo.className = "alert alert-danger small mb-4";
      onedriveReportsInfo.textContent =
        error.message || "Failed to load reports from TigerData.";
    }
  } finally {
    if (window.hideLoading) {
      window.hideLoading();
    }
  }
}

function setMonthlyUploadStatus(message, type = "info") {
  const status = document.getElementById("monthlyReportUploadStatus");

  if (!status) return;

  const colorClass =
    type === "success"
      ? "text-success"
      : type === "danger"
      ? "text-danger"
      : "text-muted";

  status.className = `mt-3 small ${colorClass}`;
  status.textContent = message;
}

async function setupMonthlyReportUpload() {
  const form = document.getElementById("monthlyReportUploadForm");
  const fileInput = document.getElementById("monthlyBillFile");

  if (!form || !fileInput) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!fileInput.files || fileInput.files.length === 0) {
      setMonthlyUploadStatus("Please select a PDF electricity bill.", "danger");
      return;
    }

    const submitButton = form.querySelector("button[type='submit']");
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    try {
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "Generating...";
      }

      if (window.showLoading) {
        window.showLoading();
      }

      setMonthlyUploadStatus("Uploading and generating monthly report...");

      const res = await fetch("/api/reports/monthly/generate-from-bill", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Failed to generate monthly report.");
      }

      setMonthlyUploadStatus(data.message || "Monthly report generated successfully.", "success");

      fileInput.value = "";

      await loadReports();
    } catch (error) {
      console.error("Monthly report generation failed:", error);
      setMonthlyUploadStatus(error.message || "Monthly report generation failed.", "danger");
    } finally {
      if (window.hideLoading) {
        window.hideLoading();
      }

      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = "Upload and Generate";
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  setupReportSearchInputs();
  await setupMonthlyReportUpload();
  await loadReports();
});