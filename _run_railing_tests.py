import subprocess
import sys

results = []
for cmd in [
    [sys.executable, "_repro_railing_1mm.py"],
    [sys.executable, "WEOS/_smoke_railing_pdf.py"],
]:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=r"d:\Downloads\window cad model")
    results.append(f"CMD {' '.join(cmd)}\nexit={p.returncode}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}\n")

open("_test_out.txt", "w", encoding="utf-8").write("\n---\n".join(results))
print("wrote _test_out.txt")
sys.exit(0 if all("exit=0" in r for r in results) else 1)
