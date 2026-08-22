# -*- coding: utf-8 -*-
"""全流程演示脚本：一键跑完 10 环（HTTP 走服务 API）。

用法：
    1. 启动服务：cd backend && python -m uvicorn main:app --port 8000
    2. 另开终端：python demo_full_10.py

流程：创建任务 → 环1选题 → 环2开题评审 → 环3文献调研 → 环4综述评审 →
      环5大纲 → 环6撰写 → 环7润色 → 环8引用校验 → 生成docx → 环9排版检查 →
      环10定稿汇总 → 下载成品 docx 到 demo_output/。

说明：
    - 环2/4 评审可能判"未通过"（需回退换题/补差异化），脚本会打印建议，
      真实产品应换题/补后再跑（此处演示全链路可见性）。
    - 环9 需先生成真实 docx；无用户模板时回退内置模板渲染。
"""
import json
import os
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:  # noqa: BLE001
        return -1, {"error": str(e)}


def get(path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(BASE + path) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return -1, {"error": str(e)}


def _brief(msg: str, n: int = 60) -> str:
    return (msg or "").replace("\n", " ")[:n]


def main() -> None:
    # 1. 创建任务
    st, body = post("/api/v1/console/tasks", {
        "title": "基于轻量化Transformer的遥感图像语义分割研究",
        "degree": "MASTER",
        "subject_field": "遥感图像处理",
        "session_id": "demo-full-10",
    })
    print(f"1) 创建任务: {st} | code={body.get('code')} | msg={_brief(body.get('msg'))}")
    tid = body.get("data", {}).get("task_id", "")
    if not tid:
        print("创建失败：", body)
        return
    print(f"   task_id = {tid}")

    # 2. 环1~10（含 docx）
    steps = [
        ("环1选题", "/rings/1/execute"),
        ("环2开题评审", "/rings/2/review"),
        ("环3文献调研", "/rings/3/execute"),
        ("环4综述评审", "/rings/4/review"),
        ("环5大纲", "/rings/5/outline"),
        ("环6撰写", "/rings/6/chapter"),
        ("环7润色", "/rings/7/polish"),
        ("环8引用校验", "/rings/8/validate"),
        ("生成docx", "/docx/generate"),
        ("环9排版检查", "/rings/9/layout"),
        ("环10定稿汇总", "/rings/10/final"),
    ]
    file_id = ""
    for name, path in steps:
        st, b = post(f"/api/v1/console/tasks/{tid}{path}?session_id=demo-full-10")
        code = b.get("code", b.get("error", "?"))
        msg = _brief(b.get("msg", b.get("error", "")))
        print(f"{name}: {st} code={code} | {msg}")
        if path == "/docx/generate" and code == 0:
            file_id = b.get("data", {}).get("download_url", "").rsplit("/", 1)[-1] or \
                      b.get("data", {}).get("file_id", "")
            print(f"   docx 下载 url = {b.get('data', {}).get('download_url', '')}")

    # 3. 下载成品 docx
    if file_id:
        st, raw = get(f"/api/v1/docx/files/{file_id}?session_id=demo-full-10")
        # 直接读二进制
        try:
            with urllib.request.urlopen(BASE + f"/api/v1/docx/files/{file_id}?session_id=demo-full-10") as r:
                data = r.read()
                if data[:2] == b'PK':  # docx 是 zip
                    os.makedirs("demo_output", exist_ok=True)
                    out = "demo_output/thesis_full_10.docx"
                    with open(out, "wb") as f:
                        f.write(data)
                    print(f"成品 docx 下载成功 -> {out} | {len(data)} bytes")
                else:
                    print(f"下载返回非 docx（可能 JSON 错误）: {data[:80]}")
        except Exception as e:  # noqa: BLE001
            print(f"下载成品 docx 失败: {e}")
    else:
        print("（未生成 docx，跳过下载）")

    # 4. 进度
    st, b = get(f"/api/v1/console/tasks/{tid}/progress?session_id=demo-full-10")
    if b.get("code") == 0:
        print(f"进度: 当前环={b['data'].get('current_ring_no')} 完成度={b['data'].get('complete_percent')}%")


if __name__ == "__main__":
    main()
