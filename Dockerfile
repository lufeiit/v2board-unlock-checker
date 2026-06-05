FROM alpine:3.20

ARG SING_BOX_VERSION=1.12.0

RUN apk add --no-cache \
      bash \
      ca-certificates \
      curl \
      jq \
      mariadb-client \
      procps \
      python3

RUN arch="$(apk --print-arch)" \
    && case "$arch" in \
       x86_64) sb_arch="amd64" ;; \
       aarch64) sb_arch="arm64" ;; \
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
