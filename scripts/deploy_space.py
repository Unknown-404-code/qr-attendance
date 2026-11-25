"""Upload the app to a Hugging Face Space (Docker). Run it on your own computer after `huggingface-cli login`.

    pip install huggingface_hub
    huggingface-cli login                     # paste a token with "write" access from huggingface.co/settings/tokens
    python scripts/deploy_space.py --space your-name/attendance

The Space rebuilds itself after each upload (5-10 minutes the first time). Secrets are set on the Space's
Settings page, never here. See DEPLOY.md.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = ["Dockerfile", ".dockerignore", "requirements-app.txt", "configs/**", "src/gesture_attendance/**",
         "scripts/run_app.py", "scripts/_common.py"]
SKIP = ["**/__pycache__/**", "**/*.pyc"]

SPACE_README = """---
title: Attendance
emoji: ✋
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

Classroom attendance with a rotating QR code, a random hand sign and a face check.
Open the app at https://{subdomain}.hf.space (not this page) so sign-in and the camera work.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True, help="your-name/space-name")
    args = ap.parse_args()
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise SystemExit("Run `pip install huggingface_hub` first.")

    api = HfApi()
    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    subdomain = args.space.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        readme.write_text(SPACE_README.format(subdomain=subdomain), encoding="utf-8")
        api.upload_file(path_or_fileobj=str(readme), path_in_repo="README.md", repo_id=args.space, repo_type="space")
    api.upload_folder(folder_path=str(ROOT), repo_id=args.space, repo_type="space", allow_patterns=FILES,
                      ignore_patterns=SKIP, commit_message="Deploy attendance app")
    print(f"Uploaded. Build progress: https://huggingface.co/spaces/{args.space}")
    print(f"When it says Running, open:  https://{subdomain}.hf.space")


if __name__ == "__main__":
    main()
