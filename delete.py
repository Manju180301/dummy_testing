#!/usr/bin/env python3

import os
import shutil
from datetime import datetime, timedelta
import logging
import re

# ✅ YOUR PATHS (Linux)
SOURCE_FOLDER = "/home/titans/humantracking_run/media/recognized_cctv"
BACKUP_FOLDER = "/home/titans/ht_backup_img"
KEEP_DAYS = 3

# ✅ LOG FILE
LOG_FILE = "/home/titans/delete_backup.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

today = datetime.now().date()
cutoff_date = today - timedelta(days=KEEP_DAYS - 1)

print("Today:", today)
print("Cutoff:", cutoff_date)

for root, dirs, files in os.walk(SOURCE_FOLDER):
    for file in files:

        if not file.lower().endswith(".jpg"):
            continue

        try:
            match = re.search(r'(\d{8})', file)

            if not match:
                logging.warning(f"Skipped (no date): {file}")
                continue

            date_str = match.group(1)
            file_date = datetime.strptime(date_str, "%Y%m%d").date()

        except Exception as e:
            logging.error(f"Error parsing {file}: {e}")
            continue

        file_path = os.path.join(root, file)

        if file_date < cutoff_date:

            relative_path = os.path.relpath(root, SOURCE_FOLDER)
            backup_dir = os.path.join(BACKUP_FOLDER, relative_path)

            os.makedirs(backup_dir, exist_ok=True)

            dest_path = os.path.join(backup_dir, file)

            try:
                shutil.move(file_path, dest_path)
                logging.info(f"Moved: {file_path} → {dest_path}")

            except Exception as e:
                logging.error(f"Move failed: {file_path} - {e}")

# ✅ Remove empty folders
for root, dirs, files in os.walk(SOURCE_FOLDER, topdown=False):
    if not os.listdir(root):
        try:
            os.rmdir(root)
            logging.info(f"Removed folder: {root}")
        except Exception as e:
            logging.error(f"Folder remove failed: {root} - {e}")

print("✅ Done")