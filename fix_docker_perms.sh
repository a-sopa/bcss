#!/bin/bash
# Fix Docker permissions and start all services
# Run with: bash fix_docker_perms.sh

echo "=== HACKATHON DOCKER SETUP ==="
echo ""

# 1. Add user to docker group (permanent fix)
echo "[1/4] A adicionar utilizador ao grupo docker..."
sudo usermod -aG docker "$USER"
echo "    -> Feito (reinicia a sessão ou usa 'newgrp docker' para aplicar)"
echo ""

# 2. Fix docker socket permissions for this session
echo "[2/4] A corrigir permissões do socket para esta sessão..."
sudo chmod 666 /var/run/docker.sock
echo "    -> Feito (válido até reiniciar)"
echo ""

# 3. Test docker works without sudo
echo "[3/4] A testar Docker sem sudo..."
docker info > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "    -> Docker OK sem sudo!"
else
    echo "    -> Ainda precisa de sudo. A usar sudo nos comandos..."
    SUDO_PREFIX="sudo"
fi
echo ""

# 4. Start services
echo "[4/4] A iniciar serviços..."
cd "$(dirname "$0")"
${SUDO_PREFIX} docker compose up -d --build
echo ""
echo "=== SERVIÇOS ATIVOS ==="
${SUDO_PREFIX} docker compose ps
echo ""
echo "URLs:"
echo "  CacheManager API:   http://localhost:8001/docs"
echo "  Honeypot Dashboard: http://localhost:8888"
echo "  Redis:              localhost:6379"
echo ""
echo "Para ver logs: docker compose logs -f"
echo "Para parar:    docker compose down"
