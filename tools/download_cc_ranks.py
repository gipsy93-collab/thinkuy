"""
Script to download Common Crawl domain-level ranks with resume support and progress reporting.

Configuración por entorno:
  THINKUY_CC_RELEASE   (def: cc-main-2026-jun-jul-aug) — release a descargar
  THINKUY_CC_RANKS_URL (opcional) — URL completa del archivo domain-ranks.txt.gz
  THINKUY_CC_RANKS_GZ  (def: D:\\cc_domain_ranks.txt.gz) — archivo de salida

Al finalizar, invoca automáticamente tools/index_cc_ranks.py.
"""
import os
import sys
import time
import urllib.request

RELEASE = os.environ.get("THINKUY_CC_RELEASE", "cc-main-2026-jun-jul-aug")
URL = os.environ.get(
    "THINKUY_CC_RANKS_URL",
    f"https://data.commoncrawl.org/projects/hyperlinkgraph/{RELEASE}/domain/{RELEASE}-domain-ranks.txt.gz",
)
OUTPUT_FILE = os.environ.get("THINKUY_CC_RANKS_GZ", r"D:\cc_domain_ranks.txt.gz")

def download():
    print(f"Connecting to {URL}...")
    headers = {"User-Agent": "Thinkuy-Scivis-Downloader/1.0"}
    
    existing_bytes = 0
    if os.path.exists(OUTPUT_FILE):
        existing_bytes = os.path.getsize(OUTPUT_FILE)
        print(f"Found existing file with {existing_bytes / (1024*1024):.2f} MB. Attempting resume...")

    # Get total size
    req_head = urllib.request.Request(URL, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req_head, timeout=15) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
    except Exception as e:
        print(f"Warning: could not get HEAD: {e}")
        total_size = 0

    if existing_bytes > 0 and total_size > 0 and existing_bytes >= total_size:
        print(f"File is already fully downloaded ({existing_bytes / (1024*1024):.2f} MB).")
        return

    if existing_bytes > 0:
        headers["Range"] = f"bytes={existing_bytes}-"
        mode = "ab"
    else:
        mode = "wb"

    req = urllib.request.Request(URL, headers=headers)
    start_time = time.time()
    last_print = start_time
    downloaded = existing_bytes
    chunk_size = 1024 * 1024 # 1 MB chunks

    with urllib.request.urlopen(req, timeout=30) as resp, open(OUTPUT_FILE, mode) as out_f:
        if "Range" not in headers:
            # If server didn't support range or we started from 0
            if existing_bytes > 0 and resp.status == 200:
                print("Server does not support Range header for resume. Restarting from byte 0...")
                out_f.seek(0)
                out_f.truncate()
                downloaded = 0

        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out_f.write(chunk)
            downloaded += len(chunk)

            now = time.time()
            if now - last_print >= 5:
                elapsed = now - start_time
                if elapsed > 0:
                    speed_mb = (downloaded - existing_bytes) / (1024 * 1024) / elapsed
                else:
                    speed_mb = 0
                
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    eta_sec = (total_size - downloaded) / (speed_mb * 1024 * 1024) if speed_mb > 0 else 0
                    print(f"[{pct:.1f}%] {downloaded / (1024*1024):.1f} / {total_size / (1024*1024):.1f} MB @ {speed_mb:.2f} MB/s (ETA: {eta_sec/60:.1f} min)", flush=True)
                else:
                    print(f"{downloaded / (1024*1024):.1f} MB downloaded @ {speed_mb:.2f} MB/s", flush=True)
                last_print = now

    total_time = time.time() - start_time
    print(f"\nDownload completed successfully in {total_time/60:.1f} minutes! Saved to {OUTPUT_FILE}")
    
    print("\n========================================================")
    print("Starting automated indexing into D:\\cc_domain_ranks.db...")
    print("========================================================")
    try:
        try:
            import tools.index_cc_ranks as indexer
        except ImportError:
            import index_cc_ranks as indexer
        indexer.index_ranks()
    except Exception as e:
        print(f"Error during automated indexing: {e}")

if __name__ == "__main__":
    download()

