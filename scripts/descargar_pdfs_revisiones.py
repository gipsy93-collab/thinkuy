"""
=============================================================================
Thinkuy — Descargador Automatizado de PDFs y Textos Completos (ES/PT)
=============================================================================
Descarga los PDFs de los 90 artículos de Revisiones Sistemáticas y Scoping
cosechados en data/lote_revisiones_es_pt_gold.json hacia:
data/descargas_revisiones_es_pt/
Utiliza resolvers de Acceso Abierto:
1. Unpaywall API (best_oa_location)
2. Europe PMC / PMC PDF direct resolver
3. SciELO direct PDF resolver
4. Landing page PDF auto-discovery
=============================================================================
"""

import os
import sys
import json
import re
import time
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

INPUT_JSON = "data/lote_revisiones_es_pt_gold.json"
OUTPUT_DIR = "data/descargas_revisiones_es_pt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8"
}

def resolve_pdf_url(client, art):
    doi = (art.get("doi") or "").strip().lower()
    url = art.get("url") or ""
    
    pdf_urls = []
    
    # 1. Unpaywall
    if doi:
        try:
            r_unp = client.get(f"https://api.unpaywall.org/v2/{doi}?email=investigador.thinkuy@gmail.com", timeout=12.0)
            if r_unp.status_code == 200:
                d_unp = r_unp.json()
                best = d_unp.get("best_oa_location") or {}
                if best.get("url_for_pdf"):
                    pdf_urls.append(best["url_for_pdf"])
                for loc in d_unp.get("oa_locations") or []:
                    if loc.get("url_for_pdf") and loc["url_for_pdf"] not in pdf_urls:
                        pdf_urls.append(loc["url_for_pdf"])
        except Exception:
            pass

    # 2. Europe PMC resolver si es PMC
    if doi:
        try:
            r_epmc = client.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:\"{doi}\"&format=json", timeout=10.0)
            if r_epmc.status_code == 200:
                results = r_epmc.json().get("resultList", {}).get("result", [])
                if results:
                    pmcid = results[0].get("pmcid")
                    if pmcid:
                        pdf_urls.append(f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf")
        except Exception:
            pass

    # 3. SciELO direct PDF pattern si el DOI es 10.1590
    if "10.1590" in doi:
        try:
            r_scielo = client.get(f"https://doi.org/{doi}", follow_redirects=True, timeout=12.0)
            if r_scielo.status_code == 200:
                # Buscar enlace a pdf en SciELO
                m_pdf = re.findall(r'href=[\'"]([^\'"]*?\.(?:pdf|PDF)[^\'"]*?)[\'"]', r_scielo.text)
                for p in m_pdf:
                    if p.startswith("/"):
                        p = f"https://www.scielo.br{p}"
                    pdf_urls.append(p)
                m_btn = re.findall(r'<a[^>]*class=[\'"][^\'"]*pdf[^\'"]*[\'"][^>]*href=[\'"]([^\'"]+)[\'"]', r_scielo.text, re.I)
                for b in m_btn:
                    if b.startswith("/"):
                        b = f"https://www.scielo.br{b}"
                    pdf_urls.append(b)
        except Exception:
            pass

    # 4. Landing page scan si tiene URL
    if url and not pdf_urls:
        try:
            r_land = client.get(url, follow_redirects=True, timeout=12.0)
            if r_land.status_code == 200:
                m_pdf = re.findall(r'href=[\'"]([^\'"]*?\.(?:pdf|PDF)[^\'"]*?)[\'"]', r_land.text)
                for p in m_pdf:
                    if not p.startswith("http"):
                        from urllib.parse import urljoin
                        p = urljoin(url, p)
                    pdf_urls.append(p)
        except Exception:
            pass

    return pdf_urls

def descargar_articulo(art, idx, total):
    doi = (art.get("doi") or "").strip()
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', doi) if doi else f"art_{idx:02d}"
    out_path = os.path.join(OUTPUT_DIR, f"{idx:02d}_{safe_name[:40]}.pdf")
    
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
        return {"id": art.get("id"), "status": "YA_EXISTE", "path": out_path, "bytes": os.path.getsize(out_path)}
        
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        candidate_urls = resolve_pdf_url(client, art)
        
        for p_url in candidate_urls:
            try:
                r = client.get(p_url)
                # Validar firma PDF o Content-Type
                if r.status_code == 200 and (r.content.startswith(b'%PDF') or 'application/pdf' in r.headers.get('content-type', '')):
                    with open(out_path, "wb") as f:
                        f.write(r.content)
                    return {
                        "id": art.get("id"),
                        "titulo": art.get("titulo"),
                        "status": "DESCARGADO_OK",
                        "path": out_path,
                        "bytes": len(r.content),
                        "url_descarga": p_url
                    }
            except Exception:
                continue
                
    return {"id": art.get("id"), "titulo": art.get("titulo"), "status": "NO_DISPONIBLE_PDF", "path": None, "bytes": 0}

def main():
    print("=" * 80)
    print("THINKUY — DESCARGADOR DE TEXTOS COMPLETOS / PDFs (ES/PT)")
    print(f"Directorio de destino: {OUTPUT_DIR}")
    print("=" * 80)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if not os.path.exists(INPUT_JSON):
        print(f"Error: No se encontró el archivo {INPUT_JSON}")
        return
        
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        articulos = json.load(f)
        
    total = len(articulos)
    print(f"Total de artículos a descargar: {total}\n")
    
    resultados = []
    
    # Descarga concurrente con ThreadPool (6 workers)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(descargar_articulo, art, idx, total): (idx, art) for idx, art in enumerate(articulos, 1)}
        
        for fut in as_completed(futures):
            idx, art = futures[fut]
            try:
                res = fut.result()
                resultados.append(res)
                st = res["status"]
                tam_kb = round(res.get("bytes", 0) / 1024, 1)
                icon = "✅" if st in ["DESCARGADO_OK", "YA_EXISTE"] else "❌"
                print(f"[{len(resultados):02d}/{total:02d}] {icon} {st:17} | {tam_kb:7.1f} KB | {art['titulo'][:55]}...")
            except Exception as e:
                print(f"[{len(resultados):02d}/{total:02d}] ❌ ERROR: {e}")
                
    descargados = sum(1 for r in resultados if r["status"] in ["DESCARGADO_OK", "YA_EXISTE"])
    print("\n" + "=" * 80)
    print("RESUMEN DE DESCARGAS:")
    print(f"  - Total PDFs Descargados con éxito: {descargados} / {total} ({descargados/total*100:.1f}%)")
    print(f"  - Guardados en la carpeta: {OUTPUT_DIR}")
    print("=" * 80)

if __name__ == "__main__":
    main()
