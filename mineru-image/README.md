# MinerU 镜像构建（源码镜像 + 运行时镜像）

两阶段镜像，**不修改官方 entrypoint**：

1. **源码镜像 `mineru-src`**：只打包仓库源码（`/src`），不装 Python 依赖
2. **运行时镜像 `mineru-runtime`**：基于 vLLM 镜像，构建时用 `RUN --mount=from=src` **临时挂载**源码，`uv pip install` 后**不保留源码层**（非 editable 安装）

改代码后重建 `mineru-src`，再重建 `mineru-runtime` 即可。

### 为什么用 mount 而不是 COPY？

| 方式 | 最终镜像里 | 适用 |
|------|-----------|------|
| `COPY --from=src` + `-e` | 源码常驻 `/app`，editable 指向源码 | 开发调试 |
| `RUN --mount=from=src` + 普通 install | **只有 site-packages**，源码随 RUN 结束丢弃 | 运行时 / 生产 |

## 目录

```
mineru-image/
├── source/Dockerfile          # 源码载体镜像
├── runtime/Dockerfile         # 运行时（海外）
├── runtime/Dockerfile.china   # 运行时（国内镜像）
├── build.sh                   # 一键构建两个镜像
└── compose.yaml               # 启动服务（沿用官方 entrypoint 写法）
```

## 构建

在仓库根目录：

```bash
chmod +x mineru-image/build.sh

# 海外
./mineru-image/build.sh

# 国内
./mineru-image/build.sh china

# 指定 extras
MINERU_EXTRAS=core ./mineru-image/build.sh china
```

等价于手动：

```bash
# 1. 源码镜像（必须在仓库根目录执行，context 为 .）
docker build -t mineru-source:v2.7.4-fix -f mineru-image/source/Dockerfile .
docker run --rm mineru-source:v2.7.4-fix ls -la /src/pyproject.toml

# 2. 运行时镜像（需已有含模型的镜像，默认 mineru-vllm:v2.7.4-fix）
docker build -t mineru-core:v2.7.4-fix \
  --build-arg SOURCE_IMAGE=mineru-source:v2.7.4-fix \
  --build-arg MODELS_IMAGE=mineru-vllm:v2.7.4-fix \
  --build-arg MINERU_EXTRAS=core \
  -f mineru-image/runtime/Dockerfile.china .
```

## 启动服务

```bash
docker compose -f mineru-image/compose.yaml --profile api up -d
docker compose -f mineru-image/compose.yaml --profile router up -d
docker compose -f mineru-image/compose.yaml --profile gradio up -d
```

## 与官方 docker 目录的区别

| | `docker/global` `docker/china` | `mineru-image/` |
|--|--|--|
| 源码 | PyPI 安装 mineru | 本地源码打进 `mineru-src` |
| 依赖安装 | pip | uv pip |
| entrypoint | 官方 bash wrapper | **相同，未修改** |

生产若仍要用 PyPI 版，继续用 `docker/china/Dockerfile` 即可。

### 模型来源（Dockerfile.china）

构建 runtime 时不再执行 `mineru-models-download`，而是从已有镜像复制：

- 默认 `MODELS_IMAGE=mineru-vllm:v2.7.4-fix`（需事先用官方 `docker/china/Dockerfile` 或等价镜像打好模型）
- 复制 `/root/mineru.json` 及 `models-dir` 指向的目录

```bash
# 先构建/准备模型镜像（只需一次）
docker build -t mineru-vllm:v2.7.4-fix -f docker/china/Dockerfile .

# 再构建源码 runtime
MODELS_TAG=mineru-vllm:v2.7.4-fix ./mineru-image/build.sh china
```
