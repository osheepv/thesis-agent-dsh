# -*- coding: utf-8 -*-
"""全流程演示脚本：严格跑完 10 环（HTTP 走服务 API）。

用法：
    1. 启动服务：cd backend && python -m uvicorn main:app --port 8000
    2. 另开终端：python demo_full_10.py

流程：每一环都执行“生成产物 → 自动验收 → 用户确认”，确认后才进入下一环；
      环8确认后生成 docx，供环9排版检查使用；环10最终确认后下载成品。

说明：
    - 本脚本会真实调用已配置的模型和文献服务，可能产生费用。
    - 任一环自动验收失败时立即停止，不会为了演示而跨过闸门。
    - 环9 需先生成真实 docx；无用户模板时回退内置模板渲染。
"""
import json
import os
import urllib.error
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

    # 2. 环1~10：执行成功后显式确认，禁止跳环。
    steps = [
        (1, "环1选题", "/rings/1/execute"),
        (2, "环2开题评审", "/rings/2/review"),
        (3, "环3文献调研", "/rings/3/execute"),
        (4, "环4综述评审", "/rings/4/review"),
        (5, "环5大纲", "/rings/5/outline"),
        (6, "环6撰写", "/rings/6/chapter"),
        (7, "环7润色", "/rings/7/polish"),
        (8, "环8引用校验", "/rings/8/validate"),
        (9, "环9排版检查", "/rings/9/layout"),
        (10, "环10定稿汇总", "/rings/10/final"),
    ]
    file_id = ""
    for ring_no, name, path in steps:
        if ring_no == 9:
            st, generated = post(
                f"/api/v1/console/tasks/{tid}/docx/generate?session_id=demo-full-10"
            )
            code = generated.get("code", generated.get("error", "?"))
            print(f"生成docx: {st} code={code} | {_brief(generated.get('msg', ''))}")
            if code != 0:
                print("docx 生成失败，流程停止：", generated)
                return
            file_id = generated.get("data", {}).get("download_url", "").rsplit("/", 1)[-1] or \
                      generated.get("data", {}).get("file_id", "")

        st, b = post(f"/api/v1/console/tasks/{tid}{path}?session_id=demo-full-10")
        code = b.get("code", b.get("error", "?"))
        msg = _brief(b.get("msg", b.get("error", "")))
        print(f"{name}: {st} code={code} | {msg}")
        if code != 0:
            print(f"{name}未通过，流程停止；请根据返回的失败原因修订后重试。")
            return

        st, progress = get(
            f"/api/v1/console/tasks/{tid}/progress?session_id=demo-full-10"
        )
        phase = progress.get("data", {}).get("phase_state")
        if progress.get("code") != 0 or phase != "WAITING_APPROVAL":
            print(f"{name}没有进入待确认状态，流程停止：", progress)
            return

        st, confirmed = post(
            f"/api/v1/console/tasks/{tid}/rings/{ring_no}/confirm?session_id=demo-full-10",
            {"confirmed": True},
        )
        if confirmed.get("code") != 0:
            print(f"{name}确认失败，流程停止：", confirmed)
            return
        print(f"   已确认环{ring_no}")

    # 3. 下载成品 docx
    if file_id:
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
        print(
            f"进度: 当前环={b['data'].get('current_ring_no')} "
            f"状态={b['data'].get('phase_state')} "
            f"完成度={b['data'].get('complete_percent')}%"
        )


if __name__ == "__main__":
    main()
