# MinIO Standalone Binary Setup (No Docker)

## Why no Docker?
Docker Desktop requires a paid licence for commercial use on Mac/Windows
for companies with >250 employees or >$10M revenue. The MinIO standalone
binary is Apache 2.0 and runs directly — no Docker, no dependencies.

## Linux Server (recommended for production)
```bash
wget https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio
sudo mv minio /usr/local/bin/minio
```

Create systemd service for auto-start:
```bash
sudo tee /etc/systemd/system/minio.service > /dev/null <<EOF
[Unit]
Description=MinIO Object Storage
After=network.target
[Service]
User=www-data
Environment="MINIO_ROOT_USER=vera"
Environment="MINIO_ROOT_PASSWORD=vera_secret123"
ExecStart=/usr/local/bin/minio server /data --console-address :9001
Restart=always
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable minio && sudo systemctl start minio
```
API: http://localhost:9000 | Console: http://localhost:9001

## macOS
```bash
brew install minio/stable/minio
MINIO_ROOT_USER=vera MINIO_ROOT_PASSWORD=vera_secret123 minio server ~/minio-data --console-address :9001
```

## Windows
Download from: https://dl.min.io/server/minio/release/windows-amd64/minio.exe
```cmd
set MINIO_ROOT_USER=vera
set MINIO_ROOT_PASSWORD=vera_secret123
minio.exe server C:\minio-data --console-address :9001
```

## Create evidence-clips bucket
```python
import boto3
s3 = boto3.client('s3', endpoint_url='http://localhost:9000',
                  aws_access_key_id='vera', aws_secret_access_key='vera_secret123')
s3.create_bucket(Bucket='evidence-clips')
print('Bucket created.')
```
