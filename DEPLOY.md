# Deployment Guide — IMS Flask App

This app uses **Flask + MySQL**. Below are step-by-step guides for the
three best free/cheap hosting options.

---

## Option A — Railway (Recommended — Easiest)

Railway gives you a free MySQL database + Python hosting in one place.

### Step 1 — Push code to GitHub

```bash
# Inside the ims_flask/ folder
git init
git add .
git commit -m "initial commit"
# Create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/ims_flask.git
git push -u origin main
```

### Step 2 — Create Railway project

1. Go to **https://railway.app** → sign in with GitHub
2. Click **New Project → Deploy from GitHub repo** → select your repo
3. Railway will detect Python and deploy automatically

### Step 3 — Add MySQL database

1. In your Railway project, click **+ New** → **Database → MySQL**
2. Click the MySQL service → go to **Variables** tab
3. Copy the `MYSQL_URL` connection string — you'll need the parts below

### Step 4 — Set environment variables

In Railway → your web service → **Variables** tab, add these:

| Variable | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | a long random string (e.g. `openssl rand -hex 32`) |
| `MYSQL_HOST` | from Railway MySQL (e.g. `containers-us-west-XX.railway.app`) |
| `MYSQL_PORT` | from Railway MySQL (usually `6033`) |
| `MYSQL_USER` | `root` |
| `MYSQL_PASSWORD` | from Railway MySQL |
| `MYSQL_DB` | `railway` |
| `MAIL_USERNAME` | `lalbaghenterprises@gmail.com` |
| `MAIL_PASSWORD` | your Gmail App Password |
| `COMPANY_UPI_ID` | `8927770267@okbizaxis` |

### Step 5 — Run database migrations

In Railway → your web service → **Settings → Deploy** → add a
**Start Command**:

```
flask db upgrade && gunicorn run:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
```

Or run migrations once from the Railway **Shell** tab:
```bash
flask db upgrade
```

Your app will be live at `https://YOUR-APP.railway.app` 🎉

---

## Option B — Render (Also Free)

Render gives a free web service but **no free MySQL** — use
**PlanetScale** (free MySQL in the cloud) for the database.

### Step 1 — Set up PlanetScale (free MySQL)

1. Go to **https://planetscale.com** → sign up → Create Database
2. Name it `ims_db`, region closest to India (e.g. `ap-south-1`)
3. Click **Connect → Connect with: Python / PyMySQL**
4. Copy the host, username, password

### Step 2 — Push code to GitHub (same as Option A Step 1)

### Step 3 — Deploy on Render

1. Go to **https://render.com** → New → **Web Service**
2. Connect your GitHub repo
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `flask db upgrade && gunicorn run:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120`
4. Add all the same environment variables as Option A (using PlanetScale DB values)

---

## Option C — VPS (DigitalOcean / Hetzner — Full Control)

Best for production use. A Hetzner CX11 costs ~€3.79/month (~₹350).

### Step 1 — Set up server

```bash
# SSH into your server
ssh root@YOUR_SERVER_IP

# Install dependencies
apt update && apt upgrade -y
apt install -y python3-pip python3-venv mysql-server nginx git

# Start MySQL
systemctl start mysql
mysql_secure_installation
```

### Step 2 — Create MySQL database

```bash
mysql -u root -p
```
```sql
CREATE DATABASE ims_db CHARACTER SET utf8mb4;
CREATE USER 'imsuser'@'localhost' IDENTIFIED BY 'YourStrongPassword123!';
GRANT ALL PRIVILEGES ON ims_db.* TO 'imsuser'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### Step 3 — Deploy the app

```bash
cd /var/www
git clone https://github.com/YOUR_USERNAME/ims_flask.git
cd ims_flask

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file
cp .env.example .env
nano .env   # fill in your real values
```

### Step 4 — Run migrations & test

```bash
source venv/bin/activate
export FLASK_APP=run.py
flask db upgrade
python run.py   # test it works, then Ctrl+C
```

### Step 5 — Set up Gunicorn as a service

```bash
nano /etc/systemd/system/ims.service
```

Paste:
```ini
[Unit]
Description=IMS Flask App
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/ims_flask
ExecStart=/var/www/ims_flask/venv/bin/gunicorn run:app \
    --workers 2 \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    --access-logfile /var/log/ims_access.log \
    --error-logfile /var/log/ims_error.log
Restart=always
EnvironmentFile=/var/www/ims_flask/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable ims
systemctl start ims
```

### Step 6 — Set up Nginx reverse proxy

```bash
nano /etc/nginx/sites-available/ims
```

Paste (replace `YOUR_DOMAIN` or use server IP):
```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /var/www/ims_flask/app/static/;
        expires 30d;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/ims /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

### Step 7 — (Optional) Free HTTPS with Let's Encrypt

```bash
apt install certbot python3-certbot-nginx -y
certbot --nginx -d YOUR_DOMAIN.com
```

---

## Important Security Checklist Before Going Live

- [ ] Change `SECRET_KEY` to a long random string
- [ ] Set `FLASK_ENV=production` (disables debug mode)
- [ ] Use a strong MySQL password (not the default)
- [ ] Remove `__pycache__` and `.pyc` files from the repo (already in `.gitignore`)
- [ ] **Never commit `.env` to GitHub** (already in `.gitignore`)
- [ ] Keep the Gmail App Password private
- [ ] Consider changing the default admin password after first login

---

## Generating a Secure SECRET_KEY

Run this in any terminal:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Troubleshooting

**App crashes on start**
```bash
# Check logs
journalctl -u ims -n 50       # systemd logs (VPS)
# Or on Railway/Render, check the Logs tab
```

**Database connection error**
- Double-check `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB` env vars
- Make sure `flask db upgrade` was run

**Invoice/upload files not saving**
- On Railway/Render, file storage is ephemeral — files are lost on redeploy
- For permanent storage, integrate **Cloudinary** or **AWS S3**
- For a VPS, files persist normally in the `invoices/` and `uploads/` folders

**Mail not sending**
- Make sure you're using a **Gmail App Password** (not your regular Gmail password)
- Enable 2FA on Gmail, then go to Google Account → Security → App Passwords
