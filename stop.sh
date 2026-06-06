#!/bin/bash
echo "关闭后端 (8010)..."
kill $(lsof -ti:8010) 2>/dev/null && echo "已关闭" || echo "未在运行"

echo "关闭前端 (5173)..."
kill $(lsof -ti:5173) 2>/dev/null && echo "已关闭" || echo "未在运行"
