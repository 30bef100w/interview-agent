# 深问产品介绍 · 截图清单

## 自动截图（推荐）

默认从你在对话里提供的 **xuyongqi 账号参考截图** 同步，并放大到 2880px 宽：

```powershell
cd docs/promo
$env:PROMO_CAPTURE = "1"
python capture_screenshots.py
.\build.ps1
```

账号密码可通过环境变量覆盖：`PROMO_USERNAME` / `PROMO_PASSWORD`（默认 xuyongqi / 123456）。

尝试 Playwright 实时截取（需 frontend 能正常请求 API）：

```powershell
$env:PROMO_MODE = "live"
python capture_screenshots.py
```

## 手动放置

也可将截图按下列文件名放入本目录，再运行 `build.ps1`。

| 文件名 | 对应页面 |
|--------|----------|
| `00-landing.png` | 产品首页 / 落地页 |
| `01-dashboard.png` | 工作台 |
| `02-new-interview.png` | 开始面试（全流程配置） |
| `03-custom-settings.png` | 自定义设置弹窗 |
| `04-target-company.png` | 目标企业 |
| `05-history.png` | 面试记录 |
| `06-growth.png` | 成长档案总览 |
| `07-targeted-practice.png` | 针对性再练卡片 |
| `08-radar-weakness.png` | 雷达图 + 短板标签 |
| `09-interview-chat.png` | 面试间对话 |
| `10-coding.png` | 手撕算法 |
| `11-report.png` | 面试报告 |
| `12-report-questions.png` | 逐题详情 |

## build.ps1 环境变量

| 变量 | 说明 |
|------|------|
| `PROMO_CAPTURE=1` | 编译前先跑 `capture_screenshots.py` |
| `PROMO_USE_ASSETS=1` | 从 Cursor assets 覆盖 images/（旧图，分辨率较低） |
