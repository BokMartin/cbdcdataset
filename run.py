import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    "score.py", "stats.py", "robustness.py", "privacy.py", "figures.py",
    "metrics.py", "spans.py", "split.py", "human_gold.py", "gold_candidate_audit.py",
    "ensemble_analysis_v10_2e.py", "verify_ensemble_analysis_v10_2e.py",
    "verify.py", "paper_check.py",
]

for step in STEPS:
    print(f"\n[{step}]", flush=True)
    command = [sys.executable, str(ROOT / "scripts" / step)]
    if step == "ensemble_analysis_v10_2e.py":
        command.append("--skip-figures")
    subprocess.run(command, check=True, cwd=ROOT)
