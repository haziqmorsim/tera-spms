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

let usersCache = [];
let editModalInstance = null;
let deleteModalInstance = null;

function showAlert(message, type = "success") {
    const alertBox = document.getElementById("settingsAlert");
    if (!alertBox) return;

    alertBox.innerHTML = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
}

function formatRoleBadge(role) {
    const normalized = String(role || "").toLowerCase();
    if (normalized === "admin") {
        return `<span class="badge bg-primary">Admin</span>`;
    }
    return `<span class="badge bg-secondary">User</span>`;
}

function formatActiveBadge(isActive) {
    return isActive
        ? `<span class="badge bg-success">Active</span>`
        : `<span class="badge bg-warning">Inactive</span>`;
}

function formatSessionStatusBadge(status) {
    if (status === "available") {
        return `<span class="badge bg-success">Available</span>`;
    }
    if (status === "missing") {
        return `<span class="badge bg-danger">Missing</span>`;
    }
    if (status === "expired") {
        return `<span class="badge bg-warning text-dark">Expired</span>`;
    }
    return `<span class="badge bg-secondary">${escapeHtml(status || "Unknown")}</span>`;
}

function renderResultsInfo(containerId, totalRows, currentPage, pageSize = PAGE_SIZE) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!totalRows || totalRows <= 0) {
        container.textContent("Showing 0-0 of 0 results");
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
        li.className = `page-item${disabled ? "disabled" : ""}${active ? "active" : ""}`;

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
    }

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
    addButton("&lsaquo;", currentPage - 1, { disabled: currentPage === 1});

    for (const item of buildPages()) {
        if (item === "...") {
            addEllipsis();
        } else {
            addButton(String(item), item, { active: item === currentPage });
        }
    }

    addButton("&rsaquo;", currentPage + 1, { disabled: currentPage === totalPages });
    addButton("&raquo;", totalPages, { disabled: currentPage === totalPages});
}

function paginateRows(rows, currentPage) {
    const start = (currentPage - 1) * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    return rows.slice(start, end);
}

function renderUsersTable(users, currentPage = 1) {
    const tbody = document.getElementById("settingsUsersTable");
    const pagination = document.getElementById("settingsUsersPagination")
    if (!tbody || !pagination) return;

    tbody.innerHTML = "";
    pagination.innerHTML = "";

    if (!users || users.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="text-center text-muted py-3">No users found</td>
            </tr>
        `;
        renderResultsInfo("settingsUsersResultsInfo", 0, 1);
        return;
    }

    const totalPages = Math.ceil(users.length / PAGE_SIZE);
    const safePage = Math.min(Math.max(currentPage, 1), totalPages);
    const pageRows = paginateRows(users, safePage);

    pageRows.forEach((user) => {
        tbody.innerHTML += `
            <tr>
                <td>${escapeHtml(user.full_name)}</td>
                <td class="text-center">${escapeHtml(user.username)}</td>
                <td>${escapeHtml(user.email)}</td>
                <td class="text-center">${formatRoleBadge(user.role)}</td>
                <td class="text-center">${formatActiveBadge(user.is_active)}</td>
                <td class="text-center">${escapeHtml(user.last_signin_at || "-")}</td>
                <td class="text-center">${escapeHtml(user.created_at || "-")}</td>
                <td class="text-center">
                    <div class="d-flex justify-content-center">
                        <button class="btn btn-sm btn-outline-primary me-2" onclick="openEditUser('${user.id}')">Edit</button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteUser('${user.id}')">Delete</button>
                    </div>
                </td>
            </tr>
        `;
    });

    renderResultsInfo("settingsUsersResultsInfo", users.length, safePage);
    renderPagination("settingsUsersPagination", { page: safePage, total_pages: totalPages }, (page) => {
        renderUsersTable(users, page);
    })
}

async function loadUsers() {
    try {
        const res = await fetch("/api/settings/users");
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to load users.");
        }

        usersCache = data.users || [];
        renderUsersTable(usersCache);
    } catch (error) {
        console.error("Failed to load users:", error);
        showAlert(error.message || "Failed to load users.", "danger");
    }
}

window.openEditUser = function (userId) {
    const user = usersCache.find((u) => u.id === userId);
    if (!user) return;

    document.getElementById("editUserId").value = user.id;
    document.getElementById("editFullName").value = user.full_name || "";
    document.getElementById("editUsername").value = user.username || "";
    document.getElementById("editEmail").value = user.email || "";
    document.getElementById("editRole").value = (user.role || "user").toLowerCase();
    document.getElementById("editIsActive").checked = !!user.is_active;

    const modalEl = document.getElementById("editUserModal");
    editModalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    editModalInstance.show();
};

window.deleteUser = async function (userId) {
    const user = usersCache.find((u) => u.id === userId);

    if (!user) {
        showAlert("User now found.", "danger");
        return;
    }

    document.getElementById("deleteUserId").value = user.id;
    document.getElementById("deleteUserName").textContent = 
        `${user.full_name || user.username || user.email}`;

    const modalEl = document.getElementById("deleteUserModal");
    deleteModalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    deleteModalInstance.show();
};

async function loadEmailSettings() {
    try {
        window.showLoading();

        const res = await fetch("/api/settings/email");
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to load email settings.");
        }

        document.getElementById("emailDeliveryMethod").value = "Microsoft Graph";
        // data.email_delivery_method || "graph"
        document.getElementById("graphTenantId").value = data.graph_tenant_id || "";
        document.getElementById("graphClientId").value = data.graph_client_id || "";
        document.getElementById("graphClientSecret").value = data.graph_client_secret || "";
        document.getElementById("graphSenderEmail").value = data.graph_sender_email || "";
        document.getElementById("emailTo").value = data.email_to || "";
    } catch (error) {
        console.error("Failed to load email settings:", error);
        showAlert("Failed to load email settings.", "danger");
    } finally {
        window.hideLoading();
    }
}

async function loadReportSettings() {
    try {
        window.showLoading();

        const res = await fetch("/api/settings/reports");
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to load report settings.");
        }

        document.getElementById("lowPshPct").value = data.low_psh_underperformance_pct ?? 10;
        document.getElementById("lowPshThreshold").value = data.low_psh_threshold ?? 3;
        document.getElementById("lowInverterCurrentThresholdPct").value = data.low_inverter_psh_threshold_pct ?? 10;       
        document.getElementById("lowStringCurrentThresholdPct").value = data.low_string_current_threshold_pct ?? 20;
        document.getElementById("stringCurrentStartTime").value = data.string_current_start_time ?? "07:30";
        document.getElementById("stringCurrentEndTime").value = data.string_current_end_time ?? "19:30";
        document.getElementById("tempThreshold").value = data.temp_threshold_c ?? 70; 
    } catch (error) {
        console.error("Failed to load report settings:", error);
        showAlert("Failed to load report settings.", "danger");
    } finally {
        window.hideLoading();
    }
}

async function loadFusionSolarSessionStatus() {
    window.showLoading();

    const res = await fetch("/api/settings/fusionsolar-session");
    const data = await res.json();

    if (!res.ok) {
        throw new Error(data.detail || "Failed to load FusionSolar session status.");
    }

    document.getElementById("fsSessionFile").textContent = data.file_name || "-";
    document.getElementById("fsSessionStatus").innerHTML = formatSessionStatusBadge(data.status);
    document.getElementById("fsSessionModified").textContent = data.last_modified || "-";
    document.getElementById("fsSessionSize").textContent =
        data.size_kb !== undefined && data.size_kb !== null ? `${data.size_kb} KB` : "-";
    document.getElementById("fsSessionPath").textContent = data.file_path || "-";
    document.getElementById("fsSessionMessage").textContent = data.message || "-";

    window.hideLoading();
}

document.addEventListener("DOMContentLoaded", async () => {
    await loadUsers();
    await loadEmailSettings();
    await loadReportSettings();
    await loadFusionSolarSessionStatus();

    const editUserForm = document.getElementById("editUserForm");
    if (editUserForm) {
        editUserForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const userId = document.getElementById("editUserId").value;
            const payload = {
                full_name: document.getElementById("editFullName").value.trim(),
                username: document.getElementById("editUsername").value.trim(),
                email: document.getElementById("editEmail").value.trim(),
                role: document.getElementById("editRole").value,
                is_active: document.getElementById("editIsActive").checked,
            };

            try {
                const res = await fetch(`/api/settings/users/${userId}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();

                if (!res.ok) {
                    throw new Error(data.detail || "Failed to update user.");
                }

                if (editModalInstance) {
                    editModalInstance.hide();
                }

                showAlert(data.message || "User updated successfully.");
                await loadUsers();
            } catch (error) {
                console.error("Update user failed:", error);
                showAlert(error.message || "Failed to update user.", "danger");
            }
        });
    }

    const confirmDeleteUserBtn = document.getElementById("confirmDeleteUserBtn");
    if (confirmDeleteUserBtn) {
        confirmDeleteUserBtn.addEventListener("click", async () => {
            const userId = document.getElementById("deleteUserId").value;

            if (!userId) {
                showAlert("No user selected for deletion.", "danger");
                return;
            }

            try {
                confirmDeleteUserBtn.disabled = true;
                confirmDeleteUserBtn.textContent = "Deleting...";

                const res = await fetch(`/api/settings/users/${userId}`, {
                    method: "DELETE",
                });

                const date = await res.json();

                if (!res.ok) {
                    throw new Error(data.detail || "Failed to delete user.");
                }

                if (deleteModalInstance) {
                    deleteModalInstance.hide();
                }

                await loadUsers();
            } catch (error) {
                console.error("Delete user failed:", error);
                showAlert(error.message, "Failed to delete user.", "danger");
            } finally {
                confirmDeleteUserBtn.disabled = false;
                confirmDeleteUserBtn.textContent = "Delete User";
            }
        });
    }

    const emailForm = document.getElementById("emailSettingsForm");
    if (emailForm) {
        emailForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const payload = {
                email_delivery_method: document.getElementById("emailDeliveryMethod").value.trim(),
                graph_tenant_id: document.getElementById("graphTenantId").value.trim(),
                graph_client_id: document.getElementById("graphClientId").value.trim(),
                graph_client_secret: document.getElementById("graphClientSecret").value,
                graph_sender_email: document.getElementById("graphSenderEmail").value.trim(),
                email_to: document.getElementById("emailTo").value.trim(),
            };

            try {
                const res = await fetch("/api/settings/email", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();

                if (!res.ok) {
                    throw new Error(data.detail || "Failed to update email settings.");
                }

                showAlert(data.message || "Email settings updated successfully.");
                await loadEmailSettings();
            } catch (error) {
                console.error("Email settings update failed:", error);
                showAlert(error.message || "Failed to update email settings.", "danger");
            }
        });
    }

    const reportForm = document.getElementById("reportSettingsForm");
    if (reportForm) {
        reportForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const payload = {
                low_psh_underperformance_pct: Number(document.getElementById("lowPshPct").value),
                low_psh_threshold: Number(document.getElementById("lowPshThreshold").value),
                temp_threshold_c: Number(document.getElementById("tempThreshold").value),
                low_string_current_threshold_pct: Number(document.getElementById("lowStringCurrentThresholdPct").value),
                string_current_start_time: document.getElementById("stringCurrentStartTime").value.trim(),
                string_current_end_time: document.getElementById("stringCurrentEndTime").value.trim(),
            };

            try {
                const res = await fetch("/api/settings/reports", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();

                if (!res.ok) {
                    throw new Error(data.detail || "Failed to update report settings.");
                }

                showAlert(data.message || "Report settings updated successfully.");
                await loadReportSettings();
            } catch (error) {
                console.error("Report settings update failed:", error);
                showAlert(error.message || "Failed to update report settings.", "danger");
            }
        });
    }

    const refreshBtn = document.getElementById("refreshFusionSolarSessionBtn");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {
            try {
                await loadFusionSolarSessionStatus();
                showAlert("FusionSolar session status refreshed.");
            } catch (error) {
                console.error("Refresh FusionSolar session failed:", error);
                showAlert(error.message || "Failed to refresh FusionSolar session status.", "danger");
            }
        });
    }

    const deleteBtn = document.getElementById("deleteFusionSolarSessionBtn");
    if (deleteBtn) {
        deleteBtn.addEventListener("click", async () => {
            const confirmed = confirm("Delete the saved FusionSolar session file?");
            if (!confirmed) return;

            try {
                const res = await fetch("/api/settings/fusionsolar-session", {
                    method: "DELETE",
                });
                const data = await res.json();

                if (!res.ok) {
                    throw new Error(data.detail || "Failed to delete FusionSolar session file.");
                }

                showAlert(data.message || "FusionSolar session file deleted successfully.");
                await loadFusionSolarSessionStatus();
            } catch (error) {
                console.error("Delete FusionSolar session failed:", error);
                showAlert(error.message || "Failed to delete FusionSolar session file.", "danger");
            }
        });
    }
});