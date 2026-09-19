"""Dashboard de Telemetría y Benchmark Tripartito en Tiempo Real (Puerto 7860).

Incluye dos vistas completas:
1. Telemetría de Entrenamiento en Vivo (GPU RTX 5060, VRAM, RAM, Loss, LR, ETA).
2. Visualizador del Benchmark Tripartito Robusto (N=32 citas holdout, Qwen Base vs Qwen V2 vs Ministral 3B).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import psutil

PORT = 7860
METRICS_FILE = Path("data/auditorias_y_benchmarks/training_live_metrics.json")
BENCHMARK_FILE = Path("data/auditorias_y_benchmarks/robust_benchmark_results.json")

# Estado global de telemetría
telemetry_state: Dict[str, Any] = {
    "gpu": {
        "name": "NVIDIA GeForce RTX 5060 Laptop GPU",
        "temp": 0,
        "vram_used_mb": 0,
        "vram_total_mb": 8151,
        "vram_percent": 0.0,
        "utilization_percent": 0,
        "power_w": 0,
    },
    "system": {
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "ram_percent": 0.0,
        "cpu_percent": 0.0,
    },
    "training": {
        "status": "Entrenamiento Completado (881/881 steps)",
        "step": 881,
        "max_steps": 881,
        "epoch": 1.0,
        "loss": 0.0938,
        "learning_rate": 0.0,
        "elapsed_seconds": 10110,
        "eta_seconds": 0,
        "loss_history": [],
        "lr_history": [],
        "logs_tail": "Modelo consolidado con éxito en models/qwen_epistemic_v2_cot",
    },
    "timestamp": time.time(),
}


def query_gpu_metrics():
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5, creationflags=0x08000000 if sys.platform == "win32" else 0)
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) >= 4:
                temp = int(float(parts[0]))
                vram_used = int(float(parts[1]))
                vram_total = int(float(parts[2]))
                util = int(float(parts[3]))
                power = float(parts[4]) if len(parts) >= 5 and parts[4].replace(".", "", 1).isdigit() else 0.0
                return {
                    "temp": temp,
                    "vram_used_mb": vram_used,
                    "vram_total_mb": vram_total,
                    "vram_percent": round((vram_used / max(vram_total, 1)) * 100, 1),
                    "utilization_percent": util,
                    "power_w": round(power, 1),
                }
    except Exception:
        pass
    return None


def telemetry_poller():
    while True:
        try:
            gpu_data = query_gpu_metrics()
            if gpu_data:
                telemetry_state["gpu"].update(gpu_data)

            vmem = psutil.virtual_memory()
            telemetry_state["system"] = {
                "ram_used_gb": round(vmem.used / (1024**3), 2),
                "ram_total_gb": round(vmem.total / (1024**3), 2),
                "ram_percent": round(vmem.percent, 1),
                "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            }

            if METRICS_FILE.exists():
                try:
                    with open(METRICS_FILE, "r", encoding="utf-8") as f:
                        tr_data = json.load(f)
                    telemetry_state["training"].update(tr_data)
                except Exception:
                    pass

            telemetry_state["timestamp"] = time.time()
        except Exception:
            pass
        time.sleep(1.0)


HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Thinkuy Lab — Telemetría y Benchmark Tripartito</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #080c14;
      --card-bg: rgba(16, 23, 38, 0.85);
      --card-border: rgba(56, 189, 248, 0.15);
      --accent-cyan: #38bdf8;
      --accent-purple: #a855f7;
      --accent-green: #22c55e;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body {
      background-color: var(--bg);
      background-image: radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.08) 0%, transparent 40%),
                        radial-gradient(circle at 85% 85%, rgba(168, 85, 247, 0.08) 0%, transparent 40%);
      color: var(--text-main);
      min-height: 100vh;
      padding: 16px 22px;
    }
    .container { max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
    
    header {
      display: flex; justify-content: space-between; align-items: center;
      background: var(--card-bg); border: 1px solid var(--card-border);
      border-radius: 12px; padding: 14px 22px; backdrop-filter: blur(12px);
    }
    .logo-badge {
      background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
      width: 38px; height: 38px; border-radius: 8px; display: flex; align-items: center;
      justify-content: center; font-weight: 900; font-size: 18px; color: #fff;
    }
    .tabs-nav { display: flex; gap: 8px; background: rgba(255, 255, 255, 0.04); padding: 4px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08); }
    .tab-btn {
      background: transparent; border: none; color: var(--text-muted); padding: 8px 16px;
      border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s;
    }
    .tab-btn.active { background: rgba(56, 189, 248, 0.15); color: var(--accent-cyan); border: 1px solid rgba(56, 189, 248, 0.3); }

    /* TAB CONTENT */
    .tab-content { display: none; flex-direction: column; gap: 16px; }
    .tab-content.active { display: flex; }

    /* METRICS GRID */
    .metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
    .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 14px 18px; backdrop-filter: blur(12px); }
    .card-label { font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); }
    .card-value { font-size: 24px; font-weight: 700; margin: 4px 0; display: flex; align-items: baseline; gap: 4px; }
    .card-subtext { font-size: 12px; color: var(--text-muted); }
    .progress-bar-bg { width: 100%; height: 5px; background: rgba(255, 255, 255, 0.08); border-radius: 99px; overflow: hidden; margin-top: 8px; }
    .progress-bar-fill { height: 100%; border-radius: 99px; transition: width 0.4s ease; }

    /* TRAINING BANNER */
    .training-banner {
      background: linear-gradient(135deg, rgba(25, 34, 56, 0.85), rgba(16, 22, 38, 0.85));
      border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 12px; padding: 16px 20px;
    }
    .main-progress-bg { width: 100%; height: 8px; background: rgba(255, 255, 255, 0.08); border-radius: 99px; overflow: hidden; margin: 10px 0 6px 0; }
    .main-progress-fill { height: 100%; background: linear-gradient(90deg, var(--accent-cyan), var(--accent-purple)); border-radius: 99px; }

    /* CHARTS */
    .charts-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
    .chart-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 16px 18px; }
    .chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .canvas-container { position: relative; height: 240px; width: 100%; }

    /* BENCHMARK TAB STYLES */
    .models-compare-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
    .model-card {
      background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px;
      padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; position: relative;
    }
    .model-card.winner {
      border: 2px solid var(--accent-cyan);
      box-shadow: 0 0 20px rgba(56, 189, 248, 0.15);
      background: linear-gradient(180deg, rgba(16, 32, 54, 0.95), var(--card-bg));
    }
    .crown-badge {
      position: absolute; top: -10px; right: 16px; background: linear-gradient(135deg, #eab308, #ca8a04);
      color: #000; font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 4px; letter-spacing: 0.5px;
    }
    .score-big { font-size: 34px; font-weight: 800; color: var(--accent-cyan); line-height: 1; }
    .score-row { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }

    /* TABLE */
    .table-container {
      background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px;
      padding: 16px; overflow-x: auto; max-height: 520px;
    }
    table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
    th { padding: 10px 12px; color: var(--text-muted); border-bottom: 1px solid rgba(255, 255, 255, 0.1); font-weight: 600; text-transform: uppercase; font-size: 11px; }
    td { padding: 10px 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); vertical-align: top; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }
    .badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; display: inline-block; }
    .badge-success { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
    .badge-error { background: rgba(244, 63, 94, 0.15); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.3); }
    .badge-neutral { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }
    .quote-box { max-width: 320px; color: #cbd5e1; font-style: italic; line-height: 1.4; }
  </style>
</head>
<body>
  <div class="container">
    <!-- HEADER -->
    <header>
      <div style="display: flex; align-items: center; gap: 12px;">
        <div class="logo-badge">T</div>
        <div>
          <h1 style="font-size: 17px; font-weight: 700;">Thinkuy Lab — Suite de Evaluación y Telemetría QLoRA V2</h1>
          <p style="font-size: 12px; color: var(--text-muted);">Qwen 2.5 1.5B CoT (r=32, Negativos Difíciles SNLI + TASS) en GPU RTX 5060</p>
        </div>
      </div>
      <div class="tabs-nav">
        <button class="tab-btn active" onclick="switchTab('tab-telemetry')">📡 Telemetría GPU</button>
        <button class="tab-btn" onclick="switchTab('tab-benchmark')">🏆 Benchmark Tripartito (N=32)</button>
      </div>
    </header>

    <!-- TAB 1: TELEMETRIA -->
    <div id="tab-telemetry" class="tab-content active">
      <div class="metrics-grid">
        <div class="card">
          <div class="card-label">Temperatura GPU</div>
          <div class="card-value"><span id="val-temp">--</span> <span style="font-size: 15px; color: var(--text-muted);">°C</span></div>
          <div class="card-subtext" id="status-temp">GeForce RTX 5060 Laptop</div>
          <div class="progress-bar-bg"><div class="progress-bar-fill" id="bar-temp" style="width: 0%; background: var(--accent-green);"></div></div>
        </div>
        <div class="card">
          <div class="card-label">Memoria VRAM (GPU)</div>
          <div class="card-value"><span id="val-vram">--</span> <span style="font-size: 13px; color: var(--text-muted);">/ 8.0 GB</span></div>
          <div class="card-subtext" id="status-vram">Uso VRAM: 0%</div>
          <div class="progress-bar-bg"><div class="progress-bar-fill" id="bar-vram" style="width: 0%; background: var(--accent-cyan);"></div></div>
        </div>
        <div class="card">
          <div class="card-label">Memoria RAM (Sistema)</div>
          <div class="card-value"><span id="val-ram">--</span> <span style="font-size: 13px; color: var(--text-muted);" id="val-ram-total">/ -- GB</span></div>
          <div class="card-subtext" id="status-ram">Uso: 0%</div>
          <div class="progress-bar-bg"><div class="progress-bar-fill" id="bar-ram" style="width: 0%; background: var(--accent-purple);"></div></div>
        </div>
        <div class="card">
          <div class="card-label">Utilización Tensor Core</div>
          <div class="card-value"><span id="val-util">--</span> <span style="font-size: 15px; color: var(--text-muted);">%</span></div>
          <div class="card-subtext" id="status-util">Potencia: 0 W</div>
          <div class="progress-bar-bg"><div class="progress-bar-fill" id="bar-util" style="width: 0%; background: var(--accent-amber);"></div></div>
        </div>
      </div>

      <div class="training-banner">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong id="tr-status-title" style="color: var(--accent-cyan); font-size: 15px;">Entrenamiento Completado</strong>
          <div style="display: flex; gap: 16px; font-size: 13px;">
            <span>Step: <strong id="tr-step">881 / 881</strong></span>
            <span>Época: <strong id="tr-epoch">1.0 / 1.0</strong></span>
            <span>Loss Final: <strong id="tr-loss" style="color: var(--accent-cyan);">0.0938</strong></span>
          </div>
        </div>
        <div class="main-progress-bg"><div class="main-progress-fill" id="main-progress-bar" style="width: 100%;"></div></div>
        <div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted);">
          <span id="tr-elapsed">Tiempo total: 2h 48m 32s</span>
          <span style="color: #4ade80; font-weight: 700;">✓ Adaptadores LoRA guardados (models/qwen_epistemic_v2_cot)</span>
        </div>
      </div>

      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-header">
            <strong style="font-size: 13px;">📉 Curva de Pérdida de Entrenamiento (Training Loss)</strong>
            <span style="font-size: 11px; color: var(--accent-cyan); padding: 2px 8px; background: rgba(56, 189, 248, 0.1); border-radius: 4px;">Loss Final: 0.0938</span>
          </div>
          <div class="canvas-container"><canvas id="lossChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-header">
            <strong style="font-size: 13px;">🎯 Decaimiento Cosine Scheduler (Learning Rate)</strong>
            <span style="font-size: 11px; color: var(--accent-purple); padding: 2px 8px; background: rgba(168, 85, 247, 0.1); border-radius: 4px;">Cosine Annealing</span>
          </div>
          <div class="canvas-container"><canvas id="lrChart"></canvas></div>
        </div>
      </div>
    </div>

    <!-- TAB 2: BENCHMARK TRIPARTITO ROBUSTO -->
    <div id="tab-benchmark" class="tab-content">
      <!-- 3 MODEL CARDS -->
      <div class="models-compare-grid">
        <!-- QWEN BASE -->
        <div class="model-card">
          <div style="font-size: 13px; font-weight: 700; color: var(--text-muted);">🤖 Qwen 2.5 1.5B Base (Zero-Shot)</div>
          <div class="score-big" style="color: #94a3b8;" id="bm-acc-base">46.9%</div>
          <div style="font-size: 12px; color: var(--text-muted);">Accuracy Global (15/32 citas acertadas)</div>
          <div class="score-row"><span>Fidelidad Verbatim:</span> <strong id="bm-verb-base" style="color: #f43f5e;">28.1%</strong></div>
          <div class="score-row"><span>Menciones Neutrales:</span> <strong style="color: #f43f5e;">0.0% (Falsos Consensos)</strong></div>
          <div class="score-row"><span>Formato JSON Válido:</span> <strong>100.0%</strong></div>
          <div class="score-row"><span>Latencia Media:</span> <span>8.5s</span></div>
        </div>

        <!-- MINISTRAL 3B -->
        <div class="model-card">
          <div style="font-size: 13px; font-weight: 700; color: var(--text-muted);">⚡ Ministral 3B (Mistral AI)</div>
          <div class="score-big" style="color: #a855f7;" id="bm-acc-mistral">50.0%</div>
          <div style="font-size: 12px; color: var(--text-muted);">Accuracy Global (16/32 citas acertadas)</div>
          <div class="score-row"><span>Fidelidad Verbatim:</span> <strong id="bm-verb-mistral" style="color: #f43f5e;">34.4%</strong></div>
          <div class="score-row"><span>Menciones Neutrales:</span> <strong style="color: #4ade80;">75.0%</strong></div>
          <div class="score-row"><span>Formato JSON Válido:</span> <strong style="color: #f59e0b;">65.6% (Errores sintácticos)</strong></div>
          <div class="score-row"><span>Latencia Media:</span> <span>20.87s</span></div>
        </div>

        <!-- NUESTRO QWEN V2 -->
        <div class="model-card winner">
          <div class="crown-badge">👑 GANADOR ABSOLUTO</div>
          <div style="font-size: 13px; font-weight: 700; color: var(--accent-cyan);">🧠 NUESTRO Qwen 2.5 1.5B CoT V2</div>
          <div class="score-big" style="color: #38bdf8;" id="bm-acc-v2">90.6%</div>
          <div style="font-size: 12px; color: var(--accent-cyan);">Accuracy Global (29/32 citas acertadas)</div>
          <div class="score-row"><span>Fidelidad Verbatim:</span> <strong id="bm-verb-v2" style="color: #4ade80;">96.9%</strong></div>
          <div class="score-row"><span>Menciones Neutrales:</span> <strong style="color: #4ade80;">100.0% (8/8 Acertadas)</strong></div>
          <div class="score-row"><span>Formato JSON Válido:</span> <strong style="color: #4ade80;">100.0% Puro</strong></div>
          <div class="score-row"><span>Latencia Media:</span> <strong style="color: #38bdf8;">5.16s (Ultra Rápido)</strong></div>
        </div>
      </div>

      <!-- CHARTS COMPARATIVE -->
      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-header"><strong style="font-size: 13px;">📊 Comparativa de Métricas Globales (%)</strong></div>
          <div class="canvas-container"><canvas id="bmGlobalChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-header"><strong style="font-size: 13px;">🎯 Precisión por Postura Epistémica Específica (%)</strong></div>
          <div class="canvas-container"><canvas id="bmClassChart"></canvas></div>
        </div>
      </div>

      <!-- DETAILED TABLE -->
      <div class="table-container">
        <h3 style="font-size: 14px; margin-bottom: 12px; color: var(--accent-cyan);">Detalle de las 32 Citas Ciegas de Evaluación Holdout</h3>
        <table id="benchmark-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Contexto de Citación</th>
              <th>Postura Real (Gold)</th>
              <th>Qwen Base (1.5B)</th>
              <th>Ministral 3B</th>
              <th>NUESTRO Qwen V2 CoT</th>
            </tr>
          </thead>
          <tbody id="benchmark-tbody">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Cargando citas evaluadas...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      document.getElementById(tabId).classList.add('active');
      event.target.classList.add('active');
    }

    // Chart.js Telemetría
    const ctxLoss = document.getElementById('lossChart').getContext('2d');
    const ctxLr = document.getElementById('lrChart').getContext('2d');
    const lossChart = new Chart(ctxLoss, {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'Loss', data: [], borderColor: '#38bdf8', borderWidth: 2, pointRadius: 1, fill: false, tension: 0.2 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }, y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } } } }
    });
    const lrChart = new Chart(ctxLr, {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'LR', data: [], borderColor: '#a855f7', borderWidth: 2, pointRadius: 1, fill: false, tension: 0.2 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }, y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } } } }
    });

    // Chart.js Benchmark
    const ctxBmGlobal = document.getElementById('bmGlobalChart').getContext('2d');
    const bmGlobalChart = new Chart(ctxBmGlobal, {
      type: 'bar',
      data: {
        labels: ['Accuracy Global', 'Fidelidad Verbatim', 'JSON Válido'],
        datasets: [
          { label: 'Qwen Base 1.5B', data: [46.9, 28.1, 100.0], backgroundColor: 'rgba(148, 163, 184, 0.6)' },
          { label: 'Ministral 3B', data: [50.0, 34.4, 65.6], backgroundColor: 'rgba(168, 85, 247, 0.6)' },
          { label: 'NUESTRO Qwen V2 CoT', data: [90.6, 96.9, 100.0], backgroundColor: 'rgba(56, 189, 248, 0.85)' }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { max: 100, ticks: { color: '#94a3b8' } }, x: { ticks: { color: '#94a3b8' } } } }
    });

    const ctxBmClass = document.getElementById('bmClassChart').getContext('2d');
    const bmClassChart = new Chart(ctxBmClass, {
      type: 'bar',
      data: {
        labels: ['Neutros (Mención)', 'Consensos Reales', 'Disensos / Crítica', 'Adopción Método'],
        datasets: [
          { label: 'Qwen Base 1.5B', data: [0.0, 75.0, 75.0, 37.5], backgroundColor: 'rgba(148, 163, 184, 0.6)' },
          { label: 'Ministral 3B', data: [75.0, 50.0, 37.5, 37.5], backgroundColor: 'rgba(168, 85, 247, 0.6)' },
          { label: 'NUESTRO Qwen V2 CoT', data: [100.0, 87.5, 87.5, 87.5], backgroundColor: 'rgba(56, 189, 248, 0.85)' }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { max: 100, ticks: { color: '#94a3b8' } }, x: { ticks: { color: '#94a3b8' } } } }
    });

    async function updateTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        if (!res.ok) return;
        const d = await res.json();
        const gpu = d.gpu || {};
        document.getElementById('val-temp').innerText = gpu.temp || 0;
        document.getElementById('bar-temp').style.width = Math.min(gpu.temp || 0, 100) + '%';
        document.getElementById('val-vram').innerText = ((gpu.vram_used_mb || 0) / 1024).toFixed(2);
        document.getElementById('bar-vram').style.width = (gpu.vram_percent || 0) + '%';
        document.getElementById('status-vram').innerText = `Uso VRAM: ${gpu.vram_percent || 0}% (${gpu.vram_used_mb || 0} MB)`;
        const sys = d.system || {};
        document.getElementById('val-ram').innerText = sys.ram_used_gb || 0;
        document.getElementById('val-ram-total').innerText = `/ ${sys.ram_total_gb || 0} GB`;
        document.getElementById('bar-ram').style.width = (sys.ram_percent || 0) + '%';
        document.getElementById('status-ram').innerText = `Uso RAM: ${sys.ram_percent || 0}%`;
        document.getElementById('val-util').innerText = gpu.utilization_percent || 0;
        document.getElementById('bar-util').style.width = (gpu.utilization_percent || 0) + '%';
        document.getElementById('status-util').innerText = `Consumo: ${gpu.power_w || 0} W`;

        const tr = d.training || {};
        if (tr.loss_history && tr.loss_history.length > 0) {
          lossChart.data.labels = tr.loss_history.map(x => `S${x.step}`);
          lossChart.data.datasets[0].data = tr.loss_history.map(x => x.loss);
          lossChart.update('none');
        }
        if (tr.lr_history && tr.lr_history.length > 0) {
          lrChart.data.labels = tr.lr_history.map(x => `S${x.step}`);
          lrChart.data.datasets[0].data = tr.lr_history.map(x => x.lr);
          lrChart.update('none');
        }
      } catch (e) {}
    }

    async function loadBenchmarkData() {
      try {
        const res = await fetch('/api/benchmark');
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('benchmark-tbody');
        tbody.innerHTML = '';

        (data.details || []).forEach(row => {
          const tr = document.createElement('tr');
          const gold = row.gold_stance;
          
          function formatCell(mObj, isCorr) {
            const st = mObj.stance || 'N/A';
            const rat = mObj.rationale || '';
            const clm = mObj.claim || '';
            const bClass = isCorr ? 'badge-success' : 'badge-error';
            const icon = isCorr ? '✓' : '✗';
            return `
              <div>
                <span class="badge ${bClass}">${icon} ${st}</span>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;"><em>"${rat}"</em></div>
                ${clm ? `<div style="font-size: 10px; color: var(--accent-cyan); margin-top: 2px;">Claim: "${clm}"</div>` : ''}
              </div>
            `;
          }

          tr.innerHTML = `
            <td style="font-weight: 700; color: var(--accent-cyan);">${row.id}</td>
            <td class="quote-box">${row.input.replace(/\\n/g, '<br>')}</td>
            <td><span class="badge badge-neutral">${gold}</span></td>
            <td>${formatCell(row.qwen_base, row.is_correct_base)}</td>
            <td>${formatCell(row.ministral_3b, row.is_correct_mistral)}</td>
            <td style="background: rgba(56, 189, 248, 0.05);">${formatCell(row.qwen_v2_cot, row.is_correct_v2)}</td>
          `;
          tbody.appendChild(tr);
        });
      } catch (e) {
        console.error("Error al cargar benchmark:", e);
      }
    }

    setInterval(updateTelemetry, 1500);
    updateTelemetry();
    loadBenchmarkData();
  </script>
</body>
</html>
"""


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            payload = json.dumps(telemetry_state, ensure_ascii=False)
            self.wfile.write(payload.encode("utf-8"))
        elif self.path == "/api/benchmark":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            bm_data = {}
            if BENCHMARK_FILE.exists():
                try:
                    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
                        bm_data = json.load(f)
                except Exception:
                    pass
            self.wfile.write(json.dumps(bm_data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def run_dashboard_server():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), DashboardHTTPHandler)
    print(f"\n[DASHBOARD ACTUALIZADO] Activo en: http://localhost:{PORT}")
    server.serve_forever()


def main():
    poller_thread = threading.Thread(target=telemetry_poller, daemon=True)
    poller_thread.start()
    run_dashboard_server()


if __name__ == "__main__":
    main()
