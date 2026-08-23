"""最小严格流程冒烟：创建任务、执行环1、确认环1、读取进度。"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

def post(path, payload=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return -1, {"error": str(e)}

def get(path):
    try:
        with urllib.request.urlopen(BASE + path) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:
        return -1, {"error": str(e)}

def main():
    st, body = post("/api/v1/console/tasks", {
        "title": "基于深度学习的社会媒体情感分析研究",
        "degree": "MASTER",
        "subject_field": "自然语言处理",
        "session_id": "run-demo",
    })
    print("1) 创建任务:", st, "| code=", body.get("code"))
    tid = body.get("data", {}).get("task_id")
    if not tid:
        print("创建失败：", body)
        return

    st, result = post(f"/api/v1/console/tasks/{tid}/rings/1/execute?session_id=run-demo")
    print("2) 环1执行:", st, "| code=", result.get("code"), "| msg=", result.get("msg"))
    if result.get("code") != 0:
        return

    st, pending = get(f"/api/v1/console/tasks/{tid}/progress?session_id=run-demo")
    print("3) 待确认:", pending.get("data", {}).get("phase_state"))
    if pending.get("data", {}).get("phase_state") != "WAITING_APPROVAL":
        return

    st, confirmed = post(
        f"/api/v1/console/tasks/{tid}/rings/1/confirm?session_id=run-demo",
        {"confirmed": True},
    )
    print("4) 确认环1:", st, "| code=", confirmed.get("code"), "| msg=", confirmed.get("msg"))

    st, progress = get(f"/api/v1/console/tasks/{tid}/progress?session_id=run-demo")
    print(
        "5) 进度:", st,
        "| 当前环=", progress.get("data", {}).get("current_ring_no"),
        "| 状态=", progress.get("data", {}).get("phase_state"),
    )
    print("TASK_ID=", tid)


if __name__ == "__main__":
    main()
