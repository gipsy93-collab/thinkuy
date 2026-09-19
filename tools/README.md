# `tools/` — utilidades vigentes

Scripts de apoyo del proyecto (el servicio vive en `backend/` + `pwa/`; el pipeline de
entrenamiento, en `entrenamiento/`). **Solo se conservan aquí las versiones vigentes**; lo
superado está en `_ARCHIVE/tools_superados/` (ver `_ARCHIVE/MANIFIESTO.md`).

## Índice por función

| Grupo | Scripts |
| :--- | :--- |
| **PWA / despliegue** | `bump_pwa_version.py` (fuente única de versión), `smoke_pwa.py` (humo con Playwright: arranca el servidor, carga la app y falla ante excepciones de JS), `make_icons.py` |
| **Common Crawl (SCIVIS)** | `download_cc_ranks.py`, `index_cc_ranks.py`, `download_cc_graph.py`, `build_cc_inlinks.py`, `cc_history.py`, `web_twins_build.py`, `synthesize_neighborhood.py` |
| **Dataset y anotación** | `build_epistemic_dataset.py` (v1), `build_epistemic_dataset_v3_hard_negatives.py` (v3, vigente), `extract_training_corpus.py`, `build_corpus_inventario.py`, `reindex_corpus_v2.py`, `etiquetador_determinista.py`, `etiquetador_protocolo.py`, `etiquetador_t2_pcc.py`, `auditor_forense_dataset.py`, `calcular_kappa.py`, `patron_dorado.py`, `diagnostico_t1_roles.py`, `medir_binario_postura.py`, `seleccion_postura_api.py`, `generar_formularios.py`, `importar_formularios.py`, `importar_anotacion_md.py`, `generar_control_ciego.py`, `generar_hoja_respuestas.py`, `generar_pases_anotacion.py`, `refrescar_control_36.py`, `remedir_control_stance.py`, `remedir_control_protocolo.py`, `verificar_control_protocolo.py` |
| **Entrenamiento y evaluación** | `train_epistemic_unsloth.py`, `train_qwen_cot_v2.py`, `train_monitor_dashboard.py`, `eval_trained_qwen.py`, `export_to_gguf.py`, `robust_tripartite_eval.py`, `benchmark_three_models_rigorous.py`, `comparar_extractores.py`, `probar_schematron.py`, `auditar_fidelidad.py` |
| **Radar / SCIVIS / revisión** | `doi_tracker.py`, `mapeobiblio.py`, `demo_informe_revision.py`, `verificar_cadena_resumen.py`, `verificar_oai_ojs.py`, `replicate_full_scopus_and_merge_thinkuy.py`, `export_results_csv.py` |

## Archivados (19)

`audit_raw_thinkuy_v2`, `audit_real_paper`, `benchmark_full_333_tripartite`, `benchmark_three_models_live`,
`blind_benchmark_duque`, `build_epistemic_dataset_v2_cot`, `compare_qwen_base`, `compare_qwen_vs_mistral`,
`compare_three_models`, `corregir_mojibake_docs`, `demo_live_probe_epistemic`, `eval_rsu_duque_fine_tuned`,
`gen_seed`, `hunt_10_refutations`, `process_wos_native`, `replicate_duque_review`,
`replicate_full_wos_thinkuy`, `run_training_with_monitor`, `test_gemma4_prompt`.

Motivo general: versiones superadas por un sucesor documentado (comparativas antiguas, datasets v2,
replicaciones parciales, diagnósticos de una sola vez). Detalle y sustituto en `_ARCHIVE/MANIFIESTO.md`.
