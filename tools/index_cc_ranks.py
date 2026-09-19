"""
Script to import cc-main domain ranks (txt.gz) into SQLite.

Rutas y release configurables por entorno:
  THINKUY_CC_RANKS_GZ    (def: D:\\cc_domain_ranks.txt.gz)
  THINKUY_CC_RANKS_DB    (def: D:\\cc_domain_ranks.db)
  THINKUY_CC_RELEASE     (def: cc-main-2026-jun-jul-aug)
  THINKUY_CC_PERIOD_SORT (def: 202608) — orden cronológico del release
  THINKUY_CC_PERIOD_LABEL (def: release id) — etiqueta legible del periodo

Guarda metadatos (release_id, total de dominios, fecha) en la tabla cc_index_meta,
que SCIVIS usa para percentiles exactos y series históricas reales.
"""
import gzip
import os
import sqlite3
import time

INPUT_GZ = os.environ.get("THINKUY_CC_RANKS_GZ", r"D:\cc_domain_ranks.txt.gz")
OUTPUT_DB = os.environ.get("THINKUY_CC_RANKS_DB", r"D:\cc_domain_ranks.db")
RELEASE_ID = os.environ.get("THINKUY_CC_RELEASE", "cc-main-2026-jun-jul-aug")
PERIOD_LABEL = os.environ.get("THINKUY_CC_PERIOD_LABEL", RELEASE_ID)
PERIOD_SORT = int(os.environ.get("THINKUY_CC_PERIOD_SORT", "202608"))
BATCH_SIZE = 100_000

def index_ranks():
    if not os.path.exists(INPUT_GZ):
        print(f"Error: {INPUT_GZ} does not exist yet. Ensure download is finished.")
        return

    print(f"Starting index of {INPUT_GZ} into {OUTPUT_DB}...")
    start_time = time.time()
    
    # If db exists, remove or append
    if os.path.exists(OUTPUT_DB):
        print(f"Removing existing {OUTPUT_DB} to ensure clean build...")
        os.remove(OUTPUT_DB)

    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()

    cursor.execute("PRAGMA page_size = 65536")
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = MEMORY")
    cursor.execute("PRAGMA cache_size = -1048576")
    cursor.execute("PRAGMA temp_store = MEMORY")
    cursor.execute("PRAGMA mmap_size = 30000000000")

    cursor.execute("""
        CREATE TABLE cc_ranks (
            domain_rev TEXT,
            domain_norm TEXT,
            harmonic_rank INTEGER,
            harmonic_val REAL,
            pagerank_rank INTEGER,
            pagerank_val REAL,
            n_hosts INTEGER
        )
    """)
    conn.commit()

    batch = []
    total_rows = 0
    last_print = time.time()

    with gzip.open(INPUT_GZ, "rt", encoding="utf-8", errors="replace") as f:
        # Check header
        header = f.readline()
        if not header.startswith("#"):
            # If not header, treat as data
            parts = header.strip().split("\t")
            if len(parts) >= 6:
                try:
                    h_pos = int(parts[0])
                    h_val = float(parts[1])
                    pr_pos = int(parts[2])
                    pr_val = float(parts[3])
                    host_rev = parts[4]
                    n_hosts = int(parts[5])
                    domain_norm = ".".join(reversed(host_rev.split(".")))
                    batch.append((host_rev, domain_norm, h_pos, h_val, pr_pos, pr_val, n_hosts))
                    total_rows += 1
                except Exception:
                    pass

        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            try:
                h_pos = int(parts[0])
                h_val = float(parts[1])
                pr_pos = int(parts[2])
                pr_val = float(parts[3])
                host_rev = parts[4]
                n_hosts = int(parts[5])
                domain_norm = ".".join(reversed(host_rev.split(".")))
                batch.append((host_rev, domain_norm, h_pos, h_val, pr_pos, pr_val, n_hosts))
                total_rows += 1
            except Exception:
                continue

            if len(batch) >= BATCH_SIZE:
                cursor.executemany("INSERT INTO cc_ranks VALUES (?,?,?,?,?,?,?)", batch)
                conn.commit()
                batch.clear()

                now = time.time()
                if now - last_print >= 5:
                    elapsed = now - start_time
                    rate = total_rows / elapsed
                    print(f"Indexed {total_rows:,} domains ({rate:,.0f} rows/s)...", flush=True)
                    last_print = now

    if batch:
        cursor.executemany("INSERT INTO cc_ranks VALUES (?,?,?,?,?,?,?)", batch)
        conn.commit()
        batch.clear()

    elapsed = time.time() - start_time
    print(f"Inserted {total_rows:,} rows in {elapsed/60:.1f} min. Now building indexes...")

    idx_start = time.time()
    cursor.execute("CREATE INDEX idx_cc_domain_norm ON cc_ranks(domain_norm)")
    cursor.execute("CREATE INDEX idx_cc_domain_rev ON cc_ranks(domain_rev)")
    cursor.execute("""
        CREATE TABLE cc_index_meta (
            release_id TEXT PRIMARY KEY,
            period_label TEXT,
            period_sort INTEGER,
            total_domains INTEGER,
            built_at TEXT
        )
    """)
    cursor.execute(
        "INSERT INTO cc_index_meta (release_id, period_label, period_sort, total_domains, built_at) VALUES (?,?,?,?,?)",
        (RELEASE_ID, PERIOD_LABEL, PERIOD_SORT, total_rows, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )
    conn.commit()
    conn.close()

    print(f"Indexes built in {(time.time() - idx_start)/60:.1f} min. Total time: {(time.time() - start_time)/60:.1f} min.")
    print(f"Database successfully ready at {OUTPUT_DB}!")
    print(f"Release: {RELEASE_ID} | dominios indexados: {total_rows:,}")

if __name__ == "__main__":
    index_ranks()
