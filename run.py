import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    "score.py", "stats.py", "robustness.py", "privacy.py", "figures.py",
    "metrics.py", "spans.py", "split.py", "verify.py", "paper_check.py",
]

for step in STEPS:
    print(f"\n[{step}]", flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / step)], check=True, cwd=ROOT)
