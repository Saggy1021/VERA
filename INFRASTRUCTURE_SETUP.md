# VERA Infrastructure Setup
All self-hosted. Zero cloud costs. Zero Docker required.

## PostgreSQL 16
```bash
sudo apt update && sudo apt install -y postgresql-16
sudo systemctl enable postgresql && sudo systemctl start postgresql
sudo -u postgres createdb vera_db
sudo -u postgres createuser vera_user
sudo -u postgres psql -c "ALTER USER vera_user WITH PASSWORD 'yourpassword';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE vera_db TO vera_user;"
```
Set in `.env`: `VERA_DB_URL=postgresql://vera_user:yourpassword@localhost:5432/vera_db`

## Redis OSS
```bash
sudo apt install -y redis-server
sudo systemctl enable redis-server && sudo systemctl start redis-server
redis-cli ping   # Should return PONG
```

## MinIO (standalone binary — NO Docker)
See [MINIO_SETUP.md](MINIO_SETUP.md)

## TLS / HTTPS (free)
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```
Auto-renews every 90 days.

## Environment Variables (.env file in project root)
```
VERA_DB_URL=postgresql://vera_user:yourpassword@localhost:5432/vera_db
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=vera
MINIO_SECRET_KEY=vera_secret123
VERA_DATA_CONTROLLER=Your Organization Name
VERA_DPO_EMAIL=privacy@yourorganization.com
SECRET_KEY=generate_a_random_256bit_key_here
```
