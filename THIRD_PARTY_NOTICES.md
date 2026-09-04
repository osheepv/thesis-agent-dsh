# 第三方软件声明

本项目自身代码使用 Apache License 2.0。第三方依赖仍分别适用其原始许可证，本项目许可证不会覆盖或替代这些条款。

## Cytoscape.js

- 文件：`ui/vendor/cytoscape.min.js`
- 项目：https://js.cytoscape.org/
- 版权：Copyright (c) 2016-2024, The Cytoscape Consortium
- 许可证：MIT License

完整MIT许可文字已经保留在该文件头部。

## Lucide 0.469.0

- 文件：`ui/vendor/lucide.min.js`
- 项目：https://lucide.dev/ / https://github.com/lucide-icons/lucide
- SHA-256：`5DE4FFFDDC1B41AD1226D5E986FCC552ADB8AD9EFD1566E71DFDCDB664F9A6C2`
- 许可证：ISC License；其中源自 Feather 的图标仍适用 MIT License

ISC 声明：

> Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as
> part of Feather (MIT). All other copyright (c) for Lucide are held by
> Lucide Contributors 2022.
>
> Permission to use, copy, modify, and/or distribute this software for any
> purpose with or without fee is hereby granted, provided that the above
> copyright notice and this permission notice appear in all copies.
>
> THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
> WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
> MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
> ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
> WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
> ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
> OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

Feather 派生图标声明：Copyright (c) 2013-2022 Cole Bemis，MIT License。

## Open Props

- 文件：`ui/vendor/open-props-easings.min.css`、`ui/vendor/open-props-shadow.min.css`
- 项目：https://open-props.style/ / https://github.com/argyleink/open-props
- SHA-256：`85CDE88E92E927E1447883CBD745591FC355D7A43198AABEAC4C2E968F3B6E8A`、`F83E3A75DD517B0FA98489130E952B5D2BFA6CB8E8EAE99AEE7C0E51F33DBCCA`
- 版本：上游版本号未保留在两份最小化 CSS 内，因此以上述哈希固定本次快照
- 许可证：MIT License，Copyright (c) 2021 Adam Argyle

Lucide 中的 Feather 派生图标与 Open Props 分别在上述版权归属下适用以下 MIT 条款：

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Python依赖

Python依赖通过`backend/requirements.txt`安装，不作为本项目源码重新授权。重新分发应用或安装包时，发布者应根据锁定版本收集并附带对应的第三方许可证与版权声明。

## Nature Skills（概念级修改实现）

- 上游：`Yuan1z0825/nature-skills`
- 固定提交：`ebd722e18808442688bd205917a3e774195c258f`
- 项目：https://github.com/Yuan1z0825/nature-skills
- 许可证：Apache License 2.0
- 涉及来源：`skills/nature-proposal-writer/references/foundation-files.md`、`skills/nature-proposal-writer/references/stopping-rules.md`
- 修改说明：本项目没有复制或安装上游 Skill；仅参考其 foundation/stopping workflow 思想，并将其重写为 Pydantic 契约、作者审批字段、服务端停止原因码和确定性测试。三轮/0.5 只作为可配置默认预算，证据缺口与专家冲突按本项目安全边界重新设计为硬停止条件。

Nature Skills 是社区项目，本项目与 Nature Portfolio 无隶属或官方合作关系；Apache-2.0 不授予 Nature 商标或官方背书权利。期刊政策必须以执行时的官方页面为准。
