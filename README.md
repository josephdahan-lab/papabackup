# PapaBackup

A self-hosted backup utility with a web interface for managing backups of your Linux servers and files.

**Version 2.1**

## Features

- **Immich Backup** — Back up Immich photo library, database dumps, and configuration files
- **Jellyfin Backup** — Back up Jellyfin configuration and cache
- **Home Directory Backup** — Back up your home folder with configurable exclusions
- **Media Library Backup** — Back up video and media collections
- **Custom Backup Jobs** — Add your own source/destination pairs through the UI
- **Google Drive Support** — Sync backups to Google Drive via rclone
- **Local Backup** — Rsync-based local/network backups with `--delete` mirroring
- **Date Range Filtering** — Back up only files modified within a specific date range
- **File Preview** — See the exact list of files before running a backup
- **Per-Source Toggle** — Include or exclude individual source directories per job, with per-directory size display
- **Live Progress** — Real-time upload/sync percentage, speed, and ETA during backups
- **Last Backup Tracking** — Each job shows when it was last backed up and whether it succeeded
- **Per-Job Size Refresh** — Recalculate sizes per job with a dedicated Refresh button
- **Light/Dark Theme** — Toggle between light and dark UI themes
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
3. Toggle source directories on/off to include or exclude them
4. Set a date range to filter files by modification time
5. Click **Est.** to preview the exact file list and total size
6. Toggle Local / Google Drive for each job
7. Click **Backup Now** to run a backup
8. Add custom backup jobs with the **+** button

## Google Drive Setup

1. Install rclone: `curl https://rclone.org/install.sh | sudo bash`
2. Run `rclone config` and set up a Google Drive remote named `gdrive`
3. Enable "Google Drive" on any backup job in the UI

## Configuration

Configuration is stored in `~/.config/papabackup/config.json`. Logs are in `~/.config/papabackup/logs/`.

## License

MIT
