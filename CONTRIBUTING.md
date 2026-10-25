# 参与改进

欢迎讨论赛事数据、字段定义、采集稳定性、模型校准和使用体验。先通过 Issue 描述具体问题；PR 尽量一次解决一个问题。

## 复现与检查

使用 Python 3.14，在虚拟环境中安装 `python -m pip install -e .` 后执行：

```bash
python tools/check_public_files.py
python -m compileall -q kpl_insight apps tests
python -m unittest discover -s tests -v
python tests/check_monitor_rolling.py
python -m kpl_insight demo
```

改变采集字段、时间顺序、特征或训练切分时，添加能发现行为错误的离线回归测试。真实数据评估须报告数据范围与模型指纹；合成样本不能替代性能验证。

## 提交内容

文件发布范围由 `.public-files.json` 的白名单控制。新增文件需明确属于允许的源码目录或白名单文件；不要把设计稿、内部文档、会议记录、研究报告、抓取数据或宣传素材加入公开提交。

启用本地上传前检查：`git config core.hooksPath tools/hooks`。GitHub CI 还会独立检查所有跟踪文件，`git add -f` 不能绕过 CI 检查。

不要提交密钥、账户信息、原始采集目录、权重、训练日志、视频或签名媒体 URL。复现数据使用最小脱敏片段或合成样本。第三方代码注明来源并保留适用许可。

## 贡献许可

本仓库为源码公开、非商业使用项目。提交新增贡献表示你有权按本仓库的 PolyForm Noncommercial 1.0.0 条款提供该贡献；第三方内容遵循各自适用许可。若你不能按这些条款提交，请先在 Issue 中说明，避免直接合入。
