#!/bin/bash
# ============================================================
# AI Agent Marketplace — EC2 Setup Script
# ============================================================
# Use this as EC2 User Data or run manually after SSH.
#
# Prerequisites: Amazon Linux 2023 or Ubuntu 22.04 AMI
# Instance type: t3.medium+ (needs RAM for Ollama models)
# Storage: 30GB+ (for models)
# Security Group: Allow port 80, 443
# ============================================================

set -e

echo "=========================================="
echo "  Setting up AI Agent Marketplace"
echo "=========================================="

# ── System updates ─────────────────────────────────────────
sudo yum update -y 2>/dev/null || sudo apt-get update -y
sudo yum install -y python3.11 python3.11-pip git nginx redis6 2>/dev/null || \
sudo apt-get install -y python3.11 python3-pip git nginx redis-server

# ── Start Redis ────────────────────────────────────────────
sudo systemctl enable redis6 2>/dev/null || sudo systemctl enable redis-server
sudo systemctl start redis6 2>/dev/null || sudo systemctl start redis-server
echo "[✓] Redis started"

# ── Install Ollama ─────────────────────────────────────────
curl -fsSL https://ollama.ai/install.sh | sh
sudo systemctl enable ollama
sudo systemctl start ollama

# Wait for Ollama
sleep 5
ollama pull qwen2.5:7b
echo "[✓] Ollama installed & model pulled"

# ── App Setup ──────────────────────────────────────────────
cd /home/ec2-user
git clone https://github.com/YOUR_REPO/Agent_Marketplace.git app
cd app

# Install Python dependencies
pip3.11 install flask flask-sqlalchemy flask-jwt-extended flask-cors \
    python-a2a requests gunicorn redis

# Copy env file
cp deployment/.env.example .env
echo "[!] IMPORTANT: Edit .env with your production values"

# ── Systemd Services ──────────────────────────────────────

# Marketplace API
sudo tee /etc/systemd/system/marketplace.service > /dev/null <<EOF
[Unit]
Description=AI Agent Marketplace
After=network.target redis.service ollama.service

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/app
EnvironmentFile=/home/ec2-user/app/.env
ExecStart=/usr/bin/gunicorn -c deployment/gunicorn.conf.py marketplace.app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Agent services (one per agent)
for agent in researcher documentation citation; do
    port=$((5000 + $(echo "$agent" | md5sum | tr -d '[a-f]' | cut -c1-4) % 10 + 1))
    sudo tee /etc/systemd/system/agent-${agent}.service > /dev/null <<EOF
[Unit]
Description=A2A ${agent} Agent
After=ollama.service

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/app
EnvironmentFile=/home/ec2-user/app/.env
ExecStart=/usr/bin/python3.11 a2a_${agent}_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
done

sudo systemctl daemon-reload
sudo systemctl enable marketplace agent-researcher agent-documentation agent-citation
sudo systemctl start marketplace agent-researcher agent-documentation agent-citation

echo "[✓] All services started"

# ── Nginx Reverse Proxy ───────────────────────────────────
sudo tee /etc/nginx/conf.d/marketplace.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none';" always;

    # Rate limiting zones
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
    limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;

    # Block access to sensitive files
    location ~ \.(py|pyc|db|env|json|csv|log|conf|sh)$ {
        return 404;
    }

    location ~ /\. {
        return 404;
    }

    # Static files (cached)
    location /static/ {
        proxy_pass http://127.0.0.1:8080;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Auth endpoints (strict rate limit)
    location /api/auth/ {
        limit_req zone=auth burst=3 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Request size limit
        client_max_body_size 16k;
    }

    # API endpoints
    location /api/ {
        limit_req zone=api burst=10 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;  # LLM timeout

        # Request size limit
        client_max_body_size 32k;
    }

    # Frontend SPA
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

sudo nginx -t && sudo systemctl restart nginx
echo "[✓] Nginx configured"

echo ""
echo "=========================================="
echo "  ✓ Setup Complete!"
echo "  → Edit /home/ec2-user/app/.env"
echo "  → Then: sudo systemctl restart marketplace"
echo "  → Open: http://YOUR_EC2_IP"
echo "=========================================="
