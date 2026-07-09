#!/usr/bin/env python3
"""Delete browser-data profile for fresh device registration."""

import shutil
import subprocess
from pathlib import Path

from config import PROFILE_DIR


def main() -> None:
    subprocess.run(
        ["pkill", "-f", str(PROFILE_DIR)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR)
        print(f"Da xoa: {PROFILE_DIR}")
    else:
        print(f"Profile khong ton tai: {PROFILE_DIR}")

    print("Chay: python setup_profile.py de dang ky thiet bi moi.")


if __name__ == "__main__":
    main()
