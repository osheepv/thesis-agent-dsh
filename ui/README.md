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
│     ├─ project-memory.js
│     ├─ evidence.js
│     └─ autosave.js
└─ vendor/
   ├─ cytoscape.min.js
   ├─ lucide.min.js
   ├─ open-props-easings.min.css
   └─ open-props-shadow.min.css
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
vendor/open-props-shadow.min.css
→ vendor/open-props-easings.min.css
→ styles/app.css

vendor/cytoscape.min.js
→ vendor/lucide.min.js
→ js/components/project-memory.js
→ js/components/evidence.js
→ js/components/autosave.js
→ js/app.js
```

Open Props 只提供本地阴影/动效曲线 Token，`app.css`在其后覆盖业务样式。`cytoscape`与`lucide`位于`<head>`；三个功能模块与`app.js`位于`</body>`前。所有 JavaScript 都是 classic script，不能添加`async`或反转顺序。`app.js`在末尾立即执行`initApp()`，功能模块因此必须先登记`window.ThesisProjectMemory`、`window.ThesisEvidence`和`window.ThesisAutosave`接口。

三份视觉依赖全部本地托管，运行时不访问 CDN。来源、版本/哈希与许可证见项目根目录`THIRD_PARTY_NOTICES.md`。

现有页面仍含少量内联事件属性，暂不能直接切换为`type="module"`。后续拆分应先把通用网络、转义、通知和任务状态收敛为核心运行时接口，再迁移证据、研究、分节和作业模块。

## 验证

```bash
node --check ui/js/app.js
node --check ui/js/components/project-memory.js
node --check ui/js/components/evidence.js
node --check ui/js/components/autosave.js
python -m pytest tests/test_ui_workbench.py -q
```

测试会检查本地资源顺序、无内联CSS/执行脚本、资源文件存在性、JavaScript语法以及临时静态服务器的HTTP状态与MIME类型。
