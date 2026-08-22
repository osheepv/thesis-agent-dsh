# -*- coding: utf-8 -*-
"""业务模块路由配置（application 层适配底座）。

集中登记 M1/M2/M5/M6 各业务模块的 HTTP 路由。后续业务模块成员如果调整了
路由路径或服务端口，只需修改本文件即可，无需改动 `service/` 编排用例。

约定（与各成员确认的契约一致）：
    M1 FSM 编排器：POST /tasks 创建任务、POST /tasks/{id}/advance 推进、
                    GET /tasks/{id}/progress 进度。
    M2 执行体：    POST /rings/1/execute  环1选题
                    POST /rings/5/outline 环5大纲
                    POST /rings/6/chapter 环6撰写
    M5/M6 docx：   POST /templates/upload 模板上传
                    POST /docx/generate   docx 生成
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceRoutes:
    """业务模块路由集中定义。"""

    # ---------- M1 FSM 编排器 ----------
    fsm_create_task: str = "/tasks"
    fsm_advance_task: str = "/tasks/{task_id}/advance"
    fsm_progress: str = "/tasks/{task_id}/progress"

    # ---------- M2 执行体 ----------
    ring_execute: str = "/rings/{ring_no}/execute"
    ring_outline: str = "/rings/5/outline"
    ring_chapter: str = "/rings/6/chapter"

    # ---------- M5/M6 docx ----------
    template_upload: str = "/templates/upload"
    docx_generate: str = "/docx/generate"


#: 全局默认路由配置（默认单实例部署，各业务模块挂载于同一 FastAPI app 内）。
ROUTES: ServiceRoutes = ServiceRoutes()


@dataclass
class ServiceEndpoints:
    """业务模块服务端点集合（含 base_url 与路由配置）。

    默认 base_url 为空串表示与当前 application 服务同进程挂载（直连路由），
    若后续业务模块拆分为独立服务，可替换为对应 host。
    """

    base_url: str = ""
    routes: ServiceRoutes = field(default_factory=lambda: ROUTES)

    def url(self, path: str) -> str:
        """将路由路径拼接为完整可调用 URL。"""
        return f"{self.base_url}{path}"
