const NOTIFICATION_REFRESH_MS = 60000;

function notificationEscapeHtml(value) {
    if (value === null || value === undefined) return "";

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function notificationTypeIcon(type) {
    const normalized = String(type || "").toLowerCase();

    if (normalized === "task") {
        return "✓";
    }

    if (normalized === "report") {
        return "📄";
    }

    if (normalized === "email") {
        return "✉";
    }

    return "•";
}

function updateNotificationBadge(unreadCount) {
    const badge = document.getElementById("notificationBadge");

    if (!badge) return;

    const count = Number(unreadCount || 0);

    if (count <= 0) {
        badge.classList.add("d-none");
        badge.textContent = "0";
        return;
    }

    badge.classList.remove("d-none");
    badge.textContent = count > 99 ? "99+" : String(count);
}

function renderNotificationList(notifications) {
    const container = document.getElementById("notificationList");

    if (!container) return;

    const safeNotifications = Array.isArray(notifications) ? notifications : [];

    if (safeNotifications.length === 0) {
        container.innerHTML = `
            <div class="notification-empty">
                No notifications.
            </div>
        `;
        return;
    }

    container.innerHTML = "";

    safeNotifications.forEach((item) => {
        const isUnread = !item.is_read;

        const itemClass = isUnread
            ? "notification-item notification-item-unread"
            : "notification-item";

        container.innerHTML += `
            <div class="${itemClass}">
                <div class="notification-item-icon">
                    ${notificationEscapeHtml(notificationTypeIcon(item.notification_type))}
                </div>

                <div class="notification-item-body">
                    <div class="notification-item-message">
                        ${notificationEscapeHtml(item.message)}
                    </div>

                    <div class="notification-item-time">
                        ${notificationEscapeHtml(item.time_ago || item.created_at || "")}
                    </div>
                </div>
            </div>
        `;
    });
}

async function loadNotifications() {
    try {
        const res = await fetch("/api/notifications?limit=20");

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();

        updateNotificationBadge(data.unread_count || 0);
        renderNotificationList(data.notifications || []);
    } catch (error) {
        console.error("Failed to load notifications:", error);

        const container = document.getElementById("notificationList");

        if (container) {
            container.innerHTML = `
                <div class="notification-empty text-danger">
                    Failed to load notifications.
                </div>
            `;
        }
    }
}

async function markAllNotificationsAsRead() {
    const button = document.getElementById("markAllNotificationsReadBtn");

    try {
        if (button) {
            button.disabled = true;
            button.textContent = "Marking...";
        }

        const res = await fetch("/api/notifications/mark-all-read", {
            method: "POST",
        });

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        await loadNotifications();
    } catch (error) {
        console.error("Failed to mark all notifications as read:", error);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Mark all as read";
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const markReadButton = document.getElementById("markAllNotificationsReadBtn");
    const dropdownButton = document.getElementById("notificationDropdownButton");
    const dropdownMenu = document.querySelector(".notification-dropdown");

    if (dropdownMenu) {
        dropdownMenu.addEventListener("click", (event) => {
            event.stopPropagation();
        });
    }

    if (markReadButton) {
        markReadButton.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();

            await markAllNotificationsAsRead();
        });
    }

    if (dropdownButton) {
        dropdownButton.addEventListener("click", loadNotifications);
    }

    loadNotifications();

    window.setInterval(loadNotifications, NOTIFICATION_REFRESH_MS);
});