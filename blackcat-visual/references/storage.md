# 存储与命令

项目文档接入使用 [轻量执行规则](environment.md#项目文档接入与轻量执行) 和项目指定目录；本页原生目录、规格预设文件及登记命令仅适用于完整 Agent。轻量批次每项可追溯，但不要求每图一份同名长文；用户批准后按项目约定更新状态和位置，不自动进入个人资产或成为主参考。旧原生记录保持原协议，不为本次文档更新迁移历史。

v3.1 新请求使用 [image-specs.md](image-specs.md) 的规格卡和 spec-adapt；个人预设存项目的过程记录/规格预设。下面命令保留兼容，旧数据无需重建，但没有独立规格记录的输出为 UNVERIFIED。

v3 的批量目录、场景模板、状态和命令见 [batch.md](batch.md)；环境能力分支见 [environment.md](environment.md)。下面保留既有角色包和 v1/v2 命令，旧角色不因升级而重新建档。

## 环境和项目

从本技能根定位 scripts/blackcat.py。Python 用验证可用的3.10+绝对路径：先 -c "import sys; print(sys.executable)"，读图前 -c "from PIL import Image; print(Image.__version__)"。复用现有环境；缺依赖才在项目运行目录建 venv 装 Pillow，不安装全套科学计算库。Windows 设置 PYTHONUTF8=1，可设 PYTHONDONTWRITEBYTECODE=1。参数独立传递，不把认可原话拼进 shell 代码。

新项目无需全局配置，用户总文件夹优先，否则用明确当前项目，无可确定位置才问一次。MD 放项目根，图路径相对 MD。

    项目根/
      角色名生图.md
      视觉资产/                正式母版、视图、表情、锚点、组合
      候审图/日期/轮次/        原图、实传输入、实际提示词和检查
      定稿图/                  用户认可的编号成片
      过程记录/角色登记/       登记JSON与MD版本快照

MD 保存当前身份/默认项/随机规则，JSON仅存引用、版本、审核元数据。历史问卷/对话/v1档案只作来源，不能与当前 MD 各改各的。搬完整项目后相对引用继续有效，不依靠移动 Python venv 来实现便携。

## v2 命令

    PYTHON CLI project-init --folder ROOT
    PYTHON CLI template document --out ROOT/角色名生图.md
    PYTHON CLI prepare --document MD --mode candidate --asset-type master --request-file REQUEST
    PYTHON CLI prepare --document MD --mode candidate --asset-type body --references REFS --request-file REQUEST
    PYTHON CLI project-save --document MD --references REFS --approval USER_STATEMENT
    PYTHON CLI project-check --document MD
    PYTHON CLI prepare --document MD
    PYTHON CLI prepare --document MD --request-file REQUEST --style-override NEW_STYLE --outfit-override OUTFIT
    PYTHON CLI prepare --document MD --request-file REQUEST --edit-target IMAGE
    PYTHON CLI record --run RUN --source IMAGE --metadata GENERATION
    PYTHON CLI review --run RUN --checks CHECKS
    PYTHON CLI review --run RUN --status 可用 --approval USER_STATEMENT
    PYTHON CLI archive --run RUN --label NAME

占位换成真实路径/文字，不要求用户写命令。MD 改动需核对后 project-save --update；临时覆盖不改 MD。锁异常先检查对应进程，孤立或未完成版本不覆盖。

## 参考清单

REFS 为候选准备或登记输入，不重复身份文字。候选最小例子：

    {"id":"my-character","name":"角色名","anchors_mode":"defined","primary_reference":"master","references":[{"id":"master","path":"候审图/母版.png","role":"identity","coverage":[],"visually_checked":true}]}

正式登记前把批准图原样复制到视觉资产并更新 MD 与清单路径。正式包唯一 identity 母版；其它图用 identity_support、style、pair。覆盖标签为 body:front、face:left_side、expression:smile、anchor:details 等（完整项见 onboarding）。每图实际查看再 visually_checked=true，不能虚填 coverage。默认样张可不同 id 登记同一图的 style/pair 两种用途，prepare 按哈希合并。

批量临时引用为每张图重新编号，并另加 owner；这不改角色原有 reference id。pair 的定义仍是角色与风格的组合，不升级为多人关系表。角色之间的关系/互动放 cast 和 shot 中。

save 校验 MD 视觉参考链接与登记图片一致，再记录哈希/尺寸、manifest和不可覆盖的版本快照。程序仅证明文件与声明一致，不能证明人物相似或实际检查已经发生，助手仍要看图。

## v1 兼容转换

init/list/status/show/select/save-character/save-style/save-pair/rebind 保留兼容，旧库不改绑定。仅旧版维护使用它们；v2日常无需全局 library。

用户指定旧角色时：status定位，show character/style 与 select读取该角色/风格/组合并核图。把已确认的当前设定转到项目 MD，默认衣服从确认记录读取；保留正式资产，将相对路径写入 MD/REFS，沿用已有批准依据 project-save，再 project-check。旧 profiles 和原图片继续保留，迁移不改人物。

没有默认组合的旧角色按建档补齐；不会把其它角色或示例图片装进新项目。旧目录迁移需备份索引，移动后rebind验证。新项目相对引用无需逐图重绑。
