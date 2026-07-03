# PapaBackup

A self-hosted backup utility with a web interface for managing backups of your Linux servers and files.

## Features

- **Immich Backup** — Back up Immich photo library, database (via `pg_dump`), and configuration files
- **Jellyfin Backup** — Back up Jellyfin configuration and cache
- **Home Directory Backup** — Back up your home folder with configurable exclusions
- **Media Library Backup** — Back up video and media collections
- **Custom Backup Jobs** — Add your own source/destination pairs through the UI
- **Google Drive Support** — Sync backups to Google Drive via rclone
- **Local Backup** — Rsync-based local/network backups with `--delete` mirroring
- **Live Logs** — View backup progress and logs in real time

## Requirements

- Python 3.10+
- `rsync` (for local backups)
- `rclone` (for Google Drive backups, optional)
- Docker (for Immich database dumps)

## Installation

```bash
cd /home/joseph/papabackup
pip install -r requirements.txt
python app.py
```

The web interface runs on **port 9999**.

## Usage

1. Open `http://your-server:9999` in your browser
2. Configure destination paths for each backup job
3. Toggle Local / Google Drive for each job
4. Click **Backup Now** to run a backup
5. Add custom backup jobs with the **+** button

## Google Drive Setup

1. Install rclone: `curl https://rclone.org/install.sh | sudo bash`
2. Run `rclone config` and set up a Google Drive remote named `gdrive`
3. Enable "Google Drive" on any backup job in the UI

## Configuration

Configuration is stored in `~/.config/papabackup/config.json`. Logs are in `~/.config/papabackup/logs/`.

## License

MIT
