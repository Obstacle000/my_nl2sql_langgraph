# my-nl2sql

多用户 NL2SQL：接入数据源（CSV 上传 / MySQL 直连）→ 三路召回（Qdrant / ES / MySQL）→ LLM 生成 SQL → 校验修正 → 只读执行 → Redis 两级缓存。

## 文档

| 文档 | 内容 |
| --- | --- |
| [立项文档](docs/立项文档.md) | 问题、场景、成功标准、范围、风险、里程碑 |
| [需求文档](docs/需求文档.md) | 功能清单（P0/P1/P2）、流程、验收条件、评测规划 |
| [数据库结构](docs/数据库结构.md) | 表结构、索引、多租户规则、Qdrant/ES/Redis 结构 |
| [接口文档](docs/接口文档.md) | 13 个已实现接口、SSE 协议、错误码、规划中接口 |
| [架构设计](docs/架构设计.md) | 分层、两层鉴权、主链路、关键决策、排障 |

## 快速开始

```bash
# 1. 依赖
uv sync

# 2. 环境变量（必填：JWT_SECRET / LLM_API_KEY / DS_SECRET_KEY）
cp .env.example .env

# 3. 基础设施（MySQL 3307 / Redis 6379 / Qdrant 6333 / ES 9201）
docker compose -f docker/docker-compose.yaml up -d

# 4. 启动
uv run fastapi dev main.py
```

启动时会自动建表（`Base.metadata.create_all`）。

## 一次完整验证

```bash
# ① 注册
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"123456"}'

# ② 登录拿 token
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"123456"}'

# ③ 建 CSV 数据集（会隐式建一个 kind=csv 的数据源）
curl -X POST http://127.0.0.1:8000/api/datasets \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"name":"电商订单","description":"2025 年订单"}'

# ④ 上传 CSV（建物理表 ds{dataset_id}_t0 + 元数据 + 索引）
curl -X POST http://127.0.0.1:8000/api/datasets/1/tables \
  -H "Authorization: Bearer <token>" \
  -F "name=订单" -F "file=@orders.csv"

# ⑤ 问数（SSE）
curl -N -X POST http://127.0.0.1:8000/api/query \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"dataset_id":1,"question":"上个月华北地区的销售总额"}'
```

## 目录结构

```text
app/
├── conf/          配置（OmegaConf + .env 插值）
├── core/          日志、request_id/user_id 上下文、JWT、异常、凭证加密
├── clients/       五个客户端管理器（MySQL / Redis / Qdrant / ES / Embedding）
├── models/        ORM：users / datasources / datasets / dataset_tables
│                  / table_info / column_info / metric_info / query_history
├── entities/      业务实体（与 ORM 解耦，供 Agent 使用）
├── datasources/   DataSource 协议 + CSV / MySQL 实现 + registry（LRU）
├── repositories/  mysql（user/dataset/datasource/meta/history）、qdrant、es、redis
├── services/      auth / dataset / datasource / meta_index
├── agent/         LangGraph：state / context / graph
└── api/           deps（Annotated 依赖）、lifespan、routers、schemas
```

## 当前进度

| 模块 | 状态 |
| --- | --- |
| 配置 / 客户端 / ORM / 迁移（create_all） | ✅ |
| 注册登录 / JWT / 两层鉴权 / 滑动续签 | ✅ |
| 数据源：probe、创建、列表、测试、同步、删除 | ✅ |
| CSV：建数据集、上传建表、写元数据、建索引 | ✅ |
| Qdrant 字段向量 + ES 取值索引（带租户字段） | ✅ |
| Redis 精确 + 语义缓存仓储 | ✅ 仓储层 |
| SSE 输出（progress / result / error） | ✅ |
| LangGraph 图 | ⚠️ 5 节点中 4 个是占位 |
| 召回 / 生成 / 校验 / 执行 | ⬜ 待实现 |
| 缓存写回、审计落库 | ⬜ 待实现 |
| 前端、测试、评测集 | ⬜ 待实现 |

> 详细清单见 [需求文档](docs/需求文档.md) 与 [接口文档](docs/接口文档.md) 的「实现状态总览」。

## 关键约定

```text
· 多租户：所有查询带 user_id / dataset_id；Qdrant/ES 过滤、Redis key 都带租户
· 只读：执行用户 SQL 用只读账号 + SELECT 白名单 + 行数/超时上限
· 凭证：数据源连接信息 Fernet 加密存储，接口只回 host/port/database
· 物理表名：程序生成 ds{dataset_id}_t{n}，不使用用户输入
· 表结构变更：schema_version += 1，旧缓存自动失效
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `JWT_SECRET` | 签发/校验 token |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 模型调用 |
| `DS_SECRET_KEY` | 数据源凭证加密（Fernet 密钥派生） |
