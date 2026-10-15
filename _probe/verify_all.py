"""最终验证：编译、单元测试、离线解析/追番测试、API 联调、端到端（真实 qBittorrent）。"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

STEPS = [
    ("① 语法编译检查", [sys.executable, "-m", "compileall", "-q", "app"]),
    ("② 单元测试套件（164 例）", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]),
    ("③ 解析/排序/字幕组离线自测", [sys.executable, r"_probe\t_parse.py"]),
    ("④ 追番引擎离线自测", [sys.executable, r"_probe\t_watcher.py"]),
    ("⑤ 后端 API 联调（真实 Bangumi + qBittorrent）", [sys.executable, r"_probe\t_api.py"]),
    ("⑥ 端到端（加入订阅 -> qB 收任务 -> 追新 -> 清理）", [sys.executable, r"_probe\t_e2e.py"]),
]

results = []
for name, cmd in STEPS:
    print("\n" + "=" * 78)
    print(name)
    print("=" * 78)
    proc = subprocess.run(cmd, env=ENV, capture_output=True, text=True, errors="replace")
    tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-6:]
    for ln in tail:
        print("   ", ln[:160])
    if proc.returncode != 0 and proc.stderr:
        print("    stderr:", proc.stderr.strip().splitlines()[-1][:200] if proc.stderr.strip() else "")
    results.append((name, proc.returncode))

print("\n" + "=" * 78)
print("汇总")
print("=" * 78)
fails = 0
for name, code in results:
    flag = "通过" if code == 0 else f"失败(exit {code})"
    fails += 0 if code == 0 else 1
    print(f"  [{flag:>12}] {name}")
print(f"\n共 {len(results)} 步，失败 {fails} 步")
sys.exit(1 if fails else 0)
