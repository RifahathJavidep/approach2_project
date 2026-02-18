# Miipe Team Server: FTP/SFTP Integration Guide

This document explains how to store documents on the Miipe Team Server (FTP/SFTP) instead of AWS S3.

## 1. Configuration (.env)

Add these settings to your `.env` file. We support both standard FTP and secure SFTP.

```env
# Protocol Choice: 'ftp' or 'sftp'
FTP_PROTOCOL=sftp

# Server Details
FTP_HOST=ftp.miipe.team
FTP_PORT=22        # Port 21 for FTP, 22 for SFTP
FTP_USER=your_username
FTP_PASS=your_password

# Remote Path
FTP_REMOTE_DIR=/uploads/prism
```

## 2. Using the Utilities

A new standalone utility file `ftp_utils.py` has been provided. It manages connections and file transfers automatically.

### Basic File Upload
```python
from ftp_utils import upload_to_miipe_server

local_file = "path/to/my_document.pdf"
# Upload and get the pseudo-URL
remote_url = upload_to_miipe_server(local_file)
print(f"File stored at: {remote_url}")
```

### Direct JSON Upload (Results)
```python
from ftp_utils import upload_json_to_miipe_server

results = {"project": "crm_cloud", "requirements": [...]}
remote_url = upload_json_to_miipe_server(results, "requirements_v1.json")
```

## 3. Implementation Summary

To integrate this into your main workflow without breaking the S3 code:

1. **Standalone**: The `ftp_utils.py` is completely separate from `s3_utils.py`.
2. **Library Requirements**: 
   - Standard FTP: No extra library needed (uses `ftplib`).
   - SFTP: Requires `paramiko` (`pip install paramiko`).
3. **Endpoint Example**: To support this in your API, you can add a new endpoint in `app.py`:

```python
@app.post("/ftp/extract")
async def extract_via_ftp(request: ExtractionRequest):
    # 1. Use ftp_utils to download files
    # 2. Run extraction
    # 3. Use ftp_utils to upload results
    pass
```

## 4. Security Recommendations

- **Use SFTP**: Plain FTP sends passwords in cleartext. Always prefer SFTP (Port 22).
- **Network**: Ensure your server's IP is whitelisted on the Miipe firewall.
- **Service Account**: Use a restricted FTP user account that only has access to the `/uploads` folder.

---
*Created for the Miipe Team integration task.*
