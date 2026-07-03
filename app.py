#!/usr/bin/env python3
import json
import os
import subprocess
import threading
import time
import shutil
from datetime import datetime, date
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

CONFIG_DIR = Path.home() / ".config" / "papabackup"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"
SIZES_CACHE_FILE = CONFIG_DIR / "sizes_cache.json"

BACKUP_FILE_EXCLUDES = [
    "*.sql",
    "*.sql.gz",
    "*.bak",
    "*.backup",
    "*_backup*",
    "*_original*",
    "*.tar.gz",
    "*.tar",
    "*.zip",
    "thumbs/",
    "thumbnails/",
    "*.tmp",
    "*.log",
]

DEFAULT_CONFIG = {
    "backup_jobs": [
        {
            "id": "immich",
            "name": "Immich",
            "enabled": True,
            "sources": [
                "/mnt/plex/immich/",
                "/home/joseph/immich-app/postgres/",
                "/home/joseph/immich-app/docker-compose.yml",
                "/home/joseph/immich-app/.env",
            ],
            "excludes": [
                "*.bak",
                "*.backup",
                "*_original*",
                "*.tar.gz",
                "*.tar",
                "*.zip",
                "*.tmp",
                "*.log",
                "thumbs/",
                "thumbnails/",
                "encoded-video/",
            ],
            "destination": "",
            "google_drive_path": "papabackup/immich",
            "use_local": True,
            "use_gdrive": False,
            "schedule": "manual",
            "date_filter": True,
            "date_from": "",
            "date_to": "",
            "pg_dump": {
                "enabled": True,
                "container": "immich_postgres",
                "user": "joseph",
                "output": "/home/joseph/immich-app/immich_db_backup.sql",
            },
        },
        {
            "id": "jellyfin",
            "name": "Jellyfin",
            "enabled": True,
            "sources": [
                "/home/joseph/jellyfin/config/",
                "/home/joseph/jellyfin/cache/",
            ],
            "excludes": BACKUP_FILE_EXCLUDES,
            "destination": "",
            "google_drive_path": "papabackup/jellyfin",
            "use_local": True,
            "use_gdrive": False,
            "schedule": "manual",
        },
        {
            "id": "home",
            "name": "Home Directory",
            "enabled": True,
            "sources": [str(Path.home())],
            "excludes": [
                ".cache",
                ".local/share/Trash",
                "node_modules",
                "__pycache__",
                ".npm",
                "snap",
            ] + BACKUP_FILE_EXCLUDES,
            "destination": "",
            "google_drive_path": "papabackup/home",
            "use_local": True,
            "use_gdrive": False,
            "schedule": "manual",
        },
        {
            "id": "media",
            "name": "Media Library",
            "enabled": False,
            "sources": ["/mnt/plex/Videos/"],
            "excludes": BACKUP_FILE_EXCLUDES,
            "destination": "",
            "google_drive_path": "papabackup/media",
            "use_local": True,
            "use_gdrive": False,
            "schedule": "manual",
        },
    ],
    "custom_jobs": [],
    "google_drive": {
        "configured": False,
        "remote_name": "gdrive",
    },
    "settings": {
        "max_log_entries": 500,
        "compression": True,
        "verify_after_backup": True,
    },
}

running_jobs = {}
cached_sizes = {}
sizes_lock = threading.Lock()
sizes_computing = False


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_sizes_cache():
    global cached_sizes
    if SIZES_CACHE_FILE.exists():
        with open(SIZES_CACHE_FILE) as f:
            cached_sizes = json.load(f)


def save_sizes_cache():
    with open(SIZES_CACHE_FILE, "w") as f:
        json.dump(cached_sizes, f, indent=2)


def get_dir_size(path):
    try:
        result = subprocess.run(
            ["du", "-sh", "--exclude=*.sql", "--exclude=*.bak",
             "--exclude=*.backup", "--exclude=*_backup*",
             "--exclude=*_original*", path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return result.stdout.split()[0]
    except Exception:
        pass
    return "unknown"


def get_dir_size_with_dates(path, date_from=None, date_to=None):
    """Get size of files within a date range using find."""
    cmd = ["find", path, "-type", "f"]
    if date_from:
        cmd.extend(["-newermt", date_from])
    if date_to:
        cmd.extend(["!", "-newermt", date_to])
    for exc in BACKUP_FILE_EXCLUDES:
        if exc.endswith("/"):
            cmd.extend(["-not", "-path", f"*/{exc}*"])
        elif exc.startswith("*"):
            cmd.extend(["-not", "-name", exc])
    cmd.extend(["-printf", "%s\n"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            total = sum(int(line) for line in result.stdout.strip().split("\n") if line.strip())
            return format_size(total)
    except Exception:
        pass
    return "unknown"


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f}K"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.1f}M"
    elif size_bytes < 1024 ** 4:
        return f"{size_bytes / 1024 ** 3:.1f}G"
    else:
        return f"{size_bytes / 1024 ** 4:.1f}T"


def count_files_with_dates(path, date_from=None, date_to=None):
    """Count files within a date range."""
    cmd = ["find", path, "-type", "f"]
    if date_from:
        cmd.extend(["-newermt", date_from])
    if date_to:
        cmd.extend(["!", "-newermt", date_to])
    for exc in BACKUP_FILE_EXCLUDES:
        if exc.endswith("/"):
            cmd.extend(["-not", "-path", f"*/{exc}*"])
        elif exc.startswith("*"):
            cmd.extend(["-not", "-name", exc])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            return len(lines)
    except Exception:
        pass
    return 0


def compute_all_sizes():
    """Background task to compute sizes for all jobs."""
    global sizes_computing
    sizes_computing = True
    config = load_config()
    all_jobs = config["backup_jobs"] + config.get("custom_jobs", [])

    for job in all_jobs:
        job_id = job["id"]
        per_source = []
        total_bytes = 0

        for src in job.get("sources", []):
            if not os.path.exists(src):
                continue
            if os.path.isfile(src):
                sz = os.path.getsize(src)
                total_bytes += sz
                per_source.append({"path": src, "size": format_size(sz)})
                continue
            try:
                result = subprocess.run(
                    ["du", "-sb", "--exclude=*.sql", "--exclude=*.bak",
                     "--exclude=*.backup", "--exclude=*_backup*",
                     "--exclude=*_original*", "--exclude=*.tar.gz",
                     "--exclude=*.tar", "--exclude=*.zip", src],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    sz = int(result.stdout.split()[0])
                    total_bytes += sz
                    per_source.append({"path": src, "size": format_size(sz)})
            except Exception:
                per_source.append({"path": src, "size": "unknown"})

        with sizes_lock:
            cached_sizes[job_id] = {
                "total": format_size(total_bytes),
                "sources": per_source,
                "computed_at": datetime.now().isoformat(),
            }

    with sizes_lock:
        save_sizes_cache()

    sizes_computing = False


def check_rclone():
    try:
        result = subprocess.run(
            ["rclone", "version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def check_rclone_remote(remote_name):
    try:
        result = subprocess.run(
            ["rclone", "listremotes"], capture_output=True, text=True, timeout=10
        )
        return f"{remote_name}:" in result.stdout
    except Exception:
        return False


def append_log(job_id, message):
    log_file = LOG_DIR / f"{job_id}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def read_log(job_id, lines=100):
    log_file = LOG_DIR / f"{job_id}.log"
    if not log_file.exists():
        return ""
    with open(log_file) as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


def build_rsync_cmd(job, source, target, date_from=None, date_to=None):
    """Build rsync command with optional date filtering and backup exclusions."""
    cmd = ["rsync", "-avh", "--delete", "--progress"]

    for exc in job.get("excludes", []):
        cmd.extend(["--exclude", exc])

    if date_from or date_to:
        filter_file = LOG_DIR / f"{job['id']}_filelist.txt"
        find_cmd = ["find", source, "-type", "f"]
        if date_from:
            find_cmd.extend(["-newermt", date_from])
        if date_to:
            find_cmd.extend(["!", "-newermt", date_to])
        for exc in job.get("excludes", []):
            if exc.endswith("/"):
                find_cmd.extend(["-not", "-path", f"*/{exc}*"])
            elif exc.startswith("*"):
                find_cmd.extend(["-not", "-name", exc])

        result = subprocess.run(find_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            files = result.stdout.strip().split("\n")
            rel_files = []
            for f in files:
                if f.strip():
                    rel = os.path.relpath(f.strip(), source)
                    rel_files.append(rel)
            with open(filter_file, "w") as fh:
                fh.write("\n".join(rel_files))
            cmd = ["rsync", "-avh", "--progress", f"--files-from={filter_file}"]
            cmd.extend([source, target + "/"])
            return cmd, len(rel_files)

    cmd.extend([source, target + "/"])
    return cmd, None


def run_backup(job, date_from=None, date_to=None):
    job_id = job["id"]
    running_jobs[job_id] = {
        "status": "running",
        "started": datetime.now().isoformat(),
        "progress": "",
    }

    date_info = ""
    if date_from or date_to:
        date_info = f" (date filter: {date_from or 'any'} to {date_to or 'now'})"
    append_log(job_id, f"=== Backup started for {job['name']}{date_info} ===")

    try:
        if job.get("pg_dump", {}).get("enabled"):
            pg = job["pg_dump"]
            append_log(job_id, f"Dumping PostgreSQL from container {pg['container']}...")
            result = subprocess.run(
                [
                    "docker", "exec", pg["container"],
                    "pg_dumpall", "-U", pg["user"],
                ],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 0:
                with open(pg["output"], "w") as f:
                    f.write(result.stdout)
                size = os.path.getsize(pg["output"])
                append_log(job_id, f"Database dump complete: {size / 1e9:.1f} GB")
            else:
                append_log(job_id, f"Database dump failed: {result.stderr}")

        if job.get("use_local") and job.get("destination"):
            dest = job["destination"]
            append_log(job_id, f"Backing up to local destination: {dest}")
            os.makedirs(dest, exist_ok=True)

            for source in job.get("sources", []):
                if not os.path.exists(source):
                    append_log(job_id, f"Source not found, skipping: {source}")
                    continue

                source_name = os.path.basename(source.rstrip("/"))
                target = os.path.join(dest, source_name)

                if os.path.isfile(source):
                    shutil.copy2(source, os.path.join(dest, os.path.basename(source)))
                    append_log(job_id, f"Copied file: {source}")
                    continue

                cmd, file_count = build_rsync_cmd(
                    job, source, target, date_from, date_to
                )

                if file_count is not None:
                    append_log(job_id, f"Date-filtered: {file_count} files to sync from {source_name}")
                append_log(job_id, f"rsync: {source} -> {target}")
                running_jobs[job_id]["progress"] = f"Syncing {source_name}..."

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=86400
                )
                if result.returncode == 0:
                    append_log(job_id, f"Completed: {source_name}")
                else:
                    append_log(job_id, f"rsync error for {source_name}: {result.stderr[-500:]}")

        if job.get("use_gdrive") and job.get("google_drive_path"):
            config = load_config()
            remote = config["google_drive"]["remote_name"]
            gdrive_path = job["google_drive_path"]

            if not check_rclone_remote(remote):
                append_log(job_id, "Google Drive remote not configured in rclone. Skipping.")
            else:
                for source in job.get("sources", []):
                    if not os.path.exists(source):
                        append_log(job_id, f"Source not found, skipping: {source}")
                        continue

                    source_name = os.path.basename(source.rstrip("/"))
                    remote_dest = f"{remote}:{gdrive_path}/{source_name}"

                    cmd = ["rclone", "sync", source, remote_dest, "--progress", "-v"]
                    for exc in job.get("excludes", []):
                        cmd.extend(["--exclude", exc])

                    if date_from:
                        cmd.extend(["--min-age", f"{date_from}"])
                    if date_to:
                        cmd.extend(["--max-age", f"{date_to}"])

                    append_log(job_id, f"rclone sync: {source} -> {remote_dest}")
                    running_jobs[job_id]["progress"] = f"Uploading {source_name} to Google Drive..."

                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=86400
                    )
                    if result.returncode == 0:
                        append_log(job_id, f"Google Drive upload complete: {source_name}")
                    else:
                        append_log(job_id, f"rclone error: {result.stderr[-500:]}")

        append_log(job_id, f"=== Backup completed for {job['name']} ===")
        running_jobs[job_id]["status"] = "completed"

    except Exception as e:
        append_log(job_id, f"ERROR: {str(e)}")
        running_jobs[job_id]["status"] = "failed"

    running_jobs[job_id]["finished"] = datetime.now().isoformat()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    config = load_config()
    return jsonify(config)


@app.route("/api/config", methods=["POST"])
def update_config():
    config = request.json
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/job/<job_id>", methods=["POST"])
def update_job(job_id):
    config = load_config()
    data = request.json

    all_jobs = config["backup_jobs"] + config.get("custom_jobs", [])
    for job in all_jobs:
        if job["id"] == job_id:
            job.update(data)
            break

    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/job/custom", methods=["POST"])
def add_custom_job():
    config = load_config()
    data = request.json
    job_id = data.get("name", "custom").lower().replace(" ", "_")
    job_id = f"custom_{job_id}_{int(time.time())}"

    job = {
        "id": job_id,
        "name": data["name"],
        "enabled": True,
        "sources": data.get("sources", []),
        "excludes": data.get("excludes", []) + BACKUP_FILE_EXCLUDES,
        "destination": data.get("destination", ""),
        "google_drive_path": f"papabackup/{job_id}",
        "use_local": data.get("use_local", True),
        "use_gdrive": data.get("use_gdrive", False),
        "schedule": "manual",
    }

    if "custom_jobs" not in config:
        config["custom_jobs"] = []
    config["custom_jobs"].append(job)
    save_config(config)
    return jsonify({"status": "ok", "job": job})


@app.route("/api/job/<job_id>/delete", methods=["POST"])
def delete_custom_job(job_id):
    config = load_config()
    config["custom_jobs"] = [
        j for j in config.get("custom_jobs", []) if j["id"] != job_id
    ]
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/backup/<job_id>", methods=["POST"])
def start_backup(job_id):
    if job_id in running_jobs and running_jobs[job_id].get("status") == "running":
        return jsonify({"error": "Backup already running"}), 409

    config = load_config()
    all_jobs = config["backup_jobs"] + config.get("custom_jobs", [])
    job = next((j for j in all_jobs if j["id"] == job_id), None)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.json or {}
    date_from = data.get("date_from", "")
    date_to = data.get("date_to", "")

    thread = threading.Thread(
        target=run_backup, args=(job, date_from or None, date_to or None),
        daemon=True
    )
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/backup/<job_id>/status", methods=["GET"])
def backup_status(job_id):
    if job_id in running_jobs:
        return jsonify(running_jobs[job_id])
    return jsonify({"status": "idle"})


@app.route("/api/backup/<job_id>/log", methods=["GET"])
def backup_log(job_id):
    return jsonify({"log": read_log(job_id)})


@app.route("/api/sizes", methods=["GET"])
def get_sizes():
    with sizes_lock:
        return jsonify({
            "sizes": cached_sizes,
            "computing": sizes_computing,
        })


@app.route("/api/sizes/refresh", methods=["POST"])
def refresh_sizes():
    global sizes_computing
    if sizes_computing:
        return jsonify({"status": "already_computing"})
    thread = threading.Thread(target=compute_all_sizes, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/sizes/filtered", methods=["POST"])
def get_filtered_size():
    """Get estimated size for a date-filtered backup."""
    data = request.json
    job_id = data.get("job_id")
    date_from = data.get("date_from", "")
    date_to = data.get("date_to", "")

    config = load_config()
    all_jobs = config["backup_jobs"] + config.get("custom_jobs", [])
    job = next((j for j in all_jobs if j["id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    total_bytes = 0
    total_files = 0
    for src in job.get("sources", []):
        if not os.path.exists(src):
            continue
        if os.path.isfile(src):
            mtime = datetime.fromtimestamp(os.path.getmtime(src))
            include = True
            if date_from:
                include = include and mtime >= datetime.fromisoformat(date_from)
            if date_to:
                include = include and mtime <= datetime.fromisoformat(date_to)
            if include:
                total_bytes += os.path.getsize(src)
                total_files += 1
            continue

        size_str = get_dir_size_with_dates(src, date_from or None, date_to or None)
        file_count = count_files_with_dates(src, date_from or None, date_to or None)
        total_files += file_count
        if size_str != "unknown":
            # parse back - this is approximate
            pass

    # Do it properly with a single pass
    total_bytes = 0
    total_files = 0
    for src in job.get("sources", []):
        if not os.path.exists(src):
            continue
        if os.path.isfile(src):
            total_bytes += os.path.getsize(src)
            total_files += 1
            continue
        cmd = ["find", src, "-type", "f"]
        if date_from:
            cmd.extend(["-newermt", date_from])
        if date_to:
            cmd.extend(["!", "-newermt", date_to])
        for exc in BACKUP_FILE_EXCLUDES:
            if exc.endswith("/"):
                cmd.extend(["-not", "-path", f"*/{exc}*"])
            elif exc.startswith("*"):
                cmd.extend(["-not", "-name", exc])
        cmd.extend(["-printf", "%s\n"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
                total_files += len(lines)
                total_bytes += sum(int(l) for l in lines)
        except Exception:
            pass

    return jsonify({
        "size": format_size(total_bytes),
        "files": total_files,
        "bytes": total_bytes,
    })


@app.route("/api/gdrive/status", methods=["GET"])
def gdrive_status():
    has_rclone = check_rclone()
    config = load_config()
    remote = config["google_drive"]["remote_name"]
    has_remote = check_rclone_remote(remote) if has_rclone else False
    return jsonify({
        "rclone_installed": has_rclone,
        "remote_configured": has_remote,
        "remote_name": remote,
    })


@app.route("/api/gdrive/setup", methods=["POST"])
def gdrive_setup_info():
    return jsonify({
        "instructions": [
            "1. Install rclone: curl https://rclone.org/install.sh | sudo bash",
            "2. Run: rclone config",
            "3. Choose 'n' for new remote",
            "4. Name it 'gdrive' (or your preferred name)",
            "5. Choose 'Google Drive' as the storage type",
            "6. Follow the authentication prompts",
            "7. Refresh this page to verify the connection",
        ]
    })


@app.route("/api/disks", methods=["GET"])
def list_disks():
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,MOUNTPOINT,FSTYPE,TYPE"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return jsonify(data)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["df", "-h", "--output=source,size,used,avail,pcent,target"],
            capture_output=True, text=True, timeout=10,
        )
        return jsonify({"raw": result.stdout})
    except Exception:
        return jsonify({"error": "Could not list disks"})


if __name__ == "__main__":
    load_config()
    load_sizes_cache()
    # Compute sizes in background on startup
    threading.Thread(target=compute_all_sizes, daemon=True).start()
    app.run(host="0.0.0.0", port=9999, debug=True)
