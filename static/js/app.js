// Shared progressive enhancement for confirmation forms.
document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
  }
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-password-toggle]");
  if (!button) return;

  const input = document.getElementById(button.dataset.passwordToggle);
  if (!input) return;

  const showPassword = input.type === "password";
  input.type = showPassword ? "text" : "password";
  button.textContent = showPassword ? "Ẩn" : "Hiện";
  button.setAttribute("aria-label", `${showPassword ? "Ẩn" : "Hiện"} mật khẩu`);
  button.setAttribute("aria-pressed", String(showPassword));
});
