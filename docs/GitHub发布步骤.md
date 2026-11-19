# 把本项目发布到 GitHub

目标仓库：**[Hoshino486/BomberStudio_Blender](https://github.com/Hoshino486/BomberStudio_Blender)**。
本次功能版为 **1.2.0**；仓库名不带版本号，之后通过 Release 标签区分各版本。

## 一、上传准备好的目录内容

1. 打开本次交付的 **GitHub发布_1.2.0** 文件夹。
2. 把里面的内容放到 GitHub 仓库根目录，不要在仓库里再多套一层 `GitHub发布_1.2.0/`。
3. 根目录应包含：

   ```text
   README.md
   CHANGELOG.md
   LICENSE.txt
   THIRD_PARTY_NOTICES.md
   SHA256SUMS.txt
   release-manifest.json
   BomberStudio_Blender_1.2.0_Universal.zip
   bomberstudio_blender/
   docs/
   tests/
   tools/
   .gitignore
   ```

4. 如果当前正在 GitHub 编辑 `README.md`，可以先复制交付的 README 全文替换原来的单行标题，再点击 **Commit changes**。
5. 然后用仓库 **Add file → Upload files** 上传其余文件 / 文件夹，保留层级。
6. 也可使用已有 Git 客户端提交这个目录的内容。这里没有自动推送，也没有替你创建远端提交。
7. 打开仓库首页，检查功能表、目录链接与下载链接。

**仅上传 README 不会自动上传插件。**README 的相对下载链接指向仓库根目录的 Universal ZIP；该文件上传后下载入口才有内容。

## 二、发布一个 Release（推荐）

1. 在仓库右侧进入 **Releases**。
2. 选择创建新 Release。
3. 使用标签 `v1.2.0`，目标分支使用实际源码所在分支（当前仓库为 `main`）。
4. 标题填写 `BomberStudio Blender Bridge 1.2.0 — 一键在线更新`。
5. 从 `CHANGELOG.md` 复制 1.2.0 的更新内容；不要覆盖已有 1.1.0 标签或历史附件。
6. 附件只需要：
   - `BomberStudio_Blender_1.2.0_Universal.zip`
   - `SHA256SUMS.txt`
7. 不勾选预发布，不仅保存草稿；确认作为最新正式 Release 发布。用户下载 Universal ZIP；自动生成的 **Source code (zip)** 是仓库源码包，不是插件安装包。
8. 发布后才能使用插件“检查版本更新”的 GitHub Release 查询；仅有仓库、没有 Release 时，检查接口可能返回 404。

1.2.0 默认填入 `Hoshino486/BomberStudio_Blender`，也接受完整地址 `https://github.com/Hoshino486/BomberStudio_Blender`。
旧版 1.1.0 仍需填简写（去掉网址前缀）。插件只有在用户点击立即更新并确认后才会下载并备份安装；首次从 1.1.x 升级需手动安装一次。
本地安装修复版而远端尚未发布它时，提示“本地版本高于已发布版本”是正常结果。

## 三、不要上传哪些内容

- 工作区 `临时文件夹/`、`输出/`、模型、贴图、PC2、`.blend`、便携 Blender 程序。
- 原来的 1.0.0 / 1.0.1 三种 ZIP，除非刻意做历史归档。
- 用户首选项、个人日志或含本机路径的完整开发诊断。
- 大体积备份、下载缓存以及第三方工具程序。

本次 **GitHub发布_1.2.0** 目录按源码、文档、测试脚本和单个 ZIP 整理，不包含游戏资产或 Blender 程序。

## 四、发布后自查

- [ ] 仓库首页显示新的 README，而不是只有项目标题。
- [ ] README 的 ZIP 下载指向 `1.2.0_Universal.zip`，且根目录存在该文件。
- [ ] ZIP 校验值与 `SHA256SUMS.txt` 一致。
- [ ] 文档中写的是实测版本范围，而不是所有历史/未来版本保证。
- [ ] 按自己的 Blender 版本选安装入口，但始终选同一个 ZIP。
- [ ] Release 的 Source code ZIP 没有被当作插件安装包。
- [ ] 1.2.0 的完整 GitHub 地址和简写均能完成手动检查。
- [ ] 远端最新正式 Release 确实为刚发布的 `v1.2.0`；只有源码提交不会改变查询结果。

## 一键更新附件要求

保持 Universal ZIP 名称与 Tag 的数字版本一致，三处内部版本也必须一致。
上传脚本生成的 `SHA256SUMS.txt` 到同一 Release；优先使用 GitHub digest，缺少时使用校验文件。
请勿只重命名旧 ZIP，也不要以 Source code ZIP 代替安装包。
详见 [一键在线更新](./一键在线更新.md)。
