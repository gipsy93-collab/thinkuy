"""Descargador de revisiones sistemáticas y scoping con PDF directo verificado desde PMC / SciELO."""
import os
import json
import re
import httpx
from html import unescape

OUTPUT_DIR = "data/descargas_revisiones_es_pt"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*"
}

def clean_txt(t):
    if not t:
        return ""
    return ' '.join(re.sub(r'<[^>]+>', ' ', unescape(t)).split())

def main():
    queries = [
        'HAS_PDF:y AND ("revisión sistemática" OR "revisión de alcance") AND (LANG:spa OR LANG:es)',
        'HAS_PDF:y AND ("revisão sistemática" OR "revisão de escopo") AND (LANG:por OR LANG:pt)',
        'HAS_PDF:y AND ("scoping review" OR "systematic review") AND (SRC:MED OR SRC:PMC) AND (LANG:spa OR LANG:por)'
    ]
    
    descargados = 0
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        for q in queries:
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": q,
                "format": "json",
                "pageSize": 40,
                "resultType": "core"
            }
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                items = r.json().get("resultList", {}).get("result", [])
                for it in items:
                    pmcid = it.get("pmcid")
                    if not pmcid:
                        continue
                        
                    doi = (it.get("doi") or "").lower()
                    titulo = clean_txt(it.get("title") or "")
                    
                    safe_name = f"pmc_{pmcid}"
                    out_path = os.path.join(OUTPUT_DIR, f"{safe_name}.pdf")
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                        continue
                        
                    pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
                    try:
                        r_pdf = client.get(pdf_url)
                        if r_pdf.status_code == 200 and r_pdf.content.startswith(b'%PDF'):
                            with open(out_path, "wb") as f_out:
                                f_out.write(r_pdf.content)
                            tam_kb = round(len(r_pdf.content)/1024, 1)
                            descargados += 1
                            print(f"[{descargados:02d}] ✅ DESCARGADO: {tam_kb:7.1f} KB | {titulo[:60]}")
                    except Exception:
                        continue
            except Exception as e:
                print(f"Error: {e}")

    total = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".pdf") and os.path.getsize(os.path.join(OUTPUT_DIR, f)) > 10000]
    print("\n" + "=" * 80)
    print(f"TOTAL FINAL DE PDFs DESCARGADOS EN DISCO: {len(total)} ARTÍCULOS")
    print(f"Carpeta: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
