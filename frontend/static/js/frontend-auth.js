async function getCurrentUser() {
  try {
    const data = await apiFetch("/api/auth/me");
    return data.user || null;
  } catch (error) {
    return null;
  }
}

async function requireAuth() {
  const user = await getCurrentUser();

  if (!user) {
    window.location.href = "/signin.html";
    return null;
  }

  document.querySelectorAll("[data-current-username]").forEach((el) => {
    el.textContent = user.username || user.full_name || "User";
  });

  document.querySelectorAll("[data-admin-only]").forEach((el) => {
    if (String(user.role || "").toLowerCase() !== "admin") {
      el.classList.add("d-none");
    }
  });

  return user;
}

async function redirectIfAuthenticated() {
  const user = await getCurrentUser();

  if (user) {
    window.location.href = "/";
  }
}

async function signOut() {
  try {
    await apiFetch("/api/auth/signout", {
      method: "POST",
    });
  } finally {
    window.location.href = "/signin.html";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-signout]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      await signOut();
    });
  });
});