# 参与贡献

欢迎提交问题、文档和代码。请先搜索已有 Issue / PR，说明问题触发方式与预期行为，再提交聚焦的改动。

## 开发与检查

使用 Apple Silicon Mac 和包含 macOS 26 SDK 的 Xcode 或 Command Line Tools。先阅读 README 的构建说明，再运行：

```sh
python3 -B script/fetch_runtime.py
# 使用上一条命令输出目录中的 bin/python3.12
python3.12 -B -m unittest discover -s Tests -q
python3 -B script/privacy_check.py --source
./script/build_and_run.sh --build-only
```

新增检查要验证用户行为和边界，不重复实现细节。使用临时目录、合成服务与空闲本机端口；不要访问或停止贡献者真实产品。界面改动需检查最小窗口、空列表、长名称、错误态和浅色模式。当前只维护浅色界面。

## 隐私与边界

- 不提交个人产品清单、真实日志、`.env`、数据库、签名材料、用户目录绝对路径或真实业务截图。
- 不把发现项目变成自动执行项目，不加入静默镜像拉取、依赖安装或服务重启。
- 应用退出时已启动服务保持独立运行；停止操作必须验证当前进程身份。
- 公开文件由 `script/public_files.py` 定义。新增文件需相应更新规则，并审查实际待提交内容。
- PR 描述写清变更、原因、验证环境及未完成的验证，不用“测试通过”代替真实产品操作验收。

提交贡献即表示该贡献可以按本项目 MIT 许可证分发。不要求贡献者提供真实姓名、个人设备数据或私有部署。
