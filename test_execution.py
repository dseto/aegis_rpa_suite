#!/usr/bin/env python3
"""Script para testar execução com monitoramento de passos."""
import os
import sys
import json
import time
import subprocess
from pathlib import Path

# Adiciona o diretório do projeto ao path
sys.path.insert(0, str(Path(__file__).parent))

# Projeto a testar
PROJECT_DIR = "C:\\Projetos\\aegis_rpa_suite\\projects\\portal_segura\\tests\\001_teste"

def monitor_steps(json_path, interval=0.5):
    """Monitora changes no historico_passos.json e printa."""
    last_count = 0
    while True:
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    steps = json.load(f)
                    if len(steps) > last_count:
                        for s in steps[last_count:]:
                            row_id = s.get('row_id', '?')
                            status = s.get('status', '?')
                            desc = s.get('desc', '?')
                            print(f"[MONITOR] Reg {row_id}: Passo #{s.get('index')} - {status} - {desc}")
                        last_count = len(steps)
            except:
                pass
        time.sleep(interval)

def main():
    print("🚀 Iniciando teste de execução...")

    # Limpa historico anterior
    hist_path = os.path.join(PROJECT_DIR, "historico_passos.json")
    if os.path.exists(hist_path):
        os.remove(hist_path)

    # Inicia monitoramento em background
    print(f"📊 Monitorando: {hist_path}")
    monitor_proc = subprocess.Popen(
        [sys.executable, "-c", f"""
import json, time, os, sys
json_path = r'{hist_path}'
last_count = 0
start = time.time()
while time.time() - start < 120:  # 2 min timeout
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                steps = json.load(f)
                if len(steps) > last_count:
                    for s in steps[last_count:]:
                        row_id = s.get('row_id', '?')
                        status = s.get('status', '?')
                        desc = s.get('desc', '?')
                        print(f"[STEP] Reg {{row_id}}: #{{s.get('index')}} {{status}} {{desc}}", flush=True)
                    last_count = len(steps)
        except: pass
    time.sleep(0.3)
"""]
    )

    time.sleep(1)  # Aguarda início do monitor

    # Executa bot
    print("▶️  Executando bot_producao.py...")
    os.chdir(PROJECT_DIR)

    try:
        result = subprocess.run(
            [sys.executable, "code/bot_producao.py"],
            capture_output=False,
            timeout=120
        )
        print(f"✅ Execução completada com code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("⏱️  Timeout na execução")
    except Exception as e:
        print(f"❌ Erro: {e}")
    finally:
        monitor_proc.terminate()
        monitor_proc.wait()

    # Lê resultado final
    if os.path.exists(hist_path):
        with open(hist_path, 'r') as f:
            steps = json.load(f)
            print(f"\n📈 Total de passos gravados: {len(steps)}")

            # Agrupa por row_id
            by_row = {}
            for s in steps:
                rid = s.get('row_id')
                if rid not in by_row:
                    by_row[rid] = []
                by_row[rid].append(s)

            print(f"🔍 Transações (row_ids):")
            for rid in sorted(by_row.keys()):
                count = len(by_row[rid])
                statuses = [s.get('status') for s in by_row[rid]]
                print(f"   Reg {rid}: {count} passos - {statuses}")

if __name__ == "__main__":
    main()
