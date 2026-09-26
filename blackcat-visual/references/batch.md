# 批量与同框

新批次先读 [image-specs.md](image-specs.md)，一次确认本批规格/制作档位及逐图例外。项目文档接入按 [轻量执行规则](environment.md#项目文档接入与轻量执行) 使用一份批次总记录；本页的 catalog、计划 JSON、快照目录和 CLI 闭环仅用于完整 Agent，不在轻量流程中手工复刻。完整 Agent 在计划顶层增加 image_specs（templates/image-specs.json 的 scope 改 batch），不复用上批认可。下面 aspect/size 是旧计划兼容写法；新规格卡取代这两个字段，其它批量规则不变。每项 prepare 后 spec-adapt --commit，再 dispatch；这只是参数预检，不增加生图调用。

## 先确定每张图是什么

用户给出人数/张数后直接展开任务表；必要时用选择题澄清“每人各几张”或“几人一起一张”。例：12 个角色各 2 张＝24 个单角色 item；5 人一起 3 个镜头＝3 个五人 item。可以在同批混排单人和同框图。不要将“24 张”改解释为 24 张拼在一张联系表中。

先用 catalog 列出角色名称、母版缩略图、MD、版本、准备状态；它只验证已登记文件，不代表本次视觉审核。候选角色额外注明仅文字/待母版/待补齐/待整包认可。按角色 ID 选择，不以同名文件或上一轮聊天记忆代替。

开始前简短展示总数、角色清单、场景、画风/画幅覆盖、失败处理与首轮调用范围。用户已明确“生成这 24 张”就不重复要批准。计划数不包含未经许可的返工、场景基准图、参考拼图或分阶段合成调用。

## 场景与镜头

场景唯一内容源为 scene.json（模板见 templates/scene.json）：id、revision、name、location、layout、key_objects、lighting、continuity、references。保存用户外部场景的真实图片；参考指向场景文件旁的相对路径。每张场景图写 allowed/forbidden，防止把场景中的路人或旧角色带入。

- 场景锁：同一地点、空间布局、关键物件及约定的时间/光线。只写不随镜头变化的事实。
- 镜头：camera、framing，以及该镜头需要的补充；允许换机位，不等于翻转整个场景布局。
- cast：角色 ID、画面位置、动作/互动、可见范围、必须可见的锚点、服装覆盖。区分世界坐标、屏幕左右和角色本人左右。
- 未知角落：参考没展示时，不假装知道。先补文字布局或请用户认可必要的场景基准；额外生成基准图要单列调用范围。

5–8 人采用清晰分层站位、足够辨识面部的景别、可读的互动关系；避免在很远的小人群中强行承诺每张脸可验。每人至少一份本人的身份参考，必要时加对应角度/锚点图。统一本张图的画风、比例和尺寸目标，不让各人的默认画风竞争。参考数量限制按 environment.md 处理，不省掉部分人的身份参考凑数。

## 计划结构

从 templates/batch.json 复制并填成真实数据。characters[].document 和可选 references 相对“输入计划文件”解析，也接受用户明确提供的绝对路径；批次冻结后使用批次内相对快照，不再依赖这些来源路径。

| 层级 | 内容 |
|---|---|
| characters | id、document、mode（production 默认；新建用 candidate）、可选候选 references 清单 |
| common | request、style_override、outfit_override、aspect、size；批次共用要求 |
| image_specs | 新规格卡：common 完整规格、overrides 按任务 ID 的例外、confirmation 本批确认；采用它时移除旧 aspect/size |
| scene | 可选场景 JSON 路径；一批用一个固定场景，不同场景建不同批 |
| items | 每张目标图一项，唯一 id、cast、request、可选覆盖及 shot |
| cast | character、position、action、visibility、required_anchors、reference_ids、coverage、outfit_override |
| 依赖 | depends_on；派生资产另设 asset_type 与 master_from |

优先级：逐角色服装 > 逐图服装 > 批次服装 > 角色默认；逐图画风/画幅 > 批次画风/画幅 > 单角色默认。同框图必须明确统一 style_override、aspect、size。common.request 与 item.request 是补充关系，不会自动消解矛盾；矛盾时先澄清再调用。不要把画风/衣服变更只塞进 request 却忘了覆盖字段。

reference_ids 精确选图；coverage 用 body:left_side、face:right_three_quarter、expression:smile、anchor:details 等已登记标签选必要辅助图。自动选择优先已选参考，再选覆盖最集中者；缺必要标签阻塞该项。提示词每张重新建立全局图片编号与归属，跨角色不按哈希混为一个主人。风格/组合只控制画法，pair 不代表两个角色。

没有场景、镜头和画面要求的单人任务，在初始化时从许可池冻结随机组合；返工不重新抽场景。已有部分要求时由助手补成兼容的明确要求。共享场景优先，不能又随机出别的地点。

### 创建模式的依赖

新角色设置 mode=candidate。首张设 asset_type=master；无参考仅限首次母版。其它资产的 master_from 指向同角色母版 item，asset_type 为 body/face/expressions/anchors/style，并用 request 明确视图覆盖。已有满意母版则用候选 references，各派生项直接引用，不设置新的 master 任务。

母版必须实际看图并做 QA，获得明确继续依据后 batch-approve --purpose continuation。用户已授权“母版自查后自动继续整包”时，记录原授权并注明 AI 自查，不伪造新的用户认可。整包最终仍依 onboarding 由用户认可并 project-save，批次本身不自动升级角色资产。

允许派生时绑定该母版的确切轮次；后来重试母版不会悄悄替换已绑定的派生任务。需要换新版母版重做派生时，明确新建受影响项的批次，不混用两版母版登记成一个完整包。

## 执行闭环

PYTHON 为当前可用 Python；CLI 为本 Skill 的 scripts/blackcat.py，均由 Agent 解析，不要求用户输入命令。

    PYTHON CLI catalog --document MD1 --document MD2 --out NEW_OVERVIEW_FOLDER
    PYTHON CLI scene-check --file SCENE_JSON
    PYTHON CLI batch-init --plan PLAN_JSON --folder NEW_BATCH_FOLDER
    PYTHON CLI batch-status --batch BATCH
    PYTHON CLI batch-prepare --batch BATCH --item ITEM

init 冻结文档/参考/场景及逐图要求。缺角色或场景会列错误，不声称已就绪；单个角色缺项不影响别人。prepare 输出本轮 prompt_file 和绝对图片路径；打开提示词和所有实传图，核对编号/用途与工具能力。prepare 没有调用生图工具，也没有生成图片。

    PYTHON CLI batch-dispatch --batch BATCH --item ITEM --evidence SUBMISSION_PLAN
    # 此刻由 Agent 真正调用当前环境的图像工具，一次调用、一张目标图。
    PYTHON CLI batch-record --batch BATCH --item ITEM --source REAL_IMAGE --metadata GENERATION_JSON
    PYTHON CLI batch-review --batch BATCH --item ITEM --checks BATCH_CHECKS_JSON

提交前先 dispatch。记录应含工具名、实际提示词、真实传图证据、可见参数、真实调用/成功次数，格式沿用 generation.json。未知模型名不猜测。队列按一项一调用记录，不在一个 attempt 内偷偷重试。record 原样保存输出字节，并不证明视觉通过。

若环境无法生图/传图且用户选择交接：batch-dispatch 加 --handoff，给出提示词、实际参考图和编号映射，待外部结果回填；handoff 不是成功。不要因没回复自动回调。

确定无输出的报错：batch-outcome --state failed --evidence ACTUAL_ERROR。超时/断线且可能仍在处理：--state unknown。继续独立任务，依赖相关失败母版的项保留 waiting_dependency。

实际已调用一次可加 --request-count 1，确定未发出调用可加 0；未知就省略。报告不会将单纯 dispatch 当作收费调用的证据。

中断续接先 status。ready 可准备，prepared 可读取相同轮次，running/unknown/handoff 不能再次发送。核对外部工具结果后：有图用 record；已确认未生成才 --state resolved_no_output --evidence VERIFIED_RESULT。未核实的 running 不能因为等待太久直接当失败。状态锁意外遗留时先核查进程，不自动删锁。

本地写入中断留下 orphaned：batch-recover --batch BATCH --item ITEM --evidence VERIFIED_CONTEXT，默认恢复为结果未知；只有确认尚未提交才加 --not-submitted 恢复为 prepared。完整轮次需通过哈希/归属校验；半成品记录不自动覆盖，保留现场并报告。其它独立任务继续。

## QA、集中返工与正式认可

templates/batch-checks.json 含 global 六项、characters 按本图全部 ID 的 identity/anchors/placement 三项、continuity。必须看实际结果；逐人检查人数/身份、锚点归属与左右、服装、站位动作、遮挡、肢体交叠。场景另查布局、物件、光向和相邻已通过镜头的连续性。该图和上一图共有的人物也应跨图对比，不能只比较整体画风。

以上与 production/image-specs 的检查合并为每图一轮。完整 Agent 的 global 结论可概括逐人观察，不再次查看同一内容；轻量批次在总记录按图保留简短观察，问题项注明角色与部位，不另写逐图长文。同批参考可复用已读取结果，单人图仍只实传本人必要参考，同框图实传所有出场角色的必要参考。

三态均写观察：通过、待修、无法判断。脸太小/被挡到无法认出身份、必须可见锚点缺失、漏人/重复人、错位、串衣服或场景漂移进入待修。非必见小饰物合理遮挡可无法判断并说明，不强制露出；不能用“无法判断”豁免缺人或必需身份。程序仅检查记录是否完整和状态规则，不会替你看图。

    PYTHON CLI batch-report --batch BATCH

先完成独立项，再展示成片和待修清单：任务 ID、问题角色/部位、建议修法、预计额外调用。用户一次选择需要返工的任务；每个被选项获准一次额外调用，其余不重做。重试只在指定项执行：

    PYTHON CLI batch-retry --batch BATCH --item ITEM --approval USER_STATEMENT --note REPAIR_REQUIREMENT
    PYTHON CLI batch-retry --batch BATCH --item ITEM --approval USER_STATEMENT --note LOCAL_FIX --base attempt --source-attempt 1

默认 original＝冻结身份/场景/要求重新生成；不是“拿第一张失败图继续改”。attempt＝明确选择历史成片作为唯一编辑底图，仍携带固定身份和必要参考。工具不支持编辑时先说明选择，不谎称局部编辑。两种方式都生成新轮次，不覆盖原始输出；之后再次 prepare/dispatch/record/review。

用户认可成片后：

    PYTHON CLI batch-approve --batch BATCH --item ITEM --approval USER_STATEMENT
    PYTHON CLI batch-archive --batch BATCH --item ITEM

多项同一认可原话可逐项记录，无需重新询问。已知偏差仅在用户明确接受时用 --accept-issues，且说明偏差；不把它当默认宽松开关。再做 QA 会使旧认可失效，旧审核历史保留。作品认可不自动变身份参考，也不自动完成角色整包登记。

## 目录、搬迁与范围

    批次目录/
      plan.json                         冻结逐图要求
      batch.json                        队列、提交事件、轮次索引
      snapshots/characters/角色ID/       冻结 MD 和真实参考图
      snapshots/scene/                  冻结场景和参考图
      候审图/批次/任务ID-a0001/           prompt、输入、原图、QA、认可
      定稿图/                            用户认可的编号成片
      批量报告.md                        可重建的查看页

搬完整批次目录可继续；不要只搬 plan.json。来源文件改动不会静默污染当前批次。更改固定要求或修复缺失源文件后，为受影响项创建新批次并说明继承关系，已完成项保留，不反复覆盖冻结计划。

报告区分计划数、已生成数、待审核/待修数、已认可数及真实调用数。初版不提供无人值守后台服务、跨机器同时写同一批次、模型自动切换或“稳定一次生成 8 人”的保证；它提供可追溯、可续接的执行协议。
