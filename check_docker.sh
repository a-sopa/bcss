#!/bin/bash
# Quick diagnostics script — run this to see what's happening
echo "=== DOCKER STATUS ==="
sudo docker compose ps 2>/dev/null || docker compose ps 2>/dev/null
echo ""
echo "=== LOGS (last 30 lines each) ==="
echo "--- cache-service ---"
sudo docker compose logs --tail=30 cache-service 2>/dev/null || docker compose logs --tail=30 cache-service 2>/dev/null
echo ""
echo "--- cloud-honeypot ---"
sudo docker compose logs --tail=30 cloud-honeypot 2>/dev/null || docker compose logs --tail=30 cloud-honeypot 2>/dev/null
echo ""
echo "--- redis ---"
sudo docker compose logs --tail=10 redis 2>/dev/null || docker compose logs --tail=10 redis 2>/dev/null
echo ""
echo "=== PORTS LISTENING ==="
ss -tlnp | grep -E '8001|8888|6379|2222|8080|2323' || netstat -tlnp 2>/dev/null | grep -E '8001|8888|6379|2222|8080|2323'
echo ""
echo "=== QUICK HEALTH CHECKS ==="
curl -s -o /dev/null -w "CacheManager (8001): %{http_code}\n" http://localhost:8001/health 2>/dev/null || echo "CacheManager (8001): NOT RESPONDING"
curl -s -o /dev/null -w "Honeypot Dashboard (8888): %{http_code}\n" http://localhost:8888 2>/dev/null || echo "Honeypot (8888): NOT RESPONDING"
