"""
=============================================================================
Thinkuy — Cosechador de Revisiones Sistemáticas y Scoping Reviews (ES/PT)
=============================================================================
Recopila entre 60 y 110 artículos únicos en Español y Portugués con
resúmenes completos provenientes de la literatura iberoamericana:
- Crossref (Revistas de SciELO, Redalyc y universidades iberoamericanas)
- Europe PMC (Literatura científica de SciELO y bases biomédicas/sociales)
- LA Referencia / OpenAIRE Graph v3 (Repositorios y revistas de acceso abierto)
=============================================================================
"""

import os
import sys
import json
import re
import csv
import time
import httpx
from html import unescape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_JSON = "data/lote_revisiones_es_pt_gold.json"
OUTPUT_CSV = "data/lote_revisiones_es_pt_gold.csv"

HEADERS = {
    "User-Agent": "Thinkuy-Scientific-Harvester/3.0 (mailto:investigador.thinkuy@gmail.com; https://thinkuy.org)",
    "Accept": "application/json"
}

def clean_xml_and_text(t):
    if not t:
        return ""
    t = unescape(t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'[\r\n\t]+', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()

def detectar_idioma(texto):
    t_lower = " " + texto.lower() + " "
    pt_markers = [" o ", " a ", " os ", " as ", " um ", " uma ", " não ", " revisão ", " escopo ", " pesquisa ", " métodos ", " resultados ", " objetivo ", " foram ", " conclui-se "]
    es_markers = [" el ", " la ", " los ", " las ", " un ", " una ", " no ", " revisión ", " alcance ", " investigación ", " métodos ", " resultados ", " objetivo ", " fueron ", " concluye "]
    
    pt_score = sum(1 for m in pt_markers if m in t_lower)
    es_score = sum(1 for m in es_markers if m in t_lower)
    
    if pt_score > es_score and pt_score >= 2:
        return "pt"
    return "es"

def cosechar_crossref(target_total=50):
    print("\n[1/3] Cosechando desde Crossref (Revistas Iberoamericanas SciELO/Redalyc)...")
    articulos = []
    
    queries = [
        "\"revisión sistemática\"",
        "\"revisión de alcance\"",
        "\"revisão sistemática\"",
        "\"revisão de escopo\"",
        "\"scoping review\" iberoamerica",
        "\"mapeo sistemático\"",
        "\"revisión integrativa\""
    ]
    
    with httpx.Client(headers=HEADERS, timeout=25.0) as client:
        for q in queries:
            if len(articulos) >= target_total:
                break
            url = "https://api.crossref.org/works"
            params = {
                "query.bibliographic": q,
                "filter": "type:journal-article,has-abstract:true,from-pub-date:2020-01-01",
                "rows": 25,
                "mailto": "investigador.thinkuy@gmail.com"
            }
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                items = r.json().get("message", {}).get("items", [])
                for it in items:
                    if len(articulos) >= target_total:
                        break
                    titles = it.get("title") or []
                    if not titles:
                        continue
                    titulo = clean_xml_and_text(titles[0])
                    abstract_raw = it.get("abstract") or ""
                    resumen = clean_xml_and_text(abstract_raw)
                    
                    if len(resumen) < 180:
                        continue
                        
                    # Validar idioma ES o PT
                    lang = detectar_idioma(titulo + " " + resumen)
                    
                    # Autores
                    autores = []
                    for au in it.get("author") or []:
                        name = f"{au.get('given', '')} {au.get('family', '')}".strip()
                        if name:
                            autores.append(name)
                            
                    doi = (it.get("DOI") or "").lower()
                    
                    # Año
                    ano = 2024
                    issued = it.get("issued", {}).get("date-parts", [[]])[0]
                    if issued:
                        ano = issued[0]
                        
                    journal = (it.get("container-title") or ["Revista Iberoamericana"])[0]
                    
                    t_low = (titulo + " " + resumen).lower()
                    if any(w in t_low for w in ["alcance", "escopo", "scoping", "mapeamento"]):
                        tipo_rev = "Scoping Review"
                    elif "integrativa" in t_low:
                        tipo_rev = "Revisión Integrativa"
                    else:
                        tipo_rev = "Revisión Sistemática"
                        
                    art_obj = {
                        "id": doi.replace("/", "_") if doi else f"cr_{len(articulos)+1}",
                        "titulo": titulo,
                        "autores": autores,
                        "ano": ano,
                        "doi": doi,
                        "url": f"https://doi.org/{doi}" if doi else it.get("URL", ""),
                        "revista": journal,
                        "fuente": "Crossref / SciELO",
                        "idioma": lang,
                        "tipo_revision": tipo_rev,
                        "abstract": resumen,
                        "longitud_palabras": len(resumen.split())
                    }
                    articulos.append(art_obj)
                    print(f"  [Crossref] ({len(articulos):02d}/{target_total}) {titulo[:60]}... [{lang.upper()}] ({len(resumen.split())} pals)")
                    time.sleep(0.1)
            except Exception as e:
                print(f"Error Crossref {q}: {e}")
                
    return articulos

def cosechar_europepmc(target_total=40):
    print("\n[2/3] Cosechando desde Europe PMC (Literatura biomédica y social en ES/PT)...")
    articulos = []
    
    queries = [
        '(TITLE:"revisión sistemática" OR TITLE:"revisión de alcance") AND (LANG:spa OR LANG:es)',
        '(TITLE:"revisão sistemática" OR TITLE:"revisão de escopo") AND (LANG:por OR LANG:pt)',
        '(TITLE:"scoping review") AND (SRC:MED OR SRC:PMC) AND (LANG:spa OR LANG:por)'
    ]
    
    with httpx.Client(headers=HEADERS, timeout=25.0) as client:
        for q in queries:
            if len(articulos) >= target_total:
                break
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": q,
                "format": "json",
                "pageSize": 25,
                "resultType": "core"
            }
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                results = r.json().get("resultList", {}).get("result", [])
                for it in results:
                    if len(articulos) >= target_total:
                        break
                    titulo = clean_xml_and_text(it.get("title") or "")
                    if not titulo:
                        continue
                        
                    resumen = clean_xml_and_text(it.get("abstractText") or "")
                    if len(resumen) < 180:
                        continue
                        
                    lang = detectar_idioma(titulo + " " + resumen)
                    doi = (it.get("doi") or "").lower()
                    
                    try:
                        ano = int(it.get("pubYear") or 2024)
                    except Exception:
                        ano = 2024
                        
                    autores_str = it.get("authorString") or ""
                    autores = [a.strip() for a in autores_str.split(",") if a.strip()]
                    
                    journal = it.get("journalTitle") or "Europe PMC / SciELO"
                    
                    t_low = (titulo + " " + resumen).lower()
                    if any(w in t_low for w in ["alcance", "escopo", "scoping", "mapeamento"]):
                        tipo_rev = "Scoping Review"
                    elif "integrativa" in t_low:
                        tipo_rev = "Revisión Integrativa"
                    else:
                        tipo_rev = "Revisión Sistemática"
                        
                    art_obj = {
                        "id": doi.replace("/", "_") if doi else f"epmc_{it.get('id', len(articulos)+1)}",
                        "titulo": titulo,
                        "autores": autores,
                        "ano": ano,
                        "doi": doi,
                        "url": f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/{it.get('source')}/{it.get('id')}",
                        "revista": journal,
                        "fuente": "Europe PMC / SciELO",
                        "idioma": lang,
                        "tipo_revision": tipo_rev,
                        "abstract": resumen,
                        "longitud_palabras": len(resumen.split())
                    }
                    articulos.append(art_obj)
                    print(f"  [Europe PMC] ({len(articulos):02d}/{target_total}) {titulo[:60]}... [{lang.upper()}] ({len(resumen.split())} pals)")
                    time.sleep(0.1)
            except Exception as e:
                print(f"Error Europe PMC {q}: {e}")
                
    return articulos

def cosechar_openaire(target_total=25):
    print("\n[3/3] Cosechando desde LA Referencia / OpenAIRE Graph v3 (ES/PT)...")
    articulos = []
    
    queries = [
        "\"revisión sistemática\"",
        "\"revisão sistemática\"",
        "\"revisión de alcance\"",
        "\"revisão de escopo\""
    ]
    with httpx.Client(headers=HEADERS, timeout=25.0) as client:
        for q in queries:
            if len(articulos) >= target_total:
                break
            url = "https://api.openaire.eu/graph/v3/research-products"
            params = {
                "query": q,
                "pageSize": 25,
                "format": "json"
            }
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                results = r.json().get("results") or []
                for it in results:
                    if len(articulos) >= target_total:
                        break
                    titulo = clean_xml_and_text(it.get("mainTitle") or "")
                    if not titulo:
                        continue
                    
                    descriptions = it.get("descriptions") or []
                    resumen = ""
                    if isinstance(descriptions, list) and descriptions:
                        resumen = clean_xml_and_text(descriptions[0])
                    elif isinstance(descriptions, str):
                        resumen = clean_xml_and_text(descriptions)
                        
                    if len(resumen) < 180:
                        continue
                        
                    lang = detectar_idioma(titulo + " " + resumen)
                    
                    doi = ""
                    for pid in it.get("pids") or []:
                        if str(pid.get("scheme", "")).lower() == "doi":
                            doi = str(pid.get("value", "")).lower().replace("https://doi.org/", "")
                            break
                            
                    autores = []
                    for au in it.get("authors") or []:
                        name = au.get("fullName") or f"{au.get('name', '')} {au.get('surname', '')}".strip()
                        if name:
                            autores.append(name)
                            
                    try:
                        ano = int(str(it.get("publicationDate") or "2024")[:4])
                    except Exception:
                        ano = 2024
                        
                    t_low = (titulo + " " + resumen).lower()
                    if any(w in t_low for w in ["alcance", "escopo", "scoping", "mapeamento"]):
                        tipo_rev = "Scoping Review"
                    else:
                        tipo_rev = "Revisión Sistemática"
                        
                    art_obj = {
                        "id": doi.replace("/", "_") if doi else f"openaire_{len(articulos)+1}",
                        "titulo": titulo,
                        "autores": autores,
                        "ano": ano,
                        "doi": doi,
                        "url": f"https://doi.org/{doi}" if doi else "https://explore.openaire.eu",
                        "revista": "LA Referencia / Repositorio Institucional",
                        "fuente": "LA Referencia / OpenAIRE",
                        "idioma": lang,
                        "tipo_revision": tipo_rev,
                        "abstract": resumen,
                        "longitud_palabras": len(resumen.split())
                    }
                    articulos.append(art_obj)
                    print(f"  [OpenAIRE] ({len(articulos):02d}/{target_total}) {titulo[:60]}... [{lang.upper()}] ({len(resumen.split())} pals)")
            except Exception as e:
                print(f"Error OpenAIRE {q}: {e}")
                
    return articulos

def main():
    print("=" * 80)
    print("THINKUY — COSECHA RIGUROSA DE REVISIONES Y SCOPING EN ESPAÑOL Y PORTUGUÉS")
    print("Fuentes: Crossref (SciELO/Redalyc), Europe PMC, LA Referencia/OpenAIRE")
    print("Objetivo: 60 - 110 artículos únicos con abstracts completos")
    print("=" * 80)
    
    art_cr = cosechar_crossref(target_total=50)
    art_epmc = cosechar_europepmc(target_total=40)
    art_aire = cosechar_openaire(target_total=25)
    
    todos = art_cr + art_epmc + art_aire
    
    # Deduplicación estricta por DOI o título normalizado
    vistos = set()
    unicos = []
    
    for a in todos:
        t_clean = re.sub(r'[^a-z0-9]', '', a["titulo"].lower())
        doi_clean = a["doi"].strip().lower() if a["doi"] else None
        
        clave = doi_clean if doi_clean else t_clean[:60]
        if clave and clave not in vistos:
            vistos.add(clave)
            unicos.append(a)
            
    total = len(unicos)
    print("\n" + "=" * 80)
    print(f"TOTAL COSECHADO Y DEDUPLICADO: {total} ARTÍCULOS")
    
    if total > 0:
        es_cnt = sum(1 for a in unicos if a["idioma"] == "es")
        pt_cnt = sum(1 for a in unicos if a["idioma"] == "pt")
        sist_cnt = sum(1 for a in unicos if a["tipo_revision"] == "Revisión Sistemática")
        scop_cnt = sum(1 for a in unicos if a["tipo_revision"] == "Scoping Review")
        integ_cnt = sum(1 for a in unicos if a["tipo_revision"] == "Revisión Integrativa")
        
        print(f"  * Idioma Español (ES)   : {es_cnt} ({es_cnt/total*100:.1f}%)")
        print(f"  * Idioma Portugués (PT) : {pt_cnt} ({pt_cnt/total*100:.1f}%)")
        print(f"  * Revisiones Sistemáticas: {sist_cnt} ({sist_cnt/total*100:.1f}%)")
        print(f"  * Scoping Reviews       : {scop_cnt} ({scop_cnt/total*100:.1f}%)")
        print(f"  * Revisiones Integrativas: {integ_cnt} ({integ_cnt/total*100:.1f}%)")
        print("=" * 80)
        
        # Guardar JSON
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(unicos, f, indent=2, ensure_ascii=False)
            
        # Guardar CSV
        with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            fieldnames = list(unicos[0].keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(unicos)
            
        print(f"\n[OK] Lote guardado con éxito:")
        print(f"  - Archivo JSON: {OUTPUT_JSON}")
        print(f"  - Archivo CSV:  {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
