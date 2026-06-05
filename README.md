# V2Board Unlock Checker

支持脚本运行或者 docker 运行，读取 V2Board 的数据库，读取节点类型或测试用户UUID，批量检测媒体和 AI 解锁结果，并输出 JSON 汇总供 V2Board 前端展示。

建议默认在v2board本机docker运行使用，简单方便

## 工作原理

程序运行时会按下面流程工作：

1. 读取 V2Board 数据库配置
   - 本地运行、默认读取挂载进容器的 V2Board `.env` 文件
   - 远程运行，填写数据库信息链接远程数据库。

2. 读取数据表
   - 自动扫描数据库中 `server_*` 节点表。
   - 跳过 `group`、`log`、`route`、`stat`、`copy` 等非节点表。
   - 默认只读取 `parent_id IS NULL` 的主节点，避免重复检测子线路。
   - 使用 `show = 1` 的可见节点。
   - 读取用户表中指定用户的 UUID 作为链接密码

3. 生成 sing-box 本地代理
   - 每个节点生成一个 sing-box outbound。
   - 每个节点对应一个本地 `mixed` 代理端口。
   - 批量检测时通过这些本地代理端口访问媒体和 AI 服务。

4. 执行解锁检测
   - 对每个节点运行媒体和 AI 检测。
   - 所有检测请求都会走对应节点的本地代理。
   - 检测结果会解析成结构化 JSON。

5. 输出结果
   - 每个节点生成单独 JSON 文件。
   - 同时生成完整汇总文件 `all.json`。
   - 额外生成脱敏汇总文件 `public.json`。
   - 在v2baord本机运行后，如果配置了 `V2BOARD_OUTPUT`，默认同步脱敏结果给 V2Board 前端读取。同步路径为v2board目录/storage/app/unlock-results/。
   - 远程主机连接数据库运行，需要自行把结果复制到storage/app/unlock-results
   - 不建议把完整 `all.json` 暴露到公网。

## 支持协议

支持 Sing-box和数据表中v2_server_的规定协议

## 准备目录

服务器目录示例：

```text
/opt/v2board-unlock-checker/
├── docker-compose.yml
├── data/
└── v2board-unlock-results/
```

创建目录：

```bash
mkdir -p /opt/v2board-unlock-checker/data &&\
mkdir -p /opt/v2board-unlock-checker/v2board-unlock-results &&\
cd /opt/v2board-unlock-checker &&\
wget https://raw.githubusercontent.com/lufeiit/v2board-unlock-checker/refs/heads/main/docker-compose.yml
```
# 修改docker-compose.yml
## 读取 V2Board .env

挂载 V2Board 的 `.env` 文件

```yaml
volumes:
  - ./v2board目录/.env:/run/secrets/v2board.env:ro
```

对应环境变量保持：

```yaml
V2BOARD_PATH: ""
V2BOARD_ENV_PATH: "/run/secrets/v2board.env"
```

## 远程数据库模式

如果检测服务器不在 V2Board 所在机器，或者不想挂载 `.env`，删除 `.env` 挂载，并设置：

```yaml
V2BOARD_ENV_PATH: ""
DB_HOST: "1.2.3.4"
DB_PORT: "3306"
DB_DATABASE: "v2board"
DB_USERNAME: "v2board_user"
DB_PASSWORD: "your_password"
DB_PREFIX: "v2_"
```

远程 MySQL 需要放行检测服务器 IP，并给该数据库账号读取权限。

## 地址模式

### 国内 VPS 模式

适合节点大部分使用国内中转入口的场景。

```yaml
ADDRESS_MODE: "panel"
```

此模式使用数据库中的：

```text
host + port
```

### 国外 VPS 模式

适合检测服务器在海外，需要直接连接落地节点服务端口的场景。

```yaml
ADDRESS_MODE: "domain"
NODE_DOMAIN: "你的域名"
DOMAIN_TEMPLATE: "{label}.{domain}"
```

例如节点名：

```text
香港HK-01
```

会自动拼接为：

```text
hk01.你的域名
```

连接端口使用数据库中的：

```text
server_port
```

## 自定义域名前缀

如果节点名不是 `香港HK-01` 这种格式，可以设置：

```yaml
DOMAIN_LABEL_MAP: "1001=hk01,特殊香港入口=hk02,美国住宅A=us01"
```

也支持 JSON：

```yaml
DOMAIN_LABEL_MAP: '{"1001":"hk01","特殊香港入口":"hk02","美国住宅A":"us01"}'
```

支持按节点 ID 或节点名称匹配。

## 排除节点

多个节点名称用英文逗号分隔，完整名称匹配：

```yaml
EXCLUDE_NAMES: "测试节点,临时节点"
```

## 常用参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `MODE` | `all` | `generate`、`singbox`、`check`、`all` |
| `V2BOARD_ENV_PATH` | `/run/secrets/v2board.env` | V2Board `.env` 文件路径 |
| `DB_HOST` | 空 | 远程数据库地址 |
| `DB_PORT` | `3306` | 数据库端口 |
| `DB_DATABASE` | 空 | 数据库名 |
| `DB_USERNAME` | 空 | 数据库用户名 |
| `DB_PASSWORD` | 空 | 数据库密码 |
| `DB_PREFIX` | `v2_` | 数据库表前缀 |
| `TEST_EMAIL` | `test@test.com` | 读取该用户 UUID 作为节点连接密码 |
| `NODE_TYPES` | `all` | 协议筛选 |
| `ADDRESS_MODE` | `panel` | 地址模式：`panel` 或 `domain` |
| `NODE_DOMAIN` | `你的域名` | 国外模式根域名 |
| `DOMAIN_LABEL_MAP` | 空 | 自定义域名前缀映射 |
| `EXCLUDE_NAMES` | `测试节点` | 排除节点名称 |
| `OUTPUT_DIR` | `/data/unlock-results` | 检测结果输出目录 |
| `V2BOARD_OUTPUT` | `/v2board-unlock-results/all.json` | 同步给 V2Board 前端读取的脱敏汇总 JSON |
| `PUBLIC_OUTPUT` | 空 | 额外输出脱敏 JSON 到只读 Web 目录 |
| `FULL_V2BOARD_OUTPUT` | `0` | 是否把完整结果同步到 `V2BOARD_OUTPUT`，公开场景建议保持 `0` |
| `LIMIT` | `0` | 限制检测数量，`0` 表示全部 |
| `TIMEOUT` | `600` | 单节点检测超时秒数 |

## 启动

检查配置：

```bash
docker compose config
```

拉取镜像：

```bash
docker compose pull
```

启动检测：

```bash
docker compose up
```

后台运行：

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

## 输出结果

默认输出目录：

```text
./data/unlock-results/
```

汇总结果：

```text
./data/unlock-results/all.json
```

脱敏结果：

```text
./data/unlock-results/public.json
```

`public.json` 会移除：

- 出口 IP
- 节点 host
- 节点端口
- 本地代理地址
- 原始检测文本 `raw`
- `no`、`failed`、`unknown` 等非解锁项目

如果需要让远程 V2Board 主动拉取结果，建议只暴露 `public.json`，不要暴露完整 `all.json`。

如果配置了：

```yaml
V2BOARD_OUTPUT: "/v2board-unlock-results/all.json"
```

会额外同步一份脱敏汇总结果到：

```text
./v2board-unlock-results/all.json
```

## 安全注意

不要公开提交以下文件：

- V2Board `.env`
- 数据库账号和密码
- 检测结果 JSON
- 生成的 sing-box 配置
