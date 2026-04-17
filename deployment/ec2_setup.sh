#!/bin/bash
# ============================================================
# AI Agent Marketplace — Hardened EC2 Setup Script
# ============================================================
# Prerequisites: Amazon Linux 2023 or Ubuntu 22.04 AMI
# Instance type: t3.large+ (needs RAM for Ollama 7B model)
# Storage: 40GB gp3
# ============================================================
set -e

echo "Starting Hardened Setup for AI Agent Marketplace..."

# 1. Detect OS
if grep -q "Amazon Linux" /etc/system-release 2>/dev/null; then
    OS="AMZN"
else
    OS="UBUNTU"
fi

# 2. System updates & Dependencies
if [ "$OS" == "AMZN" ]; then
    sudo yum update -y
    sudo yum install -y python3.11 python3.11-pip git nginx redis6 postgresql15-server fail2ban cronie logrotate
    redis_service="redis6"
else
    sudo apt-get update -y
    sudo apt-get install -y python3.11 python3-pip git nginx redis-server postgresql postgresql-contrib fail2ban cron logrotate
    redis_service="redis-server"
fi

# 3. Fail2Ban Setup (Protect Port 22 SSH)
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
echo "[✓] Fail2Ban installed and enforcing SSH limits."

# 4. Redis Lockdown
# Generate random redis password
REDIS_PASS=$(openssl rand -hex 16)
if [ "$OS" == "AMZN" ]; then
    REDIS_CONF_FILE="/etc/redis6/redis6.conf"
else
    REDIS_CONF_FILE="/etc/redis/redis.conf"
fi
# Replace bind and strict requirement
sudo sed -i 's/^#* *bind .*$/bind 127.0.0.1/' $REDIS_CONF_FILE
sudo grep -q "^requirepass " $REDIS_CONF_FILE && sudo sed -i "s/^requirepass .*$/requirepass $REDIS_PASS/" $REDIS_CONF_FILE || echo "requirepass $REDIS_PASS" | sudo tee -a $REDIS_CONF_FILE

sudo systemctl enable $redis_service
sudo systemctl restart $redis_service
echo "[✓] Redis locked down locally with auth."

# 5. PostgreSQL Local Database
DB_PASS=$(openssl rand -hex 16)
if [ "$OS" == "AMZN" ]; then
    sudo postgresql-setup --initdb || true
    sudo systemctl enable postgresql
    sudo systemctl start postgresql
    sudo -u postgres psql -c "CREATE DATABASE marketplacedb;" || true
    sudo -u postgres psql -c "CREATE USER marketplace_user WITH PASSWORD '$DB_PASS';" || true
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE marketplacedb TO marketplace_user;" || true
    sudo -u postgres psql -c "ALTER DATABASE marketplacedb OWNER TO marketplace_user;" || true
    sudo sed -i "s/ident/md5/g" /var/lib/pgsql/data/pg_hba.conf
    sudo systemctl restart postgresql
else
    sudo systemctl enable postgresql
    sudo systemctl start postgresql
    sudo -u postgres psql -c "CREATE DATABASE marketplacedb;" || true
    sudo -u postgres psql -c "CREATE USER marketplace_user WITH PASSWORD '$DB_PASS';" || true
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE marketplacedb TO marketplace_user;" || true
    sudo -u postgres psql -c "ALTER DATABASE marketplacedb OWNER TO marketplace_user;" || true
fi
echo "[✓] PostgreSQL installed and db provisioned."

# 6. Ollama
curl -fsSL https://ollama.ai/install.sh | sh
sudo systemctl enable ollama
sudo systemctl start ollama
sleep 5
echo "Pulling Qwen2.5:7b... this may take a few minutes."
ollama pull qwen2.5:7b
echo "[✓] Ollama model ready."

# 7. Clone App & Application Permissions
USER_HOME=$(eval echo ~$USER)
cd $USER_HOME
if [ ! -d "app" ]; then
    git clone https://github.com/YOUR_REPO/Agent_Marketplace.git app
fi
cd app

# Ensure only app user can read secrets
chmod 700 $USER_HOME/app

pip3.11 install flask flask-sqlalchemy flask-jwt-extended flask-cors python-a2a requests gunicorn redis psycopg2-binary

# Secure .env generation
JWT_SEC=$(openssl rand -hex 32)
MK_KEY=$(openssl rand -hex 32)

cat <<EOF > $USER_HOME/app/.env
FLASK_ENV=production
JWT_SECRET=$JWT_SEC
MARKETPLACE_MASTER_KEY=$MK_KEY
DATABASE_URL=postgresql://marketplace_user:$DB_PASS@localhost/marketplacedb
REDIS_URL=redis://:$REDIS_PASS@localhost:6379/0

# Optional DuckDNS Support
DUCKDNS_DOMAIN=
DUCKDNS_TOKEN=
EOF
chmod 600 $USER_HOME/app/.env

# 8. DuckDNS Cron Job (Dynamic IP Updater)
cat <<EOF > /tmp/duckdns.sh
#!/bin/bash
source '$USER_HOME/app/.env'
if [ -n "\$DUCKDNS_DOMAIN" ] && [ -n "\$DUCKDNS_TOKEN" ]; then
    echo url="https://www.duckdns.org/update?domains=\${DUCKDNS_DOMAIN}&token=\${DUCKDNS_TOKEN}&ip=" | curl -k -o /tmp/duckdns.log -K -
fi
EOF
chmod 700 /tmp/duckdns.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * /tmp/duckdns.sh") | crontab -
echo "[✓] App cloned, Python requirements installed, and DuckDNS cron scheduled."

# 9. Systemd Services
sudo tee /etc/systemd/system/marketplace.service > /dev/null <<EOF
[Unit]
Description=AI Agent Marketplace
After=network.target redis.service postgresql.service ollama.service

[Service]
User=$USER
WorkingDirectory=$USER_HOME/app
EnvironmentFile=$USER_HOME/app/.env
ExecStart=/usr/local/bin/gunicorn -c deployment/gunicorn.conf.py marketplace.app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

for agent in researcher documentation citation; do
    port=$((5000 + \$(echo "\$agent" | md5sum | tr -d '[a-f]' | cut -c1-4) % 10 + 1))
    sudo tee /etc/systemd/system/agent-\${agent}.service > /dev/null <<EOF
[Unit]
Description=A2A \${agent} Agent
After=ollama.service

[Service]
User=$USER
WorkingDirectory=$USER_HOME/app
EnvironmentFile=$USER_HOME/app/.env
ExecStart=/usr/bin/python3.11 a2a_\${agent}_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
done

sudo systemctl daemon-reload
sudo systemctl enable marketplace agent-researcher agent-documentation agent-citation
sudo systemctl start marketplace agent-researcher agent-documentation agent-citation
echo "[✓] App Services Started."

# 10. Logrotate Setup
sudo mkdir -p $USER_HOME/app/logs
sudo tee /etc/logrotate.d/marketplace > /dev/null <<EOF
$USER_HOME/app/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 $USER $USER
    sharedscripts
    postrotate
        systemctl reload marketplace agent-researcher agent-documentation agent-citation > /dev/null 2>/dev/null || true
    endscript
}
EOF
echo "[✓] Logrotate configured."

# 11. Nginx Hardening
sudo tee /etc/nginx/conf.d/marketplace.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none';" always;

    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
    limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;

    location ~ \.(py|pyc|db|env|json|csv|log|conf|sh)$ { return 404; }
    location ~ /\. { return 404; }

    location /static/ {
        proxy_pass http://127.0.0.1:8080;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location /api/auth/ {
        limit_req zone=auth burst=3 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 16k;
    }

    location /api/ {
        limit_req zone=api burst=10 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        
        # Security against massive payloads
        client_max_body_size 10M;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 100k;
    }
}
EOF

sudo nginx -t && sudo systemctl restart nginx
echo "[✓] Nginx Hardened Setup Complete."

echo "================================================="
echo "  ✓ Hardened Infrastructure Deployment Finished!"
echo "  → Auto-generated database passwords and secure keys"
echo "    have been written to $USER_HOME/app/.env."
echo "  → Set DUCKDNS_DOMAIN and DUCKDNS_TOKEN in $USER_HOME/app/.env"
echo "    to optionally enable auto-updating domains."
echo "================================================="
