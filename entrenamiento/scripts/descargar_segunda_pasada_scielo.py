"""Segunda pasada de descarga enfocada para resolver PDFs de SciELO y Dialnet."""
import os
import json
import re
import httpx
from html import unescape

INPUT_JSON = "data/lote_revisiones_es_pt_gold.json"
OUTPUT_DIR = "data/descargas_revisiones_es_pt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8"
}

def resolve_scielo_pdf(html, base_url):
    # Enlaces a PDF en SciELO
    patterns = [
        r'href=[\'"]([^\'"]*?\?format=pdf[^\'"]*?)[\'"]',
        r'href=[\'"]([^\'"]*?format=pdf)[\'"]',
        r'href=[\'"]([^\'"]*?\.pdf)[\'"]',
        r'<a[^>]*class=[\'"][^\'"]*pdf[^\'"]*[\'"][^>]*href=[\'"]([^\'"]+)[\'"]',
    ]
    candidates = []
    for pat in patterns:
        for m in re.findall(pat, html, re.I):
            m = unescape(m).strip()
            if not m.startswith("http"):
                from urllib.parse import urljoin
                m = urljoin(base_url, m)
            candidates.append(m)
    return candidates

def main():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        articulos = json.load(f)
        
    print("=== SEGUNDA PASADA: RESOLUCIÓN DE SCIELO, CROSSREF Y OJS ===")
    
    with httpx.Client(headers=HEADERS, timeout=25.0, follow_redirects=True) as client:
        for idx, art in enumerate(articulos, 1):
            doi = (art.get("doi") or "").strip()
            safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', doi) if doi else f"art_{idx:02d}"
            out_path = os.path.join(OUTPUT_DIR, f"{idx:02d}_{safe_name[:40]}.pdf")
            
            if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                continue
                
            titulo = art.get("titulo", "")
            target_url = f"https://doi.org/{doi}" if doi else art.get("url")
            
            if not target_url:
                continue
                
            try:
                r_land = client.get(target_url)
                if r_land.status_code == 200:
                    candidates = resolve_scielo_pdf(r_land.text, str(r_land.url))
                    
                    for c_url in candidates:
                        try:
                            r_pdf = client.get(c_url)
                            if r_pdf.status_code == 200 and (r_pdf.content.startswith(b'%PDF') or 'application/pdf' in r_pdf.headers.get('content-type', '')):
                                with open(out_path, "wb") as f_out:
                                    f_out.write(r_pdf.content)
                                print(f"[{idx:02d}/90] ✅ RESUELTO: {os.path.getsize(out_path)/1024:.1f} KB | {titulo[:60]}")
                                break
                        except Exception:
                            continue
            except Exception as e:
                pass
                
    # Conteo final en disco
    pdfs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".pdf") and os.path.getsize(os.path.join(OUTPUT_DIR, f)) > 10000]
    print("\n" + "=" * 80)
    print(f"TOTAL FINAL DE PDFs DESCARGADOS EN DISCO: {len(pdfs)} / {len(articulos)} ({len(pdfs)/len(articulos)*100:.1f}%)")
    print(f"Carpeta: {OUTPUT_DIR}")
    print("=" * 80)

if __name__ == "__main__":
    main()
