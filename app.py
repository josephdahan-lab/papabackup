#!/usr/bin/env python3
import json
import os
import subprocess
import threading
import time
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

CONFIG_DIR = Path.home() / ".config" / "papabackup"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"

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
            "destination": "",
            "google_drive_path": "papabackup/immich",
            "use_local": True,
            "use_gdrive": False,
            "schedule": "manual",
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
            ],
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


def get_dir_size(path):
    try:
        result = subprocess.run(
            ["du", "-sh", path], capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout.split()[0]
    except Exception:
        pass
    return "unknown"


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


def run_backup(job):
    job_id = job["id"]
    running_jobs[job_id] = {
        "status": "running",
        "started": datetime.now().isoformat(),
        "progress": "",
    }

    append_log(job_id, f"=== Backup started for {job['name']} ===")

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

                cmd = ["rsync", "-avh", "--delete", "--progress"]
                for exc in job.get("excludes", []):
                    cmd.extend(["--exclude", exc])
                cmd.extend([source, target + "/"])

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
        "excludes": data.get("excludes", []),
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

    thread = threading.Thread(target=run_backup, args=(job,), daemon=True)
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
    config = load_config()
    sizes = {}
    all_jobs = config["backup_jobs"] + config.get("custom_jobs", [])
    for job in all_jobs:
        total = []
        for src in job.get("sources", []):
            if os.path.exists(src):
                total.append(get_dir_size(src))
        sizes[job["id"]] = ", ".join(total) if total else "N/A"
    return jsonify(sizes)


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
    app.run(host="0.0.0.0", port=9999, debug=True)
