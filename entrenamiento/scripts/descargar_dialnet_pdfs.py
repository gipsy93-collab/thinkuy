"""Descargador de artículos desde Dialnet vía endpoints de descarga de acceso abierto."""
import os
import re
import httpx
from html import unescape

OUTPUT_DIR = "data/descargas_revisiones_es_pt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8"
}

def main():
    queries = [
        "revision sistematica educacion",
        "revision sistematica salud",
        "revisao sistematica saude",
        "revision de alcance comunicacion",
        "revisao de escopo educacao"
    ]
    
    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            url = "https://dialnet.unirioja.es/buscar/documentos"
            params = {"q": q, "t": "todos", "f": "es", "btnBuscar": "Buscar"}
            try:
                r = client.get(url, params=params)
                if r.status_code != 200:
                    continue
                matches = re.findall(r'<li\s+id=\"articulo(\d+)\"\s+class=\"articulo[^\"]*\">([\s\S]*?)</li>', r.text, re.I)
                for code, block in matches:
                    # Buscar enlace a descarga de texto completo
                    m_pdf = re.search(r'href=\"(/servlet/articulo\?codigo=\d+&amp;orden=\d+&amp;info=link_completo)\"', block)
                    if not m_pdf:
                        m_pdf = re.search(r'href=\"(/descarga/articulo/\d+\.pdf)\"', block)
                        
                    if m_pdf:
                        rel_pdf = unescape(m_pdf.group(1))
                        pdf_url = f"https://dialnet.unirioja.es{rel_pdf}"
                        out_path = os.path.join(OUTPUT_DIR, f"dialnet_{code}.pdf")
                        
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                            continue
                            
                        try:
                            r_pdf = client.get(pdf_url)
                            if r_pdf.status_code == 200 and (r_pdf.content.startswith(b'%PDF') or 'application/pdf' in r_pdf.headers.get('content-type', '')):
                                with open(out_path, "wb") as f_out:
                                    f_out.write(r_pdf.content)
                                print(f"  [Dialnet PDF] ✅ {os.path.getsize(out_path)/1024:.1f} KB -> {out_path}")
                        except Exception:
                            continue
            except Exception as e:
                print(f"Error: {e}")

    total = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".pdf") and os.path.getsize(os.path.join(OUTPUT_DIR, f)) > 10000]
    print("\n" + "=" * 80)
    print(f"TOTAL FINAL DE PDFs EN DISCO: {len(total)} ARTÍCULOS")
    print(f"Carpeta física: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
