---
version: alpha
name: Deep Thesis
description: 学位论文全流程智能写作工作台的界面设计规范
colors:
  claude: "#D77757"
  claude-hover: "#C7694B"
  claude-soft: "#D777571F"
  permission: "#5769F7"
  permission-soft: "#5769F71F"
  success: "#2C7A39"
  error: "#AB2B3F"
  warning: "#966C1E"
  bg-app: "#FFFFFF"
  bg-sidebar: "#FAF9F7"
  bg-tab-active: "#F0EDE8"
  bg-user-bubble: "#F0F0F0"
  bg-actions: "#E8ECF4"
  bg-input: "#FFFFFF"
  bg-card: "#FFFFFF"
  bg-code-block: "#F7F6F3"
  bg-canvas-dark: "#1F1F1F"
  text-primary: "#000000"
  text-inactive: "#666666"
  text-subtle: "#AFAFAF"
  border-prompt: "#999999"
  border-divider: "#E5E3DE"
  selection-bg: "#B4D5FF"
  btn-primary-bg: "#3D3D3D"
  btn-primary-text: "#FFFFFF"
typography:
  h1:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 24px
    fontWeight: 700
    lineHeight: 32px
  h2:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 18px
    fontWeight: 600
    lineHeight: 24px
  h3:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 16px
    fontWeight: 600
    lineHeight: 22px
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 14px
    fontWeight: 400
    lineHeight: 20px
  small:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 13px
    fontWeight: 400
    lineHeight: 18px
  caption:
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 12px
    fontWeight: 400
    lineHeight: 16px
  code:
    fontFamily: '"SF Mono", "JetBrains Mono", "Fira Code", Consolas, monospace'
    fontSize: 13px
    fontWeight: 400
    lineHeight: 20px
rounded:
  btn: 8px
  card: 12px
  input: 16px
  modal: 16px
  pill: 999px
spacing:
  sp-1: 4px
  sp-2: 8px
  sp-3: 12px
  sp-4: 16px
  sp-6: 24px
  sp-8: 32px
  sp-12: 48px
components:
  button-primary:
    backgroundColor: "{colors.btn-primary-bg}"
    textColor: "{colors.btn-primary-text}"
    typography: "{typography.small}"
    rounded: "{rounded.btn}"
    padding: 8px 16px
  button-secondary:
    backgroundColor: "{colors.bg-app}"
    textColor: "{colors.text-primary}"
    typography: "{typography.small}"
    rounded: "{rounded.btn}"
    padding: 8px 16px
  input:
    backgroundColor: "{colors.bg-input}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.input}"
    padding: 14px 16px
  card:
    backgroundColor: "{colors.bg-card}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.card}"
    padding: 12px 14px
  gate-card:
    backgroundColor: "{colors.claude-soft}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.card}"
    padding: 14px 16px
  stage-current:
    backgroundColor: "{colors.claude}"
    textColor: "{colors.btn-primary-text}"
    size: 14px
  stage-complete:
    backgroundColor: "{colors.success}"
    textColor: "{colors.btn-primary-text}"
    size: 14px
  stage-reverted:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.btn-primary-text}"
    size: 14px
  approval-indicator:
    backgroundColor: "{colors.permission}"
    size: 6px
---

## Overview

这是一个高信息密度、低干扰的学位论文写作工作台。界面沿用仓库现有的暖白、中性灰和品牌橙视觉语言，把用户注意力集中在当前论文任务、当前写作阶段和需要作出的决定上。浅色主题为默认主题，深色主题提供等价的阅读与操作层级。

产品的核心关系是“对话 = 论文任务 = 会话 = 专属知识库”。用户切换对话时，阶段进度、消息流、文献池、笔记和图谱必须作为同一个工作上下文一起切换。

## Colors

- `claude` 是品牌色，用于 Logo、当前阶段和少量关键强调；它不是所有按钮的通用背景色。
- `btn-primary-bg` 是默认主操作背景，确保长时间写作场景中主操作清晰但不过度抢眼。
- `permission` 只表达审批、人工确认和可见焦点，不与普通导航状态混用。
- `success`、`error`、`warning` 分别表示已验收、失败或伪引、需要回退或人工处理；状态不能只靠颜色表达，必须同时提供文字、图标或形状。
- `bg-sidebar` 为侧栏、标题栏和状态栏提供暖白层次；内容主区保持 `bg-app`。

当前格式不支持多主题 token。深色主题沿用实现中的以下覆盖值：

| Token | Light | Dark |
|---|---|---|
| `permission` | `#5769F7` | `#B1B9F9` |
| `bg-app` | `#FFFFFF` | `#1F1F1F` |
| `bg-sidebar` | `#FAF9F7` | `#181818` |
| `bg-tab-active` | `#F0EDE8` | `#2A2A2A` |
| `bg-user-bubble` | `#F0F0F0` | `#373737` |
| `bg-actions` | `#E8ECF4` | `#2C323E` |
| `bg-input` | `#FFFFFF` | `#2A2A2A` |
| `bg-card` | `#FFFFFF` | `#262626` |
| `bg-code-block` | `#F7F6F3` | `#1A1A1A` |
| `text-primary` | `#000000` | `#FFFFFF` |
| `text-inactive` | `#666666` | `#B4B4B4` |
| `text-subtle` | `#AFAFAF` | `#6E6E6E` |
| `border-divider` | `#E5E3DE` | `#2E2E2E` |
| `btn-primary-bg` | `#3D3D3D` | `#E8E6E1` |
| `btn-primary-text` | `#FFFFFF` | `#1F1F1F` |

## Typography

正文、标题和控件统一使用系统无衬线字体栈，优先保证中文跨平台可读性。路径、JSON、代码、引用标识符和机器状态使用 `code`；普通对话内容不得为了“技术感”整段使用等宽字体。

字号角色固定为 H1、H2、H3、Body、Small、Caption 和 Code。新增界面应复用这些角色，不新增相邻但无语义差异的字号。

## Layout

应用采用桌面工作台结构：40px 标题栏下方是 280px 会话侧栏、弹性主区和 300px 可折叠知识库面板，底部状态栏高 36px。最小桌面视口为 900×600；主对话内容最大宽度 820px，并在更宽窗口中居中。

主区从上到下依次是当前对话的十阶段进度条、可滚动消息流和输入区。知识库面板属于当前对话，不得实现为脱离任务上下文的全局入口。间距使用 4px 基础尺度及 frontmatter 中已有的命名值。

## Elevation & Depth

默认内容卡片通过边线和背景层次分组，不使用阴影。`0 1px 2px rgba(0,0,0,0.05)` 仅用于轻微悬浮反馈；`0 4px 12px rgba(0,0,0,0.10)` 用于下拉或较高浮层；`0 10px 24px -6px rgba(0,0,0,0.16)` 用于模态。不要用多层阴影制造仪表盘式卡片墙。

## Shapes

按钮使用 8px 圆角，内容卡片使用 12px，输入框和模态使用 16px，状态徽章使用胶囊圆角。线条图标使用 1.5px 描边和圆角端点。阶段节点是 14px 圆点，连接线是 1px。

## Components

- **会话侧栏：** 每项显示论文标题、学位、进度和更新时间。删除任务前必须明确提示其专属知识库也会删除。
- **阶段进度条：** 固定呈现选题、开题、文献、综述、大纲、撰写、润色、引用、排版、定稿十个节点。完成为成功绿，当前执行为品牌橙，等待确认为带审批蓝标识的闸门，回退为警告琥珀。
- **确认闸门：** 仅在当前环节已生成产物且自动验收通过后出现。闸门文案必须说明“已完成自动校验，待您确认”；用户确认前不得执行或越过下一环。验收失败时显示失败原因和重试或回退操作，不显示确认按钮。
- **消息与产物卡：** 检索结果、评审报告、章节草稿和校验报告内嵌消息流；长内容允许展开，摘要必须保留产物类型、验收状态和下一步。
- **知识库面板：** 文献池、笔记和图谱三个页签与当前任务同生同死。可靠度徽章必须同时显示文本等级；外部下载动作必须说明将打开浏览器。
- **输入区：** 面向自然语言指令，支持清楚的发送、附件和上下文状态。键盘焦点使用 `permission` 的 2px 可见轮廓。

## Do's and Don'ts

- 应让当前任务、当前阶段、验收结果和下一步操作在首屏内可辨认。
- 应保持人工确认闸门是流程推进的唯一显式入口，并在刷新后恢复其状态。
- 应在所有状态色旁提供文字或图标，并保留可见键盘焦点。
- 不要增加默认“全部运行”按钮；论文全流程默认逐环验收和确认。
- 不要把知识库拆成与论文任务无关的全局工作区。
- 不要把“正在执行”“等待确认”“已完成”合并成同一种视觉状态。
- 不要新增未经现有 token 支持的颜色、字号、圆角或阴影。
