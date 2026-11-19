# 第三方来源、作者与许可

## Blender Source Tools 3.4.3

- 原作者：Tom Edwards（原文件保留作者邮件和版权头）。
- 来源：用户提供的本地 `io_scene_valvesource` 目录，不假称是刚下载的官方最新版本。
- 内置路径：`bomberstudio_blender/vendor/io_scene_valvesource/`。
- 原始逐文件 SHA256：该目录 `PROVENANCE.json`；修改说明：`INTEGRATION.md`。
- 主体源文件为 GPL-2.0-or-later；本组合发布采用允许的 GPL-3.0-or-later 选项，完整文本为根目录及供应模块目录的 `LICENSE.txt`。
- `datamodel.py`：Tom Edwards，MIT；完整 MIT 声明保留在文件开头。
- `ordered_set.py`：基于 Ordered Set 3.1，MIT；Luminoso Technologies, Inc. 的完整声明见供应模块 `LICENSE-ordered-set.txt`。许可文本核对 PyPI ordered-set 3.1 源码包的 `MIT-LICENSE`；用户提供的代码保留其索引分支顺序差异。
- 没有把第三方代码改署名为 BomberAi，也没有改动用户提供的原目录。

### 本次集成修改（2026-10-03）

1. 外层中文面板、版本门控、导入导出封装、独立版共存。
2. 内置提供者使用可回滚注册，修正事件回调及九个动态顶点映射算子的清理，不停用其他插件。
3. 内置更新入口由 BomberStudio 统一管理，移除独立覆盖下载路径。
4. 导入异常恢复偏好设置、后台上下文支持、失败状态修正。
5. 参考网格固定 Basis，避免非零形态键污染 VTA / DMX 导出。

## 界面 / 工作流参考

- StarBobis / MIMIBlender：模型、顶点组、贴图与图集工作流参考。
- Team Neoneko / Cats Blender Plugin：角色工具与分组面板参考。
- 这些参考项目的完整源码或更新器未随本包内置；Source Tools 与这些界面参考项目不同，确实包含上面注明的第三方实现。

## 未随包分发

Blender 可执行程序、游戏 SDK、studiomdl、游戏资产、用户模型 / 贴图 / 缓存和第三方 FBX SDK。
