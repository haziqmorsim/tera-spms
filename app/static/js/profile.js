function escapeHtml(value) {
    if (value === null || value === undefined) return "";

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function showProfileAlert(message, type = "success") {
    const alertBox = document.getElementById("profileAlert");

    if (!alertBox) return;

    alertBox.innerHTML = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
}

function setText(id, value) {
    const el = document.getElementById(id);

    if (!el) return;

    el.textContent = value || "";
}

function formatRole(role) {
    const normalized = String(role || "").trim().toLowerCase();

    if (normalized === "admin") {
        return "Admin";
    }

    return "User";
}

function formatStatus(isActive) {
    return isActive ? "Active" : "Inactive";
}

function setFormLoading(isLoading) {
    const saveBtn = document.getElementById("saveProfileBtn");

    if (!saveBtn) return;

    saveBtn.disabled = isLoading;
    saveBtn.textContent = isLoading ? "Saving..." : "Save Changes";
}

function clearPasswordFields() {
    const fields = [
        "profileCurrentPassword", 
        "profileNewPassword", 
        "profileConfirmNewPassword",
    ];

    fields.forEach((id) => {
        const el = document.getElementById(id);

        if (el) {
            el.value = "";
        }
    });
}

function populateProfile(user) {
    const fullNameInput = document.getElementById("profileFullName");
    const usernameInput = document.getElementById("profileUsername"); 
    const emailInput = document.getElementById("profileEmail");

    if (fullNameInput) {
        fullNameInput.value = user.full_name || "";
    }

    if (usernameInput) {
        usernameInput.value = user.username || "";
    }

    if (emailInput) {
        emailInput.value = user.email || "";
    }

    setText("profileRole", formatRole(user.role));
    setText("profileStatus", formatStatus(user.is_active));
    setText("profileLastSignIn", user.last_signin_at || "-");
    setText("profileCreatedAt", user.created_at || "-");
}

async function loadProfile() {
    try {
        if (window.showLoading) {
            window.showLoading();
        }

        const res = await fetch("/api/profle", {
            headers: {
                Accept: "application/json",
            },
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || "Failed to load profile.");
        }

        populateProfile(data.user || {});
    } catch (error) {
        console.error("Load profile failed:", error);
        showProfileAlert(error.message || "Failed to load profile.", "danger");
    } finally {
        if (window.hideLoading) {
            window.hideLoading();
        }
    }
}

async function submitProfile(event) {
    event.preventDefault();

    const fullName = document.getElementById("profileFullName")?.value || "";
    const username = document.getElementById("profileUsername")?.value || "";
    const email = document.getElementById("profileEmail")?.value || "";
    const currentPassword = document.getElementById("profileCurrentPassword")?.value || "";
    const newPassword = document.getElementById("profileNewPassword")?.value || "";
    const confirmNewPassword = document.getElementById("profileConfirmNewPassword")?.value || "";

    const wantsPasswordChange = currentPassword.trim() || newPassword.trim() || confirmNewPassword.trim();

    if (wantsPasswordChange) {
        if (!currentPassword.trim()) {
            showProfileAlert("Current password is required to change your password.", "danger");
            return;
        }

        if (newPassword.length < 8) {
            showProfileAlert("New password must be at least 8 characters.", "danger");
            return;
        }

        if (newPassword != confirmNewPassword) {
            showProfileAlert("New passwords do not match.", "danger");
            return;
        }
    }

    try {
        setFormLoading(true);

        if (window.showLoading) {
            window.showLoading();
        }

        const res = await fetch("/api/profile", {
            method: "PUT", 
            headers: {
                Accept: "application/json", 
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                full_name: fullName, 
                username, 
                email, 
                current_password: currentPassword || null, 
                new_password: newPassword || null, 
                confirm_new_password: confirmNewPassword || null,
            }),
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || "Failed to update profile.");
        }

        clearPasswordFields();
        showProfileAlert(data.message || "Profile updated successfully.", "success");

        if (data.user) {
            populateProfile(data.user);

            const welcomeName = document.querySelector(".navbar .text-white b");
            if (welcomeName) {
                welcomeName.textContent = data.user.username || data.user.full_name || "User";
            }
        }
    } catch (error) {
        console.error("Update profile failed:", error);
        showProfileAlert(error.message || "Failed to update profile.", "danger");
    } finally {
        setFormLoading(false);

        if (window.hideLoading) {
            window.hideLoading();
        }
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    const form = document.getElementById("profileForm");

    if (form) {
        form.addEventListener("submit", submitProfile);
    }

    await loadProfile();
});