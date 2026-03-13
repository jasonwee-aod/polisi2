# Operations Runbook

## Deployment to DigitalOcean Droplet

### 1. Provision Droplet

```bash
# Create Ubuntu 22.04 droplet with at least 2GB RAM
doctl compute droplet create polisi-perpaduan-scraper \
  --region sgp1 \
  --size s-2vcpu-2gb \
  --image ubuntu-22-04-x64
```

### 2. Initial Setup

SSH into droplet:

```bash
ssh root@<droplet_ip>
```

Install dependencies:

```bash
apt update
apt install -y python3.11 python3.11-venv python3.11-dev git curl
```

Create system user:

```bash
useradd -m -s /bin/bash polisi
mkdir -p /opt/polisigpt/logs
mkdir -p /opt/polisigpt/.cache
chown -R polisi:polisi /opt/polisigpt
```

### 3. Deploy Scraper

```bash
sudo -u polisi bash << 'EOF'
cd /opt/polisigpt
git clone <repo_url> perpaduan-scraper
cd perpaduan-scraper
python3.11 -m venv venv
source venv/bin/activate
pip install -e .
EOF
```

### 4. Configure Credentials

Create `/opt/polisigpt/.env`:

```bash
export DO_SPACES_BUCKET="gov-my-spaces"
export DO_SPACES_KEY="<access_key>"
export DO_SPACES_SECRET="<secret_key>"
export DO_SPACES_REGION="sgp1"
export DO_SPACES_ENDPOINT="https://sgp1.digitaloceanspaces.com"
```

Secure it:

```bash
chmod 600 /opt/polisigpt/.env
chown polisi:polisi /opt/polisigpt/.env
```

### 5. Create systemd Service

Create `/etc/systemd/system/polisi-perpaduan-scraper.service`:

```ini
[Unit]
Description=POLISI Perpaduan Scraper
After=network.target
Wants=polisi-perpaduan-scraper.timer

[Service]
Type=oneshot
User=polisi
Group=polisi
WorkingDirectory=/opt/polisigpt/perpaduan-scraper
EnvironmentFile=/opt/polisigpt/.env
ExecStart=/opt/polisigpt/perpaduan-scraper/venv/bin/python -m src.main \
  --site-config configs/perpaduan.yaml \
  --state-db /opt/polisigpt/.cache/scraper_state.sqlite3 \
  --output-dir /opt/polisigpt/data/manifests/perpaduan \
  --log-level INFO
StandardOutput=journal
StandardError=journal
TimeoutStartSec=3600

# Uncomment to enable:
# ExecStartPost=/opt/polisigpt/perpaduan-scraper/venv/bin/python -m polisi.indexer
```

### 6. Create Timer (Cron Scheduling)

Create `/etc/systemd/system/polisi-perpaduan-scraper.timer`:

```ini
[Unit]
Description=Schedule POLISI Perpaduan Scraper
Requires=polisi-perpaduan-scraper.service

[Timer]
# Run at 01:00 UTC every 3 days
OnCalendar=*-*-*/3 01:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 7. Enable and Start

```bash
systemctl daemon-reload
systemctl enable polisi-perpaduan-scraper.timer
systemctl start polisi-perpaduan-scraper.timer
```

### 8. Verify

Check timer status:

```bash
systemctl status polisi-perpaduan-scraper.timer
systemctl list-timers polisi-perpaduan-scraper.timer
```

Check recent runs:

```bash
journalctl -u polisi-perpaduan-scraper -n 50
tail -f /opt/polisigpt/logs/scraper.log
```

Check output:

```bash
ls -lh /opt/polisigpt/data/manifests/perpaduan/
tail /opt/polisigpt/data/manifests/perpaduan/records.jsonl
```

## Operations

### Manual Trigger

```bash
sudo systemctl start polisi-perpaduan-scraper.service
```

### View Logs

```bash
# Recent logs
journalctl -u polisi-perpaduan-scraper -n 100 -f

# All logs for a specific run
journalctl -u polisi-perpaduan-scraper --since "2026-03-09 00:00:00"

# Error only
journalctl -u polisi-perpaduan-scraper -p err
```

### Check Scraper State

```bash
sqlite3 /opt/polisigpt/.cache/scraper_state.sqlite3 "SELECT COUNT(*) FROM urls WHERE status='active';"
sqlite3 /opt/polisigpt/.cache/scraper_state.sqlite3 "SELECT * FROM crawl_runs ORDER BY started_at DESC LIMIT 5;"
```

### Reset State (Full Rescan)

```bash
rm /opt/polisigpt/.cache/scraper_state.sqlite3
systemctl start polisi-perpaduan-scraper.service
```

## Monitoring

### Disk Space

```bash
df -h /opt/polisigpt
```

### CPU/Memory

```bash
htop
```

### Droplet Health

```bash
doctl compute droplet get polisi-perpaduan-scraper
```

## Troubleshooting

### Service Won't Start

```bash
systemctl status polisi-perpaduan-scraper.service
journalctl -u polisi-perpaduan-scraper -n 50
```

### No Records Being Produced

1. Check selectors match current HTML structure
2. Run local dry-run test
3. Verify config file syntax: `python -m yaml.dump configs/perpaduan.yaml`

### High CPU Usage

- Reduce number of workers (not implemented yet)
- Increase delay between requests in config

### Spaces Upload Failing

- Verify credentials in `/opt/polisigpt/.env`
- Check bucket exists and user has write permissions
- Test with: `aws s3 ls s3://your-bucket --endpoint-url https://sgp1.digitaloceanspaces.com`

## Maintenance

### Update Config

```bash
sudo -u polisi vim /opt/polisigpt/perpaduan-scraper/configs/perpaduan.yaml
systemctl start polisi-perpaduan-scraper.service
```

### Update Scraper Code

```bash
cd /opt/polisigpt/perpaduan-scraper
sudo -u polisi git pull
sudo -u polisi venv/bin/pip install -e .
```

### Archive Old Data

```bash
cd /opt/polisigpt/data/manifests/perpaduan
tar -czf perpaduan-records-2026-03.tar.gz records.jsonl crawl_runs.jsonl
# Upload to backup location
```

## Backup

SQLite state is small (~1MB). Back up regularly:

```bash
cp /opt/polisigpt/.cache/scraper_state.sqlite3 /backup/scraper_state.sqlite3.$(date +%Y%m%d)
```

Output files are large. Keep in DigitalOcean Spaces + archive locally.

## Alerting (Future)

Consider adding:
- Email on scraper failure
- Slack notification on high error rate
- Datadog/CloudWatch metrics
