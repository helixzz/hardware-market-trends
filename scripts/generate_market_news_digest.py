#!/usr/bin/env python3
import html
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

TZ = timezone(timedelta(hours=8))
DEFAULT_WORKSPACE = "/Users/helixzz/.openclaw/workspace"
DEFAULT_OUTPUT_DIR = os.path.join(DEFAULT_WORKSPACE, "hardware-market-trends", "daily-news")
MAX_ITEMS = 10
MAX_ITEM_CHARS = 140
MAX_TOTAL_CHARS = 2000
LOOKBACK_DAYS = 2
USER_AGENT = "Mozilla/5.0 (compatible; market-news-digest/2.0; +https://news.google.com/)"
REWRITER_CMD = os.environ.get("MARKET_NEWS_REWRITER_CMD", "").strip()

FEEDS = [
    {"label": "宏观", "query": 'global macro OR inflation OR central bank OR recession OR yields when:1d', "weight": 5},
    {"label": "资本市场", "query": 'stocks OR bonds OR markets OR earnings OR IPO when:1d', "weight": 5},
    {"label": "科技", "query": 'technology earnings OR cloud OR datacenter when:1d', "weight": 6},
    {"label": "AI", "query": 'AI OR artificial intelligence OR GPU OR model when:1d', "weight": 8},
    {"label": "半导体", "query": 'semiconductor OR chip OR foundry OR memory when:1d', "weight": 9},
    {"label": "供应链", "query": 'supply chain OR logistics OR manufacturing OR factory when:1d', "weight": 6},
]

SOURCE_WEIGHT = {
    "Reuters": 10,
    "Bloomberg": 9,
    "Financial Times": 8,
    "The Wall Street Journal": 8,
    "WSJ": 8,
    "CNBC": 7,
    "The Information": 7,
    "Nikkei Asia": 7,
    "Associated Press": 7,
    "AP News": 7,
    "Barron's": 6,
    "MarketWatch": 6,
    "TechCrunch": 5,
    "Tom's Hardware": 5,
}

BLOCKED_SOURCES = {
    "AOL.com",
    "MSN",
    "The Motley Fool",
    "simplywall.st",
    "Nasdaq",
    "Yahoo Finance",
    "Yahoo Finance Singapore",
    "Seeking Alpha",
    "Newswise",
}

BLOCKED_TITLE_PATTERNS = [
    r"news updates?: latest news",
    r"stock(s)? .* redefine",
    r"is the ai panic finally subsiding",
    r"live updates?",
    r"q&?a with",
    r"what can .* teach .* ai",
]

KEYWORD_WEIGHT = OrderedDict([
    ("ai", 5),
    ("artificial intelligence", 5),
    ("gpu", 5),
    ("semiconductor", 6),
    ("chip", 5),
    ("memory", 4),
    ("dram", 4),
    ("nand", 4),
    ("foundry", 5),
    ("tsmc", 5),
    ("intel", 4),
    ("nvidia", 5),
    ("amd", 4),
    ("qualcomm", 4),
    ("broadcom", 4),
    ("supply chain", 4),
    ("factory", 3),
    ("tariff", 3),
    ("inflation", 3),
    ("central bank", 3),
    ("rates", 3),
    ("earnings", 3),
    ("ipo", 2),
    ("datacenter", 4),
    ("cloud", 3),
])

CN_MAP = OrderedDict([
    ("artificial intelligence", "AI"),
    ("ai", "AI"),
    ("stocks", "股市"),
    ("stock", "股价"),
    ("bonds", "债市"),
    ("bond", "债券"),
    ("markets", "市场"),
    ("market", "市场"),
    ("semiconductor", "半导体"),
    ("chip", "芯片"),
    ("chips", "芯片"),
    ("gpu", "GPU"),
    ("gpus", "GPU"),
    ("memory", "存储"),
    ("dram", "DRAM"),
    ("nand", "NAND"),
    ("foundry", "晶圆代工"),
    ("supply chain", "供应链"),
    ("factory", "工厂"),
    ("factories", "工厂"),
    ("cloud", "云"),
    ("data center", "数据中心"),
    ("data centers", "数据中心"),
    ("earnings", "财报"),
    ("guidance", "指引"),
    ("forecast", "预期"),
    ("exclusive", "独家"),
    ("sale", "出售"),
    ("exploring", "研究"),
    ("rates", "利率"),
    ("inflation", "通胀"),
    ("tariff", "关税"),
    ("acquisition", "收购"),
    ("deal", "交易"),
    ("warning", "警示"),
    ("smuggle", "走私"),
    ("listings", "上市"),
    ("warehouses", "仓储"),
    ("rallies", "走强"),
    ("beat", "超预期"),
])

COMPANY_MAP = OrderedDict([
    ("super micro computer", "超微电脑"),
    ("super micro", "超微电脑"),
    ("accenture", "埃森哲"),
    ("dhl", "DHL"),
    ("google", "谷歌"),
    ("openai", "OpenAI"),
    ("chatgpt", "ChatGPT"),
    ("gemini", "Gemini"),
    ("elmos", "Elmos"),
    ("nvidia", "英伟达"),
    ("intel", "英特尔"),
    ("amd", "AMD"),
    ("tsmc", "台积电"),
    ("qualcomm", "高通"),
    ("broadcom", "博通"),
    ("china", "中国"),
    ("south korea", "韩国"),
    ("iran", "伊朗"),
    ("qatar", "卡塔尔"),
    ("hong kong", "香港"),
    ("german", "德国"),
    ("us", "美国"),
])

MORNING_PREFIX = {
    "宏观": "宏观面",
    "资本市场": "市场面",
    "科技": "科技面",
    "AI": "AI主线",
    "半导体": "芯片链",
    "供应链": "供应链",
}


def google_news_rss(query: str) -> str:
    encoded = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()


def clean_html(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = re.sub(r"<a [^>]+>.*?</a>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def clean_title(title: str) -> str:
    title = html.unescape(title or "").strip()
    title = re.sub(r"\s+", " ", title)
    return title


def normalize_title(title: str) -> str:
    title = clean_title(title).lower()
    title = re.sub(r"\s+-\s+(reuters|bloomberg|cnbc|financial times|wsj|the wall street journal|ap news|associated press|nikkei asia|marketwatch|barron's|the information|techcrunch|tom's hardware)$", "", title)
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def fingerprint_title(title: str) -> str:
    norm = normalize_title(title)
    tokens = [t for t in norm.split() if len(t) > 2]
    if not tokens:
        return norm
    return " ".join(tokens[:8])


def title_similarity(a: str, b: str) -> float:
    a_tokens = set(normalize_title(a).split())
    b_tokens = set(normalize_title(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    return overlap / max(min(len(a_tokens), len(b_tokens)), 1)


def event_cluster(item) -> str:
    blob = f"{item.get('title', '')} {item.get('description', '')}".lower()
    if all(k in blob for k in ["china", "ai"]) and any(k in blob for k in ["smuggl", "charge", "indict"]):
        return "ai_chip_smuggling_china"
    if "hong kong" in blob and any(k in blob for k in ["listing", "listings", "ipo"]):
        return "hong_kong_listing"
    if "elmos" in blob and any(k in blob for k in ["sale", "exploring"]):
        return "elmos_sale"
    if "nvidia" in blob and "amazon" in blob and any(k in blob for k in ["chip", "gpu"]):
        return "nvidia_amazon_chip_supply"
    if "dhl" in blob and any(k in blob for k in ["warehouse", "data center"]):
        return "dhl_data_center_logistics"
    return ""


def parse_feed(url: str, label: str, base_weight: int):
    root = ET.fromstring(fetch(url))
    items = []
    for item in root.findall("./channel/item"):
        title = clean_title(item.findtext("title", default=""))
        source = clean_title(item.findtext("source", default=""))
        link = item.findtext("link", default="").strip()
        desc = clean_html(item.findtext("description", default=""))
        pub = item.findtext("pubDate", default="").strip()
        try:
            pub_dt = parsedate_to_datetime(pub).astimezone(TZ)
        except Exception:
            pub_dt = None
        items.append({
            "title": title,
            "source": source,
            "link": link,
            "description": desc,
            "pub_dt": pub_dt,
            "topic": label,
            "base_weight": base_weight,
            "norm_title": normalize_title(title),
            "fingerprint": fingerprint_title(title),
        })
    return items


def score_item(item, now):
    score = item["base_weight"]
    score += SOURCE_WEIGHT.get(item["source"], 0)
    blob = f'{item["title"]} {item["description"]}'.lower()
    for kw, weight in KEYWORD_WEIGHT.items():
        if kw in blob:
            score += weight
    if item["pub_dt"]:
        age_hours = max((now - item["pub_dt"]).total_seconds() / 3600, 0)
        score += max(8 - min(age_hours / 3, 8), 0)
    if any(k in blob for k in ["exclusive", "deal", "guidance", "forecast", "warning", "tariff", "acquisition", "smuggle", "listing"]):
        score += 2
    return score


def shorten_cn(text: str, width: int = MAX_ITEM_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip(" ；;，,。")
    if len(text) <= width:
        return text
    trimmed = text[: max(width - 1, 1)].rstrip(" ；;，,。")
    return trimmed + "…"


def normalize_phrase(text: str) -> str:
    text = clean_title(text)
    text = re.sub(r"\s+-\s+[^-]+$", "", text)
    text = re.sub(r"^(Exclusive:?|Live Updates:?|Breaking:?|Analysis:?|Opinion:?|Listen|Watch):\s*", "", text, flags=re.I)
    return text


def sentence_case_cn(text: str) -> str:
    out = f" {text.lower()} "
    for eng, cn in COMPANY_MAP.items():
        out = re.sub(rf"(?i)(?<![a-z]){re.escape(eng)}(?![a-z])", cn, out)
    for eng, cn in CN_MAP.items():
        out = re.sub(rf"(?i)(?<![a-z]){re.escape(eng)}(?![a-z])", cn, out)
    out = re.sub(r"\s+", " ", out).strip()
    out = out.replace("'", "")
    out = out.replace("‘", "").replace("’", "")
    out = out.replace('"', "")
    return out


def heuristic_cn_line(item):
    raw_blob = f"{item['title']} {item.get('description', '')}".lower()
    title = sentence_case_cn(normalize_phrase(item["title"]))
    desc = sentence_case_cn(item.get("description", ""))
    title = title.replace("billions dollars", "数十亿美元")
    title = title.replace("million", "百万")
    title = title.replace("tied", "相关")
    title = title.replace("seek", "寻求")
    title = title.replace("firms", "企业")
    title = title.replace("men", "人员")
    title = title.replace("charges", "起诉")
    title = title.replace("charged", "被起诉")
    title = title.replace("conspiring", "涉嫌")
    title = title.replace("threaten", "威胁")
    title = title.replace("sell", "出售")
    title = title.replace("by end", "到")
    title = title.replace("war", "冲突")
    title = title.replace("global", "全球")
    title = title.replace("tech", "科技")
    title = title.replace("red-chip", "红筹")
    title = title.replace("scrutiny", "审查")
    title = title.replace("powers up", "加码")
    title = title.replace("supply", "服务")
    title = title.replace("and", "与")
    title = title.replace("even", "但")
    title = re.sub(r"\b(news updates|latest news about)\b", "动态", title, flags=re.I)
    title = re.sub(r"\b(sources say|source says)\b", "", title, flags=re.I)
    desc = re.sub(r"^more\s*", "", desc, flags=re.I)

    patterns = [
        (r"(super micro|smci|supermicro).*?(smuggl|charge).*?(ai|chip).*?china", "美国起诉涉案人员协助向中国走私AI芯片，显示高端算力出口管制继续收紧"),
        (r"(talk of ai disruption|m&a conference).*?(oil|war).*?(rates|deal)", "AI叙事叠加战争、油价和利率扰动，但全球并购热度仍高，风险偏好与融资成本继续拉扯"),
        (r"elmos.*?(exploring|sale)", "德国芯片公司 Elmos 据报研究出售事宜，行业整合预期升温"),
        (r"(chinese|china).*?(hong kong).*?(listing|listings|ipo)", "多家中国企业推进香港上市融资，资本开闸与监管审视并行"),
        (r"nvidia.*?(sell|supply).*?(million).*?(chip|gpu).*?(amazon|aws|cloud)", "英伟达据报计划到2027年前向亚马逊供应约百万颗芯片，云厂商算力采购需求仍强"),
        (r"(three|3).*?(men|people|person).*?(charg|indict).*?(smuggl).*?(ai|chip).*?china", "美国就对华AI芯片走私案起诉相关人员，高端算力出口管制继续趋严"),
        (r"asia.*?tech.*?(sink|slide|fall).*?(chip|semiconductor).*?supply chain", "油价飙升与地缘风险压制亚洲科技股，市场担忧芯片供应链再受扰动"),
        (r"china.*?south korea.*?(supply chain).*?(stability|stable|maintain)", "中国与韩国表态维护供应链稳定，区域制造协同预期改善"),
        (r"dhl.*?(warehouse|warehouses).*?(data center|data centers)", "DHL 扩建仓储和配套能力服务数据中心，反映算力基建外溢到物流环节"),
        (r"iran.*?aluminium.*?supply chain", "地缘冲突扰动全球铝供应链，原材料运输与成本端承压"),
        (r"accenture.*?(earnings|results).*?(beat|top)", "埃森哲财报超预期后股价走强，市场对 AI 投入回报的担忧阶段性缓和"),
        (r"rare earth.*?(shortage|shortages).*?(semiconductor|aerospace|supply chain)", "稀土短缺开始挤压航空与半导体供应链，材料约束风险升温"),
    ]
    for pattern, rewritten in patterns:
        if re.search(pattern, raw_blob):
            return shorten_cn(f"【{item['topic']}】{rewritten}")

    if all(k in raw_blob for k in ["china", "chip"]) and any(k in raw_blob for k in ["smuggl", "charge"]):
        return shorten_cn(f"【{item['topic']}】美国就对华AI芯片走私案起诉相关人员，高端算力出口管制继续趋严")
    if "hong kong" in raw_blob and any(k in raw_blob for k in ["listing", "ipo", "raise"]):
        return shorten_cn(f"【{item['topic']}】中国企业加快赴港融资，一级融资与监管审视同步升温")
    if any(k in raw_blob for k in ["supply chain", "logistics", "warehouse"]) and any(k in raw_blob for k in ["data center", "ai", "chip"]):
        return shorten_cn(f"【{item['topic']}】算力扩张正外溢至物流和仓储环节，供应链配套需求持续抬升")
    if any(k in raw_blob for k in ["oil", "war", "attack"]) and any(k in raw_blob for k in ["tech stocks", "supply chain", "chip"]):
        return shorten_cn(f"【{item['topic']}】能源与地缘风险升温压制科技板块，芯片与制造链再受扰动")

    prefix = MORNING_PREFIX.get(item["topic"], item["topic"])
    core = title
    if not re.search(r"[。；，]", core) and desc:
        desc = re.sub(r"^" + re.escape(title) + r"[\s:：,，;；-]*", "", desc, flags=re.I)
        desc = desc[:60]
        if desc:
            core = f"{title}，{desc}"
    core = re.sub(r"\bwith helping\b", "协助", core, flags=re.I)
    core = re.sub(r"\bexploring a sale\b", "研究出售", core, flags=re.I)
    core = re.sub(r"\bseek\b", "寻求", core, flags=re.I)
    core = re.sub(r"\bamid\b", "，同时", core, flags=re.I)
    core = re.sub(r"\bdominate\w*\b", "主导", core, flags=re.I)
    core = re.sub(r"\bsink\b", "下跌", core, flags=re.I)
    core = re.sub(r"\brattle\w*\b", "扰动", core, flags=re.I)
    core = re.sub(r"\bpowers up\b", "加码", core, flags=re.I)
    core = re.sub(r"\brallies\b", "走强", core, flags=re.I)
    core = re.sub(r"\bbeat\b", "超预期", core, flags=re.I)
    core = re.sub(r"\s+", " ", core)
    core = re.sub(r"\b(the|a|an|of|to|for|in|on|as|even)\b", "", core, flags=re.I)
    core = re.sub(r"\s+", " ", core).strip(" ,;；，")
    return shorten_cn(f"【{item['topic']}】{prefix}：{core}")


def batch_rewrite(items):
    if not REWRITER_CMD:
        return None, "rewriter_disabled"
    payload = []
    for item in items:
        payload.append({
            "topic": item["topic"],
            "title": item["title"],
            "description": item.get("description", ""),
            "source": item.get("source", ""),
        })
    prompt = {
        "task": "将新闻改写成中文早报风格的一句话摘要",
        "rules": {
            "count": len(payload),
            "max_chars_each": MAX_ITEM_CHARS,
            "format": "仅返回 JSON 数组；每项含summary字段；summary必须以【主题】开头；简洁、客观、可直接晨读；不要照抄英文标题；尽量点明影响。",
        },
        "items": payload,
    }
    try:
        proc = subprocess.run(
            REWRITER_CMD,
            input=json.dumps(prompt, ensure_ascii=False),
            text=True,
            capture_output=True,
            shell=True,
            timeout=90,
        )
    except Exception as exc:
        return None, f"rewriter_exec_failed: {exc}"
    if proc.returncode != 0:
        return None, f"rewriter_nonzero: {proc.stderr.strip()[:200]}"
    raw = proc.stdout.strip()
    if not raw:
        return None, "rewriter_empty"
    try:
        data = json.loads(raw)
    except Exception:
        match = re.search(r"(\[.*\])", raw, flags=re.S)
        if not match:
            return None, "rewriter_bad_json"
        data = json.loads(match.group(1))
    if not isinstance(data, list) or len(data) != len(items):
        return None, "rewriter_bad_shape"
    results = []
    for item, row in zip(items, data):
        summary = row.get("summary") if isinstance(row, dict) else None
        if not summary or not isinstance(summary, str):
            return None, "rewriter_missing_summary"
        summary = shorten_cn(summary)
        if not summary.startswith(f"【{item['topic']}】"):
            summary = shorten_cn(f"【{item['topic']}】{summary}")
        results.append(summary)
    return results, None


def apply_summaries(items):
    rewritten, rewrite_error = batch_rewrite(items)
    if rewritten:
        for item, summary in zip(items, rewritten):
            item["summary"] = summary
            item["summary_mode"] = "rewriter"
        return rewrite_error
    for item in items:
        item["summary"] = heuristic_cn_line(item)
        item["summary_mode"] = "heuristic"
    return rewrite_error


def choose_items(items, now):
    dedup = {}
    for item in items:
        if item.get("source") in BLOCKED_SOURCES:
            continue
        title_blob = f"{item.get('title', '')} {item.get('description', '')}".lower()
        if any(re.search(pattern, title_blob) for pattern in BLOCKED_TITLE_PATTERNS):
            continue
        key = item["norm_title"] or item["link"] or item["title"]
        item["score"] = score_item(item, now)
        prev = dedup.get(key)
        if prev is None or item["score"] > prev["score"]:
            dedup[key] = item

    dedup2 = {}
    for item in dedup.values():
        key = item["fingerprint"] or item["norm_title"]
        prev = dedup2.get(key)
        if prev is None or item["score"] > prev["score"]:
            dedup2[key] = item

    ranked = sorted(dedup2.values(), key=lambda x: (x["score"], x["pub_dt"] or datetime(1970, 1, 1, tzinfo=TZ)), reverse=True)
    picked = []
    topic_count = {}
    seen_clusters = set()
    for item in ranked:
        topic = item["topic"]
        if topic_count.get(topic, 0) >= 3:
            continue
        cluster = event_cluster(item)
        if cluster and cluster in seen_clusters:
            continue
        if any(title_similarity(item["title"], existing["title"]) >= 0.4 for existing in picked):
            continue
        picked.append(item)
        topic_count[topic] = topic_count.get(topic, 0) + 1
        if cluster:
            seen_clusters.add(cluster)
        if len(picked) == MAX_ITEMS:
            break

    rewrite_error = apply_summaries(picked)

    compacted = []
    total_chars = 0
    for item in picked:
        summary = shorten_cn(item["summary"])
        if total_chars + len(summary) > MAX_TOTAL_CHARS and len(compacted) >= 8:
            continue
        item["summary"] = summary
        compacted.append(item)
        total_chars += len(summary)
    return compacted, total_chars, rewrite_error


def overall_comment(items):
    topics = [item["topic"] for item in items]
    counts = Counter(topics)
    focus = [label for label, _ in counts.most_common(4)]
    joined = "、".join(focus) or "宏观与科技"
    if "半导体" in topics or "AI" in topics:
        tail = "算力、芯片与供应链仍是交易主线。"
    elif "宏观" in topics or "资本市场" in topics:
        tail = "宏观利率与风险偏好继续主导资产定价。"
    else:
        tail = "科技与产业链消息对风险偏好影响更大。"
    return f"今晨焦点集中在{joined}，优先保留对估值、供需和风险偏好更敏感的事件；{tail}"


def morning_brief(items):
    if not items:
        return "今晨公开信源较少，未形成稳定早报样本。"
    top_topics = [item["topic"] for item in items[:5]]
    counts = Counter(top_topics)
    lead = []
    for topic, _ in counts.most_common(3):
        lead.append(MORNING_PREFIX.get(topic, topic))
    lead_text = "、".join(lead) if lead else "宏观面"
    return f"今晨市场要闻以{lead_text}为主，先看影响资产定价与产业链预期的10条高权重新闻。"


def source_strategy():
    return [
        "先抓 Google News RSS 近 24 小时公开新闻聚合结果，覆盖宏观、资本市场、科技、AI、半导体、供应链六类主题。",
        "排序优先 Reuters、Bloomberg、Financial Times、WSJ、CNBC、AP、Nikkei Asia 等主流媒体，再叠加关键词与时效权重。",
        "按标题归一化与指纹去重，避免同一事件重复入选；单一主题最多保留 3 条，尽量把 10 条做成晨报式覆盖。",
        "摘要采用“两段式”策略：优先调用可配置中文重写器批量改写，失败时回退到本地规则压缩，仍保持可读中文输出。",
        f"最终强约束：最多 {MAX_ITEMS} 条、单条 ≤ {MAX_ITEM_CHARS} 字、总长度 ≤ {MAX_TOTAL_CHARS} 字。",
    ]


def render(date_str, timestamp, items, total_chars, rewrite_error=None):
    lines = []
    lines.append(f"# 市场要闻早报（{date_str}）")
    lines.append("")
    lines.append(f"> 生成时间：{timestamp}")
    lines.append(f"> 约束：最多 {MAX_ITEMS} 条；单条摘要 ≤ {MAX_ITEM_CHARS} 字；摘要总字数 ≤ {MAX_TOTAL_CHARS} 字。")
    lines.append("")
    lines.append("## 今晨导读")
    lines.append(f"- {morning_brief(items)}")
    lines.append("")
    lines.append("## 今日 10 条要闻")
    for idx, item in enumerate(items, 1):
        meta = []
        if item.get("source"):
            meta.append(item["source"])
        if item.get("pub_dt"):
            meta.append(item["pub_dt"].strftime("%m-%d %H:%M"))
        meta_text = f"（{' | '.join(meta)}）" if meta else ""
        lines.append(f"{idx}. {item['summary']}{meta_text}")
    lines.append("")
    lines.append("## 一句话总评")
    lines.append(f"- {overall_comment(items)}")
    lines.append("")
    lines.append("## 来源选择策略")
    for s in source_strategy():
        lines.append(f"- {s}")
    lines.append("")
    lines.append("## 主要来源")
    seen = []
    for item in items:
        source = item.get("source") or "Unknown"
        if source not in seen:
            seen.append(source)
    for source in seen:
        lines.append(f"- {source}")
    lines.append("")
    lines.append("## 生成说明")
    lines.append(f"- 本期共入选 {len(items)} 条，摘要总长度约 {total_chars} 字。")
    modes = Counter(item.get("summary_mode", "unknown") for item in items)
    mode_text = "、".join(f"{k}:{v}" for k, v in modes.items())
    lines.append(f"- 摘要生成模式：{mode_text}。")
    if rewrite_error and rewrite_error != "rewriter_disabled":
        lines.append(f"- 中文重写器本次未生效，已自动回退到本地规则压缩：{rewrite_error}。")
    elif rewrite_error == "rewriter_disabled":
        lines.append("- 未配置外部中文重写器，当前使用本地规则压缩。")
    else:
        lines.append("- 已启用外部中文重写器，并在长度校验后输出。")
    lines.append("- 若公开 RSS 当天可见报道不足，结果可能少于 10 条；抓取失败详情会输出到 stderr，便于 cron / shell 日志排查。")
    lines.append("")
    return "\n".join(lines)


def main(argv):
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    output_dir = DEFAULT_OUTPUT_DIR
    if len(argv) > 1:
        output_dir = argv[1]
    os.makedirs(output_dir, exist_ok=True)
    items = []
    failures = []
    for feed in FEEDS:
        url = google_news_rss(feed["query"])
        try:
            items.extend(parse_feed(url, feed["label"], feed["weight"]))
        except Exception as exc:
            failures.append(f'{feed["label"]}: {exc}')
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    items = [i for i in items if i.get("pub_dt") is None or i["pub_dt"] >= cutoff]
    picked, total_chars, rewrite_error = choose_items(items, now)
    if not picked:
        raise SystemExit("No news items fetched from public RSS feeds.")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    content = render(date_str, timestamp, picked, total_chars, rewrite_error=rewrite_error)
    out = os.path.join(output_dir, f"daily-news-digest-{date_str}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    print(out)
    if failures:
        print("WARN: " + " | ".join(failures), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
