const PAGE_SIZE = 10;

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function severityBadge(severity) {
  const s = (severity || "").toLowerCase();

  if (s === "critical") return `<span class="badge bg-danger">Critical</span>`;
  if (s === "major") return `<span class="badge bg-major">Major</span>`;
  if (s === "minor") return `<span class="badge bg-warning">Minor</span>`;
  if (s === "warning") return `<span class="badge bg-info">Warning</span>`;
  return `<span class="badge bg-warning">${escapeHtml(severity || "Unknown")}</span>`;
}

function roundDown2(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Math.floor(Number(value) * 100) / 100;
}

function format2(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(2);
}

function format1(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(1);
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

    if (totalPages <=4) {
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
  const start = (currentPage - 1) * PAGE_SIZE;
  const end = start + PAGE_SIZE;
  return rows.slice(start, end);
}

function sortByPlantName(rows) {
  return [...rows].sort((a, b) => {
    const plantA = (a.plant_name || "").toLowerCase();
    const plantB = (b.plant_name || "").toLowerCase();
    return plantA.localeCompare(plantB);
  });
}

function renderLowPerformingTable(rows, currentPage = 1) {
  const tbody = document.getElementById("lowPerformingPlantsTable");
  const pagination = document.getElementById("lowPerformingPagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="text-muted text-center py-3">No low-performing plants found</td>
      </tr>
    `;
    pagination.innerHTML = "";
    renderResultsInfo("lowPerformingResultsInfo", 0, 1);
    return;
  }

  const sortedRows = sortByPlantName(rows);
  const totalPages = Math.ceil(sortedRows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(sortedRows, safePage);

  pageRows.forEach((row) => {
    const plantPsh = row.plant_avg_psh;
    const cityAvgPsh = roundDown2(row.overall_avg_psh);
    const deviation = row.psh_deviation_pct;

    tbody.innerHTML += `
      <tr>
        <td class="px-3">${escapeHtml(row.plant_name || "-")}</td>
        <td class="text-center">${format2(plantPsh)}</td>
        <td class="text-center">${format2(cityAvgPsh)}</td>
        <td class="text-center">${format2(deviation)}</td>
      </tr>
    `;
  });

  renderResultsInfo("lowPerformingResultsInfo", sortedRows.length, safePage);
  renderPagination(
    "lowPerformingPagination",
    { page: safePage, total_pages: totalPages },
    (page) => renderLowPerformingTable(sortedRows, page)
  );
}

function renderAlarmsTable(rows, currentPage = 1) {
  const tbody = document.getElementById("activeAlarmsTable");
  const pagination = document.getElementById("alarmsPagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="text-muted text-center py-3">No active alarms found</td>
      </tr>
    `;
    pagination.innerHTML = "";
    renderResultsInfo("alarmsResultsInfo", 0, 1);
    return;
  }

  const sortedRows = sortByPlantName(rows);
  const totalPages = Math.ceil(sortedRows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(sortedRows, safePage);

  pageRows.forEach((row) => {
    tbody.innerHTML += `
      <tr>
        <td class="px-3">${escapeHtml(row.plant_name || "-")}</td>
        <td class="text-center">${escapeHtml(row.device_name || "-")}</td>
        <td class="text-center">${escapeHtml(row.device_sn || "-")}</td>
        <td class="text-center">${escapeHtml(row.alarm_name || "-")}</td>
        <td class="text-center">${severityBadge(row.severity)}</td>
      </tr>
    `;
  });

  renderResultsInfo("alarmsResultsInfo", sortedRows.length, safePage);
  renderPagination(
    "alarmsPagination",
    { page: safePage, total_pages: totalPages },
    (page) => renderAlarmsTable(sortedRows, page)
  );
}

function renderHighTemperatureTable(rows, currentPage = 1) {
  const tbody = document.getElementById("highTemperatureInvertersTable");
  const pagination = document.getElementById("temperaturePagination");

  if (!tbody || !pagination) return;

  tbody.innerHTML = "";

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="text-muted text-center py-3">No high-temperature inverters found</td>
      </tr>
    `;
    pagination.innerHTML = "";
    renderResultsInfo("temperatureResultsInfo", 0, 1);
    return;
  }

  const sortedRows = sortByPlantName(rows);
  const totalPages = Math.ceil(sortedRows.length / PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(sortedRows, safePage);

  pageRows.forEach((row) => {
    tbody.innerHTML += `
      <tr>
        <td class="px-3">${escapeHtml(row.plant_name || "-")}</td>
        <td class="text-center">${escapeHtml(row.device_name || "-")}</td>
        <td class="text-center">${escapeHtml(row.device_sn || "-")}</td>
        <td class="text-center">${format1(row.internal_temperature_c)}</td>
      </tr>
    `;
  });

  renderResultsInfo("temperatureResultsInfo", sortedRows.length, safePage);
  renderPagination(
    "temperaturePagination",
    { page: safePage, total_pages: totalPages },
    (page) => renderHighTemperatureTable(sortedRows, page)
  );
}

async function loadDashboard() {
  try {
    window.showLoading();

    const res = await fetch("/api/dashboard/overview");
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();

    const lowCount = document.getElementById("lowPerformingPlantCount");
    const alarmCount = document.getElementById("alarmCount");
    const highTempCount = document.getElementById("highTemperatureCount");

    if (lowCount) {
      lowCount.textContent = data.summary.low_performing_plant_count ?? 0;
    }
    if (alarmCount) {
      alarmCount.textContent = data.summary.active_alarm_count ?? 0;
    }
    if (highTempCount) {
      highTempCount.textContent = data.summary.high_temperature_inverter_count ?? 0;
    }

    renderLowPerformingTable(data.low_performing_plants || [], 1);
    renderAlarmsTable(data.alarms || [], 1);
    renderHighTemperatureTable(data.high_temperature_inverters || [], 1);
  } catch (error) {
    console.error("Failed to load dashboard:", error);

    const lowCount = document.getElementById("lowPerformingPlantCount");
    const alarmCount = document.getElementById("alarmCount");
    const highTempCount = document.getElementById("highTemperatureCount");

    if (lowCount) lowCount.textContent = "!";
    if (alarmCount) alarmCount.textContent = "!";
    if (highTempCount) highTempCount.textContent = "!";

    renderLowPerformingTable([], 1);
    renderAlarmsTable([], 1);
    renderHighTemperatureTable([], 1);
  } finally {
    window.hideLoading();
  }
}

document.addEventListener("DOMContentLoaded", loadDashboard);