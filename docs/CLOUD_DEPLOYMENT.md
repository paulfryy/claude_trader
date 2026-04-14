# Cloud Deployment Guide — AWS EC2

Deploy the trading agent to AWS so it runs 24/7 without your computer.

**Cost: ~$3/month** (t4g.nano) or **$0/month** (t3.micro with free tier)

---

## Prerequisites

- An AWS account (create at https://aws.amazon.com)
- Your code pushed to a GitHub repo (private is fine)
- Your `.env.live` and `.env.paper` files ready locally

---

## Step 1: Create an AWS Account

1. Go to https://aws.amazon.com and click "Create an AWS Account"
2. Enter your email, create a password
3. Add a payment method (credit card — you won't be charged if using free tier)
4. Choose the "Basic (Free)" support plan
5. Sign in to the AWS Console

---

## Step 2: Launch an EC2 Instance

1. In the AWS Console, search for "EC2" in the top search bar and click it
2. Click the orange **"Launch Instance"** button

### Configure the instance:

**Name:** `trading-agent`

**Application and OS Images (AMI):**
- Click "Amazon Linux" (should be the default)
- Select **Amazon Linux 2023 AMI**
- Architecture: **64-bit (Arm)** — this is cheaper (Graviton processor)
- If you want free tier: select **64-bit (x86)** instead

**Instance type:**
- For cheapest: `t4g.nano` ($3.07/month) — ARM, 2 vCPU, 512MB RAM
- For free tier: `t3.micro` ($0 for 12 months) — x86, 2 vCPU, 1GB RAM

**Key pair (login):**
- Click **"Create new key pair"**
- Name: `trading-agent-key`
- Type: RSA
- Format: `.pem`
- Click "Create" — a file downloads. **SAVE THIS FILE. You cannot download it again.**

**Network settings:**
- Click "Edit"
- Allow SSH traffic: **"My IP"** (not "Anywhere" — security risk)

**Storage:**
- 8 GB gp3 (default is fine)

3. Click **"Launch Instance"**
4. Wait ~1 minute for it to start
5. Click on the instance ID to see its details
6. Copy the **Public IPv4 address** (e.g., `3.14.159.26`)

---

## Step 3: Connect to Your Server

### On Windows (PowerShell):

```powershell
# Navigate to where you saved the .pem key file
cd Downloads

# Connect (replace IP with yours)
ssh -i trading-agent-key.pem ec2-user@3.14.159.26
```

If you get a "permissions are too open" error:
```powershell
icacls trading-agent-key.pem /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

Then try the ssh command again.

**You should see:** `[ec2-user@ip-xxx ~]$` — you're on the server.

---

## Step 4: Set Up the Server

Run these commands on the server (copy-paste each line):

```bash
# Update the system
sudo dnf update -y

# Install Python 3.11 and git
sudo dnf install -y python3.11 python3.11-pip git

# Set timezone to Eastern (market time)
sudo timedatectl set-timezone America/New_York

# Verify
python3.11 --version    # Should show 3.11.x
date                     # Should show Eastern time
```

---

## Step 5: Deploy the Code

### Option A: From GitHub (recommended)

```bash
# Clone your repo (replace with your repo URL)
# For private repos, you'll need a GitHub personal access token
git clone https://github.com/YOUR_USERNAME/claude_agent.git /home/ec2-user/claude_agent
cd /home/ec2-user/claude_agent

# Install dependencies
python3.11 -m pip install --user -e .
```

### Option B: Upload directly (if repo isn't on GitHub)

From your Windows machine in a NEW PowerShell window:
```powershell
# Zip the project (excluding venv and logs)
# Then upload:
scp -i Downloads/trading-agent-key.pem claude_agent.zip ec2-user@3.14.159.26:/home/ec2-user/
```

Then on the server:
```bash
unzip claude_agent.zip -d /home/ec2-user/claude_agent
cd /home/ec2-user/claude_agent
python3.11 -m pip install --user -e .
```

---

## Step 6: Upload Your Secret Files

From your Windows machine (PowerShell), in the project directory:

```powershell
# Upload .env.paper
scp -i Downloads/trading-agent-key.pem .env.paper ec2-user@3.14.159.26:/home/ec2-user/claude_agent/

# Upload .env.live
scp -i Downloads/trading-agent-key.pem .env.live ec2-user@3.14.159.26:/home/ec2-user/claude_agent/

# Lock permissions (on the server)
ssh -i Downloads/trading-agent-key.pem ec2-user@3.14.159.26 "chmod 600 /home/ec2-user/claude_agent/.env.*"
```

---

## Step 7: Test It Works

On the server:

```bash
cd /home/ec2-user/claude_agent

# Test paper mode
python3.11 -m src.agent.orchestrator --env .env.paper --dry-run

# Test live mode (set the bypass so it doesn't wait for input)
SKIP_LIVE_CONFIRM=true python3.11 -m src.agent.orchestrator --env .env.live --dry-run
```

Both should complete without errors.

---

## Step 8: Create Auto-Start Services

These make the agent start automatically on boot and restart if it crashes.

### Create the paper trading service:

```bash
sudo tee /etc/systemd/system/trading-agent-paper.service << 'EOF'
[Unit]
Description=Claude Trading Agent (Paper)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/claude_agent
Environment=TZ=America/New_York
Environment=SKIP_LIVE_CONFIRM=true
ExecStart=/home/ec2-user/.local/bin/python3.11 -m src.agent.scheduler --env .env.paper
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
```

### Create the live trading service:

```bash
sudo tee /etc/systemd/system/trading-agent-live.service << 'EOF'
[Unit]
Description=Claude Trading Agent (Live)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/claude_agent
Environment=TZ=America/New_York
Environment=SKIP_LIVE_CONFIRM=true
ExecStart=/home/ec2-user/.local/bin/python3.11 -m src.agent.scheduler --env .env.live
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
```

### Enable and start both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-agent-paper trading-agent-live
sudo systemctl start trading-agent-paper
sudo systemctl start trading-agent-live
```

---

## Step 9: Verify Everything is Running

```bash
# Check status
sudo systemctl status trading-agent-paper
sudo systemctl status trading-agent-live

# Should show "active (running)" for both

# Watch live logs
sudo journalctl -u trading-agent-live -f

# Watch paper logs
sudo journalctl -u trading-agent-paper -f

# Check summary files
ls -la /home/ec2-user/claude_agent/logs/live/summaries/
ls -la /home/ec2-user/claude_agent/logs/paper/summaries/

# Read today's live summary
cat /home/ec2-user/claude_agent/logs/live/summaries/$(date +%Y-%m-%d).md
```

---

## Daily Operations

### Check how things are going (from Windows):

```powershell
# SSH in
ssh -i Downloads/trading-agent-key.pem ec2-user@3.14.159.26

# Read today's live summary
cat /home/ec2-user/claude_agent/logs/live/summaries/$(date +%Y-%m-%d).md

# Read today's paper summary
cat /home/ec2-user/claude_agent/logs/paper/summaries/$(date +%Y-%m-%d).md

# Check if services are running
sudo systemctl status trading-agent-live
```

### Deploy code updates:

```bash
ssh -i Downloads/trading-agent-key.pem ec2-user@3.14.159.26
cd /home/ec2-user/claude_agent
git pull
sudo systemctl restart trading-agent-paper trading-agent-live
```

### Restart after a crash:

```bash
sudo systemctl restart trading-agent-live
# or
sudo systemctl restart trading-agent-paper
```

### Stop trading:

```bash
# Stop live only
sudo systemctl stop trading-agent-live

# Stop both
sudo systemctl stop trading-agent-paper trading-agent-live
```

---

## Enable Dashboard Controls (sudoers)

The dashboard has a Controls page that can restart/start/stop the trading services.
For the buttons to work, `ec2-user` needs passwordless sudo access to `systemctl`
for ONLY the trading services (not general sudo — this is safe).

Run this on the server:

```bash
sudo tee /etc/sudoers.d/trading-agent-controls << 'EOF'
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl restart trading-agent-paper
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl restart trading-agent-live
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl restart trading-dashboard
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl start trading-agent-paper
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl start trading-agent-live
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl stop trading-agent-paper
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl stop trading-agent-live
EOF

sudo chmod 440 /etc/sudoers.d/trading-agent-controls
sudo visudo -c  # Validates the file
```

Test it:
```bash
sudo systemctl restart trading-agent-paper
```
If it doesn't prompt for a password, it's working.

---

## Recommended: Log Backup to S3

Protects your logs, summaries, reports, and trade history from disk failures
or instance termination. Costs roughly $0.02/month for the data volumes we generate.

### Step 1: Create an S3 Bucket

1. In the AWS Console, go to **S3** → **Create bucket**
2. Bucket name: `trading-agent-logs-<your-unique-suffix>` (S3 bucket names must be globally unique)
3. Region: same as your EC2 instance (us-east-1)
4. Keep **Block all public access** enabled
5. Enable **Versioning** (lets you recover deleted files)
6. Click **Create bucket**

### Step 2: Create an IAM Role for the EC2 Instance

1. Go to **IAM** → **Roles** → **Create role**
2. Trusted entity: **AWS service** → **EC2**
3. Click **Next**
4. Don't attach any policies yet, click **Next**
5. Role name: `trading-agent-s3-sync`
6. Click **Create role**
7. Open the new role, click **Add permissions** → **Create inline policy**
8. Switch to JSON tab and paste (replace `YOUR-BUCKET-NAME`):

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::YOUR-BUCKET-NAME",
                "arn:aws:s3:::YOUR-BUCKET-NAME/*"
            ]
        }
    ]
}
```

9. Review, name it `trading-agent-s3-sync-policy`, click **Create policy**

### Step 3: Attach the Role to Your EC2 Instance

1. Go to **EC2** → **Instances** → click your instance
2. **Actions** → **Security** → **Modify IAM role**
3. Select `trading-agent-s3-sync`
4. Click **Update IAM role**

### Step 4: Install AWS CLI on EC2 (if not already installed)

```bash
which aws || sudo dnf install -y awscli
aws --version
```

### Step 5: Test the Sync

```bash
export BUCKET=trading-agent-logs-your-unique-suffix
aws s3 sync /home/ec2-user/claude_agent/logs/ s3://$BUCKET/logs/ --quiet
aws s3 ls s3://$BUCKET/logs/
```

You should see your log directories listed.

### Step 6: Schedule Daily Syncs

Open the user's cron:

```bash
crontab -e
```

Add these lines (replace `YOUR-BUCKET-NAME`):

```cron
# Sync logs to S3 every day at 5 PM ET (after close)
0 17 * * 1-5 /usr/bin/aws s3 sync /home/ec2-user/claude_agent/logs/ s3://YOUR-BUCKET-NAME/logs/ --quiet >> /home/ec2-user/claude_agent/logs/s3-sync.log 2>&1

# Weekly full sync on Saturdays (catches anything missed)
0 2 * * 6 /usr/bin/aws s3 sync /home/ec2-user/claude_agent/logs/ s3://YOUR-BUCKET-NAME/logs/ >> /home/ec2-user/claude_agent/logs/s3-sync.log 2>&1
```

Save and exit. Verify:

```bash
crontab -l
```

### Step 7: Restoring from Backup

If your instance dies or logs are lost:

```bash
aws s3 sync s3://YOUR-BUCKET-NAME/logs/ /home/ec2-user/claude_agent/logs/
```

---

## Legacy: Log Backup to S3 (old instructions)

Back up logs daily so you don't lose them if the server dies:

```bash
# Create an S3 bucket (do this once, in AWS Console):
# Go to S3 > Create Bucket > Name: trading-agent-logs-<yourname>

# On the server, set up a daily sync:
crontab -e
# Add this line:
0 17 * * 1-5 aws s3 sync /home/ec2-user/claude_agent/logs/ s3://trading-agent-logs-yourname/logs/ --quiet
```

---

## Troubleshooting

**"Permission denied (publickey)"** when SSH-ing:
- Make sure you're using the right `.pem` file
- Make sure the file permissions are restricted (see Step 3)

**Service won't start:**
```bash
sudo journalctl -u trading-agent-live -n 50
# Shows the last 50 lines of logs — look for errors
```

**Python packages missing:**
```bash
cd /home/ec2-user/claude_agent
python3.11 -m pip install --user -e .
```

**Server IP changed after reboot:**
- EC2 instances get a new public IP on reboot by default
- Fix: in EC2 Console, go to "Elastic IPs", allocate one, and associate it with your instance (free while the instance is running)

---

## Dashboard Service

In addition to the two trading agents, a Flask-based read-only dashboard runs
on port 8080 for monitoring and controls.

### Create the dashboard service

```bash
sudo tee /etc/systemd/system/trading-dashboard.service << 'EOF'
[Unit]
Description=Claude Trading Agent Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/claude_agent
Environment=TZ=America/New_York
Environment=DASHBOARD_PORT=8080
Environment=DASHBOARD_HOST=0.0.0.0
ExecStart=/usr/bin/python3.11 -m src.dashboard.app
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable trading-dashboard
sudo systemctl start trading-dashboard
```

### Open port 8080 to your IP

1. Go to **EC2 → Security Groups** in the AWS Console
2. Click your instance's security group
3. **Inbound rules → Edit → Add rule**
4. Type: Custom TCP, Port: 8080, Source: **My IP**, Description: Dashboard
5. Save

Visit `http://YOUR-EC2-IP:8080` from your browser.

---

## Dashboard Controls Sudoers

For the Controls page to restart services and pull code, `ec2-user` needs
passwordless sudo on only these specific commands (NOT general sudo):

```bash
sudo tee /etc/sudoers.d/trading-agent-controls << 'EOF'
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl restart trading-agent-paper
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl restart trading-agent-live
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl restart trading-dashboard
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl start trading-agent-paper
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl start trading-agent-live
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl stop trading-agent-paper
ec2-user ALL=(root) NOPASSWD: /usr/bin/systemctl stop trading-agent-live
EOF

sudo chmod 440 /etc/sudoers.d/trading-agent-controls
sudo visudo -c
```

Test (should NOT prompt for password):
```bash
sudo systemctl restart trading-agent-paper
```

---

## Daily Operations

Once everything is set up, day-to-day operation is mostly dashboard-driven.

### Normal workflow after a code push
1. On your local machine: commit and `git push` to GitHub
2. In your browser: open the dashboard Controls page
3. Click **Git Pull** (updates files on disk)
4. Click **Restart** on each affected service:
   - `trading-agent-live` (if agent code changed)
   - `trading-agent-paper` (if agent code changed)
   - `trading-dashboard` (if dashboard code changed — deferred 2s restart)

### Check on the agent remotely

```bash
ssh -i C:\Users\fourf\.ssh\trading-agent-key.pem ec2-user@YOUR-IP
```

Common commands on the server:
```bash
# Read today's live EOD report
cat ~/claude_agent/logs/live/reports/$(date +%Y-%m-%d).md

# Read today's paper EOD report
cat ~/claude_agent/logs/paper/reports/$(date +%Y-%m-%d).md

# Stream live logs
sudo journalctl -u trading-agent-live -f

# Check if services are running
sudo systemctl status trading-agent-live --no-pager
sudo systemctl status trading-agent-paper --no-pager
sudo systemctl status trading-dashboard --no-pager

# Recent anomalies
cat ~/claude_agent/logs/live/anomalies.jsonl | tail -20
```

### Deploy new env file settings

```powershell
# From Windows PowerShell, in the project dir
scp -i C:\Users\fourf\.ssh\trading-agent-key.pem .env.live ec2-user@YOUR-IP:/home/ec2-user/claude_agent/
scp -i C:\Users\fourf\.ssh\trading-agent-key.pem .env.paper ec2-user@YOUR-IP:/home/ec2-user/claude_agent/
```

Then on the server:
```bash
chmod 600 ~/claude_agent/.env.live ~/claude_agent/.env.paper
sudo systemctl restart trading-agent-live trading-agent-paper
```

### Emergency stop

```bash
sudo systemctl stop trading-agent-live
```

To also close all open positions (via the Alpaca web dashboard is easiest, but from the server):
```bash
python3.11 -c "
from dotenv import load_dotenv
load_dotenv('.env.live', override=True)
from alpaca.trading.client import TradingClient
from src.config import load_settings
s = load_settings(env_file='.env.live')
c = TradingClient(api_key=s.alpaca.api_key, secret_key=s.alpaca.secret_key, paper=False)
c.cancel_orders()
c.close_all_positions(cancel_orders=True)
print('All positions closed')
"
```

---

## Cost Summary

| Item | Monthly Cost |
|---|---|
| EC2 t4g.nano (or t3.micro free tier) | $3.07 (or $0) |
| EBS storage (8GB) | $0.64 |
| S3 log backup (optional) | ~$0.02 |
| Data transfer | ~$0 (minimal) |
| Anthropic API (~3 cycles/day × 22 days) | ~$2-3 |
| Finnhub earnings calendar (free tier) | $0 |
| **Total** | **~$6-7/month** |

With AWS free tier: **~$3/month** in year 1 (just API costs).
