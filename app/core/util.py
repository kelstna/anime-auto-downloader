# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
文本与通用工具：Windows 文件名净化、剧集编号解析、大小/时间解析、中文简繁转换。
仅使用标准库。
"""
from __future__ import annotations

import datetime
import os
import re
from datetime import date
from functools import lru_cache
import unicodedata
from typing import Iterable, Optional

# --------------------------------------------------------------------------- #
# Windows 文件/目录名净化
# --------------------------------------------------------------------------- #
_WIN_FORBIDDEN = r'<>:"/\|?*'
# 方括号等不是 Windows 非法字符，但番剧名/字幕组名里的 []【】 属于标记，去掉更干净
_WIN_STRIP_CHARS = "[]【】{}「」『』"
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_FALLBACK_NAME = "未命名"


def sanitize_name(name: str, fallback: str | None = None, max_len: int = 120) -> str:
    """
    把任意字符串净化成安全的 Windows 文件/目录名。
    - 去掉 Windows 非法字符与控制字符，以及作标记用的方括号/书名号
    - 去掉结尾的点与空格（Windows 不允许）
    - 规避 CON/PRN 等保留名
    - 空结果时返回 fallback（默认「未命名」）
    """
    fallback = fallback or _FALLBACK_NAME
    if not name:
        return fallback
    name = name.replace("\u3000", " ")
    out = []
    for ch in name:
        if ch in _WIN_FORBIDDEN or ch in _WIN_STRIP_CHARS or ord(ch) < 32:
            continue
        out.append(ch)
    s = re.sub(r"\s+", " ", "".join(out)).strip().rstrip(". ")
    if not s:
        return fallback
    if s.upper() in _WIN_RESERVED or s.split(".")[0].upper() in _WIN_RESERVED:
        s = "_" + s
    if len(s) > max_len:
        s = s[:max_len].rstrip(". ")
    return s or fallback


def join_path(root: str, *parts: str) -> str:
    return os.path.normpath(os.path.join(root, *parts))


# --------------------------------------------------------------------------- #
# 剧集编号解析
# --------------------------------------------------------------------------- #
_EP_PATTERNS = (
    re.compile(r"[Ss]\d{1,2}\s*[Ee][Pp]?(\d{1,4})"),                       # S02E05
    re.compile(r"(?:^|[\s\[\]（）()_\-–—~～])(?:EP|Ep|ep|E)\s*0*(\d{1,4})(?![\dA-Za-z])"),
    re.compile(r"第\s*0*(\d{1,4})\s*[话話集回]"),                            # 第09话 / 第9集
    re.compile(r"\[\s*0*(\d{1,4})\s*(?:v\d)?\s*\]"),                        # [09] / [12v2]
    re.compile(r"【\s*0*(\d{1,4})\s*】"),
    re.compile(r"[\s\-–—_]\s*0*(\d{1,4})\s*(?:v\d)?\s*(?:$|[\s\[(])"),      # Title - 09 [
)
_RANGE_PATTERNS = (
    re.compile(r"\[\s*0*(\d{1,4})\s*[-~～]\s*0*(\d{1,4})\s*(?:v\d)?\s*\]"),  # [01-12]
    re.compile(r"第\s*0*(\d{1,4})\s*[-~～]\s*0*(\d{1,4})\s*[话話集]"),
    re.compile(r"[\s\[(]0*(\d{1,4})\s*[-~～]\s*0*(\d{1,4})\s*(?:END|Fin|fin|全集|完)"),
)
_BATCH_HINTS = (
    "全集", "合集", "季度全集", "batch", "fin", "end", "完", "movie",
    "剧场版", "劇場版", "oad", "ova 合集",
)

# 季数标记：「Season 2」「第2季」「2nd Season」「S02」（S02E05 里的 S02 不动，那是集号前缀）。
# 解析集数前先把它们抹成空格，否则「[ANi] Season 2 - 171」会被解析成第 2 集（用户报的 bug：
# 黑色五叶草第二季的发布组沿用系列连续编号 171，界面却显示成第 2 集）。
_SEASON_MASK = re.compile(
    r"第\s*[0-9０-９一二三四五六七八九十]+\s*[季期部]"
    r"|[0-9]{1,2}(?:st|nd|rd|th)\s+season"
    r"|season\s*[0-9]{1,2}"
    r"|(?<![A-Za-z0-9])s[0-9]{1,2}(?![Ee0-9])",
    re.I)

# 明显不是本篇剧集的标题特征（PV/CM/音乐/字幕单独文件等）
_NOISE_PATTERNS = (
    re.compile(r"\b(pv|cm|sp\d?|ncop|nced|menu|creditless)\b", re.I),
    re.compile(r"(先行|预告|預告|音乐|音樂|无损|無損|flac|专辑|專輯|\bost\b|\bcd\b|op单曲|ed单曲)", re.I),
    re.compile(r"(字幕|subtitle)\s*(文件|文件包)?\s*$", re.I),
)


def is_noise_title(title: str) -> bool:
    """判断是否是 PV/音乐/字幕之类应当默认忽略的资源。"""
    return any(p.search(title or "") for p in _NOISE_PATTERNS)


def _aniparse_numbers(title: str) -> list[int]:
    """
    用 aniparse（参考项目 anime-server-autowidth-2.5 用的同一个解析库）读文件名里的集号。
    它是「按概率评分」的解析器，比自己写的正则更能分辨 1080p/年份/版本号之类。
    没装这个库、或解析不出来时返回空列表，由下面的正则兜底。
    """
    try:
        import aniparse                      # 可选依赖：装了就优先用
    except Exception:                        # noqa: BLE001
        return []
    try:
        result = aniparse.parse(title) or {}
        series = result.get("series") or []
        if not series:
            return []
        nums = []
        for ep in (series[0].get("episode") or []):
            num = ep.get("number")
            try:
                num = int(num)
            except (TypeError, ValueError):
                continue
            if 0 <= num <= 5000:
                nums.append(num)
        return nums
    except Exception:                        # noqa: BLE001
        return []


# 这些数字不是集号：帧率（143.8561fps）、位深（10bit）、编码（x265/H.264/AVC）、音频（AAC2.0）
_NON_EPISODE_NUMBERS = re.compile(
    r"\d+(?:\.\d+)?\s*fps"
    r"|\d+\s*bit"
    r"|[xh]\.?26[45]"
    r"|\bavc\b|\bhevc\b|\baac\d?(?:\.\d+)?",
    re.I)


def parse_episode_range(title: str) -> tuple[Optional[int], Optional[int], bool]:
    """解析标题的剧集范围，返回 (起始, 结束, 是否合集)。无法解析返回 (None, None, is_batch)。"""
    if not title:
        return None, None, False
    low = title.lower()
    is_batch = any(h in low for h in _BATCH_HINTS)
    # 先把季数标记抹掉：Season 2 / 第2季 / 2nd Season / S02 里的数字不是集数
    probe = _SEASON_MASK.sub(" ", title)
    # 再抹掉「不是集数」的数字：帧率 143.8561fps、10bit、x265、H.264、AAC2.0 之类
    probe = _NON_EPISODE_NUMBERS.sub(" ", probe)

    for pat in _RANGE_PATTERNS:
        m = pat.search(probe)
        if not m:
            continue
        try:
            a, b = int(m.group(1)), int(m.group(2))
        except (TypeError, ValueError):
            continue
        if 0 <= a <= b <= 2000 and (b - a) >= 1:
            return a, b, True

    # 优先用 aniparse（与参考项目同款解析器）：它能区分 1080p、年份、版本号、季数
    nums = _aniparse_numbers(probe)
    if len(nums) >= 2 and nums[1] > nums[0]:
        return nums[0], nums[1], True
    if len(nums) == 1:
        return nums[0], nums[0], is_batch

    for pat in _EP_PATTERNS:
        for m in pat.finditer(probe):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 <= n <= 2000:
                return n, n, is_batch
    return None, None, is_batch


def parse_episode(title: str) -> Optional[int]:
    """取标题中最可能的单集编号（合集取结束话）。"""
    a, b, _ = parse_episode_range(title)
    return None if a is None else b


def parse_resolution(text: str) -> str:
    """从标题中提取分辨率标记，统一成 2160p/1080p/720p 形式。"""
    if not text:
        return ""
    m = re.search(r"(2160p|1440p|1080p|1080i|720p|576p|480p|8K|4K)", text, re.I)
    if not m:
        return ""
    low = m.group(1).lower()
    return {"4k": "2160p", "8k": "4320p"}.get(low, low)


_SIZE_UNITS = {
    "B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4,
    "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4,
}


def parse_size(text: str) -> int:
    """'1.4 GiB' / '48.5GB' -> 字节数；解析失败返回 0。"""
    if not text:
        return 0
    m = re.search(r"([\d.]+)\s*([KMGT]?i?B)", text, re.I)
    if not m:
        return 0
    try:
        val = float(m.group(1))
    except ValueError:
        return 0
    return int(val * _SIZE_UNITS.get(m.group(2).upper(), 1))


def human_size(n: int) -> str:
    if not n:
        return "-"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024.0 or unit == "TB":
            return f"{int(v)} B" if unit == "B" else f"{v:.2f} {unit}"
        v /= 1024.0
    return "-"


def lan_ipv4_addresses(host: str = "") -> list[str]:
    """
    本机可用于**局域网访问**的 IPv4 地址（给「允许局域网访问」那个开关显示用）。

    纯标准库实现：`getaddrinfo(主机名)` 拿本机所有地址，然后过滤掉
      - 回环 127.*            —— 别人访问不到
      - 链路本地 169.254.*     —— 没有 DHCP 时的自动地址
      - 198.18.0.0/15         —— 代理软件（Clash/Meta）的 fake-IP 段，不是真网卡
    剩下的按「家用/办公网最常见」排序：192.168.* → 10.* → 172.16~31.* → 其它，
    这样用户一眼就能认出该在手机/平板上填哪个（比如 192.168.1.100）。
    """
    import socket as _socket
    addrs: set[str] = set()
    candidates = []
    if host and host not in ("0.0.0.0", "::"):
        candidates.append(host)
    try:
        candidates.append(_socket.gethostname())
    except OSError:
        pass
    for name in candidates:
        try:
            infos = _socket.getaddrinfo(name, None, _socket.AF_INET)
        except (OSError, UnicodeError):
            continue
        for info in infos:
            ip = str(info[4][0])
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip.startswith("198.18.") or ip.startswith("198.19."):
                continue
            addrs.add(ip)

    def rank(ip: str) -> tuple:
        if ip.startswith("192.168."):
            return (0, ip)
        if ip.startswith("10."):
            return (1, ip)
        if ip.startswith("172.") and len(ip.split(".")) > 1:
            try:
                second = int(ip.split(".")[1])
            except ValueError:
                second = 0
            return (2, ip) if 16 <= second <= 31 else (4, ip)
        return (3, ip)

    return sorted(addrs, key=rank)


# --------------------------------------------------------------------------- #
# 中文简繁转换（显式映射表，覆盖番剧名高频字）
# --------------------------------------------------------------------------- #
# 键=繁体，值=简体。用显式字典而不是「两字一组」的紧凑字符串，
# 避免手工排版错位导致整表串位（曾出现过这类 bug）。
_T2S_MAP: dict[str, str] = {
    # —— 日常高频 ——
    "這": "这", "個": "个", "們": "们", "來": "来", "時": "时", "會": "会", "對": "对",
    "後": "后", "點": "点", "國": "国", "學": "学", "實": "实", "樣": "样", "麼": "么",
    "種": "种", "義": "义", "聲": "声", "體": "体", "戰": "战", "記": "记", "將": "将",
    "總": "总", "過": "过", "應": "应", "頭": "头", "長": "长", "見": "见", "話": "话",
    "業": "业", "產": "产", "動": "动", "務": "务", "區": "区", "單": "单", "幹": "干",
    "廣": "广", "從": "从", "愛": "爱", "戲": "戏", "擊": "击", "數": "数", "於": "于",
    "書": "书", "樂": "乐", "機": "机", "氣": "气", "決": "决", "沒": "没", "燈": "灯",
    "爾": "尔", "獨": "独", "現": "现", "環": "环", "畫": "画", "當": "当", "發": "发",
    "盡": "尽", "監": "监", "盤": "盘", "眾": "众", "綠": "绿", "網": "网", "線": "线",
    "編": "编", "續": "续", "羅": "罗", "習": "习", "聯": "联", "聽": "听", "臉": "脸",
    "臨": "临", "舊": "旧", "華": "华", "萬": "万", "藍": "蓝", "藝": "艺", "藥": "药",
    "處": "处", "號": "号", "術": "术", "衛": "卫", "補": "补", "裝": "装", "複": "复",
    "觀": "观", "規": "规", "視": "视", "覺": "觉", "覽": "览", "計": "计", "訓": "训",
    "討": "讨", "訊": "讯", "評": "评", "詞": "词", "週": "周", "遊": "游", "遞": "递",
    "遠": "远", "適": "适", "選": "选", "遺": "遗", "鄉": "乡", "醫": "医", "釋": "释",
    "銀": "银", "錢": "钱", "錄": "录", "鐘": "钟", "閉": "闭", "閒": "闲", "關": "关",
    "陳": "陈", "陸": "陆", "隊": "队", "階": "阶", "隨": "随", "險": "险", "隱": "隐",
    "雖": "虽", "雙": "双", "雜": "杂", "雞": "鸡", "難": "难", "雲": "云", "電": "电",
    "靜": "静", "頁": "页", "頂": "顶", "項": "项", "順": "顺", "須": "须", "預": "预",
    "領": "领", "顏": "颜", "願": "愿", "類": "类", "顧": "顾", "顯": "显", "風": "风",
    "飛": "飞", "飢": "饥", "飯": "饭", "飲": "饮", "飾": "饰", "養": "养", "館": "馆",
    "馬": "马", "駐": "驻", "驗": "验", "髮": "发", "鬥": "斗", "魯": "鲁", "鮮": "鲜",
    "鳥": "鸟", "鳴": "鸣", "麗": "丽", "麥": "麦", "黃": "黄", "齊": "齐", "齒": "齿",
    "龍": "龙", "龜": "龟", "黨": "党", "與": "与", "東": "东", "車": "车", "魚": "鱼",
    "歲": "岁", "歷": "历", "歸": "归", "殘": "残", "殺": "杀", "為": "为", "無": "无",
    "煙": "烟", "熱": "热", "營": "营", "燒": "烧", "爭": "争", "牆": "墙", "獎": "奖",
    "稱": "称", "穩": "稳", "窮": "穷", "競": "竞", "筆": "笔", "節": "节", "範": "范",
    "築": "筑", "簡": "简", "籃": "篮", "籤": "签", "紀": "纪", "紅": "红", "純": "纯",
    "紙": "纸", "級": "级", "紛": "纷", "細": "细", "終": "终", "組": "组", "結": "结",
    "絕": "绝", "統": "统", "絲": "丝", "經": "经", "緊": "紧", "緒": "绪", "緣": "缘",
    "緩": "缓", "練": "练", "縮": "缩", "織": "织", "繼": "继", "纏": "缠", "罰": "罚",
    "誼": "谊", "請": "请", "諾": "诺", "謀": "谋", "講": "讲", "謝": "谢", "證": "证",
    "議": "议", "護": "护", "譽": "誉", "變": "变", "戀": "恋", "灣": "湾", "歡": "欢",
    "歐": "欧", "設": "设", "訪": "访", "訴": "诉", "試": "试", "詩": "诗", "誠": "诚",
    "誤": "误", "調": "调", "談": "谈", "讓": "让", "認": "认", "識": "识", "語": "语",
    "說": "说", "讀": "读", "誰": "谁", "課": "课", "諸": "诸", "際": "际", "陽": "阳",
    "陰": "阴", "門": "门", "問": "问", "間": "间", "開": "开", "貝": "贝",
    # —— 作品名常见 ——
    "構": "构", "槍": "枪", "標": "标", "樓": "楼", "樹": "树", "橋": "桥", "檢": "检",
    "權": "权", "毆": "殴", "沖": "冲", "淨": "净", "淚": "泪", "淺": "浅", "測": "测",
    "渾": "浑", "溝": "沟", "滅": "灭", "滿": "满", "潔": "洁", "濃": "浓", "濕": "湿",
    "瀨": "濑", "濤": "涛", "瀧": "泷", "災": "灾", "烏": "乌", "煩": "烦", "疊": "叠",
    "睜": "睁", "瞞": "瞒", "矯": "矫", "礎": "础", "穀": "谷", "窩": "窝", "竄": "窜",
    "篩": "筛", "籬": "篱", "粧": "妆", "佈": "布", "餘": "余", "彆": "别", "參": "参",
    "隻": "只", "臺": "台", "檯": "台", "颱": "台", "幾": "几", "據": "据", "劃": "划",
    "嚇": "吓", "準": "准", "涼": "凉", "凱": "凯", "剛": "刚", "創": "创", "劍": "剑",
    "勁": "劲", "勝": "胜", "勞": "劳", "勢": "势", "協": "协", "卻": "却", "嚴": "严",
    "囑": "嘱", "團": "团", "園": "园", "圍": "围", "圖": "图", "執": "执", "場": "场",
    "塊": "块", "夢": "梦", "奪": "夺", "奮": "奋", "婦": "妇", "媽": "妈", "嫵": "妩",
    "孫": "孙", "寧": "宁", "寶": "宝", "審": "审", "寫": "写", "寬": "宽", "層": "层",
    "島": "岛", "峽": "峡", "崗": "岗", "嶺": "岭", "巖": "岩", "帥": "帅", "師": "师",
    "帳": "帐", "帶": "带", "幫": "帮", "庫": "库", "廟": "庙", "廢": "废", "彈": "弹",
    "彙": "汇", "徹": "彻", "徑": "径", "憶": "忆", "懷": "怀", "懸": "悬", "懼": "惧",
    "懇": "恳", "懶": "懒", "戶": "户", "紮": "扎", "擴": "扩", "攔": "拦", "攝": "摄",
    "擺": "摆", "攜": "携", "敗": "败", "敵": "敌", "斃": "毙", "斷": "断", "暢": "畅",
    "極": "极", "疇": "畴", "瘋": "疯", "療": "疗", "癢": "痒", "瞭": "了", "矚": "瞩",
    "礙": "碍", "禮": "礼", "積": "积", "粵": "粤", "針": "针", "鑑": "鉴", "頸": "颈",
    "鴉": "鸦", "鵝": "鹅", "鷹": "鹰", "鹹": "咸", "爲": "为", "證": "证", "讚": "赞",
    "豔": "艳", "賺": "赚", "贈": "赠", "趕": "赶", "踴": "踊", "蹟": "迹",
    "軀": "躯", "車": "车", "軌": "轨", "軍": "军", "軒": "轩", "軟": "软", "較": "较",
    "載": "载", "輔": "辅", "輕": "轻", "輝": "辉", "輩": "辈", "輪": "轮", "輸": "输",
    "轉": "转", "辦": "办", "農": "农", "邊": "边", "邏": "逻", "郵": "邮", "鄉": "乡",
    "醫": "医", "醜": "丑", "釋": "释", "鐘": "钟", "鋼": "钢", "錯": "错", "錄": "录",
    "錢": "钱", "鍋": "锅", "鎮": "镇", "鏡": "镜", "鐵": "铁", "鑄": "铸", "長": "长",
    "閃": "闪", "閉": "闭", "閱": "阅", "闊": "阔", "隊": "队", "陽": "阳", "隨": "随",
    "難": "难", "霧": "雾", "靈": "灵", "韓": "韩", "韻": "韵", "頁": "页", "頂": "顶",
    "順": "顺", "須": "须", "預": "预", "領": "领", "頻": "频", "題": "题", "顏": "颜",
    "願": "愿", "類": "类", "顧": "顾", "顯": "显", "風": "风", "飛": "飞", "飆": "飙",
    "飾": "饰", "養": "养", "餓": "饿", "館": "馆", "馬": "马", "駕": "驾",
    "騎": "骑", "驚": "惊", "體": "体", "髮": "发", "鬥": "斗", "魯": "鲁",
    "鮮": "鲜", "鳥": "鸟", "鳳": "凤", "鳴": "鸣", "鴻": "鸿", "鵬": "鹏", "鶴": "鹤",
    "鷹": "鹰", "麗": "丽", "黃": "黄", "點": "点", "齊": "齐", "齒": "齿", "龍": "龙",
    "龜": "龟",
}

# 完整对照表：app/data/t2s.tsv（OpenCC 标准字典，约 4100 条）。
# 上面的手写表作为兜底，两者合并后以文件内容为准（文件更权威）。
_T2S_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "t2s.tsv")


def _load_t2s_file() -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        with open(_T2S_DATA, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2 and len(parts[0]) == 1 and len(parts[1]) == 1:
                    table[parts[0]] = parts[1]
    except OSError:
        pass
    return table


# 启动时自检：保证不存在「自我映射」，防止手工维护时写错
_T2S_MAP_FULL: dict[str, str] = {}
for _tr, _si in _load_t2s_file().items():
    if _tr != _si:
        _T2S_MAP_FULL[_tr] = _si
for _tr, _si in _T2S_MAP.items():          # 手写表补充（不覆盖文件内容）
    if _tr != _si:
        _T2S_MAP_FULL.setdefault(_tr, _si)

_T2S: dict[int, str] = {ord(_tr): _si for _tr, _si in _T2S_MAP_FULL.items()}
# 反向表：简体 -> 繁体。同一简体字可能对应多个繁体字，保留先出现的（文件顺序更常用）
_T2S_REVERSE: dict[int, str] = {}
for _tr, _si in _T2S_MAP_FULL.items():
    _T2S_REVERSE.setdefault(ord(_si), _tr)
del _tr, _si, _T2S_MAP


def t2s_size() -> int:
    """对照表条目数（自检/测试用）。"""
    return len(_T2S)


def to_simplified(text: str) -> str:
    """繁体 -> 简体（表驱动，未收录字符原样保留）。"""
    return text.translate(_T2S) if text else ""


def to_traditional(text: str) -> str:
    """简体 -> 繁体（反向映射，未收录字符原样保留）。"""
    return text.translate(_T2S_REVERSE) if text else ""


def has_traditional(text: str) -> bool:
    return any(ord(ch) in _T2S for ch in (text or ""))


def normalize_title(text: str) -> str:
    """归一化标题用于比较：全角转半角、去掉空格与标点、转小写。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s\-_~～·、,，。.！!？?：:；;（）()\[\]【】「」『』/\\|]+", "", s)


# --------------------------------------------------------------------------- #
# 搜索关键词清洗（用户要求：不带标点、多段用空格隔开、不带第几季）
# --------------------------------------------------------------------------- #
# 站内搜索基本都是「标题 LIKE %关键词%」，关键词里多一个标点就少一堆结果：
#   「野生的大魔王出现了！第二季」在动漫花园只搜到 2 条，而「野生的大魔王出现了」能搜到 11 条。
# 所以：
#   1) 中日文全角标点（！？。，、·～…「」【】等）一律换成空格 —— 它们是标题里的装饰，
#      换成空格反而能匹配上「出现了！ 第二季」这种带空格的写法；
#   2) ASCII 标点（- : . & × 等）默认保留，因为英文标题里它们有意义
#      （「FX Senshi Kurumi-chan」去掉连字符反而搜不到），需要时另给一个更激进的变体兜底；
#   3) 「第2季 / 第二期 / Season 2 / S02 / 2nd Season」一律去掉：带上它站内搜索会漏掉大量结果。
_CJK_PUNCT = "！？。，、；：·・…‥～〜「」『』【】〔〕〖〗（）《》〈〉｛｝［］“”‘’｜＼　"
_ASCII_PUNCT = "!?.,;:~`\"'*+=<>|{}[]()×※÷°/\\"
_SEASON_RE = re.compile(
    r"第\s*[0-9０-９一二三四五六七八九十]+\s*[季期部]"
    r"|\b[0-9]{1,2}(?:st|nd|rd|th)\s+season\b"
    r"|\bseason\s*[0-9]{1,2}\b"
    r"|(?<![A-Za-z0-9])s[0-9]{1,2}(?![0-9])",
    re.I)
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def season_of(text: str) -> int:
    """
    从番剧名/资源标题里抽出「第几季」，没有则返回 0。

    用途：关键词里不再带「第二季」之后，搜索结果会混进其它季的资源，
    自动追番必须能认出「这是第 3 季的资源」，别把第 1 季当成新集下载。
    """
    if not text:
        return 0
    t = unicodedata.normalize("NFKC", str(text))
    for m in _SEASON_RE.finditer(t):
        raw = m.group(0)
        num = re.search(r"[0-9]+", raw)
        if num:
            return int(num.group(0))
        cn = re.search(r"([一二三四五六七八九十]+)", raw)
        if not cn:
            continue
        s = cn.group(1)
        if len(s) == 1:
            return _CN_DIGITS.get(s, 0)
        if s.startswith("十"):
            return 10 + _CN_DIGITS.get(s[1:], 0)
        if s.endswith("十"):
            return _CN_DIGITS.get(s[0], 0) * 10
        if "十" in s:
            a, _, b = s.partition("十")
            return _CN_DIGITS.get(a, 0) * 10 + _CN_DIGITS.get(b, 0)
    return 0


def clean_keyword(text: str, *, drop_season: bool = True, cjk_only: bool = False) -> str:
    """
    清洗站内搜索关键词：中日文标点 -> 空格、折叠空白、去掉「第几季」。

    cjk_only=True 时连 ASCII 标点也换成空格（更激进的变体，作为兜底关键词）。
    """
    s = str(text or "")
    # 先处理全角标点：NFKC 会把「！」变成半角「!」，之后就认不出来了
    s = s.translate({ord(ch): " " for ch in _CJK_PUNCT})
    s = unicodedata.normalize("NFKC", s)
    s = s.translate({ord(ch): " " for ch in _CJK_PUNCT})
    if cjk_only:
        s = s.translate({ord(ch): " " for ch in _ASCII_PUNCT})
    if drop_season:
        s = _SEASON_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -_·:./・")
    return s


def episode_offset_for(episodes: Iterable[int], total_episodes: int) -> int:
    """
    判断一批资源的集号用的是「整部系列的连续编号」还是「本季编号」，返回要减掉的偏移量。

    只看「超过本季话数」的那些集号（连续编号一定超过本季话数），要求它们自身跨度不超过本季长度：
      药屋少女的呢喃 第三季（12 话）结果里是 49~60 → 偏移 48（49 就是本季第 1 集）
      黑色五叶草 第二季（13 话）结果里混着第 1 季的 20/40/72 和本季的 171 → 跨度太大，这里判不出来，
      由 resolve_episode_offset() 的「季数标记」那条规则接手
    判不出来就返回 0（不换算），绝不瞎猜。
    """
    try:
        total = int(total_episodes or 0)
    except (TypeError, ValueError):
        return 0
    if total < 3:
        return 0
    eps = sorted({int(e) for e in episodes if isinstance(e, int) and 0 < e <= 5000})
    high = [e for e in eps if e > total]
    if not high:
        return 0
    if high[-1] - high[0] + 1 > total + 2:
        return 0
    return high[0] - 1


def _item_field(item, name: str, default=None):
    """兼容 dict 与 Resource 对象（两者都能取字段）。"""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


_DATE_IN_TEXT = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def date_ordinal(text) -> int:
    """把 `2026/10/03 23:00`、`2026-10-02` 之类变成日期序号（用于比较先后）；认不出返回 0。"""
    m = _DATE_IN_TEXT.search(str(text or ""))
    if not m:
        return 0
    try:
        y, mo, d = (int(x) for x in m.groups())
        return datetime.date(y, mo, d).toordinal()
    except (TypeError, ValueError):
        return 0


def resolve_episode_offset(items: Iterable, total_episodes: int,
                           sub_season: int = 0, air_date: str = "") -> tuple[int, int]:
    """
    综合判断「系列连续编号」的换算方式，返回 (偏移量, 该季最小集号 = 本季第 1 集在标题里的编号)。

    三条规则按可靠程度依次尝试，都判不出来就返回 (0, 0) 不换算：

    1. **发布时间**（最可靠）：本季开播那天的资源才是本季的。
       药屋少女的呢喃 第三季（12 话）开播 2026-10-02，之前的资源是第 1/2 季的 1~48，
       开播之后的只有 49~ → 本季起点 49、偏移 48。
    2. **标题里的季数标记**：黑色五叶草第二季的结果混着第 1 季（20/40/72…）和本季（171…），
       只有带「Season 2 / 2nd Season」的那批属于本季，最小集号 171 就是起点。
    3. **整批超过本季话数的集号是否连续**：只有一批 171~183 这种连续编号时的兜底判断。
    """
    rows = list(items)
    try:
        total = int(total_episodes or 0)
    except (TypeError, ValueError):
        total = 0
    if total < 3:
        return 0, 0

    def base_from(eps: list[int]) -> tuple[int, int]:
        """
        从一批集号里找「本季起点」：只看超过本季话数的那些（连续编号一定超过本季话数），
        它们必须自身连续（跨度不超过本季长度）才认。
        同一批里有人用本季编号（1、2…）也照样能用：它们不参与，起点仍按连续编号那批算。
        """
        high = [e for e in eps if e > total]
        if high and high[-1] - high[0] + 1 <= total + 2:
            return high[0] - 1, high[0]
        return 0, 0

    def eps_of(subset) -> list[int]:
        return sorted({e for e in (_item_field(it, "episode") for it in subset)
                       if isinstance(e, int) and 0 < e <= 5000})

    # 规则 1：发布时间在本季开播前后一周内（本季资源；放宽是为了容纳先行配信 —— 
    # 野生的大魔王出现了！第二季 电视开播 2026-10-03，但先行配信的 13（=本季第 1 集）09-27 就发了）
    air = date_ordinal(air_date)
    if air:
        got = base_from(eps_of([it for it in rows
                                if date_ordinal(_item_field(it, "published", "")) >= air - 7]))
        if got[0]:
            return got

    # 规则 2：标题里写明本季季数
    if sub_season:
        got = base_from(eps_of([it for it in rows
                                if season_of(str(_item_field(it, "title", "") or "")) == sub_season]))
        if got[0]:
            return got

    # 规则 3：所有资源一起看
    return base_from(eps_of(rows))


_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})"),
    re.compile(r"(\d{4})(\d{2})(\d{2})"),
)


def parse_date(value) -> "date | None":
    """从 '2026/10/17 18:50'、'2026-10-17'、'2026年10月17日' 这类字符串里取日期（精确到天）。"""
    text = str(value or "").strip()
    if not text:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


def in_current_season(item, *, base: int, total_episodes: int, sub_season: int = 0,
                      air_date: str = "") -> bool:
    """
    这条资源属不属于「当前这一季」（用户定的规则）：

      1. 标题写明**别的季** → 排除
      2. 标题写明**本季季数** → 保留（有的组用本季编号，如「第五季 - 01」）
      3. 其余：集号不在本季区间 [base, base+总话数-1] 内 → 排除
         （小于起点 = 上季；大于区间上沿 = 后面篇章/别的季）
      4. 集号不明 / 判不出起点 → 保留（宁可不筛）

    base 是本季第 1 集在标题里的编号（如凡人修仙传第五季 = 176，黑色五叶草第二季 = 171）。
    `air_date` 保留参数位以便兼容旧调用，本规则不再按发布时间判断。
    """
    title = str(_item_field(item, "title", "") or "")
    season = season_of(title)
    if sub_season and season and season != sub_season:
        return False
    if sub_season and season == sub_season:
        return True
    ep = _item_field(item, "episode")
    if not isinstance(ep, int) or ep <= 0:
        return True                      # 集号都没解析出来，不做判断
    try:
        total = int(total_episodes or 0)
    except (TypeError, ValueError):
        total = 0
    if not base or total < 1:
        return True                      # 判不出本季起点，不筛
    # 本季区间 = [起点, 起点 + 总话数 - 1]
    # 例：凡人修仙传第五季 起点 176、52 话 → 177…228；超过 228 的是后面篇章/别的季，丢弃。
    # 注意上限用的是「这季实际覆盖到的最大编号」，不是「总话数 52」本身。
    upper = base + total - 1
    return base <= ep <= upper


# 本季标识（用户定的规则）：从「番剧名 + 别名」里搜集这三类片段，
# 搜索结果的标题里出现任何一个 → 判定为本季。
#   1) 第 N 季 / 第 N 期 / 第 N 部
#   2) Season N / Nnd Season（英文名、英文组常见）
#   3) …篇 / …編 / …编：取「篇」前面那段空格之后的字符（凡人修仙传 慕兰之战篇 → 慕兰之战）；
#      「篇」前面没有空格的连写（凡人慕兰之战篇）不切，避免把番名也切进来
_SEASON_TOKEN = re.compile(
    r"第\s*[0-9０-９一二三四五六七八九十]+\s*[季期部]"
    r"|\bseason\s*[0-9]{1,2}\b"
    r"|\b[0-9]{1,2}(?:st|nd|rd|th)[\s_-]*season\b",
    re.I)
_ARC_SUFFIXES = ("篇", "編", "编")
_ARC_CHARS = "".join(_ARC_SUFFIXES)
# 「…篇」只在**前面有空格**时才能切出篇章名：凡人修仙传 慕兰之战篇 → 慕兰之战。
# 连写的「凡人慕兰之战篇」没有空格，切不出可靠边界（会连番名一起切进来）→ 不用。
_ARC_HEAD_SPLIT = re.compile(r"\s+")
_TOKEN_EDGE = " 　-_:：/／·・,，、.。()（）[]【】「」『』\"'"


@lru_cache(maxsize=512)
def _token_pattern(tok: str) -> "re.Pattern[str]":
    """标识 -> 匹配用的正则：ASCII 字边界防止「Season 2」命中「Season 20」。"""
    pat = re.escape(tok)
    if tok[:1].isascii() and tok[:1].isalnum():
        pat = r"(?<![A-Za-z0-9])" + pat
    if tok[-1:].isascii() and tok[-1:].isalnum():
        pat = pat + r"(?![A-Za-z0-9])"
    return re.compile(pat, re.I)


def season_tokens(sources) -> list[str]:
    """
    从一批文本（番剧自己的名字 + Bangumi 别名）里搜集「能代表本季」的标识：

      - 「第 N 季」型 → 直接用（鬼灭之刃 第二季 → 第二季）
      - 「Season N」/「Nnd Season」型 → 直接用（X Season 2 → Season 2）
      - 「…篇/編/编」型 → 取「篇」前最后一个空格之后的字符
        （凡人修仙传 慕兰之战篇 → 慕兰之战，另保留「慕兰之战篇」）
        「篇」前面没有空格的连写（凡人慕兰之战篇）切不出边界 → 整条不用

    裸番名（「凡人修仙传」）不算标识，否则整部系列都会被当成本季。
    """
    if isinstance(sources, str):
        sources = [sources]
    tokens: list[str] = []
    for raw in (sources or []):
        text = unicodedata.normalize("NFKC", str(raw or "")).strip()
        if not text:
            continue
        for m in _SEASON_TOKEN.finditer(text):
            tokens.append(re.sub(r"\s+", " ", m.group(0)).strip())
        for m in re.finditer("[篇編编]", text):
            parts = _ARC_HEAD_SPLIT.split(text[:m.start()])
            if len(parts) < 2:
                continue                     # 「篇」前面没有空格（如「凡人慕兰之战篇」）→ 不切
            tail = parts[-1].strip(_TOKEN_EDGE)
            if len(tail) >= 3:
                tokens.append(tail + m.group(0))
            trimmed = tail.rstrip(_ARC_CHARS).strip(_TOKEN_EDGE)
            if len(trimmed) >= 2:
                tokens.append(trimmed)
    # 去重保序（大小写不敏感）
    seen, out = set(), []
    for tok in tokens:
        key = tok.casefold()
        if tok and key not in seen:
            seen.add(key)
            out.append(tok)
    return out


def season_hit(title: str, tokens) -> bool:
    """标题里出现任何一个本季标识（第N季 / Season N / 篇章名）= 属于本季。"""
    text = unicodedata.normalize("NFKC", str(title or ""))
    if not text:
        return False
    return any(_token_pattern(tok).search(text) for tok in (tokens or []) if tok)


def alias_tokens(aliases) -> list[str]:
    """兼容旧调用：只从别名里搜集本季标识（见 season_tokens）。"""
    return season_tokens(aliases)


def alias_hit(title: str, aliases) -> bool:
    """兼容旧调用：标题是否命中别名里的本季标识。"""
    return season_hit(title, season_tokens(aliases))


def apply_season_rules(items, *, total_episodes: int = 0, sub_season: int = 0,
                       air_date: str = "", start_ep: int = 0,
                       aliases=None, names=None) -> tuple[list[int], int, int]:
    """
    统一的「季判定 + 集号换算」：**页面搜索、补下载、自动追番三条路都调它**。

    items:   资源 dict 列表（有 title/episode 字段）
    names:   番剧自己的名字（display_name / 中文名 / 原名）
    aliases: Bangumi 别名
    返回 (保留项的下标列表, 偏移量, 隐藏条数)

    判定顺序（用户定的规则，先成立先算）：
      1. 标题命中本季标识（第N季 / Season N / Nnd season / 某某篇）→ 保留
         （标识从「番剧名 + 别名」两处搜集，见 season_tokens）
      2. 标题写明别的季 → 排除
      3. 标题写明本季季数 → 保留（有的组用本季编号，如「第五季 - 01」）
      4. 集号不在本季区间 [起点, 起点+总话数-1] → 排除
      5. 集号 / 起点判不出来 → 保留（宁可不筛）
    保留的项若用的是系列连续编号，集号换算成本季编号。
    """
    def _as_list(value):
        if not value:
            return []
        return [value] if isinstance(value, str) else list(value)

    tokens = season_tokens(_as_list(names) + _as_list(aliases))
    if start_ep and start_ep > 0:
        # Bangumi 章节表给出的「本季第一集累计编号」（凡人第五季 = 177）最可靠，直接用它
        base = int(start_ep)
        offset = base - 1
    else:
        offset, base = resolve_episode_offset(list(items), total_episodes, sub_season, air_date)
    keep: list[int] = []
    hidden = 0
    for idx, it in enumerate(items):
        if not isinstance(it, (dict,)) and not hasattr(it, "title"):
            hidden += 1
            continue
        # 标题命中本季标识（例如「凡人修仙传 慕兰之战」）→ 一定是本季
        if tokens and season_hit(_item_field(it, "title") or "", tokens):
            keep.append(idx)
            continue
        if not in_current_season(it, base=base, total_episodes=total_episodes,
                                 sub_season=sub_season, air_date=air_date):
            hidden += 1
            continue
        keep.append(idx)
    return keep, offset, hidden


def keyword_variants(text: str) -> list[str]:
    """一个名字对应的搜索关键词变体（清洗后的放最前，原样保留在后面兜底）。"""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return []
    seen, out = set(), []
    for k in (clean_keyword(raw), clean_keyword(raw, cjk_only=True), raw):
        k = k.strip()
        if len(k) < 2 or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def uniq_keep_order(items) -> list:
    seen, out = set(), []
    for it in items:
        key = it if isinstance(it, str) else str(it)
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out
