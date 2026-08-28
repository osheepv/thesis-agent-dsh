# UI开发与静态托管

前端保持原生HTML/CSS/JavaScript和零构建启动，但已不再是单文件。

## 目录

```text
ui/
├─ index.html
├─ styles/
│  └─ app.css
├─ js/
│  ├─ app.js
│  └─ components/
│     └─ project-memory.js
└─ vendor/
   └─ cytoscape.min.js
```

## 运行

必须托管整个`ui/`目录，不能只复制`index.html`：

```bash
cd ui
python -m http.server 8787
```

默认连接`http://127.0.0.1:8000`。可以通过页面查询参数`?apiBase=...`或在加载前设定`window.API_BASE`改写。

## 脚本顺序是接口的一部分

```text
vendor/cytoscape.min.js
→ js/components/project-memory.js
→ js/app.js
```

三者都是位于`</body>`前的classic script，不能添加`async`或反转顺序。`app.js`在末尾立即执行`initApp()`；项目记忆模块因此必须先登记`window.ThesisProjectMemory`接口。

现有页面仍含少量内联事件属性，暂不能直接切换为`type="module"`。后续拆分应先把通用网络、转义、通知和任务状态收敛为核心运行时接口，再迁移证据、研究、分节和作业模块。

## 验证

```bash
node --check ui/js/app.js
node --check ui/js/components/project-memory.js
python -m pytest tests/test_ui_workbench.py -q
```

测试会检查本地资源顺序、无内联CSS/执行脚本、资源文件存在性、JavaScript语法以及临时静态服务器的HTTP状态与MIME类型。
