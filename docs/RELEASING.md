# SDK 二进制发布（0.5.0）

发行目标：SDK 源码在 `Entertech/edu-glasses-host` 内部维护；demo、使用说明和 API 参考在
[公开 demo 仓库](https://github.com/Entertech/edu-glasses-demo)维护。
发布 Cython wheel，保留 `edu_host` 公共接口、低层 API、extras 与类型提示。禁用 sdist，
构建门禁拒绝 `.py/.pyx/.c` 等实现源文件。二进制仍可被逆向分析，Cython 不提供加密或绝对源码保护。

## 一次性配置：你需要完成的步骤

1. 注册 [PyPI 账号](https://pypi.org/account/register/)，验证邮箱，启用双因素认证，保存恢复码。
   GitHub 账号/组织权限与 PyPI 权限互相独立；首次发布后该 PyPI 账号成为项目 Owner。
2. 登录 PyPI → Account settings → Publishing，添加 **pending trusted publisher**，选择 GitHub：

   | 字段 | 填写值 |
   |---|---|
   | PyPI Project Name | `edu-glasses-host` |
   | Owner | `Entertech` |
   | Repository name | `edu-glasses-host` |
   | Workflow name | `publish-pypi.yml` |
   | Environment name | `pypi` |

   Workflow 只填文件名，不填 `.github/workflows/`。首次成功上传时创建项目，不必先手动上传包；
   pending publisher 不预留项目名，若名字被占用需先解决项目归属。后续使用同一 publisher 发布。
3. 由 GitHub 仓库 Admin/组织 Owner 将 SDK 仓库设为 **private**；demo 保持 **public**。
   2026-10-26 核验：登录账号 `xdpan1234` 对 SDK 只有 Maintain 权限，不能执行可见性修改。
   路径：SDK 仓库 Settings → General → Danger Zone → Change repository visibility。
   过去已公开的 Git 历史可能已有克隆或缓存，改 private 无法收回这些副本。
4. 将 workflow 合并到 SDK 默认分支 `main`，由有权限者在 Settings → Environments 创建/确认 `pypi`。
   可设置环境 required reviewers 和只允许版本 tag 的部署规则（视 GitHub 计划支持），防止误发布。
   仓库/组织 Actions 策略须允许使用本 workflow 固定的 GitHub/PyPA actions。
   不用设置 PyPI API token 或密码 secret；publish job 使用 OIDC 临时凭证。

参考：[PyPI pending publisher 官方步骤](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)、
[GitHub environment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。
账号注册、邮箱验证、2FA 和 PyPI 授权需要账号持有人完成，凭据不要发到聊天或提交仓库。

## 日常手动发布

首次落地顺序：SDK 仓库改 private → 推送并将 workflow 合入 main → CI 仅构建验证 →
tag 发布到 PyPI → 干净环境安装确认 → 合入 demo 的 PyPI 依赖切换。
PyPI 发布前将 demo 切换保留在候选分支，避免默认分支安装依赖尚不存在的版本。

1. 同步 `pyproject.toml` 与 `edu_host.__version__`；更新公共指南、API 和 demo 固定依赖版本。
2. Actions → **Build and publish SDK wheels** → Run workflow，选择候选分支，version 填 `0.5.0`，
   `publish` 保持关闭。也可运行：

   ```bash
   gh workflow run publish-pypi.yml --repo Entertech/edu-glasses-host --ref main -f version=0.5.0 -f publish=false
   ```

3. 全部构建通过后，下载 artifact 核对 wheel。将已审核提交合入 main，基于该提交创建 `v0.5.0` tag 并推送。
4. 再运行同一 workflow，选择 **v0.5.0**，填 `0.5.0`，勾选 publish：

   ```bash
   gh workflow run publish-pypi.yml --repo Entertech/edu-glasses-host --ref v0.5.0 -f version=0.5.0 -f publish=true
   ```

   正式发布要求版本/tag 完全匹配、SDK 仓库 private、全部构建成功；再由 `pypi` 环境发布。
   仅 publish job 拥有 `id-token: write`。上传只读取经审计的 wheel，不上传 sdist 或构建源码。
5. 从干净环境通过 PyPI 安装，并检查 `from edu_host import EduSession`、demo 启动与版本。
   PyPI 相同版本文件不可覆盖；失败先核实已上传文件，修复后通常提升版本，不能依赖跳过重复文件掩盖部分发布。

首次发布前，公开文档必须保留“发布后可安装”的说明；确认 PyPI 可用后移除该提示。
SDK 无需向外部开发者开放源码仓库，PyPI 项目和已发布 wheel 均公开可下载。

## 构建和检查范围

| 项目 | 支持范围 |
|---|---|
| Python | 标准 CPython 3.9–3.14，每个版本独立 wheel |
| Windows | x64 |
| macOS | Intel x64、Apple Silicon ARM64，构建最低目标 11.0 |
| Linux | x64、ARM64，manylinux2014 / glibc 2.17+ |

Python 自身及可选依赖可能提高最低 OS 版本。暂不构建 PyPy、free-threaded、Windows ARM64、32 位和 musl wheel。
CI 原生 runner 分别构建五种平台/架构；每个 wheel 安装后运行既有 55 项检查和 `verify_installed.py`。
macOS 额外检查 PyObjC 委托注册与独立解释器导入。检查不连接设备，不代表各平台实机收发全部通过。
`verify_wheels.py` 检查版本、18 个扩展和类型声明、无源码/CLI入口/非SDK文件；`twine check` 检查发布元数据。
所有平台通过后才会进入 publish job。

内部本地构建（需要 C 编译器）：

```bash
python -m pip install build
python -m build --wheel
python scripts/verify_wheels.py dist --version 0.5.0
```

本地审计另需 `packaging`；macOS 构建前设置 `MACOSX_DEPLOYMENT_TARGET=11.0`。
默认 `python -m build` 会尝试 sdist，因源码分发已禁用，应显式使用 `--wheel`。
现有 API/线协议保持兼容，只把一处等价字节解包改为 `struct.unpack_from` 以避开 Cython 编译器崩溃。

## 本轮本地验收（2026-10-26）

- macOS ARM64 的 CPython 3.12 / 3.13 wheel 均完成构建、独立安装、18 个扩展与类型声明审计，未包含实现源码。
  3.12 wheel 最低构建目标为 macOS 11.0，3.13 使用本机 Homebrew Python，目标为 macOS 26.0。
  最低目标标记不等于在对应旧系统上实机验证通过。
- 两个已安装二进制环境分别通过既有 55 项检查和 PyObjC 委托/独立解释器导入检查。
  去掉既有测试中的源码路径注入，确认检查实际导入已安装扩展；未新增单元测试。
- demo 独立安装、现有 3 项 CLI 检查、命令/三个新调用示例的 help、参数拒绝及依赖检查通过。
  文档 Python 示例语法和本地链接检查通过；未连接设备。
- 正式发布的 tag/版本/private 门禁、源码混入拒绝及 sdist 禁用自检通过。
- 尚未推送/运行远端 CI 或上传 PyPI；SDK 仍公开，需管理员改为 private，账号持有人完成 PyPI publisher 配置。
  Windows、Linux、macOS Intel 及其余 Python 版本等待 CI 验证。
