# PM2 Setup Guide - Run Crypto AI News Bot 24/7 on Linux Server

This guide walks you through deploying the bot on a Linux VPS (Ubuntu/Debian) using PM2 for process management.

---

## 📋 Prerequisites

- Linux VPS (Ubuntu 20.04+ / Debian 11+ recommended)
- Python 3.10+ installed
- Root or sudo access

---

## 🚀 Step-by-Step Deployment

### 1. Connect to Your Server
```bash
ssh user@your-server-ip
```

### 2. Install System Dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl
```

### 3. Install PM2 (via Node.js)
```bash
# Install Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install PM2 globally
sudo npm install -g pm2
```

### 4. Clone/Upload Your Project
```bash
# Option A: Clone from Git
git clone https://github.com/yourusername/crypto-news-bot.git
cd crypto-news-bot

# Option B: Create directory and upload files manually
mkdir -p ~/crypto-news-bot
cd ~/crypto-news-bot
# Upload main.py, requirements.txt, .env.example via SFTP/SCP
```

### 5. Setup Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Configure Environment Variables
```bash
cp .env.example .env
nano .env
```

**Fill in your actual values:**
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789
CRYPTOPANIC_API_KEY=abcdef1234567890abcdef1234567890
OPENROUTER_API_KEY=sk-or-v1-abcdef1234567890abcdef1234567890abcdef12
```

> **Tip:** Get `TELEGRAM_CHAT_ID` by messaging `@userinfobot` on Telegram.

### 7. Test Run Manually First
```bash
source venv/bin/activate
python main.py
```
- Press `Ctrl+C` after confirming it works (you should see "Bot Starting..." and first poll)

### 8. Create PM2 Ecosystem Config
```bash
cat > ecosystem.config.js << 'EOF'
module.exports = {
  apps: [{
    name: 'crypto-news-bot',
    script: 'venv/bin/python',
    args: 'main.py',
    cwd: '/home/user/crypto-news-bot',  // CHANGE THIS TO YOUR ACTUAL PATH
    interpreter: 'none',
    env: {
      NODE_ENV: 'production'
    },
    error_file: '/home/user/crypto-news-bot/logs/err.log',
    out_file: '/home/user/crypto-news-bot/logs/out.log',
    log_file: '/home/user/crypto-news-bot/logs/combined.log',
    time: true,
    max_memory_restart: '500M',
    restart_delay: 10000,
    max_restarts: 10,
    min_uptime: '60s',
    watch: false,
    autorestart: true
  }]
};
EOF
```

> **Important:** Update `cwd` and log paths to match your actual project directory.

### 9. Create Logs Directory
```bash
mkdir -p logs
```

### 10. Start with PM2
```bash
pm2 start ecosystem.config.js
```

### 11. Save PM2 Process List (Auto-restart on Reboot)
```bash
pm2 save
pm2 startup
```

**Run the command PM2 outputs** (it will look like):
```bash
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u user --hp /home/user
```

---

## 📊 PM2 Management Commands

| Command | Description |
|---------|-------------|
| `pm2 status` | Show all processes |
| `pm2 logs crypto-news-bot` | View live logs |
| `pm2 logs crypto-news-bot --lines 100` | View last 100 lines |
| `pm2 restart crypto-news-bot` | Restart bot |
| `pm2 stop crypto-news-bot` | Stop bot |
| `pm2 delete crypto-news-bot` | Remove from PM2 |
| `pm2 monit` | Interactive monitoring dashboard |

---

## 🔧 Troubleshooting

### Bot Not Starting?
```bash
# Check PM2 logs
pm2 logs crypto-news-bot --err

# Common issues:
# 1. Wrong cwd path in ecosystem.config.js
# 2. .env file not in project root
# 3. Python packages not installed in venv
# 4. Permission issues on log files
```

### Test Telegram Connection
```bash
source venv/bin/activate
python -c "
import requests, os
from dotenv import load_dotenv
load_dotenv()
token = os.getenv('TELEGRAM_BOT_TOKEN')
chat = os.getenv('TELEGRAM_CHAT_ID')
r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat, 'text': '🤖 Bot test from server!'})
print(r.json())
"
```

### Update Bot Code
```bash
cd ~/crypto-news-bot
git pull  # or upload new files
source venv/bin/activate
pip install -r requirements.txt  # if requirements changed
pm2 restart crypto-news-bot
```

---

## 🛡️ Security Hardening (Recommended)

### Firewall (UFW)
```bash
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### Fail2Ban (SSH Protection)
```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### Non-Root User
```bash
# Run as dedicated user (not root)
sudo adduser --disabled-password --gecos "" botuser
sudo su - botuser
# Then follow steps 3-11 as botuser
```

---

## 📈 Monitoring & Alerts

### Health Check Script (Optional)
Create `healthcheck.sh`:
```bash
#!/bin/bash
if ! pm2 list | grep -q "crypto-news-bot.*online"; then
    curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
         -d "chat_id=$TELEGRAM_CHAT_ID" \
         -d "text=⚠️ Crypto News Bot is DOWN on $(hostname)!"
fi
```
Add to crontab (`crontab -e`):
```bash
*/5 * * * * /home/user/crypto-news-bot/healthcheck.sh
```

---

## ✅ Quick Verification Checklist

- [ ] `.env` file has all 4 keys correctly
- [ ] `pm2 status` shows `online` status
- [ ] `pm2 logs crypto-news-bot` shows polling activity
- [ ] Test message received in Telegram
- [ ] `pm2 save` and `pm2 startup` completed
- [ ] Server reboot test: `sudo reboot` → verify bot comes back

---

## 💡 Pro Tips

1. **Use a dedicated VPS** - $5-10/mo VPS (DigitalOcean, Linode, Vultr, Hetzner) is plenty
2. **Monitor API limits** - CryptoPanic free tier: 10 calls/min, OpenRouter: check your plan
3. **Rotate logs** - PM2 handles rotation, but check disk space monthly
4. **Backup `.env`** - Store securely, never commit to Git
5. **Use PM2 monitoring** - `pm2 monit` shows CPU/Memory in real-time

---

## 🆘 Need Help?

- PM2 Docs: https://pm2.keymetrics.io/docs/usage/quick-start/
- CryptoPanic API: https://cryptopanic.com/developers/api/
- OpenRouter Models: https://openrouter.ai/models/nvidia/nemotron-3-ultra

**Happy botting! 🚀📈**