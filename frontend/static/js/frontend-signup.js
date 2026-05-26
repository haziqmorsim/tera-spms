document.addEventListener("DOMContentLoaded", async () => {
  await redirectIfAuthenticated();

  const form = document.getElementById("signUpForm");

  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const password = document.getElementById("password").value;
    const confirmPassword = document.getElementById("confirm_password").value;
    const submitButton = form.querySelector("button[type='submit']");

    if (password !== confirmPassword) {
      showPageAlert("authAlert", "Passwords do not match.");
      return;
    }

    try {
      if (window.showLoading) window.showLoading();

      if (submitButton) {
        submitButton.disabled = true;
        submitButton.classList.add("is-loading");
      }

      await apiFetch("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          full_name: document.getElementById("full_name").value,
          username: document.getElementById("username").value,
          email: document.getElementById("email").value,
          password,
          confirm_password: confirmPassword,
        }),
      });

      window.location.href = "/signin.html?signup=success";
    } catch (error) {
      showPageAlert("authAlert", error.message || "Failed to sign up.");
    } finally {
      if (window.hideLoading) window.hideLoading();

      if (submitButton) {
        submitButton.disabled = false;
        submitButton.classList.remove("is-loading");
      }
    }
  });
});