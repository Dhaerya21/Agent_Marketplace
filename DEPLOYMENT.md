# AWS Learner Lab Deployment Guide (Hardened Edition)

*Optimized for a 4-5 day evaluation window with $50 budget ceilings.*

This guide walks you through deploying the hardened AI Agent Marketplace using the automated `ec2_setup.sh` script.

---

## 🛑 Prerequisite: Dynamic DNS Setup

Since AWS Academy revokes your IP address every 4 hours when the session dies, we will use **DuckDNS** so your SSL certificates and domain names stay valid automatically.

1. Go to [duckdns.org](https://www.duckdns.org/) and log in (via GitHub or Google).
2. Create a free subdomain (e.g., `my-agent-market.duckdns.org`).
3. Copy your **Token** from the top of the DuckDNS page. Keep this handy.

---

## 🛡️ Step 1: AWS Security Group (Firewall) Configuration

In your AWS Academy Console:

1. Navigate to the **EC2 Dashboard**.
2. Click **Security Groups** on the left menu, then **Create security group**.
3. Name it `Marketplace-Firewall`.
4. Add these **Inbound Rules**:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| **22** | SSH | **My IP** | Remote terminal access. *Only your current IP.* |
| **80** | HTTP | 0.0.0.0/0 | Public web traffic (Load Balancer / Nginx). |
| **443** | HTTPS| 0.0.0.0/0 | Encrypted web traffic. |

*Note: Port 8080 or 5000+ are NOT open. They are completely locked down behind Nginx.*

---

## 🚀 Step 2: The 1-Click EC2 Deployment

1. Go to **Instances** → **Launch Instance**.
2. **Name**: `Agent-Marketplace-Production`
3. **OS Images (AMI)**: Select **Amazon Linux 2023** (or Ubuntu 22.04 LTS).
4. **Instance Type**: Select **`t3.large`** or **`t3.xlarge`** (You need minimum 8GB RAM to run the Qwen2.5 7B model locally).
5. **Key Pair**: Create a new key pair (e.g., `market-key.pem`) and download it securely.
6. **Network Settings**: Choose the `Marketplace-Firewall` Security Group you made in Step 1.
7. **Configure Storage**: Set it to **40 GB** and change the type to **gp3**.
8. **Advanced Details**: Scroll all the way down to **User Data**. 
   - Open your `deployment/ec2_setup.sh` file from VS Code. 
   - **Copy all the text** in that script and paste it into the User Data box.
9. Click **Launch Instance**!

> **What happens now?** AWS will boot the server. Over the next 5-10 minutes, the User Data script will automatically install Nginx, Ollama, Fail2Ban, Redis, PostgreSQL (generating secure random passwords!), and clone your repository.

---

## 🔐 Step 3: Pushing Your DuckDNS Variables

Once the Instance is marked as `Running` in AWS, it needs your DuckDNS token so it can automate its own IP addressing.

1. Find the **Public IPv4 address** of your new EC2 instance in the AWS Console.
2. Open Git Bash, PowerShell, or macOS Terminal and SSH into the box:
   ```bash
   ssh -i /path/to/market-key.pem ec2-user@<YOUR-EC2-PUBLIC-IP>
   ```
3. Edit the automatically deployed `.env` file:
   ```bash
   nano ~/app/.env
   ```
4. Find the DuckDNS variables at the bottom and fill them in:
   ```env
   DUCKDNS_DOMAIN=my-agent-market
   DUCKDNS_TOKEN=your-token-from-duckdns-website
   ```
5. Save and exit (Press `Ctrl+O`, `Enter`, then `Ctrl+X`).
6. Because your IP just changed or boot just finished, manually fire the updater script once:
   ```bash
   /tmp/duckdns.sh
   ```

*From now on, even if AWS shuts off your machine and changes your IP address, the server will ping DuckDNS every 5 minutes and fix its own IP automatically!*

---

## 🌐 Step 4: HTTPS (SSL Certificate Setup)

To ensure the evaluator sees a secure lock icon (and to protect JWT passwords), secure your DuckDNS domain with free Let's Encrypt SSL:

```bash
# While still SSH'd into the machine
sudo snap install core; sudo snap refresh core
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot

# Auto-configure Nginx SSL (Replace with your DuckDNS domain)
sudo certbot --nginx -d my-agent-market.duckdns.org
```

When Certbot asks if you want to redirect HTTP traffic to HTTPS, say **Yes** (option 2).

---

## 🎉 Step 5: Verification

1. In your browser, navigate to your domain: `https://my-agent-market.duckdns.org`
2. You should instantly see the AI Agent Marketplace.
3. Test your tools/agents! The Ollama `qwen2.5` model was automatically pulled during setup.

### What Happens when the 4-Hour AWS Academy Timer Hits?
When AWS aggressively stops your instance:
1. All your database variables, user accounts, and AI models are safely permanently stored on the 40GB `gp3` drive. 
2. Next morning, go to AWS and click **Start Instance**.
3. AWS will give you a new Public IP.
4. Wait 2 minutes for the EC2 to fully boot. The `crontab` we injected will automatically fire, notice the new IP, and tell DuckDNS.
5. `my-agent-market.duckdns.org` will seamlessly route to the new IP address. You don't have to touch a single terminal window.
