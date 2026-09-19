"""Lanzador local de Thinkuy: dos instancias de uvicorn en el puerto 8000
(IPv4 127.0.0.1 + IPv6 ::1) para que 'localhost' funcione SIEMPRE en el navegador,
independientemente de si Windows resuelve localhost a ::1 o a 127.0.0.1.

Uso:  .venv\\Scripts\\python.exe run_server.py   (Ctrl+C para detener)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = HERE / ".venv" / "Scripts" / "python.exe"


def obtener_pid_del_puerto(port: str) -> int | None:
    """Averigua el PID escuchando en el puerto TCP especificado."""
    try:
        if os.name == "nt":
            out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING":
                    return int(parts[4])
    except Exception:
        pass
    return None


def liberar_puerto(port: str) -> bool:
    """Intenta matar el proceso ocupante del puerto si está obsoleto."""
    pid = obtener_pid_del_puerto(port)
    if not pid:
        return False
    try:
        if os.name == "nt":
            res = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            return res.returncode == 0
    except Exception:
        pass
    return False


def puerto_ocupado(port: str) -> dict | None:
    """Si ya hay algo respondiendo en el puerto, devuelve su huella de compilación."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def avisar_si_ocupado(port: str) -> bool:
    """Devuelve True si conviene detenerse (ya hay una instancia sirviendo)."""
    existente = puerto_ocupado(port)
    if not existente:
        return False

    huella = existente.get("build")
    if not huella:
        print("=" * 62)
        print(f"  AVISO: el puerto {port} está ocupado por una instancia ANTIGUA.")
        print("  Intentando cerrar la instancia obsoleta para cargar el nuevo código...")
        if liberar_puerto(port):
            print("  ✅ Instancia obsoleta cerrada con éxito. Reanudando arranque.")
            print("=" * 62)
            time.sleep(1)
            return False
        else:
            print("  ❌ No se pudo cerrar automáticamente la instancia antigua.")
            print("  -> Cierra la ventana del servidor anterior manualmente y vuelve a intentar.")
            print("=" * 62)
            return True

    nuevos = huella.get("endpoints_nuevos") or {}
    faltan = sorted(k for k, v in nuevos.items() if not v)

    print("=" * 62)
    print(f"  INFORMACIÓN: el puerto {port} ya está activo.")
    print(f"  Instancia activa: {huella.get('codigo')}")
    print(f"  main.py cargado en memoria: {huella.get('main_py_modificado')}")
    print(f"  Rutas expuestas: {huella.get('rutas_totales')}")
    if faltan:
        print(f"  ENDPOINTS QUE FALTAN en esa instancia: {faltan}")
        print("  Intentando cerrar la instancia obsoleta...")
        if liberar_puerto(port):
            print("  ✅ Instancia obsoleta cerrada con éxito. Reanudando arranque.")
            print("=" * 62)
            time.sleep(1)
            return False
        else:
            print("  -> Cierra la ventana del servidor anterior manualmente y vuelve a intentar.")
            print("=" * 62)
            return True
    else:
        print("  ✅ La instancia activa está AL DÍA. Abriendo la aplicación...")
        import webbrowser
        webbrowser.open(f"http://localhost:{port}/app/")
        print(f"  URL: http://localhost:{port}/app/")
        print("=" * 62)
        return True


def urls_de_red(port: str) -> list[str]:
    """URLs por las que OTROS dispositivos pueden alcanzar esta instancia."""
    import socket

    direcciones = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in direcciones:
                direcciones.append(ip)
    except OSError:
        pass
    if not direcciones:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            direcciones.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return [f"http://{ip}:{port}/app/" for ip in direcciones]


def main() -> int:
    if not PY.exists():
        print("[ERROR] No existe el entorno virtual en .venv. Ejecuta antes:")
        print("        uv venv .venv")
        print("        uv pip install --python .venv fastapi \"uvicorn[standard]\" apscheduler httpx")
        return 1

    port = str(os.environ.get("THINKUY_PORT", "8000"))
    host = str(os.environ.get("THINKUY_HOST", "127.0.0.1")).strip()

    if avisar_si_ocupado(port):
        return 0

    ruta_codigo = Path(__file__).resolve().parent / "radar" / "api" / "main.py"
    try:
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ruta_codigo.stat().st_mtime))
    except OSError:
        mtime = "desconocido"

    p = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "radar.api.main:app", "--host", host, "--port", port, "--reload"],
        cwd=HERE,
    )

    import threading
    import webbrowser

    def _abrir_navegador():
        time.sleep(1.5)
        try:
            webbrowser.open(f"http://localhost:{port}/app/")
        except Exception:
            pass

    threading.Thread(target=_abrir_navegador, daemon=True).start()

    print("=" * 62)
    print("  THINKUY — servidor activo")
    print(f"  Código servido: {ruta_codigo}")
    print(f"  main.py modificado: {mtime}")
    print(f"  Escuchando en: {host}:{port}")
    print(f"  En esta máquina:  http://127.0.0.1:{port}/app/")
    if host not in ("127.0.0.1", "localhost"):
        for url in urls_de_red(port):
            print(f"  Desde la red:     {url}")
        print("  (si no conecta desde otro equipo, permite el puerto en el cortafuegos)")
    print(f"  Widget:  http://127.0.0.1:{port}/widget")
    print(f"  API:  http://127.0.0.1:{port}/api/health")
    print("  Ctrl+C para detener.")
    print("=" * 62)

    try:
        while True:
            time.sleep(2)
            if p.poll() is not None:
                p = subprocess.Popen(
                    [str(PY), "-m", "uvicorn", "radar.api.main:app", "--host", host, "--port", port, "--reload"],
                    cwd=HERE,
                )
    except KeyboardInterrupt:
        print("\nDeteniendo Thinkuy…")
        p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())