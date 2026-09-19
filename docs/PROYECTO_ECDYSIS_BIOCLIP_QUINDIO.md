# Proyecto Ecdysis-Bio: IA Móvil Offline para Biodiversidad y Apropiación Social

> **Grupo de Investigación**: Ecdysis — Universidad del Quindío  
> **Fecha de formulación y validación empírica**: Septiembre 2026  
> **Conversación de referencia**: `868df875-e985-4a75-8f05-7371381be19e`  
> **Estado**: Prueba de concepto validada empíricamente; listo para diseño de prototipo PWA.

---

## 1. Resumen Ejecutivo
Propuesta de desarrollo de una **Aplicación Web Progresiva (PWA) 100% Offline** para la identificación taxonómica asistida por IA de especies endémicas, fauna subterránea (cuevas) y microfauna del Paisaje Cultural Cafetero y la Cordillera Central de Colombia, liderada por el **Grupo de Investigación Ecdysis de la Universidad del Quindío**.

---

## 2. Caso de Estudio Empírico Validado en Sesión

Se realizó una prueba empírica en tiempo real sobre el artículo científico:
* **Título**: *Whip spiders (Arachnida, Amblypygi) from Colombian Caves: A review, new records and description of a new species*.
* **Autores**: Osvaldo Villarreal, **Leonardo Delgado-Santa (Universidad del Quindío)**, Carlos A. Lasso.
* **Publicación**: *Subterranean Biology* 52: 1–28 (Mayo 2025). DOI: `10.3897/subtbiol.52.150357`.

### Hallazgos de la Prueba con BioCLIP (`open_clip_torch` / ViT-B-16):
Se recortaron y evaluaron fotografías vivas de campo de la caverna (Figura 14):

1. **Nueva especie descubierta para la ciencia**: ***Charinus santandereanus sp. nov.*** (Cueva El Nitro, Villanueva, Santander):
   - **Diagnóstico de Género**: 🥇 **`Charinus` al 61.48%** (frente a otros amblipígidos y arañas comunes).
   - **Afinidad de Especie dentro del Paper**: 🥇 **`Charinus santandereanus` al 90.19%** (separada claramente de su especie hermana *C. tronchonii* al 9.74%).
2. ***Charinus tronchonii*** (Cueva del Cuarzo):
   - 🥇 **`Charinus tronchonii` al 86.79%** (frente a 7.21% para *C. santandereanus*).
3. ***Phrynus araya*** (Cueva Fumador):
   - **Fenómeno biológico detectado**: La silueta oscura en cueva fue confundida con una tarántula (*Pamphobeteus* 92.16%).
   - **Importancia metodológica**: Demuestra empíricamente por qué el modelo base genérico falla ante la morfología andina y por qué la calibración *Few-Shot* del Grupo Ecdysis es indispensable.

---

## 3. Propuesta de Valor y Diferenciación frente a Apps Globales (Seek / Google Lens)

| Eje | Apps Globales (Seek / Lens) | App Ecdysis / UniQuindío |
| :--- | :--- | :--- |
| **Cobertura de Taxones** | Sesgo hacia Norteamérica y Europa. Especies endémicas o descritas en 2025 no existen en sus bases. | **Hiperlocal**: Especializada en la cordillera central, cuevas colombianas y fauna del cafetal. |
| **Apropiación Social** | Fichas frías de Wikipedia en inglés o latín. | **Fichas dialógicas comunitarias**: Desmitificación de veneno (semáforo de peligrosidad). |
| **Agroecología** | Desconectada del sector productivo. | **Aliada del caficultor**: Explica si el animal es control biológico de plagas (broca, grillos). |
| **Ecoturismo** | Genérica. | **Guía Oficial de Microfauna de la UniQuindío** para guías en Salento, Filandia y Cocora. |
| **Soberanía Científica** | Los datos van a servidores en el extranjero. | Los registros alimentan la **Colección Entomológica de la UniQuindío** y el SiB Colombia. |

---

## 4. Arquitectura Técnica (Offline-First)

```
[ Celular en Cueva / Finca sin Señal ]
  │
  ├── 1. Cámara PWA (HTML5 Video / Canvas)
  ├── 2. Sensor GPS nativo (Captura coordenadas satelitales offline)
  ├── 3. Motor ONNX Runtime Web / WebGPU (Modelo MobileNet/BioCLIP cuantizado a INT8, ~15 MB)
  │      └── Inferencia local en el dispositivo (< 300 ms, 0 bytes gastados)
  ├── 4. Ficha Pedagógica Inmediata (Lenguaje campesino y escolar)
  └── 5. IndexedDB (Almacena el reporte georreferenciado en cola)
          │
          └── [Al detectar conexión Wi-Fi] ──> Sincronización con Servidor Ecdysis UniQuindío
```

---

## 5. Scripts y Recursos Generados en la Sesión

* **Script de consulta de especies del Quindío**: [`scratch/check_quindio_species.py`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/scratch/check_quindio_species.py) (iNaturalist / GBIF Quindío: 234 arácnidos y 3.758 insectos documentados).
* **Script de evaluación BioCLIP**: [`scratch/test_bioclip_paper.py`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/scratch/test_bioclip_paper.py) (Entorno PyTorch + OpenCLIP configurado y funcional).
* **Imágenes recortadas de los especímenes**:
  - [`scratch/live_charinus_santandereanus.jpg`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/scratch/live_charinus_santandereanus.jpg)
  - [`scratch/live_charinus_tronchonii.jpg`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/scratch/live_charinus_tronchonii.jpg)
  - [`scratch/live_phrynus_araya.jpg`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/scratch/live_phrynus_araya.jpg)
* **XML del paper analizado**: [`scratch/amblypygi_paper.xml`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/scratch/amblypygi_paper.xml).

---

## 6. Pasos para Retomar

1. **Diseñar el Wireframe de la PWA móvil**: Pantalla de cámara, semáforo de peligrosidad y ficha agroecológica/etnobiológica.
2. **Exportar el clasificador a formato ONNX / WebAssembly**: Reducir el modelo para ejecución directa en el navegador del teléfono.
3. **Curar el dataset de 10 a 20 especies prioritarias de Ecdysis**: Recopilar fotos de especímenes testigo del laboratorio de la Universidad del Quindío.
