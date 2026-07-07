#!/usr/bin/env python3
import json
import os
import re
import sys


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
REGION_RE = re.compile(r"Region:\s*([A-Za-z0-9_-]+)")
DISNEY_SOON_RE = re.compile(r"Available For \[Disney\+\s+([A-Za-z]{2})\] Soon", re.I)
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
STATUS_TOKEN_VALUES = {"YES", "NO", "N/A"}
FIXED_WIDTH_STATUS_RE = re.compile(
    r"^(?P<name>.+?)\s{2,}(?P<value>(?:yes|no|failed|failure|unsupported|unsupport|n/a|"
    r"originals only|oversea only|app only|website only|idc ip|available\b|"
    r"[A-Z]{2,3})(?:\s*\(.*\))?)$",
    re.I,
)
COUNTRY_NAME_MAP = {
    "hong kong": "HK",
    "taiwan": "TW",
    "china": "CN",
    "japan": "JP",
    "korea": "KR",
    "south korea": "KR",
    "singapore": "SG",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "germany": "DE",
    "france": "FR",
    "canada": "CA",
    "australia": "AU",
    "netherlands": "NL",
}
CURRENCY_COUNTRY_MAP = {
    "HKD": "HK",
    "TWD": "TW",
    "JPY": "JP",
    "CNY": "CN",
    "USD": "US",
    "SGD": "SG",
    "KRW": "KR",
    "GBP": "GB",
    "EUR": "EU",
    "CAD": "CA",
    "AUD": "AU",
}
DISPLAY_COUNTRY_MAP = {
    "CN": "中国",
    "HK": "香港",
    "TW": "台湾",
    "JP": "日本",
    "KR": "韩国",
    "SG": "新加坡",
    "US": "美国",
    "GB": "英国",
    "DE": "德国",
    "FR": "法国",
    "CA": "加拿大",
    "AU": "澳大利亚",
    "NL": "荷兰",
    "EU": "欧洲",
}
NETWORK_RE = re.compile(
    r"(?:Your Network Provider|你的网络为)\s*:\s*(?P<isp>.*?)\s*\((?P<ip>[^)]*)\)",
    re.I,
)
SECTION_CLEAN_RE = re.compile(r"[\s=\-\[\]【】|:：]+")

AI_SERVICES = {
    "chatgpt",
    "openai",
    "openai_api",
    "google_gemini",
    "gemini",
    "bing_region",
    "bing",
    "copilot",
    "microsoft_copilot",
    "github_copilot",
    "claude",
    "anthropic_claude",
    "claude_api",
    "claude_code",
    "anthropic",
    "poe",
    "perplexity",
    "grok",
    "xai_grok",
    "x_ai_grok",
    "meta_ai",
    "google_ai_studio",
    "google_vertex_ai",
    "deepseek",
    "mistral",
    "mistral_ai",
    "notion_ai",
    "vercel_v0",
    "cursor",
    "windsurf",
    "kimi",
    "qwen",
    "doubao",
}

OTHER_SERVICES = {
    "apple",
    "apple_region",
    "google_play_store",
    "steam",
    "steam_currency",
    "wikipedia_editability",
    "reddit",
}

REGION_VALUE_SERVICES = {
    "apple_region",
    "bing_region",
    "google_play_store",
    "steam_currency",
}

IGNORE_NAME_PREFIXES = (
    "input number",
    "please input",
    "请输入",
    "输入数字",
    "项目地址",
    "改版地址",
    "脚本适配os",
    "测试时间",
    "你的网络为",
    "your network provider",
    "today",
    "total",
    "今日",
    "总计",
    "更多套餐",
    "更多优惠",
    "优惠",
)

IGNORE_VALUE_PREFIXES = (
    "[ multination",
    "[ sport",
    "[ 跨国",
    "[   ",
    "[跨国",
)


def clean_line(line):
    line = ANSI_RE.sub("", line).replace("\r", "")
    # Codex改动：只清理纯分隔线，不能清掉 "Claude    NO" 这类无地区的英文检测行。
    line = re.sub(r"^[=\-\s\[\]【】|:：]+$", "", line)
    return line.strip()


def service_key(name):
    key = name.strip().lower()
    key = key.replace("+", " plus")
    key = key.replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", "_", key)
    return key.strip("_")


def split_service_line(line):
    fixed_match = FIXED_WIDTH_STATUS_RE.match(line)
    if fixed_match:
        return fixed_match.group("name").strip(), fixed_match.group("value").strip()
    if ":" not in line:
        return None, None
    name, value = line.split(":", 1)
    return name.strip(), value.strip()


def detect_section(line):
    raw = ANSI_RE.sub("", line).replace("\r", "").strip()
    if not raw:
        return None
    normalized = SECTION_CLEAN_RE.sub("", raw).lower()
    if not normalized:
        return None
    if normalized in {"ai", "aigc", "人工智能", "ai检测", "aigc检测"}:
        return "ai"
    if normalized in {"other", "others", "misc", "其他", "其它", "商店", "游戏", "forum", "game"}:
        return "other"
    if normalized in {"multination", "media", "流媒体", "跨国平台", "跨国", "global"}:
        return "media"
    return None


def category_for(key, section=None):
    if key in AI_SERVICES:
        return "ai"
    if key in OTHER_SERVICES:
        return "other"
    if section in {"ai", "other", "media"}:
        return section
    return "media"


def normalize_status(value):
    lower = value.lower()
    if "originals only" in lower:
        return "originals_only"
    if "idc ip" in lower:
        return "idc_ip"
    if "oversea only" in lower:
        return "oversea_only"
    if "app only" in lower:
        return "app_only"
    if "website only" in lower:
        return "website_only"
    if "available for" in lower and "soon" in lower:
        return "coming_soon"
    if re.search(r"\byes\b", lower):
        return "yes"
    if re.search(r"\bno\b", lower):
        return "no"
    if "failed" in lower:
        return "failed"
    if "unsupport" in lower:
        return "unsupported"
    return "unknown"


def unlock_type(value):
    if "原生解锁" in value or "Native" in value:
        return "native"
    if "DNS 解锁" in value or "Via DNS" in value:
        return "dns"
    if "代理解锁" in value or "Via Proxy" in value or "Proxy" in value:
        return "proxy"
    return None


def country_from_region(region):
    if not region:
        return None
    region = region.strip()
    region_upper = region.upper()
    if region_upper in STATUS_TOKEN_VALUES:
        return None
    if COUNTRY_RE.match(region_upper):
        return region_upper
    normalized = region.lower()
    return COUNTRY_NAME_MAP.get(normalized)


def extract_region(value):
    region_match = REGION_RE.search(value)
    if region_match:
        return region_match.group(1).strip()

    disney_soon_match = DISNEY_SOON_RE.search(value)
    if disney_soon_match:
        return disney_soon_match.group(1).strip()

    normalized = value.strip()
    if normalized.upper() in STATUS_TOKEN_VALUES:
        return None
    if normalized.lower() in COUNTRY_NAME_MAP:
        return normalized

    tokens = [token for token in re.findall(r"\b[A-Z]{2}\b", value) if token not in STATUS_TOKEN_VALUES]
    if tokens:
        return tokens[-1]

    # Google Gemini currently prints a three-letter region token such as HKG.
    if re.fullmatch(r"[A-Z]{3}", normalized) and normalized not in CURRENCY_COUNTRY_MAP:
        return normalized

    return None


def extract_country(value):
    region = extract_region(value)
    if region:
        return country_from_region(region), region

    tokens = re.findall(r"\b[A-Z]{2}\b", value)
    tokens = [token for token in tokens if token not in STATUS_TOKEN_VALUES]
    if tokens:
        return tokens[-1], tokens[-1]

    normalized = value.strip().lower()
    if normalized in COUNTRY_NAME_MAP:
        return COUNTRY_NAME_MAP[normalized], value.strip()

    currency = value.strip().upper()
    if CURRENCY_RE.match(currency) and currency in CURRENCY_COUNTRY_MAP:
        return CURRENCY_COUNTRY_MAP[currency], None

    return None, None


def display_country(country_code, region_raw):
    if country_code:
        return DISPLAY_COUNTRY_MAP.get(country_code, country_code)
    if region_raw:
        normalized = region_raw.strip()
        mapped = country_from_region(normalized)
        if mapped:
            return DISPLAY_COUNTRY_MAP.get(mapped, normalized)
        return normalized
    return None


def display_value_for(key, value, country_code, region_raw):
    if key == "steam_currency":
        currency = value.strip().upper()
        if CURRENCY_RE.match(currency):
            return currency
        return None
    if key in {"apple", "apple_region", "bing", "bing_region"}:
        return display_country(country_code, region_raw)
    if key == "google_play_store":
        country = display_country(country_code, region_raw)
        if country and country.lower() != "china":
            return country
        return None
    return None


def parse_line(line, section=None):
    line = clean_line(line)
    if not line or ":" not in line:
        fixed_name, fixed_value = split_service_line(line)
        if not fixed_name or not fixed_value:
            return None
    if re.search(r"https?://|//[A-Za-z0-9.-]+\.[A-Za-z]{2,}", line):
        return None

    name, value = split_service_line(line)
    if not name or value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    if not name or not value:
        return None

    ignore_name = re.sub(r"^[^A-Za-z0-9\u4e00-\u9fff]+", "", name).lower()
    lower_value = value.lower()
    if ignore_name.startswith(IGNORE_NAME_PREFIXES):
        return None
    if lower_value.startswith(IGNORE_VALUE_PREFIXES):
        return None
    if re.search(r"[A-Za-z0-9.-]+\.(com|net|org|xyz|cn|io|me|tv|host)\b", name + " " + value, re.I):
        return None
    if re.fullmatch(r"\[?\s*\d+\]?", name):
        return None

    key = service_key(name)
    if not key:
        return None
    country_code, region_raw = extract_country(value)

    status = normalize_status(value)
    # Codex改动：区域/货币类检测通常直接输出 HK/HKD/国家名，不带 Yes；前端只展示 yes，因此这里归一为可用。
    if key in REGION_VALUE_SERVICES and status == "unknown" and value:
        status = "yes"
    # Codex改动：Google Play 检测到 China 时不视为可展示解锁结果，其它国家再展示国家。
    if key == "google_play_store" and (country_code == "CN" or value.strip().lower() == "china"):
        status = "no"

    item = {
        "name": name,
        "status": status,
        "raw": value,
    }

    detected_unlock_type = unlock_type(value)
    if detected_unlock_type:
        item["unlock_type"] = detected_unlock_type
    if key == "steam_currency" and CURRENCY_RE.match(value):
        item["currency_code"] = value.upper()
    if region_raw:
        item["region"] = region_raw
    if country_code:
        item["country_code"] = country_code
    if region_raw and region_raw != country_code:
        item["region_raw"] = region_raw
    display_value = display_value_for(key, value, country_code, region_raw)
    if display_value:
        item["display_value"] = display_value

    return category_for(key, section), key, item


def parse_network_line(line):
    line = clean_line(line)
    line = re.sub(r"^[^A-Za-z0-9\u4e00-\u9fff]+", "", line).strip()
    match = NETWORK_RE.search(line)
    if not match:
        return None
    return {
        "outbound_isp": re.sub(r"\s+", " ", match.group("isp")).strip(),
        "outbound_ip": match.group("ip").strip(),
    }


def node_meta_from_env():
    node = {}
    env_map = {
        "id": "UNLOCK_NODE_ID",
        "name": "UNLOCK_NODE_NAME",
        "host": "UNLOCK_NODE_HOST",
        "port": "UNLOCK_NODE_PORT",
        "proxy": "UNLOCK_NODE_PROXY",
        "outbound_ip": "UNLOCK_NODE_OUTBOUND_IP",
    }
    for key, env_key in env_map.items():
        value = os.environ.get(env_key)
        if not value:
            continue
        if key in {"id", "port"}:
            try:
                node[key] = int(value)
                continue
            except ValueError:
                pass
        node[key] = value
    return node


def main():
    result = {
        "node": node_meta_from_env(),
        "media": {},
        "ai": {},
        "other": {},
    }

    current_section = None
    for line in sys.stdin:
        section = detect_section(line)
        if section:
            current_section = section
            continue
        network = parse_network_line(line)
        if network:
            result["node"].update(network)
            continue
        parsed = parse_line(line, current_section)
        if not parsed:
            continue
        category, key, item = parsed
        result[category][key] = item

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
