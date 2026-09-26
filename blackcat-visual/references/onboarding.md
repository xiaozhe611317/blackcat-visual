# 新手建档

## 收齐选择

从用户已有名字、总文件夹、参考和描述开始。读取 questionnaire.md，一次展示固定 Q01–Q18，预填已有答案，不随机编题、不问已确定的问题。支持编号、自然语言、自定义和“交给 AI”。仅影响身份的矛盾集中澄清；普通漏答按合理默认补齐并标注。

以用户总文件夹为项目根，运行 project-init --folder ROOT，再用 template document --out ROOT/角色名生图.md 创建模板。问卷答案放过程记录，当前设定只写 MD。

输出短卡：身份｜固定锚点｜默认穿搭/风格｜随机范围｜资产与张数。用户已说开始生成就继续；选择仅文字则完成文档即停。模板占位必须替换，禁止项写具体，不能以“漂亮”代替身份。

## 按母版派生整包

默认六张：母版、六角度全身板、五角度脸部板、六表情板、锚点板、默认风格场景样张。无独立锚点时五张；已有合格素材复用。图板过密不可读时说明需拆分部分，按已授权范围处理。

| 资产 | 实际覆盖 | 用途 |
|---|---|---|
| 母版 | 正面或轻三分之四清晰脸、中性表情 | 最高身份优先 |
| 全身板 | front、left_three_quarter、right_three_quarter、left_side、right_side、back | 简单同服装、中性站姿、完整头脚；侧面90度 |
| 脸部板 | front、left_three_quarter、right_three_quarter、left_side、right_side | 五官关系、耳部、发际线和轮廓 |
| 表情板 | neutral、smile、laugh、sad、surprised、angry | 情绪变化不换脸或年龄 |
| 锚点板 | details | 本人左右、形状、颜色和遮挡；可含饰物单体 |
| 场景样张 | 默认风格中的角色 | style 与 pair 可由同一图片承担 |

非人形用对应部件覆盖同一观察任务，不生造人类鼻唇。无面部表情能力时用姿态/眼灯等六种情绪表现，并注明；标签只能表示实际可见内容。

先做母版并检查。按 Q18 等待母版判断或自动继续，整组授权不逐张问。后续每张实际查看并传入同一母版，按需追加角度/锚点。转面的默认服装不永久固化为身份。

## 候选也走同一记录流程

首张母版无图：prepare --document MD --mode candidate --asset-type master --request-file REQUEST。
其它资产：prepare --document MD --mode candidate --asset-type body --references REFS --request-file REQUEST；asset-type 可为 face、expressions、anchors、style。

REFS 可指向项目内已查看的候选母版，无需提前正式登记。已有满意母版必须传入，不能用 master 豁免重新文字捏脸。REQUEST 明确资产覆盖，不能仅靠 asset-type 生成正确图板。

实际生图后执行 record/review（见 production）。发现错位锚点时保留失败版本并修相关图，不将未通过内容登记为覆盖。

## 一次认可、完整交付

展示实际整包和尚不可判断的细节。用户认可后把采用图原样复制到视觉资产，更新 MD 中的相对引用；建立 REFS（格式见 storage），执行 project-save --document MD --references REFS --approval USER_STATEMENT。已认可这些素材时沿用原话，不再逐图问。

save 验证完整覆盖、真实文件和哈希并保存版本，不替代目视检查。project-check 验证后交付 MD＋整个资产目录；新用户不必另走全局人物库/风格库登记流程。

## 多角色创建与批量衔接

一次为多位新角色建档时，先给每人一个稳定 ID、独立 MD 和参考归属；同一问卷表可列多人的答案，不把所有人合成一个身份模板。建立角色总览，列出“仅文字／待母版／待补齐／待整包认可／可用”。

需要连续完成母版与派生图时，用 batch.md 的 candidate＋master_from 依赖。例如一个 master 后接 body、face、expressions、anchors、style；无锚点则省略 anchors。派生图只依赖本人的母版，不依赖上一张派生图。已有满意母版通过候选 REFS 直接使用，不再生一张母版。

母版自查通过后：Q18A 等用户确认；Q18B 或明确整包授权可把原授权作为 continuation 的依据，继续派生。continuation 仅允许继续，不将角色登记为正式可用。母版失败不带着错误继续该人的派生图，其它角色照常推进。角色包最后仍按本页的整包认可与 project-save 登记。
