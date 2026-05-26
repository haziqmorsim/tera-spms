const DASHBOARD_REFRESH_MS = 300000;
const DASHBOARD_PAGE_SIZE = 10;

let dashboardState = {
  lowPerformingPlants: [],
  activeAlarms: [],
  highTemperatureInverters: [],
};

let dashboardSortState = {
  lowPerformingPlants: {
    key: null,
    direction: "asc",
  },
  activeAlarms: {
    key: null,
    direction: "asc",
  },
  highTemperatureInverters: {
    key: null,
    direction: "asc",
  },
};

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

function isInvalidNumberValue(value) {
  if (value === null || value === undefined || value === "") {
    return true;
  }

  const textValue = String(value).trim().toLowerCase();

  return (
    textValue === "nan" ||
    textValue === "inf" ||
    textValue === "infinity" ||
    textValue === "-inf" ||
    textValue === "-infinity"
  );
}

function safeNumber(value, fallback = null) {
  if (isInvalidNumberValue(value)) {
    return fallback;
  }

  const numberValue = Number(value);

  if (!Number.isFinite(numberValue)) {
    return fallback;
  }

  return numberValue;
}

function formatNumber(value, digits = 2, fallback = "-") {
  const numberValue = safeNumber(value, null);

  if (numberValue === null) {
    return fallback;
  }

  return numberValue.toFixed(digits);
}

function formatPercent(value, digits = 2, fallback = "-") {
  const numberValue = safeNumber(value, null);

  if (numberValue === null) {
    return fallback;
  }

  return `${numberValue.toFixed(digits)}%`;
}

function valueOrDash(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  const textValue = String(value).trim().toLowerCase();

  if (
    textValue === "nan" ||
    textValue === "infinity" ||
    textValue === "-infinity"
  ) {
    return "-";
  }

  return String(value);
}

function getFirstElement(ids) {
  for (const id of ids) {
    const el = document.getElementById(id);

    if (el) {
      return el;
    }
  }

  return null;
}

function getElementInCardByText(cardTitleText, selector) {
  const cards = Array.from(document.querySelectorAll(".card"));

  const targetCard = cards.find((card) => {
    const headerText = (card.querySelector(".card-header")?.textContent || "").trim().toLowerCase();
    const bodyText = (card.querySelector(".card-body")?.textContent || "").trim().toLowerCase();
    const fullText = `${headerText} ${bodyText}`;

    return fullText.includes(cardTitleText.toLowerCase());
  });

  if (!targetCard) {
    return null;
  }

  return targetCard.querySelector(selector);
}

function getTableBundle(config) {
  const tbody = getFirstElement(config.tbodyIds) || getElementInCardByText(config.cardText, "tbody");
  const table = tbody ? tbody.closest("table") : null;
  const card = tbody ? tbody.closest(".card") : null;

  let resultsInfo = getFirstElement(config.resultsInfoIds);

  if (!resultsInfo && card) {
    resultsInfo = Array.from(card.querySelectorAll(".small.text-muted, .text-muted"))
      .find((el) => (el.textContent || "").toLowerCase().includes("showing")) || null;
  }

  let pagination = getFirstElement(config.paginationIds);

  if (!pagination && card) {
    pagination = card.querySelector("ul.custom-pagination, ul.pagination");
  }

  const colCount = table ? table.querySelectorAll("thead th").length : config.defaultColspan;

  return {
    tbody,
    table,
    card,
    resultsInfo,
    pagination,
    colCount: colCount || config.defaultColspan,
  };
}

function setTextByIds(ids, value) {
  ids.forEach((id) => {
    const el = document.getElementById(id);

    if (el) {
      el.textContent = value;
    }
  });
}

function setCardCountByTitle(titleText, value) {
  const cards = Array.from(document.querySelectorAll(".card"));

  const card = cards.find((item) => {
    const text = (item.textContent || "").toLowerCase();
    return text.includes(titleText.toLowerCase());
  });

  if (!card) {
    return;
  }

  const h2 = card.querySelector("h2");
  const countEl = card.querySelector("[data-count]");

  if (h2) {
    h2.textContent = value;
  } else if (countEl) {
    countEl.textContent = value;
  }
}

function renderStatusBadge(status) {
  const normalized = String(status || "").trim().toLowerCase();
  const label = status || "Unknown";

  if (
    normalized === "success" ||
    normalized === "normal" ||
    normalized === "completed"
  ) {
    return `<span class="badge bg-success">${escapeHtml(label)}</span>`;
  }

  if (normalized === "running" || normalized === "pending") {
    return `<span class="badge bg-primary">${escapeHtml(label)}</span>`;
  }

  if (
    normalized === "fail" ||
    normalized === "failed" ||
    normalized === "faulty" ||
    normalized === "error"
  ) {
    return `<span class="badge bg-danger">${escapeHtml(label)}</span>`;
  }

  if (normalized === "offline") {
    return `<span class="badge bg-secondary">${escapeHtml(label)}</span>`;
  }

  if (normalized === "standby" || normalized === "warning") {
    return `<span class="badge bg-warning text-dark">${escapeHtml(label)}</span>`;
  }

  return `<span class="badge bg-secondary">${escapeHtml(label)}</span>`;
}

function renderSeverityBadge(severity) {
  const normalized = String(severity || "").trim().toLowerCase();
  const label = severity || "-";

  if (normalized === "critical" || normalized === "high") {
    return `<span class="badge bg-danger">${escapeHtml(label)}</span>`;
  }

  if (normalized === "major") {
    return `<span class="badge bg-major">${escapeHtml(label)}</span>`;
  }

  if (normalized === "minor" || normalized === "medium") {
    return `<span class="badge bg-warning">${escapeHtml(label)}</span>`;
  }

  if (normalized === "warning") {
    return `<span class="badge bg-info">${escapeHtml(label)}</span>`;
  }

  if (normalized === "low" || normalized === "info") {
    return `<span class="badge bg-info text-dark">${escapeHtml(label)}</span>`;
  }

  return `<span class="badge bg-secondary">${escapeHtml(label)}</span>`;
}

function getDashboardSortValue(tableKey, row, sortKey) {
  if (!row) {
    return "";
  }

  if (tableKey === "lowPerformingPlants") {
    if (sortKey === "plant_name") {
      return row.plant_name || row.plantName || "";
    }

    if (sortKey === "psh") {
      return row.psh ?? row.plant_psh ?? row.plant_avg_psh;
    }

    if (sortKey === "city_avg_psh") {
      return row.city_avg_psh ?? row.overall_avg_psh;
    }

    if (sortKey === "deviation_pct") {
      return (
        row.deviation_pct ??
        row.psh_deviation_pct ??
        row.psh_deviation_pct_vs_city_avg
      );
    }
  }

  if (tableKey === "activeAlarms") {
    if (sortKey === "plant_name") {
      return row.plant_name || "";
    }

    if (sortKey === "device_name") {
      return row.device_name || "";
    }

    if (sortKey === "device_sn") {
      return row.device_sn || "";
    }

    if (sortKey === "alarm_name") {
      return row.alarm_name || "";
    }

    if (sortKey === "severity") {
      return row.severity || "";
    }
  }

  if (tableKey === "highTemperatureInverters") {
    if (sortKey === "plant_name") {
      return row.plant_name || "";
    }

    if (sortKey === "device_name") {
      return row.device_name || row.inverter_name || "";
    }

    if (sortKey === "device_sn") {
      return row.device_sn || row.inverter_sn || "";
    }

    if (sortKey === "internal_temperature_c") {
      return (
        row.internal_temperature_c ??
        row.temperature_c ??
        row.temperature
      );
    }
  }

  return row[sortKey] ?? "";
}

function compareDashboardSortValues(leftValue, rightValue) {
  const leftNumber = safeNumber(leftValue, null);
  const rightNumber = safeNumber(rightValue, null);

  if (leftNumber !== null && rightNumber !== null) {
    return leftNumber - rightNumber;
  }

  if (leftNumber !== null && rightNumber === null) {
    return -1;
  }

  if (leftNumber === null && rightNumber !== null) {
    return 1;
  }

  const leftText = valueOrDash(leftValue).toLowerCase();
  const rightText = valueOrDash(rightValue).toLowerCase();

  return leftText.localeCompare(rightText, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function getSortedDashboardRows(tableKey, rows) {
  const safeRows = asArray(rows);
  const sortState = dashboardSortState[tableKey];

  if (!sortState || !sortState.key) {
    return safeRows;
  }

  const directionMultiplier = sortState.direction === "desc" ? -1 : 1;

  return [...safeRows].sort((leftRow, rightRow) => {
    const leftValue = getDashboardSortValue(tableKey, leftRow, sortState.key);
    const rightValue = getDashboardSortValue(tableKey, rightRow, sortState.key);

    return compareDashboardSortValues(leftValue, rightValue) * directionMultiplier;
  });
}

function updateDashboardSortIcons() {
  const buttons = document.querySelectorAll(".dashboard-sort-header");

  buttons.forEach((button) => {
    const tableKey = button.dataset.dashboardSortTable;
    const sortKey = button.dataset.dashboardSortKey;
    const icon = button.querySelector(".dashboard-sort-icon");
    const sortState = dashboardSortState[tableKey];

    button.classList.remove("active");

    if (!icon) {
      return;
    }

    if (!sortState || sortState.key !== sortKey) {
      icon.textContent = "⇅";
      return;
    }

    button.classList.add("active");
    icon.textContent = sortState.direction === "asc" ? "🠅" : "🠇";
  });
}

function renderSortedDashboardTable(tableKey) {
  if (tableKey === "lowPerformingPlants") {
    renderLowPerformingPlants(1);
    return;
  }

  if (tableKey === "activeAlarms") {
    renderActiveAlarms(1);
    return;
  }

  if (tableKey === "highTemperatureInverters") {
    renderHighTemperatureInverters(1);
    return;
  }
}

function setupDashboardSorting() {
  const buttons = document.querySelectorAll(".dashboard-sort-header");

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const tableKey = button.dataset.dashboardSortTable;
      const sortKey = button.dataset.dashboardSortKey;

      if (!tableKey || !sortKey || !dashboardSortState[tableKey]) {
        return;
      }

      const currentSort = dashboardSortState[tableKey];

      if (currentSort.key === sortKey) {
        currentSort.direction = currentSort.direction === "asc" ? "desc" : "asc";
      } else {
        currentSort.key = sortKey;
        currentSort.direction = "asc";
      }

      updateDashboardSortIcons();
      renderSortedDashboardTable(tableKey);
    });
  });

  updateDashboardSortIcons();
}

function renderResultsInfo(container, totalRows, currentPage, pageSize = DASHBOARD_PAGE_SIZE) {
  if (!container) return;

  if (!totalRows || totalRows <= 0) {
    container.textContent = "Showing 0-0 of 0 results";
    return;
  }

  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalRows);

  container.textContent = `Showing ${start}-${end} of ${totalRows} results`;
}

function renderPagination(container, totalRows, currentPage, onPageClick) {
  if (!container) return;

  container.innerHTML = "";

  const totalPages = Math.ceil(totalRows / DASHBOARD_PAGE_SIZE);

  if (totalPages <= 1) return;

  const addButton = (label, page, options = {}) => {
    const disabled = options.disabled || false;
    const active = options.active || false;

    const li = document.createElement("li");
    li.className = `page-item${disabled ? " disabled" : ""}${active ? " active" : ""}`;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-link";
    button.innerHTML = label;

    if (disabled) {
      button.disabled = true;
    } else if (!active) {
      button.addEventListener("click", () => onPageClick(page));
    }

    li.appendChild(button);
    container.appendChild(li);
  };

  const addEllipsis = () => {
    const li = document.createElement("li");
    li.className = "page-item disabled";

    const span = document.createElement("span");
    span.className = "page-link";
    span.textContent = "...";

    li.appendChild(span);
    container.appendChild(li);
  };

  const totalPagesToShow = [];

  if (totalPages <= 5) {
    for (let page = 1; page <= totalPages; page += 1) {
      totalPagesToShow.push(page);
    }
  } else {
    const visible = new Set([
      1,
      totalPages,
      currentPage,
      currentPage - 1,
      currentPage + 1,
    ]);

    if (currentPage <= 3) {
      visible.add(2);
      visible.add(3);
      visible.add(4);
    }

    if (currentPage >= totalPages - 2) {
      visible.add(totalPages - 1);
      visible.add(totalPages - 2);
      visible.add(totalPages - 3);
    }

    const sorted = [...visible]
      .filter((page) => page >= 1 && page <= totalPages)
      .sort((a, b) => a - b);

    for (let index = 0; index < sorted.length; index += 1) {
      if (index > 0 && sorted[index] - sorted[index - 1] > 1) {
        totalPagesToShow.push("...");
      }

      totalPagesToShow.push(sorted[index]);
    }
  }

  addButton("&laquo;", 1, { disabled: currentPage === 1 });
  addButton("&lsaquo;", currentPage - 1, { disabled: currentPage === 1 });

  totalPagesToShow.forEach((page) => {
    if (page === "...") {
      addEllipsis();
    } else {
      addButton(String(page), page, { active: page === currentPage });
    }
  });

  addButton("&rsaquo;", currentPage + 1, { disabled: currentPage === totalPages });
  addButton("&raquo;", totalPages, { disabled: currentPage === totalPages });
}

function paginateRows(rows, currentPage) {
  const safeRows = asArray(rows);
  const start = (currentPage - 1) * DASHBOARD_PAGE_SIZE;

  return safeRows.slice(start, start + DASHBOARD_PAGE_SIZE);
}

function renderEmptyRow(tbody, colspan, message) {
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="${colspan}" class="text-center text-muted py-3">
        ${escapeHtml(message)}
      </td>
    </tr>
  `;
}

function updateKpis(data) {
  const kpis = data?.kpis || {};

  const lowPlants = safeNumber(kpis.low_performing_plants, 0);
  const activeAlarms = safeNumber(kpis.active_alarms, 0);
  const highTemp = safeNumber(kpis.high_temperature_inverters, 0);

  setTextByIds(
    [
      "lowPerformingPlantCount",
      "lowPerformingPlantsCount",
      "lowPshPlantsCount",
      "lowPlantsCount",
      "underperformingPlantsCount",
      "lowPerformingCount",
      "lowPshCount",
    ],
    lowPlants
  );

  setTextByIds(
    [
      "activeAlarmsCount",
      "alarmsCount",
      "alarmCount",
    ],
    activeAlarms
  );

  setTextByIds(
    [
      "highTemperatureInvertersCount",
      "highTempInvertersCount",
      "highTemperatureCount",
      "highTempCount",
    ],
    highTemp
  );

  setCardCountByTitle("Low-performing Plants", lowPlants);
  setCardCountByTitle("Active Alarms", activeAlarms);
  setCardCountByTitle("High-temperature Inverters", highTemp);

  const lowPshDay = data?.data_days?.low_psh_plants || data?.report_day;
  const highTempDay = data?.data_days?.high_temperature_inverters;

  setTextByIds(["dashboardReportDay", "reportDay"], valueOrDash(data?.report_day));
  setTextByIds(["lowPshReportDay", "lowPlantsReportDay"], valueOrDash(lowPshDay));
  setTextByIds(["highTemperatureReportDay", "highTempReportDay"], valueOrDash(highTempDay));
}

function renderLowPerformingPlants(currentPage = 1) {
  const bundle = getTableBundle({
    cardText: "Low-performing Plants",
    tbodyIds: [
      "lowPerformingPlantsTable",
      "lowPshPlantsTable",
      "underperformingPlantsTable",
    ],
    resultsInfoIds: [
      "lowPerformingResultsInfo",
      "lowPerformingPlantsResultsInfo",
      "lowPshPlantsResultsInfo",
      "underperformingPlantsResultsInfo",
    ],
    paginationIds: [
      "lowPerformingPagination",
      "lowPerformingPlantsPagination",
      "lowPshPlantsPagination",
      "underperformingPlantsPagination",
    ],
    defaultColspan: 4,
  });

  const tbody = bundle.tbody;

  if (!tbody) return;

  const rows = getSortedDashboardRows(
    "lowPerformingPlants",
    dashboardState.lowPerformingPlants
  );
  const colCount = bundle.colCount;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    renderEmptyRow(tbody, colCount, "No low-performing plants found.");
    renderResultsInfo(bundle.resultsInfo, 0, 1);

    if (bundle.pagination) {
      bundle.pagination.innerHTML = "";
    }

    return;
  }

  const totalPages = Math.ceil(rows.length / DASHBOARD_PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    const plantName = row.plant_name || row.plantName || "-";
    const psh = row.psh ?? row.plant_psh ?? row.plant_avg_psh;
    const cityAvgPsh = row.city_avg_psh ?? row.overall_avg_psh;
    const deviation =
      row.deviation_pct ??
      row.psh_deviation_pct ??
      row.psh_deviation_pct_vs_city_avg;

    if (colCount <= 4) {
      tbody.innerHTML += `
        <tr>
          <td class="px-3">${escapeHtml(plantName)}</td>
          <td class="text-center">${formatNumber(psh, 3)}</td>
          <td class="text-center">${formatNumber(cityAvgPsh, 3)}</td>
          <td class="text-center">${formatPercent(deviation, 2)}</td>
        </tr>
      `;
    } else {
      tbody.innerHTML += `
        <tr>
          <td class="px-3">${escapeHtml(plantName)}</td>
          <td class="text-center">${escapeHtml(row.city || "-")}</td>
          <td class="text-center">${renderStatusBadge(row.status || row.plant_status)}</td>
          <td class="text-center">${formatNumber(psh, 3)}</td>
          <td class="text-center">${formatNumber(cityAvgPsh, 3)}</td>
          <td class="text-center">${formatNumber(row.threshold_psh, 3)}</td>
          <td class="text-center">${formatPercent(deviation, 2)}</td>
        </tr>
      `;
    }
  });

  renderResultsInfo(bundle.resultsInfo, rows.length, safePage);
  renderPagination(bundle.pagination, rows.length, safePage, renderLowPerformingPlants);
}

function renderActiveAlarms(currentPage = 1) {
  const bundle = getTableBundle({
    cardText: "Active Alarms",
    tbodyIds: [
      "activeAlarmsTable",
      "alarmsTable",
    ],
    resultsInfoIds: [
      "alarmsResultsInfo",
      "activeAlarmsResultsInfo",
    ],
    paginationIds: [
      "alarmsPagination",
      "activeAlarmsPagination",
    ],
    defaultColspan: 5,
  });

  const tbody = bundle.tbody;

  if (!tbody) return;

  const rows = getSortedDashboardRows(
    "activeAlarms",
    dashboardState.activeAlarms
  );
  const colCount = bundle.colCount;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    renderEmptyRow(tbody, colCount, "No active alarms found.");
    renderResultsInfo(bundle.resultsInfo, 0, 1);

    if (bundle.pagination) {
      bundle.pagination.innerHTML = "";
    }

    return;
  }

  const totalPages = Math.ceil(rows.length / DASHBOARD_PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    if (colCount >= 6) {
      tbody.innerHTML += `
        <tr>
          <td class="px-3">${escapeHtml(row.plant_name || "-")}</td>
          <td>${escapeHtml(row.device_name || "-")}</td>
          <td class="text-center">${escapeHtml(row.device_sn || "-")}</td>
          <td>${escapeHtml(row.alarm_name || "-")}</td>
          <td class="text-center">${renderSeverityBadge(row.severity)}</td>
          <td class="text-center">${escapeHtml(valueOrDash(row.occurrence_ts))}</td>
        </tr>
      `;
    } else {
      tbody.innerHTML += `
        <tr>
          <td class="px-3">${escapeHtml(row.plant_name || "-")}</td>
          <td>${escapeHtml(row.device_name || "-")}</td>
          <td class="text-center">${escapeHtml(row.device_sn || "-")}</td>
          <td>${escapeHtml(row.alarm_name || "-")}</td>
          <td class="text-center">${renderSeverityBadge(row.severity)}</td>
        </tr>
      `;
    }
  });

  renderResultsInfo(bundle.resultsInfo, rows.length, safePage);
  renderPagination(bundle.pagination, rows.length, safePage, renderActiveAlarms);
}

function renderHighTemperatureInverters(currentPage = 1) {
  const bundle = getTableBundle({
    cardText: "High-temperature Inverters",
    tbodyIds: [
      "highTemperatureInvertersTable",
      "highTempInvertersTable",
    ],
    resultsInfoIds: [
      "temperatureResultsInfo",
      "highTemperatureInvertersResultsInfo",
      "highTempInvertersResultsInfo",
    ],
    paginationIds: [
      "temperaturePagination",
      "highTemperatureInvertersPagination",
      "highTempInvertersPagination",
    ],
    defaultColspan: 4,
  });

  const tbody = bundle.tbody;

  if (!tbody) return;

  const rows = getSortedDashboardRows(
    "highTemperatureInverters",
    dashboardState.highTemperatureInverters
  );
  const colCount = bundle.colCount;

  tbody.innerHTML = "";

  if (rows.length === 0) {
    renderEmptyRow(tbody, colCount, "No high-temperature inverters found.");
    renderResultsInfo(bundle.resultsInfo, 0, 1);

    if (bundle.pagination) {
      bundle.pagination.innerHTML = "";
    }

    return;
  }

  const totalPages = Math.ceil(rows.length / DASHBOARD_PAGE_SIZE);
  const safePage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageRows = paginateRows(rows, safePage);

  pageRows.forEach((row) => {
    const temperature =
      row.internal_temperature_c ??
      row.temperature_c ??
      row.temperature;

    tbody.innerHTML += `
      <tr>
        <td class="px-3">${escapeHtml(row.plant_name || "-")}</td>
        <td>${escapeHtml(row.device_name || row.inverter_name || "-")}</td>
        <td class="text-center">${escapeHtml(row.device_sn || row.inverter_sn || "-")}</td>
        <td class="text-center">${formatNumber(temperature, 1)}</td>
      </tr>
    `;
  });

  renderResultsInfo(bundle.resultsInfo, rows.length, safePage);
  renderPagination(bundle.pagination, rows.length, safePage, renderHighTemperatureInverters);
}

function renderDashboardError(message) {
  const target = getFirstElement([
    "dashboardError",
    "dashboardAlert",
    "dashboardMessage",
  ]);

  if (!target) {
    console.error(message);
    return;
  }

  target.innerHTML = `
    <div class="alert alert-danger" role="alert">
      ${escapeHtml(message || "Failed to load dashboard data.")}
    </div>
  `;
}

function clearDashboardError() {
  ["dashboardError", "dashboardAlert", "dashboardMessage"].forEach((id) => {
    const el = document.getElementById(id);

    if (el) {
      el.innerHTML = "";
    }
  });
}

function renderDashboardTables() {
  renderLowPerformingPlants(1);
  renderActiveAlarms(1);
  renderHighTemperatureInverters(1);
  updateDashboardSortIcons();
}

async function loadDashboard() {
  try {
    if (window.showLoading) {
      window.showLoading();
    }

    clearDashboardError();

    const res = await fetch("/api/dashboard/overview", {
      headers: {
        Accept: "application/json",
      },
    });

    if (!res.ok) {
      throw new Error(`Dashboard API failed with HTTP ${res.status}`);
    }

    const data = await res.json();

    updateKpis(data);

    dashboardState.lowPerformingPlants = asArray(
      data.low_performing_plants ||
      data.low_psh_plants ||
      data.underperforming_plants
    );

    dashboardState.activeAlarms = asArray(
      data.active_alarms ||
      data.alarms
    );

    dashboardState.highTemperatureInverters = asArray(
      data.high_temperature_inverters ||
      data.high_temp_inverters
    );

    renderDashboardTables();
  } catch (error) {
    console.error("Failed to load dashboard:", error);

    renderDashboardError(
      error.message ||
      "Failed to load dashboard data. Please check the FastAPI terminal."
    );

    updateKpis({
      kpis: {
        low_performing_plants: 0,
        active_alarms: 0,
        high_temperature_inverters: 0,
      },
    });

    dashboardState.lowPerformingPlants = [];
    dashboardState.activeAlarms = [];
    dashboardState.highTemperatureInverters = [];

    renderDashboardTables();
  } finally {
    if (window.hideLoading) {
      window.hideLoading();
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupDashboardSorting();
  loadDashboard();

  window.setInterval(() => {
    loadDashboard();
  }, DASHBOARD_REFRESH_MS);
});