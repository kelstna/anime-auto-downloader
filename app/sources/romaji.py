# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
日语假名 -> 罗马字 转换。
用途：Bangumi 的日文原名（如「葬送のフリーレン」）转成「Sousou no Frieren」，
以便在 nyaa 这类以罗马字标题为主的站点搜索。
表驱动实现，仅依赖标准库，覆盖常用假名与拗音/促音/长音规则。
"""
from __future__ import annotations

import re

# 浊音/半浊音先行处理，避免被清音规则截断
_DIGRAPHS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo", "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo", "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo", "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "ふゅ": "fyu",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "ちぇ": "che", "しぇ": "she",
    "じぇ": "je", "うぃ": "wi", "うぇ": "we", "うぉ": "wo", "ゔぁ": "va", "ゔぃ": "vi",
    "ゔぇ": "ve", "ゔぉ": "vo", "くぁ": "kwa", "ぐぁ": "gwa", "つぁ": "tsa", "つぃ": "tsi",
    "つぇ": "tse", "つぉ": "tso", "いぇ": "ye", "きぇ": "kye", "ぎぇ": "gye",
    "すぃ": "si", "ずぃ": "zi", "とぁ": "twa",
}

_MONO = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "wo", "ん": "n",
    "ゔ": "vu", "ゕ": "ka", "ゖ": "ke",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "っ": "", "ー": "",
    "ゎ": "wa",
}

_KATA_TO_HIRA = {chr(ord("ァ") + i): chr(ord("ぁ") + i) for i in range(0x56)}
_KATA_TO_HIRA["ヴ"] = "ゔ"
_KATA_TO_HIRA["ヵ"] = "ゕ"
_KATA_TO_HIRA["ヶ"] = "ゖ"

# 片假名外来语 -> 英文拼写。逐字转写对动漫标题里的外来语不友好
# （ゾンビ -> Zonbi，而正确写法是 Zombie），这里按「最长优先」先替换。
_LOANWORDS: tuple[tuple[str, str], ...] = (
    # 人名 / 作品名常用
    ("フリーレン", "Frieren"), ("ゾンビ", "Zombie"), ("エルフ", "Elf"), ("ドラゴン", "Dragon"),
    ("マジック", "Magic"), ("マギ", "Magi"), ("ヒーロー", "Hero"), ("ヒロイン", "Heroine"),
    ("アカデミー", "Academy"), ("スクール", "School"), ("ガール", "Girl"), ("ボーイ", "Boy"),
    ("ラブ", "Love"), ("コメディ", "Comedy"), ("ストーリー", "Story"), ("ワールド", "World"),
    ("ワンダー", "Wonder"), ("ランド", "Land"), ("ドリーム", "Dream"), ("メモリー", "Memory"),
    ("ファンタジー", "Fantasy"), ("ミステリー", "Mystery"), ("アドベンチャー", "Adventure"),
    ("サイエンス", "Science"), ("スペース", "Space"), ("スター", "Star"), ("ムーン", "Moon"),
    ("サン", "Sun"), ("スカイ", "Sky"), ("オーシャン", "Ocean"), ("シティ", "City"),
    ("タウン", "Town"), ("ヴィレッジ", "Village"), ("ビレッジ", "Village"), ("ホーム", "Home"),
    ("ハウス", "House"), ("ルーム", "Room"), ("ホテル", "Hotel"), ("カフェ", "Cafe"),
    ("レストラン", "Restaurant"), ("キッチン", "Kitchen"), ("ケーキ", "Cake"),
    ("スイーツ", "Sweets"), ("コーヒー", "Coffee"), ("ティー", "Tea"), ("ミルク", "Milk"),
    ("ウォーズ", "Wars"), ("ウォー", "War"), ("バトル", "Battle"), ("ファイト", "Fight"),
    ("ソード", "Sword"), ("ブレイド", "Blade"), ("ナイト", "Night"), ("ライト", "Light"),
    ("ダーク", "Dark"), ("シャドウ", "Shadow"), ("ゴースト", "Ghost"), ("デビル", "Devil"),
    ("エンジェル", "Angel"), ("ゴッド", "God"), ("デーモン", "Demon"), ("モンスター", "Monster"),
    ("ロボット", "Robot"), ("ロボ", "Robo"), ("マシン", "Machine"), ("エンジン", "Engine"),
    ("サイボーグ", "Cyborg"), ("アンドロイド", "Android"), ("サイバー", "Cyber"),
    ("パンク", "Punk"), ("ゲーム", "Game"), ("プレイ", "Play"), ("プレイヤー", "Player"),
    ("レベル", "Level"), ("クエスト", "Quest"), ("ギルド", "Guild"), ("パーティー", "Party"),
    ("ナンバー", "Number"), ("データ", "Data"), ("システム", "System"), ("プログラム", "Program"),
    ("ネット", "Net"), ("オンライン", "Online"), ("デジタル", "Digital"), ("バーチャル", "Virtual"),
    ("ミュージック", "Music"), ("バンド", "Band"), ("ソング", "Song"), ("メロディ", "Melody"),
    ("ピアノ", "Piano"), ("ギター", "Guitar"), ("ドラム", "Drum"), ("ステージ", "Stage"),
    ("アイドル", "Idol"), ("スターライト", "Starlight"), ("ムーンライト", "Moonlight"),
    ("サンシャイン", "Sunshine"), ("レインボー", "Rainbow"), ("クリスタル", "Crystal"),
    ("ダイヤ", "Dia"), ("ゴールド", "Gold"), ("シルバー", "Silver"), ("プラチナ", "Platinum"),
    ("ルビー", "Ruby"), ("サファイア", "Sapphire"), ("エメラルド", "Emerald"),
    ("ローズ", "Rose"), ("リリー", "Lily"), ("フラワー", "Flower"), ("ガーデン", "Garden"),
    ("ツリー", "Tree"), ("フォレスト", "Forest"), ("リバー", "River"), ("マウンテン", "Mountain"),
    ("アイランド", "Island"), ("ビーチ", "Beach"), ("スノー", "Snow"), ("レイン", "Rain"),
    ("ウィンド", "Wind"), ("ファイア", "Fire"), ("フレイム", "Flame"), ("アイス", "Ice"),
    ("サンダー", "Thunder"), ("ストーム", "Storm"), ("クラウド", "Cloud"), ("エア", "Air"),
    ("タイム", "Time"), ("クロノ", "Chrono"), ("エターナル", "Eternal"), ("インフィニティ", "Infinity"),
    ("ゼロ", "Zero"), ("ワン", "One"), ("ツー", "Two"), ("スリー", "Three"), ("フォー", "Four"),
    ("ファイブ", "Five"), ("シックス", "Six"), ("セブン", "Seven"), ("エイト", "Eight"),
    ("ナイン", "Nine"), ("テン", "Ten"), ("ファースト", "First"), ("セカンド", "Second"),
    ("サード", "Third"), ("フォース", "Fourth"), ("ラスト", "Last"), ("ファイナル", "Final"),
    ("ニュー", "New"), ("オールド", "Old"), ("ヤング", "Young"), ("ベスト", "Best"),
    ("グレート", "Great"), ("スーパー", "Super"), ("ウルトラ", "Ultra"), ("ハイパー", "Hyper"),
    ("ミラクル", "Miracle"), ("エンジェル", "Angel"), ("ハート", "Heart"), ("ソウル", "Soul"),
    ("マインド", "Mind"), ("スピリット", "Spirit"), ("パワー", "Power"), ("エナジー", "Energy"),
    ("マスター", "Master"), ("レディ", "Lady"), ("キング", "King"), ("クイーン", "Queen"),
    ("プリンス", "Prince"), ("プリンセス", "Princess"), ("ロード", "Lord"), ("レディース", "Ladies"),
    ("シスター", "Sister"), ("ブラザー", "Brother"), ("ファミリー", "Family"), ("フレンド", "Friend"),
    ("パートナー", "Partner"), ("チーム", "Team"), ("メンバー", "Member"), ("クラス", "Class"),
    ("ルーム", "Room"), ("デイズ", "Days"), ("デイ", "Day"), ("ウィーク", "Week"),
    ("イヤー", "Year"), ("シーズン", "Season"), ("バージョン", "Version"), ("タイプ", "Type"),
    ("モード", "Mode"), ("ケース", "Case"), ("ファイル", "File"), ("ドア", "Door"),
    ("キー", "Key"), ("ロック", "Lock"), ("ブレイブ", "Brave"), ("ブレイカー", "Breaker"),
    ("エース", "Ace"), ("ジョーカー", "Joker"), ("カード", "Card"), ("ダイス", "Dice"),
    ("チェス", "Chess"), ("パズル", "Puzzle"), ("ミステイク", "Mistake"), ("トリック", "Trick"),
    ("エラー", "Error"), ("プロジェクト", "Project"), ("シグナル", "Signal"), ("コード", "Code"),
    ("ネーム", "Name"), ("ワード", "Word"), ("レター", "Letter"), ("ノート", "Note"),
    ("ブック", "Book"), ("ページ", "Page"), ("ドキュメント", "Document"), ("レポート", "Report"),
    ("ニュース", "News"), ("メール", "Mail"), ("フォン", "Phone"), ("カメラ", "Camera"),
    ("ビデオ", "Video"), ("ムービー", "Movie"), ("シネマ", "Cinema"), ("ドラマ", "Drama"),
    ("アニメ", "Anime"), ("コミック", "Comic"), ("ノベル", "Novel"), ("マンガ", "Manga"),
    ("カラオケ", "Karaoke"), ("フェス", "Fest"), ("フェスティバル", "Festival"), ("パレード", "Parade"),
    ("ダンス", "Dance"), ("ステップ", "Step"), ("ジャンプ", "Jump"), ("ラン", "Run"),
    ("スピード", "Speed"), ("ダッシュ", "Dash"), ("フライト", "Flight"), ("フライ", "Fly"),
    ("ドライブ", "Drive"), ("バイク", "Bike"), ("カー", "Car"), ("トレイン", "Train"),
    ("バス", "Bus"), ("シップ", "Ship"), ("ボート", "Boat"), ("プレーン", "Plane"),
    ("ロケット", "Rocket"), ("コスモ", "Cosmo"), ("ユニバース", "Universe"), ("ギャラクシー", "Galaxy"),
    ("プラネット", "Planet"), ("ヘブン", "Heaven"), ("ヘル", "Hell"),
    ("パラダイス", "Paradise"), ("ヨミ", "Yomi"), ("カミ", "Kami"), ("オニ", "Oni"),
    ("サムライ", "Samurai"), ("ニンジャ", "Ninja"), ("ブシドー", "Bushido"), ("ケンポウ", "Kenpo"),
    ("カタナ", "Katana"), ("センパイ", "Senpai"), ("コウハイ", "Kohai"), ("センス", "Sensei"),
    ("マジョ", "Majo"), ("メイド", "Maid"), ("バトラー", "Butler"), ("オフィス", "Office"),
    ("カンパニー", "Company"), ("ビジネス", "Business"), ("マネー", "Money"), ("ショップ", "Shop"),
    ("ストア", "Store"), ("マート", "Mart"), ("マーケット", "Market"), ("バンク", "Bank"),
    ("サラリー", "Salary"), ("ジョブ", "Job"), ("ワーク", "Work"), ("タスク", "Task"),
    ("ミッション", "Mission"), ("ゴール", "Goal"), ("チャンス", "Chance"), ("ラッキー", "Lucky"),
    ("アンラッキー", "Unlucky"), ("デンジャー", "Danger"), ("セーフ", "Safe"), ("リスク", "Risk"),
    ("ピース", "Peace"), ("フリー", "Free"), ("ハッピー", "Happy"), ("スマイル", "Smile"),
    ("ティアーズ", "Tears"), ("クライ", "Cry"), ("ラフ", "Laugh"), ("ジョイ", "Joy"),
    ("エンド", "End"), ("スタート", "Start"), ("ビギン", "Begin"), ("オープン", "Open"),
    ("クローズ", "Close"), ("ネクスト", "Next"), ("バック", "Back"), ("フロント", "Front"),
    ("サイド", "Side"), ("トップ", "Top"), ("ボトム", "Bottom"), ("アップ", "Up"),
    ("ダウン", "Down"), ("レフト", "Left"), ("ライト", "Right"), ("センター", "Center"),
)

# 长词优先替换，避免「マジック」被「マギ」抢先切分
_LOANWORD_PATTERN = re.compile(
    "|".join(re.escape(k) for k, _ in sorted(_LOANWORDS, key=lambda kv: -len(kv[0])))
) if _LOANWORDS else None
_LOANWORD_MAP = dict(_LOANWORDS)

_YOON_FOLLOWERS = set("ゃゅょぁぃぅぇぉ")

# 日语助词（は/へ/を）在标题中通常按原音读，不做特殊处理
_SMALL_TSU = "っ"


def _to_hiragana(text: str) -> str:
    return text.translate({ord(k): v for k, v in _KATA_TO_HIRA.items()})


def _substitute_loanwords(text: str) -> str:
    """片假名外来语替换为英文拼写（替换后可能残留少量片假名，由主流程继续逐字转写）。"""
    if _LOANWORD_PATTERN is None:
        return text
    return _LOANWORD_PATTERN.sub(lambda m: _LOANWORD_MAP.get(m.group(0), m.group(0)), text)


def has_kana(text: str) -> bool:
    return bool(re.search(r"[\u3041-\u309f\u30a0-\u30ff]", text or ""))


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_OK = re.compile(r"^[0-9A-Za-z\u00c0-\u024f\s'\-.,:!?&+/()\[\]]+$")
# 标题里的装饰符（`#ゾンビさがしてます`、`★4月新番★`、`♪` …）：转换前先抠掉，否则会连装饰符一起转
_DECOR = re.compile(r"[#＃★☆♪♡♥◆●○■□▲△▼▽※→←\[\]【】「」『』()（）]+")
# 「像罗马音」的日语助词（作为独立单词出现才算，且不能是首词）。
# `to` / `de` / `ni` / `mo` 这类短助词看着像英文，但正是它们把「真罗马字」和
# 「机器生拼的串」区分开：`Dark Summoner to Dekiteiru`（助词 to 独立成词 ✓）
# vs `Dark Samon atodekiteiru`（to 被吞进 atode… ✗）—— 用户实测只有前者能搜到资源。
_ROMAJI_PARTICLES = frozenset((
    "no", "ga", "wo", "ni", "wa", "to", "de", "mo", "ya", "e", "ka", "ne", "yo",
    "kara", "made", "desu", "deshita", "suru", "shita", "shite",
    "aru", "iru", "nai", "tai", "chan", "kun", "sama", "san", "tachi", "nado", "yori", "dake",
))
# 日语特有的罗马字音节（英文里极少见）
_ROMAJI_SYLLABLES = re.compile(
    r"(shi|tsu|chi|sha|shu|sho|cha|chu|cho|ja|ju|jo|kya|kyu|kyo|gya|gyu|gyo|rya|ryu|ryo|"
    r"nya|nyu|nyo|hya|hyu|hyo|bya|byu|byo|pya|pyu|pyo|kyou|ryuu|bou|dou|gou|tou)",
    re.I)


def looks_like_romaji(text: str) -> bool:
    """
    这条名字看起来是不是「日文罗马字」（而不是英文名/英文句子）。

    用户要求「英文名搜索改成罗马音搜索」：Bangumi 的别名里既有罗马字（`Kusuriya no Hitorigoto`、
    `Seitokai ni mo Ana wa Aru`）也有英文句子（`There is also a hole in the student organization!`），
    后者拿去站内搜索一条都搜不到，所以优先用罗马字。
    判断依据：含日语助词（no/ga/ni/wa…）或日语特有音节（shi/tsu/kya…），且本身是拉丁字符。
    """
    return romaji_score(text) > 0


def romaji_score(text: str) -> int:
    """
    「像罗马音」的程度（越大越像），用来在一堆别名里挑最地道的罗马字。

    例：`FX Senshi Kurumi-chan`（助词 chan + 音节 shi = 3）应当排在
    `FX Fighter Kurumi-chan`（只有 chan = 2）前面。
    """
    s = (text or "").strip()
    if not s or _CJK.search(s) or has_kana(s):
        return 0
    words = re.findall(r"[A-Za-z']+", s.lower())
    if not words:
        return 0
    score = 0
    if len(words) > 1:
        score += 2 * sum(1 for w in words[1:] if w in _ROMAJI_PARTICLES)
    if len(words) == 1 and words[0] in _ROMAJI_PARTICLES:
        score += 1
    score += len(set(m.group(0).lower() for m in _ROMAJI_SYLLABLES.finditer(s)))
    return score


def romanize(text: str, capitalize: bool = True) -> str:
    """
    把含假名的日文标题转成罗马字。
    汉字无法在不依赖词典的情况下转写，因此结果中若仍含汉字，视为转换失败。
    """
    if not text:
        return ""
    text = _DECOR.sub(" ", str(text))
    # 外来语替换后补空格：否则「ゾンビさがしてます」会拼成 Zombiesagashitemasu（站内搜不到）
    s = _to_hiragana(_substitute_loanwords(text))
    s = re.sub(r"(?<=[A-Za-z])(?=[\u3041-\u309f])", " ", s)
    s = re.sub(r"(?<=[\u3041-\u309f])(?=[A-Z])", " ", s)
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        # 促音：双写下一个辅音
        if ch == _SMALL_TSU:
            nxt = ""
            if i + 2 < n and s[i + 1: i + 3] in _DIGRAPHS:
                nxt = _DIGRAPHS[s[i + 1: i + 3]]
            elif i + 1 < n:
                nxt = _MONO.get(s[i + 1], "")
            if nxt:
                out.append(nxt[0])
            i += 1
            continue
        pair = s[i: i + 2]
        if len(pair) == 2 and pair in _DIGRAPHS:
            out.append(_DIGRAPHS[pair])
            i += 2
            continue
        if ch in _MONO:
            out.append(_MONO[ch])
            i += 1
            continue
        out.append(ch)
        i += 1

    result = "".join(out)
    # 汉字残留 -> 转换不可信，放弃（避免产生 "好kin'a人n'i" 这类垃圾关键词）
    if _CJK.search(result):
        return ""
    result = re.sub(r"\s+", " ", result).strip()
    if not result:
        return ""
    # ん 后接元音/y 时加撇号，避免误读（Shin'ya）；但 'na' 属正常拼写，不加
    result = re.sub(r"n(?=[aiueo]|y(?!a))", "n'", result)
    if capitalize:
        result = " ".join(w[:1].upper() + w[1:] if w else w for w in result.split(" "))
    return result


def is_usable_romaji(text: str) -> bool:
    """转换结果是否只剩拉丁字符（可用作搜索关键词）。"""
    return bool(text) and not _CJK.search(text) and bool(_LATIN_OK.match(text))


def romaji_variants(title: str) -> list[str]:
    """生成标题的罗马字变体（含去撇号、去标点形式），用于提高搜索命中率。"""
    r = romanize(title)
    if not r or not is_usable_romaji(r):
        return []
    out = [r]
    if "'" in r:
        out.append(r.replace("'", ""))
    squashed = re.sub(r"[^0-9A-Za-z\s]+", " ", r)
    squashed = re.sub(r"\s+", " ", squashed).strip()
    if squashed and squashed != r:
        out.append(squashed)
    return [x for x in dict.fromkeys(out) if x]
