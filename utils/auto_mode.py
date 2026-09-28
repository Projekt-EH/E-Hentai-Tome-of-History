# E-Hentai Tome of History - a gallery comment fetcher and preserver for E-Hentai
# Copyright (C) 2026  Projekt-EH & AXIS5(AXIS5hacker)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import json
import time
import random
from datetime import datetime, timedelta

from .urlfetch import sleep_with_jitter
from .batch_crawling import crawl_uploader_galleries, crawl_gallery_urls
from .result import print_batch_crawling_report


def get_default_auto_config_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auto_jobs.json")


def parse_local_time(value, field_name):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError(f"{field_name} must use format YYYY-MM-DD HH:MM.")


def read_positive_float(config, key, default):
    value = config.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        print(f"Invalid {key}; using default {default}.")
        return default
    if value <= 0:
        print(f"Invalid {key}; using default {default}.")
        return default
    return value


def read_nonnegative_float(config, key, default):
    value = config.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        print(f"Invalid {key}; using default {default}.")
        return default
    if value < 0:
        print(f"Invalid {key}; using default {default}.")
        return default
    return value


def load_auto_config(config_path: str):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Auto config not found: {config_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Auto config is invalid JSON: {e}")
        return None

    if not isinstance(config, dict):
        print("Auto config must be a JSON object.")
        return None

    try:
        config["_start_at"] = parse_local_time(config.get("start_at"), "start_at")
        config["_end_at"] = parse_local_time(config.get("end_at"), "end_at")
    except ValueError as e:
        print(f"Auto config error: {e}")
        return None

    config["_interval_minutes"] = read_positive_float(config, "interval_minutes", 60)
    config["_interval_jitter"] = read_nonnegative_float(config, "interval_jitter", 0.10)
    jobs = config.get("jobs", [])
    if jobs is None:
        jobs = []
    if not isinstance(jobs, list):
        print("Auto config field jobs must be an array.")
        return None
    config["jobs"] = jobs
    return config


def get_interval_sleep_seconds(config: dict) -> float:
    base_seconds = config.get("_interval_minutes", 60) * 60
    jitter_seconds = base_seconds * config.get("_interval_jitter", 0.10)
    return random.uniform(base_seconds - jitter_seconds, base_seconds + jitter_seconds)


def normalize_gallery_urls(job: dict):
    if "url" in job:
        print("Gallery job uses unsupported field 'url'; use 'urls' instead.")
        return []

    urls_value = job.get("urls")
    if isinstance(urls_value, str):
        raw_urls = [urls_value]
    elif isinstance(urls_value, list):
        raw_urls = urls_value
    else:
        print("Gallery job requires urls as a string or string array.")
        return []

    urls = []
    seen = set()
    for url in raw_urls:
        if not isinstance(url, str) or not url.strip():
            print("Gallery job contains a non-string or empty URL; skipping that entry.")
            continue
        url = url.strip()
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        print("Gallery job has no valid URLs.")
    return urls


def run_gallery_job(job: dict, client=None):
    urls = normalize_gallery_urls(job)
    if client is None:
        raise ValueError("A MongoDB client is required for gallery jobs.")

    # Same path as the interactive mode: one shared buffer and one deletion-check snapshot for
    # the whole list of URLs of this job.
    crawl_gallery_urls(urls, client, label="Auto gallery job")


def run_uploader_job(job: dict, max_workers: int = 15, client=None):
    url = job.get("url")
    if not isinstance(url, str) or not url.strip():
        print("Uploader job requires url.")
        return

    if client is None:
        raise ValueError("A MongoDB client is required for uploader jobs.")

    page_depth_raw = job.get("page_depth")
    if page_depth_raw is None or str(page_depth_raw).strip() == "":
        page_depth = None
    else:
        try:
            page_depth = int(page_depth_raw)
            if page_depth < 0:
                raise ValueError
        except ValueError:
            print(f"Invalid uploader job page_depth: {page_depth_raw}")
            return

    report = crawl_uploader_galleries(url.strip(), page_depth, max_workers=max_workers, client=client)
    if report:
        print_batch_crawling_report(report)


def run_auto_jobs(jobs, max_workers: int = 15, client=None):
    enabled_jobs = [job for job in jobs if isinstance(job, dict) and job.get("enabled", True)]
    for index, job in enumerate(enabled_jobs, start=1):
        job_type = job.get("type")
        print(f"\nAuto job [{index}/{len(enabled_jobs)}]: {job_type or 'unknown'}")
        try:
            if job_type == "gallery":
                run_gallery_job(job, client=client)
            elif job_type == "uploader":
                run_uploader_job(job, max_workers=max_workers, client=client)
            else:
                print(f"Unsupported auto job type: {job_type}")
        except Exception as e:
            print(f"Auto job failed: {e}")
        if index < len(enabled_jobs):
            sleep_with_jitter()


def sleep_until_or_stop(seconds: float, end_at):
    deadline = datetime.now() + timedelta(seconds=max(0, seconds))
    while True:
        now = datetime.now()
        if end_at and now >= end_at:
            return False
        if now >= deadline:
            return True
        next_wake = min(deadline, now + timedelta(seconds=60))
        if end_at:
            next_wake = min(next_wake, end_at)
        time.sleep(max(0, (next_wake - now).total_seconds()))


def run_auto_mode(config_path: str, max_workers: int = 15, client=None):
    config_path = config_path or get_default_auto_config_path()
    print(f"Auto mode config: {config_path}")

    if load_auto_config(config_path) is None:
        return 1

    try:
        while True:
            config = load_auto_config(config_path)
            if config is None:
                return 1

            now = datetime.now()
            start_at = config.get("_start_at")
            end_at = config.get("_end_at")
            if end_at and now >= end_at:
                print("Auto mode reached end_at. Exiting.")
                return 0
            if start_at and now < start_at:
                wait_seconds = (start_at - now).total_seconds()
                print(f"Auto mode waiting until start_at: {start_at.strftime('%Y-%m-%d %H:%M')}")
                if not sleep_until_or_stop(wait_seconds, end_at):
                    print("Auto mode reached end_at before start_at. Exiting.")
                    return 0
                continue

            print(f"\nAuto mode round started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            run_auto_jobs(config.get("jobs", []), max_workers=max_workers, client=client)

            sleep_seconds = get_interval_sleep_seconds(config)
            print(f"Auto mode sleeping {sleep_seconds / 60:.2f} minutes before next round.")
            if not sleep_until_or_stop(sleep_seconds, end_at):
                print("Auto mode reached end_at. Exiting.")
                return 0
    except KeyboardInterrupt:
        print("\nAuto mode stopped by user.")
        return 0
