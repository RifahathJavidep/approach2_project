"""
FTP/SFTP Utility Functions for Miipe Team Server.
Handles file uploads and downloads using standard FTP or secure SFTP.
"""

import os
import io
import json
from pathlib import Path
from ftplib import FTP
from dotenv import load_dotenv

load_dotenv()

def get_ftp_config():
    """Load FTP/SFTP configuration from environment."""
    return {
        "protocol": os.getenv("FTP_PROTOCOL", "ftp").lower(),
        "host": os.getenv("FTP_HOST"),
        "port": int(os.getenv("FTP_PORT", 21)),
        "user": os.getenv("FTP_USER"),
        "pass": os.getenv("FTP_PASS"),
        "remote_dir": os.getenv("FTP_REMOTE_DIR", "/uploads"),
    }

def _upload_ftp(local_path, remote_filename, config):
    """Standard FTP Upload."""
    print(f"  FTP Connecting to {config['host']}...")
    with FTP() as ftp:
        ftp.connect(config['host'], config['port'])
        ftp.login(config['user'], config['pass'])
        
        # Navigate to target directory
        try:
            ftp.cwd(config['remote_dir'])
        except:
            print(f"  Creating directory {config['remote_dir']}...")
            ftp.mkd(config['remote_dir'])
            ftp.cwd(config['remote_dir'])

        with open(local_path, 'rb') as f:
            print(f"  Uploading {remote_filename} via FTP...")
            ftp.storbinary(f'STOR {remote_filename}', f)
    
    return f"ftp://{config['host']}{config['remote_dir']}/{remote_filename}"

def _upload_sftp(local_path, remote_filename, config):
    """Secure SFTP Upload using paramiko."""
    try:
        import paramiko
    except ImportError:
        raise ImportError("SFTP requires 'paramiko' library. Install it with: pip install paramiko")

    print(f"  SFTP Connecting to {config['host']}...")
    transport = paramiko.Transport((config['host'], config['port']))
    transport.connect(username=config['user'], password=config['pass'])
    
    with paramiko.SFTPClient.from_transport(transport) as sftp:
        # Ensure remote directory exists
        try:
            sftp.chdir(config['remote_dir'])
        except IOError:
            print(f"  Creating directory {config['remote_dir']}...")
            sftp.mkdir(config['remote_dir'])
            sftp.chdir(config['remote_dir'])

        print(f"  Uploading {remote_filename} via SFTP...")
        sftp.put(local_path, remote_filename)
    
    transport.close()
    return f"sftp://{config['host']}{config['remote_dir']}/{remote_filename}"

def _download_ftp(remote_filename, local_path, config):
    """Standard FTP Download."""
    print(f"  FTP Connecting to {config['host']}...")
    with FTP() as ftp:
        ftp.connect(config['host'], config['port'])
        ftp.login(config['user'], config['pass'])
        ftp.cwd(config['remote_dir'])
        
        with open(local_path, 'wb') as f:
            print(f"  Downloading {remote_filename} via FTP...")
            ftp.retrbinary(f'RETR {remote_filename}', f.write)
    
    return local_path

def _download_sftp(remote_filename, local_path, config):
    """Secure SFTP Download."""
    try:
        import paramiko
    except ImportError:
        raise ImportError("SFTP requires 'paramiko' library.")

    print(f"  SFTP Connecting to {config['host']}...")
    transport = paramiko.Transport((config['host'], config['port']))
    transport.connect(username=config['user'], password=config['pass'])
    
    with paramiko.SFTPClient.from_transport(transport) as sftp:
        sftp.chdir(config['remote_dir'])
        print(f"  Downloading {remote_filename} via SFTP...")
        sftp.get(remote_filename, local_path)
    
    transport.close()
    return local_path

def upload_to_miipe_server(local_path, remote_filename=None):
    """
    Unified upload function for Miipe Team Server.
    Automatically chooses FTP or SFTP based on .env config.
    """
    config = get_ftp_config()
    if not remote_filename:
        remote_filename = os.path.basename(local_path)

    if config["protocol"] == "sftp":
        return _upload_sftp(local_path, remote_filename, config)
    else:
        return _upload_ftp(local_path, remote_filename, config)

def upload_json_to_miipe_server(data, remote_filename):
    """Directly upload a Python dictionary as a JSON file to the server."""
    config = get_ftp_config()
    
    # Write JSON to a temporary local file first
    temp_local = f"temp_{remote_filename}"
    with open(temp_local, 'w') as f:
        json.dump(data, f, indent=2)
    
    try:
        url = upload_to_miipe_server(temp_local, remote_filename)
        return url
    finally:
        if os.path.exists(temp_local):
            os.remove(temp_local)

def download_from_miipe_server(remote_path, local_dir):
    """
    Unified download function for Miipe Team Server.
    Handles path parsing to extract filename.
    """
    config = get_ftp_config()
    remote_filename = os.path.basename(remote_path)
    local_path = os.path.join(local_dir, remote_filename)
    
    os.makedirs(local_dir, exist_ok=True)

    if config["protocol"] == "sftp":
        return _download_sftp(remote_filename, local_path, config)
    else:
        return _download_ftp(remote_filename, local_path, config)

def download_json_from_miipe_server(remote_filename):
    """Download and parse a JSON file from the server."""
    with io.BytesIO() as bio:
        config = get_ftp_config()
        if config["protocol"] == "sftp":
            # SFTP download to buffer
            import paramiko
            transport = paramiko.Transport((config['host'], config['port']))
            transport.connect(username=config['user'], password=config['pass'])
            with paramiko.SFTPClient.from_transport(transport) as sftp:
                sftp.chdir(config['remote_dir'])
                sftp.getfo(remote_filename, bio)
            transport.close()
        else:
            # FTP download to buffer
            with FTP() as ftp:
                ftp.connect(config['host'], config['port'])
                ftp.login(config['user'], config['pass'])
                ftp.cwd(config['remote_dir'])
                ftp.retrbinary(f'RETR {remote_filename}', bio.write)
        
        bio.seek(0)
        return json.loads(bio.read().decode('utf-8'))

if __name__ == "__main__":
    # Self-test (requires valid .env)
    print("Miipe Server Integration Test")
    print("="*30)
    try:
        # Create a test file
        with open("test_file.txt", "w") as f:
            f.write("Test file for Miipe Team Server integration")
        
        # Try to upload
        # url = upload_to_miipe_server("test_file.txt")
        # print(f"Success! File available at: {url}")
        print("Protocol configured:", get_ftp_config()["protocol"])
        print("Host configured:", get_ftp_config()["host"])
    except Exception as e:
        print(f"Integration Check Failed: {e}")
    finally:
        if os.path.exists("test_file.txt"):
            os.remove("test_file.txt")
