FROM debian:12-slim

ARG SING_BOX_VERSION=1.12.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash ca-certificates curl default-mysql-client jq procps python3 \
    && rm -rf /var/lib/apt/lists/*

RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
       amd64) sb_arch="amd64" ;; \
       arm64) sb_arch="arm64" ;; \
       *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/sing-box.tar.gz \
       "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-${sb_arch}.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && mv "/tmp/sing-box-${SING_BOX_VERSION}-linux-${sb_arch}/sing-box" /usr/local/bin/sing-box \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box*

WORKDIR /app

COPY check.sh parse_unlock_result.py generate_anytls_singbox.py check_anytls_batch.py docker-entrypoint.sh /app/

RUN chmod +x /app/check.sh /app/parse_unlock_result.py /app/generate_anytls_singbox.py /app/check_anytls_batch.py /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
