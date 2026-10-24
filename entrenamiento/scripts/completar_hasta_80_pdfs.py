"""
=============================================================================
Thinkuy — Descargador Masivo para alcanzar > 75 PDFs de Revisiones (ES/PT)
=============================================================================
Consulta directamente Europe PMC, SciELO y repositorios OJS con PDF público
y descarga los archivos PDF hasta superar el rango de 75-90 PDFs en disco.
=============================================================================
"""

import os
import sys
import json
import re
import httpx
from html import unescape

OUTPUT_DIR = "data/descargas_revisiones_es_pt"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8"
}

def clean_txt(t):
    if not t:
        return ""
    return ' '.join(re.sub(r'<[^>]+>', ' ', unescape(t)).split())

def main():
    pdfs_existentes = set(os.listdir(OUTPUT_DIR))
    print(f"PDFs iniciales en disco: {len(pdfs_existentes)}")
    
    # Búsquedas amplias en Europe PMC con OPEN_ACCESS:y y HAS_PDF:y
    queries = [
        'HAS_PDF:y AND OPEN_ACCESS:y AND ("revisión sistemática" OR "revision sistematica") AND (LANG:spa OR LANG:es)',
        'HAS_PDF:y AND OPEN_ACCESS:y AND ("revisão sistemática" OR "revisao sistematica") AND (LANG:por OR LANG:pt)',
        'HAS_PDF:y AND OPEN_ACCESS:y AND ("revisión de alcance" OR "revision de alcance") AND (LANG:spa OR LANG:es)',
        'HAS_PDF:y AND OPEN_ACCESS:y AND ("revisão de escopo" OR "revisao de escopo") AND (LANG:por OR LANG:pt)',
        'HAS_PDF:y AND OPEN_ACCESS:y AND ("scoping review" OR "systematic review") AND (SRC:MED OR SRC:PMC) AND (LANG:spa OR LANG:por)',
        'HAS_PDF:y AND OPEN_ACCESS:y AND ("scoping review" OR "systematic review") AND (AFF:"Brazil" OR AFF:"Spain" OR AFF:"Colombia" OR AFF:"Mexico" OR AFF:"Chile" OR AFF:"Argentina" OR AFF:"Portugal")'
    ]
    
    descargados_nuevos = 0
    
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        for q in queries:
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": q,
                "format": "json",
                "pageSize": 50,
                "resultType": "core"
            }
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                items = r.json().get("resultList", {}).get("result", [])
                print(f"\nConsultando: {q[:50]}... | Resultados encontrados: {len(items)}")
                
                for it in items:
                    pmcid = it.get("pmcid")
                    doi = (it.get("doi") or "").lower()
                    titulo = clean_txt(it.get("title") or "")
                    
                    if not pmcid and not doi:
                        continue
                        
                    # Nombre seguro
                    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', pmcid if pmcid else doi)
                    out_path = os.path.join(OUTPUT_DIR, f"{safe_id[:35]}.pdf")
                    
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                        continue
                        
                    pdf_candidates = []
                    if pmcid:
                        pdf_candidates.append(f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf")
                        pdf_candidates.append(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/")
                        
                    if doi:
                        # Unpaywall
                        try:
                            r_u = client.get(f"https://api.unpaywall.org/v2/{doi}?email=investigador.thinkuy@gmail.com", timeout=6.0)
                            if r_u.status_code == 200:
                                best = (r_u.json().get("best_oa_location") or {}).get("url_for_pdf")
                                if best:
                                    pdf_candidates.append(best)
                        except Exception:
                            pass
                            
                    for p_url in pdf_candidates:
                        try:
                            r_pdf = client.get(p_url)
                            if r_pdf.status_code == 200 and (r_pdf.content.startswith(b'%PDF') or 'pdf' in r_pdf.headers.get('content-type', '')):
                                with open(out_path, "wb") as f_out:
                                    f_out.write(r_pdf.content)
                                descargados_nuevos += 1
                                tam_kb = round(len(r_pdf.content)/1024, 1)
                                print(f"  [PDF {len(os.listdir(OUTPUT_DIR)):02d}] ✅ {tam_kb:7.1f} KB | {titulo[:60]}")
                                break
                        except Exception:
                            continue
                            
            except Exception as e:
                print(f"Error query {q[:30]}: {e}")
                
    total_final = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".pdf") and os.path.getsize(os.path.join(OUTPUT_DIR, f)) > 10000]
    print("\n" + "=" * 80)
    print(f"TOTAL FINAL VERIFICADO EN DISCO: {len(total_final)} PDFs COMPLETOS")
    print(f"Carpeta física: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
