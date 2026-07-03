#!/bin/bash
# Testa polling live durante execução

PROJECT_DIR="C:\Projetos\aegis_rpa_suite\projects\portal_segura\tests\001_teste"
HIST_FILE="$PROJECT_DIR/historico_passos.json"

# Remove arquivo anterior
rm -f "$HIST_FILE"

echo "[TEST] Iniciando execução do bot em background..."
cd "$PROJECT_DIR" && timeout 120 python code/bot_producao.py > /tmp/bot_exec.log 2>&1 &
BOT_PID=$!

echo "[TEST] Bot PID: $BOT_PID"
echo "[TEST] Aguardando início da execução..."
sleep 2

# Poll Cockpit a cada 1s enquanto bot está rodando
echo "[TEST] Iniciando polling em tempo real..."
for i in {1..120}; do
    if ! ps -p $BOT_PID > /dev/null 2>&1; then
        echo "[TEST] Bot finalizado"
        break
    fi

    if [ -f "$HIST_FILE" ]; then
        COUNT=$(cat "$HIST_FILE" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "0")
        LAST=$(cat "$HIST_FILE" | python -c "import sys,json; d=json.load(sys.stdin); s=d[-1] if d else {}; print(f\"{s.get('index','?')} - {s.get('status','?')} - {s.get('desc','?')[:40]}\") " 2>/dev/null || echo "N/A")
        echo "[POLL $i] Steps: $COUNT | Last: $LAST"
    else
        echo "[POLL $i] historico_passos.json não existe ainda"
    fi

    sleep 1
done

wait $BOT_PID

echo ""
echo "[FINAL] Resultado final:"
if [ -f "$HIST_FILE" ]; then
    cat "$HIST_FILE" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Total: {len(d)} passos'); print(f'Row IDs: {set(x.get(\"row_id\") for x in d)}')"
fi
