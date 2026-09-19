"""
download_cc_graph.py — Descarga vertices/edges del WebGraph de Common Crawl con resume.

Uso:
  python tools/download_cc_graph.py vertices
  python tools/download_cc_graph.py edges
  python tools/download_cc_graph.py all

Config por entorno:
  THINKUY_CC_RELEASE   (def: cc-main-2026-jun-jul-aug)
"""
import os
import sys
import time
import urllib.request

RELEASE = os.environ.get("THINKUY_CC_RELEASE", "cc-main-2026-jun-jul-aug")
BASE = f"https://data.commoncrawl.org/projects/hyperlinkgraph/{RELEASE}/domain/{RELEASE}-domain-"

TARGETS = {
    "vertices": (BASE + "vertices.txt.gz", os.environ.get("THINKUY_CC_VERTICES_GZ", r"D:\cc_vertices.txt.gz")),
    "edges": (BASE + "edges.txt.gz", os.environ.get("THINKUY_CC_EDGES_GZ", r"D:\cc_edges.txt.gz")),
}


def download_one(kind: str) -> None:
    url, out = TARGETS[kind]
    headers = {"User-Agent": "Thinkuy-Scivis-Downloader/1.0"}

    existing = os.path.getsize(out) if os.path.exists(out) else 0
    req_head = urllib.request.Request(url, headers=headers, method="HEAD")
    with urllib.request.urlopen(req_head, timeout=20) as resp:
        total = int(resp.headers.get("Content-Length", 0))
    print(f"[{kind}] remoto={total/1024**3:.2f} GiB, local={existing/1024**3:.2f} GiB", flush=True)

    if existing and total and existing >= total:
        print(f"[{kind}] ya descargado completo.", flush=True)
        return

    if existing:
        headers["Range"] = f"bytes={existing}-"
        mode = "ab"
    else:
        mode = "wb"

    req = urllib.request.Request(url, headers=headers)
    downloaded = existing
    start = time.time()
    last = start
    with urllib.request.urlopen(req, timeout=60) as resp, open(out, mode) as f:
        if "Range" not in headers and existing:
            print(f"[{kind}] sin soporte Range, reinicio desde 0.", flush=True)
            downloaded = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if now - last >= 30:
                mbps = (downloaded - existing) / 1024**2 / (now - start) if now > start else 0
                eta = (total - downloaded) / (mbps * 1024 * 1024) / 3600 if mbps and total else 0
                print(f"[{kind}] {downloaded/1024**3:.2f}/{total/1024**3:.2f} GiB "
                      f"({downloaded/total*100:.1f}%) @ {mbps:.1f} MB/s ETA {eta:.1f} h", flush=True)
                last = now
    print(f"[{kind}] COMPLETO -> {out}", flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    kinds = ["vertices", "edges"] if which == "all" else [which]
    for k in kinds:
        download_one(k)
