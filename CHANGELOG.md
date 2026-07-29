# Changelog

格式大差不差参考 [Keep a Changelog](https://keepachangelog.com/)，但其实没那
么严格。

## [1.2.0] - 2026-07-15

### 新增
- PWA 离线支持（Service Worker 缓存模型库和真题库）
- 移动端响应式适配

### 修改
- DeepSeek API 超时从 30s 调到 120s（某些长题目处理时间太长）
- 前端 tab 切换不再闪烁

### 修复
- Safari 上输入框 placeholder 不显示
- LaTeX 公式在暗色模式下对比度太低
- 移动端导航栏偶尔遮挡内容

## [1.1.0] - 2026-06-20

### 新增
- 33 个数学模型速查库，支持三维筛选
- 2000-2024 美赛 MCM/ICM + 国赛 CUMCM 真题库
- Roles 页面（团队分工 + 每日任务 + 检查点）
- Paper 页面 AI 查重和引用验证

### 修改
- 生成的论文框架从纯文本改成 Markdown 渲染
- API 调用加入重试机制（DeepSeek 偶尔抽风）

## [1.0.0] - 2026-05-15

### 新增
- 初始版本发布
- Generator 页面：选题 → 论文方案生成
- Paper 页面：格式化论文预览
- Guide 页面：竞赛避坑指南 + 工具链推荐
- Flask API 完整脚手架
- Railway 云端部署
- PyInstaller 桌面打包（macOS + Windows）
