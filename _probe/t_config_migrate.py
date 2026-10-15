"""验证配置迁移：可重入、不破坏其它字段、能纠正旧值。"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


# ---- 1. 用临时数据目录模拟「老版本配置」 ----
TMP = tempfile.mkdtemp(prefix="cfgtest-")
os.environ["ANIME_DATA_DIR"] = TMP
from app.core import config   # noqa: E402

legacy = {
    "version": 1,
    "bangumi_token": "abc123",
    "qbittorrent": {"base_url": "http://127.0.0.1:8080", "category": "Bangumi",
                    "create_subfolder": True},
    "download": {"root": "D:\\Anime"},
}
with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(legacy, f, ensure_ascii=False, indent=2)

print("1. 老配置（version=1, create_subfolder=true）")
config._cache = None
c = config.load(force=True)
check("迁移后 version=3", c.get("version") == 3, c.get("version"))
check("迁移后 create_subfolder=False", c["qbittorrent"]["create_subfolder"] is False,
      c["qbittorrent"]["create_subfolder"])
check("v3：关键词预算提到 10（旧配置里存的 4 会被纠正）",
      int(c["search"]["max_keyword_variants"]) >= 10, c["search"]["max_keyword_variants"])
check("用户自己的字段没被破坏（token）", c.get("bangumi_token") == "abc123", c.get("bangumi_token"))
check("用户自己的字段没被破坏（下载目录）", c["download"]["root"] == "D:\\Anime", c["download"]["root"])
check("新增默认值已补齐（cache 段）", isinstance(c.get("cache"), dict), str(c.get("cache"))[:60])

disk = json.load(open(config.CONFIG_PATH, encoding="utf-8"))
check("改动已落盘", disk.get("version") == 3 and disk["qbittorrent"]["create_subfolder"] is False)
check("落盘内容保留 token", disk.get("bangumi_token") == "abc123")

print("\n2. 可重入：连续读 3 次结果一致且不再改动")
snapshots = []
for _ in range(3):
    config._cache = None
    cc = config.load(force=True)
    snapshots.append(json.dumps(cc, ensure_ascii=False, sort_keys=True))
check("三次读取结果完全一致", len(set(snapshots)) == 1)
mtime1 = os.path.getmtime(config.CONFIG_PATH)
config._cache = None
config.load(force=True)
check("已迁移的配置不再重复写盘", os.path.getmtime(config.CONFIG_PATH) == mtime1)

print("\n3. 用户显式改回 True 时尊重用户选择（迁移只跑一次）")
c2 = config.load()
c2["qbittorrent"]["create_subfolder"] = True
config.save(c2)
config._cache = None
c3 = config.load(force=True)
check("用户显式设为 true 后不被再次覆盖（version 已是 3，迁移不重复执行）",
      c3["qbittorrent"]["create_subfolder"] is True, c3["qbittorrent"]["create_subfolder"])

print("\n4. 生产配置现状")
prod = json.load(open(os.path.join(ROOT, "data", "config.json"), encoding="utf-8"))
check("生产配置 version=3", prod.get("version") == 3, prod.get("version"))
check("生产配置关键词预算 >= 10", int(prod["search"]["max_keyword_variants"]) >= 10,
      prod["search"]["max_keyword_variants"])
check("生产配置 create_subfolder=False（不再多包一层文件夹）",
      prod["qbittorrent"].get("create_subfolder") is False,
      prod["qbittorrent"].get("create_subfolder"))
check("生产配置 token 仍在", len(prod.get("bangumi_token") or "") == 40, len(prod.get("bangumi_token") or ""))
check("生产配置下载目录仍是 D:\\Anime", prod["download"]["root"] == "D:\\Anime", prod["download"]["root"])

import shutil   # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
