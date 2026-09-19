(function () {
  var script = document.currentScript;
  if (!script) return;
  var base = script.src.replace(/embed\.js(\?.*)?$/, "");
  var mode = script.getAttribute("data-mode") || "conversation";
  var lang = script.getAttribute("data-lang") || "es";
  var limit = script.getAttribute("data-limit") || "5";
  var server = script.getAttribute("data-server") || "";
  var iframe = document.createElement("iframe");
  iframe.src = base + "widget.html?mode=" + encodeURIComponent(mode)
    + "&lang=" + encodeURIComponent(lang)
    + "&limit=" + encodeURIComponent(limit)
    + (server ? "&server=" + encodeURIComponent(server) : "");
  iframe.loading = "lazy";
  iframe.title = "Thinkuy — Radar de comunicación científica";
  iframe.style.cssText = "width:100%;max-width:400px;height:560px;border:0;border-radius:12px;overflow:hidden;background:#0B1226;";
  script.parentNode.insertBefore(iframe, script.nextSibling);
})();
