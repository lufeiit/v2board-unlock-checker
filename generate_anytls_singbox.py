#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile


SUPPORTED_TABLE_SUFFIXES = {
    "server_anytls": "anytls",
    "server_hysteria": "hysteria",
    "server_shadowsocks": "shadowsocks",
    "server_trojan": "trojan",
    "server_tuic": "tuic",
    "server_v2node": "v2node",
    "server_vless": "vless",
    "server_vmess": "vmess",
}

NON_NODE_TABLE_PATTERNS = ("group", "log", "route", "stat", "copy")


def read_env(path):
    env = {}
    if not path or not os.path.isfile(path):
        return env
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            env[key.strip()] = value
    return env


def merge_db_env(env):
    merged = dict(env)
    for key in ("DB_HOST", "DB_PORT", "DB_DATABASE", "DB_USERNAME", "DB_PASSWORD"):
        if os.getenv(key):
            merged[key] = os.getenv(key)
    return merged


def mysql_query(env, query, skip_column_names=True):
    defaults = "\n".join(
        [
            "[client]",
            f"user={env['DB_USERNAME']}",
            f"password={env.get('DB_PASSWORD', '')}",
            f"host={env.get('DB_HOST', '127.0.0.1')}",
            f"port={env.get('DB_PORT', '3306')}",
            f"database={env['DB_DATABASE']}",
            "protocol=tcp",
            "default-character-set=utf8mb4",
            "",
        ]
    )
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as file:
        file.write(defaults)
        defaults_path = file.name
    os.chmod(defaults_path, 0o600)
    command = [
        "mysql",
        f"--defaults-extra-file={defaults_path}",
        "--batch",
        "--raw",
    ]
    if skip_column_names:
        command.append("--skip-column-names")
    command.extend(["-e", query])
    try:
        proc = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        os.unlink(defaults_path)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "mysql query failed")
    return proc.stdout


def mysql_literal(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def mysql_identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"invalid mysql identifier: {value}")
    return f"`{value}`"


def parse_rows(output, columns=None):
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        row = line.split("\t")
        if columns and len(row) < columns:
            row.extend([""] * (columns - len(row)))
        rows.append(row)
    return rows


def parse_table_rows(output):
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    columns = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        values.extend([""] * (len(columns) - len(values)))
        rows.append(dict(zip(columns, values)))
    return rows


def table_columns(env, table):
    rows = parse_rows(
        mysql_query(
            env,
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = "
            + mysql_literal(table)
            + " ORDER BY ORDINAL_POSITION",
        ),
        columns=1,
    )
    return [row[0] for row in rows]


def load_table_json_rows(env, table, where, order):
    columns = table_columns(env, table)
    if not columns:
        return []
    pairs = []
    for column in columns:
        pairs.append(mysql_literal(column))
        pairs.append(f"`{column}`")
    query = f"SELECT JSON_OBJECT({', '.join(pairs)}) FROM `{table}` WHERE {where} {order}"
    rows = []
    for line in mysql_query(env, query).splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def json_value(value, default=None):
    if value in (None, "", "NULL"):
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def safe_int(value, default=0):
    try:
        if value in (None, "", "NULL"):
            return default
        return int(value)
    except Exception:
        return default


def first_port(port):
    port = str(port).strip()
    if "," in port:
        port = port.split(",", 1)[0]
    if "-" in port:
        port = port.split("-", 1)[0]
    if not re.fullmatch(r"\d+", port):
        raise ValueError(f"invalid port: {port}")
    return int(port)


def clean_tag(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")


def node_domain_label(name):
    match = re.search(r"([A-Za-z]{2})\D*0*(\d{1,3})", name)
    if match:
        return f"{match.group(1).lower()}{int(match.group(2)):02d}"
    slug = re.sub(r"[^A-Za-z0-9]+", "", name).lower()
    return slug or "node"


def parse_kv_map(value):
    mapping = {}
    if not value:
        return mapping
    if os.path.isfile(value):
        with open(value, "r", encoding="utf-8") as file:
            value = file.read()
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            return {str(key): str(val) for key, val in data.items()}
    except Exception:
        pass
    for item in value.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, val = item.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key and val:
            mapping[key] = val
    return mapping


def domain_label(row, args):
    mapping = args.domain_label_map or {}
    for key in (str(row.get("id", "")), row.get("name", "")):
        if key in mapping:
            return mapping[key]
    return node_domain_label(row["name"])


def split_csv(value):
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_remote(row, args):
    if args.address_mode == "panel":
        return row["host"], first_port(row["port"])
    if not args.domain:
        raise RuntimeError("--domain is required when --address-mode domain")
    label = domain_label(row, args)
    try:
        host = args.domain_template.format(label=label, domain=args.domain)
    except ValueError as exc:
        raise RuntimeError(
            f"invalid DOMAIN_TEMPLATE={args.domain_template!r}: use placeholders like "
            "{label}.{domain}, and escape literal braces as {{ or }}"
        ) from exc
    except KeyError as exc:
        raise RuntimeError(
            f"invalid DOMAIN_TEMPLATE={args.domain_template!r}: unsupported placeholder {exc}; "
            "only {label} and {domain} are supported"
        ) from exc
    return host, first_port(row.get("server_port") or row["port"])


def uuid_to_base64(uuid, length):
    return base64.b64encode(uuid[:length].encode()).decode()


def server_key(timestamp, length):
    return base64.b64encode(hashlib.md5(str(timestamp).encode()).hexdigest()[:length].encode()).decode()


def tls_config(row, enabled=True, insecure=True, server_name=None, alpn=None):
    if not enabled:
        return None
    tls_settings = json_value(row.get("tls_settings") or row.get("tlsSettings"))
    config = {
        "enabled": True,
        "insecure": bool(insecure),
    }
    name = server_name or row.get("server_name") or tls_settings.get("server_name") or tls_settings.get("serverName")
    if name:
        config["server_name"] = name
    if alpn:
        config["alpn"] = alpn
    if str(row.get("tls", "0")) == "2" and tls_settings.get("public_key"):
        config["reality"] = {
            "enabled": True,
            "public_key": tls_settings.get("public_key", ""),
            "short_id": tls_settings.get("short_id", ""),
        }
    fingerprint = tls_settings.get("fingerprint")
    if fingerprint:
        config["utls"] = {"enabled": True, "fingerprint": fingerprint}
    return config


def apply_transport(outbound, row):
    network = row.get("network")
    settings = json_value(row.get("network_settings") or row.get("networkSettings"))
    if network == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": settings.get("path", "/"),
            "max_early_data": 2048,
            "early_data_header_name": "Sec-WebSocket-Protocol",
        }
        host = (settings.get("headers") or {}).get("Host")
        if host:
            outbound["transport"]["headers"] = {"Host": [host]}
    elif network == "grpc":
        outbound["transport"] = {"type": "grpc"}
        if settings.get("serviceName"):
            outbound["transport"]["service_name"] = settings["serviceName"]
    elif network == "tcp":
        header = settings.get("header") or {}
        request = header.get("request") or {}
        if header.get("type") == "http":
            outbound["transport"] = {"type": "http"}
            hosts = (request.get("headers") or {}).get("Host")
            if hosts:
                outbound["transport"]["host"] = hosts
            paths = request.get("path")
            if paths:
                outbound["transport"]["path"] = paths[0] if isinstance(paths, list) else paths


def build_shadowsocks(row, uuid, server, server_port, args):
    password = uuid
    method = row.get("cipher") or "aes-128-gcm"
    if "2022-blake3" in method:
        length = 16 if method == "2022-blake3-aes-128-gcm" else 32
        password = f"{server_key(row.get('created_at', ''), length)}:{uuid_to_base64(uuid, length)}"
    outbound = {
        "type": "shadowsocks",
        "server": server,
        "server_port": server_port,
        "method": method,
        "password": password,
    }
    obfs_settings = json_value(row.get("obfs_settings"))
    if row.get("obfs") == "http":
        parts = ["obfs=http"]
        if obfs_settings.get("host"):
            parts.append(f"obfs-host={obfs_settings['host']}")
        if obfs_settings.get("path"):
            parts.append(f"path={obfs_settings['path']}")
        outbound["plugin"] = "obfs-local"
        outbound["plugin_opts"] = ";".join(parts)
    return outbound


def build_vmess(row, uuid, server, server_port, args):
    outbound = {
        "type": "vmess",
        "server": server,
        "server_port": server_port,
        "uuid": uuid,
        "security": "auto",
        "alter_id": 0,
    }
    if truthy(row.get("tls")):
        outbound["tls"] = tls_config(row, insecure=args.insecure, server_name=None)
    apply_transport(outbound, row)
    return outbound


def build_vless(row, uuid, server, server_port, args):
    outbound = {
        "type": "vless",
        "server": server,
        "server_port": server_port,
        "uuid": uuid,
        "packet_encoding": "xudp",
    }
    if row.get("flow"):
        outbound["flow"] = row["flow"]
    if truthy(row.get("tls")) or str(row.get("tls")) == "2":
        outbound["tls"] = tls_config(row, insecure=args.insecure, server_name=None)
    apply_transport(outbound, row)
    return outbound


def build_trojan(row, uuid, server, server_port, args):
    outbound = {
        "type": "trojan",
        "server": server,
        "server_port": server_port,
        "password": uuid,
        "tls": tls_config(row, insecure=args.insecure or truthy(row.get("allow_insecure"))),
    }
    apply_transport(outbound, row)
    return outbound


def build_tuic(row, uuid, server, server_port, args):
    return {
        "type": "tuic",
        "server": server,
        "server_port": server_port,
        "uuid": uuid,
        "password": uuid,
        "congestion_control": row.get("congestion_control") or "cubic",
        "udp_relay_mode": row.get("udp_relay_mode") or "native",
        "zero_rtt_handshake": truthy(row.get("zero_rtt_handshake")),
        "tls": tls_config(
            row,
            insecure=args.insecure or truthy(row.get("insecure")),
            server_name=row.get("server_name"),
            alpn=["h3"],
        ),
    }


def build_anytls(row, uuid, server, server_port, args):
    return {
        "type": "anytls",
        "server": server,
        "server_port": server_port,
        "password": uuid,
        "tls": tls_config(
            row,
            insecure=args.insecure or truthy(row.get("insecure")),
            server_name=row.get("server_name") or server,
            alpn=["h2", "http/1.1"],
        ),
    }


def build_hysteria(row, uuid, server, server_port, args):
    version = str(row.get("version") or "2")
    if version == "1":
        outbound = {
            "type": "hysteria",
            "server": server,
            "server_port": server_port,
            "auth_str": uuid,
            "up_mbps": int(row.get("up_mbps") or 100),
            "down_mbps": int(row.get("down_mbps") or 100),
            "tls": tls_config(row, insecure=args.insecure or truthy(row.get("insecure"))),
            "disable_mtu_discovery": True,
        }
        if row.get("obfs_password"):
            outbound["obfs"] = row["obfs_password"]
        return outbound
    outbound = {
        "type": "hysteria2",
        "server": server,
        "server_port": server_port,
        "password": uuid,
        "tls": tls_config(row, insecure=args.insecure or truthy(row.get("insecure"))),
    }
    if row.get("obfs"):
        outbound["obfs"] = {"type": row["obfs"], "password": row.get("obfs_password") or ""}
    return outbound


BUILDERS = {
    "anytls": build_anytls,
    "hysteria": build_hysteria,
    "shadowsocks": build_shadowsocks,
    "trojan": build_trojan,
    "tuic": build_tuic,
    "vless": build_vless,
    "vmess": build_vmess,
}


def effective_protocol(table_protocol, row):
    if table_protocol == "v2node":
        return (row.get("protocol") or "").lower()
    return table_protocol


def discover_tables(env, selected_types, table_prefix):
    rows = parse_rows(
        mysql_query(
            env,
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()",
        ),
        columns=1,
    )
    tables = []
    selected = set(selected_types) if selected_types else None
    server_prefix = f"{table_prefix}server_"
    for row in rows:
        table = row[0]
        lowered = table.lower()
        if any(pattern in lowered for pattern in NON_NODE_TABLE_PATTERNS):
            continue
        if not table.startswith(server_prefix):
            continue
        suffix = "server_" + table[len(server_prefix):]
        if suffix not in SUPPORTED_TABLE_SUFFIXES:
            continue
        protocol = SUPPORTED_TABLE_SUFFIXES[suffix]
        table_type = table[len(server_prefix):]
        if selected and protocol not in selected and table_type not in selected:
            continue
        tables.append((table, protocol))
    return sorted(tables)


def load_nodes(env, args):
    nodes = []
    for table, table_protocol in discover_tables(env, args.types, args.table_prefix):
        where = ["parent_id IS NULL"]
        if not args.include_hidden:
            where.append("`show` = 1")
        where_sql = " AND ".join(where)
        for row in load_table_json_rows(env, table, where_sql, "ORDER BY sort ASC, id ASC"):
            if args.exclude_name and row.get("name") in set(args.exclude_name):
                continue
            protocol = effective_protocol(table_protocol, row)
            if protocol not in BUILDERS:
                continue
            row["_table"] = table
            row["_protocol"] = protocol
            nodes.append(row)
    return sorted(nodes, key=lambda item: (safe_int(item.get("sort")), safe_int(item.get("id"))))


def build_config(nodes, uuid, args):
    inbounds = []
    outbounds = []
    route_rules = []
    proxy_map = []

    for index, row in enumerate(nodes):
        local_port = args.base_port + index
        node_id = int(row["id"])
        protocol = row["_protocol"]
        server, server_port = resolve_remote(row, args)
        tag = f"{protocol}-{node_id}"
        inbound_tag = f"{tag}-in"
        outbound_tag = f"{tag}-out"
        outbound = BUILDERS[protocol](row, uuid, server, server_port, args)
        outbound["tag"] = outbound_tag

        inbounds.append(
            {
                "type": "mixed",
                "tag": inbound_tag,
                "listen": args.listen,
                "listen_port": local_port,
            }
        )
        outbounds.append(outbound)
        route_rules.append({"inbound": inbound_tag, "outbound": outbound_tag})
        proxy_map.append(
            {
                "id": node_id,
                "type": protocol,
                "table": row["_table"],
                "name": row["name"],
                "panel_host": row.get("host"),
                "panel_port": first_port(row.get("port")),
                "server": server,
                "server_port": server_port,
                "listen": args.listen,
                "listen_port": local_port,
                "proxy": f"socks5h://{args.listen}:{local_port}",
            }
        )

    config = {
        "log": {"level": args.log_level},
        "inbounds": inbounds,
        "outbounds": [{"type": "direct", "tag": "direct"}] + outbounds,
        "route": {"rules": route_rules, "final": "direct"},
    }
    return config, proxy_map


def main():
    parser = argparse.ArgumentParser(description="Generate sing-box mixed proxies for supported v2board nodes.")
    parser.add_argument("--v2board", default=os.getenv("V2BOARD_PATH", "/www/wwwroot/v2board"), help="v2board project path")
    parser.add_argument("--env-path", default=os.getenv("V2BOARD_ENV_PATH", ""), help="custom v2board .env path; overrides --v2board/.env")
    parser.add_argument("--table-prefix", default=os.getenv("DB_PREFIX", "v2_"), help="v2board database table prefix, default v2_")
    parser.add_argument("--email", default=os.getenv("TEST_EMAIL", "test@test.com"), help="user email whose uuid is used as node password")
    parser.add_argument("--listen", default=os.getenv("LISTEN", "127.0.0.1"), help="local proxy listen address")
    parser.add_argument("--base-port", type=int, default=int(os.getenv("BASE_PORT", "21001")), help="first local proxy port")
    parser.add_argument("--output", default=os.getenv("SINGBOX_CONFIG", "/root/node/anytls-singbox.json"), help="sing-box config output path")
    parser.add_argument("--map", default=os.getenv("PROXY_MAP", "/root/node/anytls-proxies.json"), help="proxy mapping output path")
    parser.add_argument("--include-hidden", action="store_true", default=truthy(os.getenv("INCLUDE_HIDDEN")), help="include nodes with show=0")
    parser.add_argument("--exclude-name", action="append", default=[], help="exclude node by exact name; can be used multiple times")
    parser.add_argument("--exclude-names", default=os.getenv("EXCLUDE_NAMES", "测试节点1,测试节点2"), help="comma separated node names to exclude")
    parser.add_argument("--types", default=os.getenv("NODE_TYPES", "all"), help="comma separated protocols/tables, default all")
    parser.add_argument("--address-mode", choices=("panel", "domain"), default=os.getenv("ADDRESS_MODE", "panel"), help="panel: use host+port; domain: use generated domain+server_port")
    parser.add_argument("--domain", default=os.getenv("NODE_DOMAIN", ""), help="root domain for --address-mode domain, e.g. 你的域名")
    parser.add_argument("--domain-template", default=os.getenv("DOMAIN_TEMPLATE", "{label}.{domain}"), help="domain template with {label} and {domain}")
    parser.add_argument("--domain-label-map", default=os.getenv("DOMAIN_LABEL_MAP", ""), help="custom domain label map, JSON/file or comma pairs: id=hk01,name=sg01")
    parser.add_argument("--insecure", action="store_true", default=truthy(os.getenv("TLS_INSECURE", "1")), help="skip certificate verification for TLS protocols")
    parser.add_argument("--log-level", default=os.getenv("SINGBOX_LOG_LEVEL", "warn"), help="sing-box log level")
    args = parser.parse_args()

    if isinstance(args.types, str):
        args.types = [] if args.types.lower() == "all" else [item.strip().lower() for item in args.types.split(",") if item.strip()]
    args.exclude_name = split_csv(args.exclude_names) + (args.exclude_name or [])
    args.domain_label_map = parse_kv_map(args.domain_label_map)

    env_path = args.env_path or (os.path.join(args.v2board, ".env") if args.v2board else "")
    env = merge_db_env(read_env(env_path))
    for key in ("DB_USERNAME", "DB_DATABASE"):
        if not env.get(key):
            raise RuntimeError(f"missing {key}; set it in {env_path or '.env'} or pass environment variables")

    user_table = mysql_identifier(f"{args.table_prefix}user")
    user_rows = parse_rows(
        mysql_query(
            env,
            f"SELECT uuid FROM {user_table} WHERE email = "
            + mysql_literal(args.email)
            + " LIMIT 1",
        ),
        columns=1,
    )
    if not user_rows:
        raise RuntimeError(f"user not found: {args.email}")
    uuid = user_rows[0][0]

    nodes = load_nodes(env, args)
    if not nodes:
        raise RuntimeError("no supported nodes found")

    config, proxy_map = build_config(nodes, uuid, args)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.map) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write("\n")
    with open(args.map, "w", encoding="utf-8") as file:
        json.dump(proxy_map, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"Generated {len(proxy_map)} proxies")
    print(f"sing-box config: {args.output}")
    print(f"proxy map: {args.map}")
    for item in proxy_map:
        print(f"{item['type']}\t{item['id']}\t{item['name']}\t{item['server']}:{item['server_port']}\t{item['proxy']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
