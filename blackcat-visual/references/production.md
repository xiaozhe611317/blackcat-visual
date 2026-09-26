# 日常生图、改图与审核

新请求先按 [image-specs.md](image-specs.md) 选择本次规格与制作档位。项目文档接入按 [轻量执行规则](environment.md#项目文档接入与轻量执行) 记录，不运行本页 CLI；以下 prepare、spec-adapt、record、review 等命令及原生文件适用于完整 Agent。旧命令保留兼容，不意味着旧轮次已完成规格确认。

## 读取与覆盖

每批首次读取当前角色 MD；完整 Agent 运行 project-check --document MD。同批版本和参考未变时复用检查结果。正式调用读取已批准版本；未登记建档使用 candidate。阅读或询问文档不触发生图。

- 未指定衣服或风格：沿用 MD 默认外观与风格。
- 未写画面：prepare --document MD 从场景/动作/时间/构图抽取具体值，存入 request 与 random_choices。
- 部分已指定：助手只补缺项并检查组合合理性，保存 REQUEST 后调用 prepare；不能改用户指定部分。
- 换装：完整服装要求传 --outfit-override；换画风：完整新风格及限制传 --style-override，排除旧 style/pair 图和旧风格章节。仅在 request 写“换画风”还会带入旧默认，必须使用覆盖参数。
- 视角、表情、细节按需用 --reference REF_ID。临时覆盖无需重新登记；长期修改才更新 MD 与相关资产，用 project-save --update 留历史。

随机只在建档时许可的池内抽取，不随机脸、年龄、锚点或默认穿搭。prepare 后检查组合能否共存；若不合理，选兼容项写明确 REQUEST，重做 prepare，不调用生图工具盲试。通用禁忌写默认风格的“通用限制”或生图规则的“画面约束”；旧画风独有限制集中于“当前风格限制”。

## 真正调用图像工具

prepare 返回 prompt_file、inputs、run。读取实际 prompt 和所有输入；返回 path 是实传绝对路径，磁盘 inputs.json 使用相对路径以便搬家。

按 environment.md 选择用户指定或环境默认图像工具，读取该工具实际说明，打开并实传全部必要参考。传图参数或上传方式以当前接口为准，不猜字段、不将本地路径当作模型已读到图片。只有首次母版可纯文字；后续缺身份图不能退化成文字重画。输出尺寸以真实文件为准。

prompt.txt 是绘画要求；MD 快照、哈希和审核是追溯资料，不把行政流程混进绘画提示。工具若需调整提示词，记录实际提交文字。仅有内联图片且无法取原文件时展示结果并标明归档未完成。

按 generation.json 记录 tool、actual_submitted_prompt、reference_delivery.verified/evidence、visible_parameters、request_count、success_count。未暴露的模型或参数写未暴露；实传图片证据才能 verified=true。

新规格流程另记 applied_parameters（真实提交参数对象，未取得则省略）；record 返回 spec_verification，规格不符或无法核验要展示并进入待处理，不能偷偷放大、转格式或重生成。用户明确接受已知规格偏差时才使用 --accept-issues，保留偏差记录。

record --run RUN --source IMAGE --metadata GENERATION 保存真实字节；随后在一轮视觉检查中看整图、脸、头发、手及问题区域，与规格/批量清单合并，不各开一轮。按 checks.json 填身份/锚点/画风/形体/需求/纹理，通过 review --run RUN --checks CHECKS 保存。无新疑点或输入变化不重复检查。

## 用户审核与归档

结论仅通过/待修/无法判断；角度、遮挡、尺度导致不可见时说明，不为露锚点扭曲姿态。工具成功或文件存在不证明人物一致。

显示实际候选、必要对比、简短偏差和路径。用户通过后 review --run RUN --status 可用 --approval USER_STATEMENT，再 archive --run RUN --label NAME 编号到定稿图。同轮归档可幂等重做；原图保留。作品可用不自动变成身份参考。

日常默认一张，已授权多张或完整包按母版依赖连续执行。额外调用遵守用户范围；不无限重试，不擅自切换计费服务。截图或占位图不能冒充生成原图。

多张任务改用 batch.md 的逐项队列；同样的身份、锚点与默认项由共用渲染逻辑处理。单图也可以作为只有一个 item 的批次执行，获得冻结参考和中断续接能力。
