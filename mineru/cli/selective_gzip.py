# Copyright (c) Opendatalab. All rights reserved.
"""gzip 中间件配置：排除二进制流 + 降低压缩级别。

starlette>=1.10 的 GZipMiddleware 已经：
- 默认排除 application/zip 等不可压缩 content-type（不 gzip）；
- 对大响应（>=thread_minimum_size，默认 128KiB）把压缩 offload 到
  anyio 工作线程，不再阻塞事件循环。

本模块在其之上做两件环境相关的事：
1. 追加排除 application/octet-stream（router 代理的 zip 结果在 upstream
   content-type 缺失时以此为 media_type，属于不可压缩内容）；
2. compresslevel 默认降为 1——大 JSON（middle_json 等）压缩快数倍，
   CPU 受限（K8s cpu limit）环境下显著降低压缩延迟与节流风险。

旧版 starlette（无 exclude_content_types 参数）退化为原生 GZipMiddleware
行为（不优于也不劣于现状），并打 warning。
"""

import inspect
from typing import Any

from loguru import logger
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp

try:
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
except ImportError:  # 旧版 starlette 没有该常量
    DEFAULT_EXCLUDED_CONTENT_TYPES = (
        "application/grpc",
        "application/gzip",
        "application/x-gzip",
        "application/zip",
    )

# router/worker 的结果下载在 content-type 缺失时是 octet-stream，实际为 zip
EXTRA_EXCLUDED_CONTENT_TYPES = ("application/octet-stream",)


class SelectiveGZipMiddleware(GZipMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 1000,
        compresslevel: int = 1,
        **kwargs: Any,
    ) -> None:
        params = inspect.signature(GZipMiddleware.__init__).parameters
        if "exclude_content_types" in params:
            super().__init__(
                app,
                minimum_size=minimum_size,
                compresslevel=compresslevel,
                exclude_content_types=tuple(DEFAULT_EXCLUDED_CONTENT_TYPES)
                + EXTRA_EXCLUDED_CONTENT_TYPES,
                **kwargs,
            )
        else:
            logger.warning(
                "starlette 无 exclude_content_types 支持（<1.10），"
                "gzip 退化为原生行为：二进制流也会被压缩且压缩发生在线程外"
            )
            super().__init__(
                app,
                minimum_size=minimum_size,
                compresslevel=compresslevel,
            )
