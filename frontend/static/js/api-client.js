async function apiFetch(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };

  const hasBody = options.body !== undefined && options.body !== null;

  if (hasBody && !(options.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "include",
  });

  let data = null;

  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    const message =
      data && typeof data === "object"
        ? data.detail || data.message || `HTTP ${response.status}`
        : data || `HTTP ${response.status}`;

    throw new Error(message);
  }

  return data;
}

function showPageAlert(containerId, message, type = "danger") {
  const container = document.getElementById(containerId);

  if (!container) {
    alert(message);
    return;
  }

  container.innerHTML = `
    <div class="alert alert-${type}" role="alert">
      ${String(message)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")}
    </div>
  `;
}