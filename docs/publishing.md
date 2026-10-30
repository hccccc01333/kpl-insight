# 发布与贡献流程

## 本仓库的定位

本仓库 `kpl-insight` 是项目代码、测试、用户文档与内置前端的唯一维护入口。Issue、PR、版本发布和讨论都在这里完成。

## PR 流程

1. 先开 Issue 说明问题、使用场景和复现方式。涉及数据契约、模型、许可或公开数据结构的较大改动，先确认方向再实现。
2. Fork 仓库或从 `main` 建分支，一次 PR 尽量只解决一个问题。
3. 在本地运行相关检查，并在 PR 中写明运行命令与结果。
4. 维护者审查、CI 通过后合并；默认使用 squash merge，贡献者通过提交、PR 链接或 `Co-authored-by` 保留署名。
5. 涉及数据、模型或许可的改动会优先核对来源与边界；不承诺每个建议都进入路线图。

## 文件白名单

本仓库跟踪的文件由 [`.public-files.json`](../.public-files.json) 控制：

- `kpl_insight/` 与 `tests/` 下的 Python 文件按目录允许；
- 文档、图片、工作流和其它文件必须显式列入白名单；
- `.secrets/`、`output/`、`logs/`、`weights/`、`raw_snapshots/`、`promo/`、`reports/` 等目录始终拒绝；
- CI 和本地钩子都会检查，`git add -f` 不能绕过。

新增文件时，请同时更新白名单，并确认其中不含密钥、个人信息、原始采集数据或未获许可的第三方素材。

## 本地检查

提交前至少执行：

```bash
python tools/check_public_files.py
python tools/check_links.py
python -m compileall -q kpl_insight apps tests
python -m unittest discover -s tests -v
python -m kpl_insight demo
```

CI 还会在 Ubuntu 与 Windows 上运行离线检查；Windows 任务重点覆盖 `start.py`、内置前端和本地运行时。提交信息使用用户可感知的语言，例如 `feat: 赛程页支持对阵预测`，不写内部路径、TODO 或实验细节。

## 版本发布

1. 更新 `CHANGELOG.md` 与 `pyproject.toml` 中的版本号；
2. 运行上面的本地检查，确认 CI 通过；
3. 提交发布提交并打标签，例如 `v0.2.0`；
4. 在 GitHub Releases 中写出版本说明、安装/演示命令、已知边界和许可信息；
5. 发布包只包含可公开的源码、测试、文档与打包前端；不附带预训练权重、完整采集快照或原始媒体。
