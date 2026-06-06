#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "启动后端..."
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/backend' && uv run uvicorn app.main:app --host 0.0.0.0 --port 8010\""

sleep 1

echo "启动前端..."
osascript -e "tell app \"Terminal\" to do script \"cd '$ROOT/frontend' && npm run dev\""

sleep 3
echo "已启动，正在打开浏览器..."
open http://localhost:5173
