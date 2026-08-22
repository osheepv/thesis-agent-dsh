import json, urllib.request, os

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

st, body = post("/api/v1/console/tasks", {"title":"基于深度学习的社会媒体情感分析研究","degree":"MASTER","subject_field":"自然语言处理","session_id":"run-demo"})
print("1) 创建任务:", st, "| code=", body.get("code"), "| task_id=", body.get("data",{}).get("task_id"))
tid = body["data"]["task_id"]

st, b = post(f"/api/v1/console/tasks/{tid}/rings/1/execute?session_id=run-demo")
print("2) 环1选题:", st, "| code=", b.get("code"), "| msg=", b.get("msg"), "| 候选数=", len(b.get("data",{}).get("candidates",[])))

st, b = post(f"/api/v1/console/tasks/{tid}/rings/5/outline?session_id=run-demo")
print("3) 环5大纲:", st, "| code=", b.get("code"), "| msg=", b.get("msg"), "| 章节数=", len(b.get("data",{}).get("chapters",[])))

st, b = post(f"/api/v1/console/tasks/{tid}/rings/6/chapter?session_id=run-demo")
print("4) 环6撰写:", st, "| code=", b.get("code"), "| msg=", b.get("msg"), "| 总字数=", b.get("data",{}).get("total_words"))

st, b = post(f"/api/v1/console/tasks/{tid}/docx/generate?session_id=run-demo")
print("5) 生成docx:", st, "| code=", b.get("code"), "| msg=", b.get("msg"), "| file_id=", b.get("data",{}).get("file_id"), "| url=", b.get("data",{}).get("download_url"))
# 下载端点按文件 ID（download_url 最后一段）访问，而非内部 file_id 代号
file_id = b.get("data",{}).get("download_url", "").rsplit("/", 1)[-1]

st, b = get(f"/api/v1/console/tasks/{tid}/progress?session_id=run-demo")
print("6) 进度:", st, "| code=", b.get("code"), "| 当前环=", b.get("data",{}).get("current_ring_no"), "| 完成度=", b.get("data",{}).get("complete_percent"), "%")

if file_id:
    try:
        with urllib.request.urlopen(BASE + f"/api/v1/docx/files/{file_id}?session_id=run-demo") as r:
            data = r.read()
            out = "demo_output/thesis_demo.docx"
            os.makedirs("demo_output", exist_ok=True)
            with open(out,'wb') as f: f.write(data)
            print("7) 下载docx: 成功 ->", out, "|", len(data), "bytes")
    except Exception as e:
        print("7) 下载docx: 失败", e)

print("TASK_ID=", tid)
