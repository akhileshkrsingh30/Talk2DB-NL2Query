import sys
import subprocess

# Auto-install huggingface_hub if missing in virtual environment
try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("Installing 'huggingface_hub' package...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub"])
    from huggingface_hub import snapshot_download

import os

model_id = "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"
local_dir = r"C:\Users\Administrator\qwen2.5-coder-32b-awq"

print(f"\nResuming download for '{model_id}' to target directory:")
print(f"  {local_dir}\n")

try:
    snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        max_workers=4,
        resume_download=True
    )
    print("\n✓ Download completed successfully!")
except Exception as e:
    print(f"\n✗ Download error: {e}")
