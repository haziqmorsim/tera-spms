const PAGE_SIZE = 10;

let jobRunsCache = [];
let emailDeliveriesCache = [];
let oneDriveUploadsCache = [];
let activityLogsCache = [];

let jobRunsSearchTerm = "";
let emailDeliveriesSearchTerm = "";
let oneDriveUploadsSearchTerm = "";
let activityLogsSearchTerm = "";

function escapeHtml(value) {
  if (value === null || value === undefined) return "";

  if (typeof value === "object") {
    return escapeHtml(JSON.stringify(value, null, 2));
  }

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

  if (!term) return safeRows;

  return safeRows.filter((row) => buildSearchText(row).includes(term));
}

function paginateRows(rows, currentPage) {
  const safeRows = asArray(rows);
  const start = (currentPage - 1) * PAGE_SIZE;
  return safeRows.slice(start, start + PAGE_SIZE);
}

function statusBadge(status) {
  const s = (status || "").toLowerCase();

  if (s === "success") return `<span class="badge bg-success">Success</span>`;
  if (s === "fail") return `<span class="badge bg-danger">Fail</span>`;
  if (s === "running") return `<span class="badge bg-primary">Running</span>`;
  if (s === "resolved") return `<span class="badge bg-success">Resolved</span>`;
  if (s === "closed") return `<span class="badge bg-secondary">Closed</span>`;

  return `<span class="badge bg-warning text-dark">${escapeHtml(status || "Unknown")}</span>`;
}

function deliveryBadge(action) {
  return action === "Email sent"
    ? `<span class="badge bg-success">Delivered</span>`
    : `<span class="badge bg-danger">Failed</span>`;
}

function uploadBadge(action) {
  return action === "OneDrive upload"
    ? `<span class="badge bg-success">Uploaded</span>`
    : `<span class="badge bg-danger">Failed</span>`;
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

    if (totalPages <= 4) {
      for (let p = 1; p <= totalPages; p++) pages.push(p);
      return pages;
    }

    const visiblePages = new Set([
      1,
      totalPages,
      currentPage,
      currentPage - 1,
      currentPage + 1,
    ]);

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

      if (i > 0 && page - previousPage > 1) pages.push("...");
      pages.push(page);
    }

    return pages;
  };

  addButton("&laquo;", 1, { disabled: currentPage === 1 });
  addButton("&lsaquo;", currentPage - 1, { disabled: currentPage === 1 });

  for (const item of buildPages()) {
    if (item === "...") addEllipsis();
    else addButton(String(item), item, { active: item === currentPage });
  }

  addButton("&rsaquo;", currentPage + 1, { disabled: currentPage === totalPages });
  addButton("&raquo;", totalPages, { disabled: currentPage === totalPages });
}

function renderJobRunsTable(currentPage = 1) {
  const rows = filterRows(jobRunsCache, jobRunsSearchTerm);
  const tbody = document.getElementById("jobRunsTable");
  const pagination = document.getElementById("jobRunsPagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted text-center py-3">No job runs found</td></tr>`;
    pagination.innerHTML = "";
    renderResultsInfo("jobRunsResultsInfo", 0, 1);
    return;
  }

  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    tbody.innerHTML += `
      <tr>
        <td class="px-3">${escapeHtml(row.job_name || "-")}</td>
        <td class="text-center">${statusBadge(row.status)}</td>
        <td class="text-center">${escapeHtml(row.started_at || "-")}</td>
        <td class="text-center">${escapeHtml(row.finished_at || "-")}</td>
        <td class="details-line" style="white-space: pre-line;">${escapeHtml(row.details || "-")}</td>
      </tr>
    `;
  });

  renderResultsInfo("jobRunsResultsInfo", rows.length, safePage);
  renderPagination("jobRunsPagination", { page: safePage, total_pages: totalPages }, renderJobRunsTable);
}

function renderEmailDeliveriesTable(currentPage = 1) {
  const rows = filterRows(emailDeliveriesCache, emailDeliveriesSearchTerm);
  const tbody = document.getElementById("emailDeliveriesTable");
  const pagination = document.getElementById("emailDeliveriesPagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-muted text-center py-3">No email deliveries found</td></tr>`;
    pagination.innerHTML = "";
    renderResultsInfo("emailDeliveriesResultsInfo", 0, 1);
    return;
  }

  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    tbody.innerHTML += `
      <tr>
        <td class="text-center">${escapeHtml(row.event_time || "-")}</td>
        <td class="text-center">${escapeHtml(row.recipient || "-")}</td>
        <td class="text-center">${escapeHtml(row.subject || "-")}</td>
        <td class="text-center">${deliveryBadge(row.action)}</td>
      </tr>
    `;
  });

  renderResultsInfo("emailDeliveriesResultsInfo", rows.length, safePage);
  renderPagination("emailDeliveriesPagination", { page: safePage, total_pages: totalPages }, renderEmailDeliveriesTable);
}

function renderOneDriveUploadsTable(currentPage = 1) {
  const rows = filterRows(oneDriveUploadsCache, oneDriveUploadsSearchTerm);
  const tbody = document.getElementById("oneDriveUploadsTable");
  const pagination = document.getElementById("oneDriveUploadsPagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-muted text-center py-3">No OneDrive uploads found</td></tr>`;
    pagination.innerHTML = "";
    renderResultsInfo("oneDriveUploadsResultsInfo", 0, 1);
    return;
  }

  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    tbody.innerHTML += `
      <tr>
        <td class="text-center">${escapeHtml(row.event_time || "-")}</td>
        <td class="text-center">${escapeHtml(row.category || "-")}</td>
        <td>${escapeHtml(row.target || "-")}</td>
        <td class="text-center">${uploadBadge(row.action)}</td>
      </tr>
    `;
  });

  renderResultsInfo("oneDriveUploadsResultsInfo", rows.length, safePage);
  renderPagination("oneDriveUploadsPagination", { page: safePage, total_pages: totalPages }, renderOneDriveUploadsTable);
}

function renderActivityLogsTable(currentPage = 1) {
  const rows = filterRows(activityLogsCache, activityLogsSearchTerm);
  const tbody = document.getElementById("activityLogsTable");
  const pagination = document.getElementById("activityLogsPagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted text-center py-3">No activity logs found</td></tr>`;
    pagination.innerHTML = "";
    renderResultsInfo("activityLogsResultsInfo", 0, 1);
    return;
  }

  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    tbody.innerHTML += `
      <tr>
        <td class="text-center">${escapeHtml(row.event_time || "-")}</td>
        <td>${escapeHtml(row.full_name || "-")}</td>
        <td class="text-center">${escapeHtml(row.action || "-")}</td>
        <td>${escapeHtml(row.target || "-")}</td>
        <td class="text-center">${escapeHtml(row.status_code || "-")}</td>
      </tr>
    `;
  });

  renderResultsInfo("activityLogsResultsInfo", rows.length, safePage);
  renderPagination("activityLogsPagination", { page: safePage, total_pages: totalPages }, renderActivityLogsTable);
}

function setupLogSearchInputs() {
  const jobRunsInput = document.getElementById("jobRunsSearch");
  const emailDeliveriesInput = document.getElementById("emailDeliveriesSearch");
  const oneDriveUploadsInput = document.getElementById("oneDriveUploadsSearch");
  const activityLogsInput = document.getElementById("activityLogsSearch");

  if (jobRunsInput) {
    jobRunsInput.addEventListener("input", (event) => {
      jobRunsSearchTerm = event.target.value;
      renderJobRunsTable(1);
    });
  }

  if (emailDeliveriesInput) {
    emailDeliveriesInput.addEventListener("input", (event) => {
      emailDeliveriesSearchTerm = event.target.value;
      renderEmailDeliveriesTable(1);
    });
  }

  if (oneDriveUploadsInput) {
    oneDriveUploadsInput.addEventListener("input", (event) => {
      oneDriveUploadsSearchTerm = event.target.value;
      renderOneDriveUploadsTable(1);
    });
  }

  if (activityLogsInput) {
    activityLogsInput.addEventListener("input", (event) => {
      activityLogsSearchTerm = event.target.value;
      renderActivityLogsTable(1);
    });
  }
}

async function loadLogs() {
  try {
    if (window.showLoading) window.showLoading();

    const res = await fetch("/api/logs/overview");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();

    document.getElementById("jobRunCount").textContent = data.summary?.job_run_count ?? 0;
    document.getElementById("emailDeliveryCount").textContent = data.summary?.email_delivery_count ?? 0;
    document.getElementById("oneDriveUploadCount").textContent = data.summary?.onedrive_upload_count ?? 0;
    document.getElementById("activityLogCount").textContent = data.summary?.activity_log_count ?? 0;

    jobRunsCache = asArray(data.job_runs);
    emailDeliveriesCache = asArray(data.email_deliveries);
    oneDriveUploadsCache = asArray(data.onedrive_uploads);
    activityLogsCache = asArray(data.activity_logs);

    renderJobRunsTable(1);
    renderEmailDeliveriesTable(1);
    renderOneDriveUploadsTable(1);
    renderActivityLogsTable(1);
  } catch (error) {
    console.error("Failed to load logs:", error);
  } finally {
    if (window.hideLoading) window.hideLoading();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupLogSearchInputs();
  loadLogs();
});