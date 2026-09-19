/* Thinkuy — utilidades de DOM y avisos (módulo ES). */
"use strict";

/** Escapa texto para insertarlo en HTML (evita inyección con datos de terceros). */
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const escapeHtml = esc;

/** Aviso transitorio (toast). Único punto para informar al usuario de errores y estados. */
export function showNotification({ title, message, type = "info" }) {
  console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
  const toast = document.createElement("div");
  toast.className = `thinkuy-toast toast-${type}`;
  toast.style.cssText = "position:fixed;bottom:24px;right:24px;background:#1e293b;color:#f8fafc;padding:12px 20px;border-radius:8px;box-shadow:0 10px 25px rgba(0,0,0,0.3);z-index:9999;font-size:14px;max-width:380px;display:flex;flex-direction:column;gap:4px;border-left:4px solid " + (type === "error" ? "#ef4444" : "#006a6a") + ";";
  toast.innerHTML = `<strong>${esc(title)}</strong><span>${esc(message)}</span>`;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.transition = "opacity 0.4s ease";
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 400);
  }, 4500);
}
