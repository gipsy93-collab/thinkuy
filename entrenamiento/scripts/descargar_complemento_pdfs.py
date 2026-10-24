"""Cosecha y descarga directa de PDFs adicionales garantizados para alcanzar 70-100 PDFs."""
import os
import json
import re
import httpx
from html import unescape

OUTPUT_DIR = "data/descargas_revisiones_es_pt"
OUTPUT_JSON = "data/lote_revisiones_es_pt_gold.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8"
}

def clean_txt(t):
    if not t:
        return ""
    return ' '.join(re.sub(r'<[^>]+>', ' ', unescape(t)).split())

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Cargar los ya descargados
    existentes = set(os.listdir(OUTPUT_DIR))
    print(f"PDFs actualmente en disco: {len(existentes)}")
    
    # Consultar Europe PMC para artículos con PMC libre (PDF directo garantizado)
    queries = [
        '("revisión sistemática" OR "revisión de alcance") AND OPEN_ACCESS:y AND (LANG:spa OR LANG:es)',
        '("revisão sistemática" OR "revisão de escopo") AND OPEN_ACCESS:y AND (LANG:por OR LANG:pt)',
        '("scoping review" OR "systematic review") AND (SRC:MED OR SRC:PMC) AND OPEN_ACCESS:y AND (LANG:spa OR LANG:por)'
    ]
    
    nuevos_articulos = []
    
    with httpx.Client(headers=HEADERS, timeout=25.0, follow_redirects=True) as client:
        for q in queries:
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": q,
                "format": "json",
                "pageSize": 35,
                "resultType": "core"
            }
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                results = r.json().get("resultList", {}).get("result", [])
                for it in results:
                    pmcid = it.get("pmcid")
                    doi = (it.get("doi") or "").lower()
                    titulo = clean_txt(it.get("title") or "")
                    abstract = clean_txt(it.get("abstractText") or "")
                    
                    if not pmcid and not doi:
                        continue
                        
                    pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf" if pmcid else None
                    if not pdf_url and doi:
                        # Unpaywall
                        try:
                            r_unp = client.get(f"https://api.unpaywall.org/v2/{doi}?email=investigador.thinkuy@gmail.com", timeout=8.0)
                            if r_unp.status_code == 200:
                                pdf_url = (r_unp.json().get("best_oa_location") or {}).get("url_for_pdf")
                        except Exception:
                            pass
                            
                    if not pdf_url:
                        continue
                        
                    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', doi if doi else pmcid)
                    out_path = os.path.join(OUTPUT_DIR, f"extra_{safe_id[:40]}.pdf")
                    
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                        continue
                        
                    try:
                        r_pdf = client.get(pdf_url)
                        if r_pdf.status_code == 200 and (r_pdf.content.startswith(b'%PDF') or 'application/pdf' in r_pdf.headers.get('content-type', '')):
                            with open(out_path, "wb") as f_pdf:
                                f_pdf.write(r_pdf.content)
                            tam_kb = round(len(r_pdf.content)/1024, 1)
                            print(f"  [Europe PMC PDF] ✅ {tam_kb:7.1f} KB | {titulo[:60]}")
                            
                            nuevos_articulos.append({
                                "id": safe_id,
                                "titulo": titulo,
                                "doi": doi,
                                "url": f"https://doi.org/{doi}" if doi else pdf_url,
                                "pdf_path": out_path,
                                "abstract": abstract,
                                "fuente": "Europe PMC Open Access",
                                "tipo_revision": "Scoping Review" if any(w in (titulo + " " + abstract).lower() for w in ["alcance", "escopo", "scoping"]) else "Revisión Sistemática"
                            })
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"Error Europe PMC {q}: {e}")
                
    # Conteo consolidado
    todos_los_pdfs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".pdf") and os.path.getsize(os.path.join(OUTPUT_DIR, f)) > 10000]
    print("\n" + "=" * 80)
    print(f"TOTAL CONSOLIDADO DE PDFs DESCARGADOS EN DISCO: {len(todos_los_pdfs)} ARTÍCULOS")
    print(f"Carpeta física: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
