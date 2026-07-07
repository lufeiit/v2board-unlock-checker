#!/usr/bin/env bash

# Codex改动：以 test.sh 使用的 unlock-test 为主体，同时保留旧批量流程需要的 -J / -P 兼容层。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNLOCK_TEST_VERSION_URL="${UNLOCK_TEST_VERSION_URL:-https://unlock.icmp.ing/test/latest/version}"
UNLOCK_TEST_DOWNLOAD_BASE="${UNLOCK_TEST_DOWNLOAD_BASE:-https://unlock.icmp.ing/test/latest}"
UNLOCK_TEST_BIN="${UNLOCK_TEST_BIN:-}"
UNLOCK_TEST_INSTALL_DIR="${UNLOCK_TEST_INSTALL_DIR:-/usr/local/bin}"
UNLOCK_TEST_AUTO_UPDATE="${UNLOCK_TEST_AUTO_UPDATE:-0}"

has_arg() {
    local wanted="$1"
    shift
    local arg
    for arg in "$@"; do
        if [ "$arg" = "$wanted" ]; then
            return 0
        fi
    done
    return 1
}

run_json_mode() {
    local args=()
    local arg
    for arg in "$@"; do
        if [ "$arg" != "-J" ]; then
            args+=("$arg")
        fi
    done

    local output_file
    output_file="$(mktemp)"
    # Codex改动：新版 unlock-test 可能把部分检测/分区输出写到 stderr，JSON 模式统一收集后交给 parser 过滤。
    # Codex改动：批量检测通过 UNLOCK_MENU 自动选择菜单，避免 Docker 非交互下只跑默认/卡住。
    if [ -n "${UNLOCK_MENU:-}" ]; then
        printf '%s\n' "$UNLOCK_MENU" | UNLOCK_JSON_MODE=1 bash "$0" "${args[@]}" >"$output_file" 2>&1
    else
        UNLOCK_JSON_MODE=1 bash "$0" "${args[@]}" >"$output_file" 2>&1
    fi
    local status=$?
    "$SCRIPT_DIR/parse_unlock_result.py" <"$output_file"
    rm -f "$output_file"
    exit "$status"
}

if has_arg "-J" "$@"; then
    run_json_mode "$@"
fi

map_unlock_test_arch() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
        x86|i386|i686) echo "386" ;;
        x86_64|amd64) echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        armv7*|armv8l) echo "arm7" ;;
        armv6*) echo "arm6" ;;
        armv5*) echo "arm5" ;;
        loongarch64) echo "loong64" ;;
        mips64el) echo "mips64le" ;;
        mipsel) echo "mipsle" ;;
        *) echo "unsupported" ;;
    esac
}

map_unlock_test_os() {
    if [ -f /etc/openwrt_release ]; then
        uname -s | awk '{print tolower($0)}'
        return
    fi
    if command -v termux-setup-storage >/dev/null 2>&1; then
        echo "android"
        return
    fi
    uname -s | tr '[:upper:]' '[:lower:]'
}

find_unlock_test() {
    if [ -n "$UNLOCK_TEST_BIN" ] && [ -x "$UNLOCK_TEST_BIN" ]; then
        echo "$UNLOCK_TEST_BIN"
        return 0
    fi
    if command -v unlock-test >/dev/null 2>&1; then
        command -v unlock-test
        return 0
    fi
    if [ -x "$UNLOCK_TEST_INSTALL_DIR/unlock-test" ]; then
        echo "$UNLOCK_TEST_INSTALL_DIR/unlock-test"
        return 0
    fi
    return 1
}

download_unlock_test() {
    local os arch url target
    os="$(map_unlock_test_os)"
    arch="$(map_unlock_test_arch)"
    if [ "$arch" = "unsupported" ]; then
        echo "error: unsupported architecture: $(uname -m)" >&2
        return 1
    fi

    if [ ! -d "$UNLOCK_TEST_INSTALL_DIR" ]; then
        mkdir -p "$UNLOCK_TEST_INSTALL_DIR" 2>/dev/null || true
    fi
    if [ ! -w "$UNLOCK_TEST_INSTALL_DIR" ]; then
        UNLOCK_TEST_INSTALL_DIR="${HOME}/.local/bin"
        mkdir -p "$UNLOCK_TEST_INSTALL_DIR"
    fi

    url="${UNLOCK_TEST_DOWNLOAD_BASE}/unlock-test_${os}_${arch}"
    target="${UNLOCK_TEST_INSTALL_DIR}/unlock-test"
    echo "installing unlock-test from ${url}" >&2
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$target"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$url" -O "$target"
    else
        echo "error: curl or wget is required to install unlock-test" >&2
        return 1
    fi
    chmod +x "$target"
    echo "$target"
}

ensure_unlock_test() {
    local bin
    if bin="$(find_unlock_test)"; then
        if [ "$UNLOCK_TEST_AUTO_UPDATE" = "1" ]; then
            "$bin" -u >/dev/null 2>&1 || true
        fi
        echo "$bin"
        return 0
    fi
    download_unlock_test
}

build_unlock_test_args() {
    UNLOCK_ARGS=()
    local proxy_enabled=0
    local mode_set=0
    local show_active_set=0
    local proxy

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -P|--proxy)
                if [ "$#" -lt 2 ]; then
                    echo "error: $1 requires a proxy URL" >&2
                    return 1
                fi
                proxy="$2"
                case "$proxy" in
                    http://*|https://*)
                        UNLOCK_ARGS+=("-http-proxy" "$proxy")
                        ;;
                    socks5h://*)
                        UNLOCK_ARGS+=("-socks-proxy" "socks5://${proxy#socks5h://}")
                        ;;
                    socks5://*)
                        UNLOCK_ARGS+=("-socks-proxy" "$proxy")
                        ;;
                    socks://*)
                        UNLOCK_ARGS+=("-socks-proxy" "socks5://${proxy#socks://}")
                        ;;
                    *)
                        echo "error: unsupported proxy URL: $proxy" >&2
                        return 1
                        ;;
                esac
                proxy_enabled=1
                shift 2
                ;;
            -m)
                mode_set=1
                UNLOCK_ARGS+=("$1")
                if [ "$#" -ge 2 ]; then
                    UNLOCK_ARGS+=("$2")
                    shift 2
                else
                    shift
                fi
                ;;
            -show-active|-show-active=*)
                show_active_set=1
                UNLOCK_ARGS+=("$1")
                shift
                ;;
            -J)
                shift
                ;;
            *)
                UNLOCK_ARGS+=("$1")
                shift
                ;;
        esac
    done

    # Codex改动：旧脚本代理检测固定 IPv4，避免 SOCKS 代理下 IPv6 结果混入。
    if [ "$proxy_enabled" = "1" ] && [ "$mode_set" = "0" ]; then
        UNLOCK_ARGS+=("-m" "4")
    fi
    # Codex改动：批量/JSON 解析不需要动态进度条，减少输出噪声。
    if [ "$show_active_set" = "0" ]; then
        UNLOCK_ARGS+=("-show-active=false")
    fi
}

main() {
    local bin
    bin="$(ensure_unlock_test)" || exit 1

    local UNLOCK_ARGS=()
    build_unlock_test_args "$@" || exit 1

    exec "$bin" "${UNLOCK_ARGS[@]}"
}

main "$@"
