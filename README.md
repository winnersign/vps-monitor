# CN2/GIA VPS 库存监控

## 这是什么

每小时自动扫描 BandwagonHost（搬瓦工）、DMIT 等商家的 CN2/GIA 优化线路 VPS，年付 $15-50 范围内的套餐一旦补货，**立刻发邮件到你 QQ 邮箱**。

## 工作原理

```
GitHub Actions (每小时触发)
    ↓
vps_monitor.py (并发扫描多个来源)
    ↓
比对上次状态 → 发现补货？
    ↓ 是
QQ 邮箱 SMTP 发通知邮件给你
    ↓
状态写入 vps_monitor_state.json (Git 持久化)
```

## 监控范围

| 商家 | 来源 | 监控内容 |
|------|------|----------|
| **BandwagonHost (搬瓦工)** | teddysun.com/bwh.html | 全部 CN2/GIA/软银/香港/日本套餐 |
| **BandwagonHost** | 直接 PID 检查 | 5 个热门限量版套餐 |
| **DMIT** | dmit.io/cart.php | CN2 GIA 套餐 |

预算限制：年付 $15-50（等效于月付 $1.25-4.17）

## 部署步骤

### 1. 创建 GitHub 仓库

去 [github.com/new](https://github.com/new) 创建一个 **Public**（公开）仓库，名字随意，比如 `vps-monitor`。

### 2. 上传文件

把这些文件上传到仓库根目录：
- `vps_monitor.py`
- `.github/workflows/monitor.yml`
- `requirements.txt`

**注意**：`.github/workflows/` 是目录结构，在 GitHub 网页上创建文件时文件名写 `.github/workflows/monitor.yml` 就会自动创建目录。

### 3. 配置 Secrets

在仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，添加以下 3 个：

| Secret 名称 | 值 |
|-------------|-----|
| `QQMAIL_USER` | `1970701290@qq.com` |
| `QQMAIL_PASS` | 你的 QQ 邮箱 SMTP 授权码（16位） |
| `QQMAIL_TO` | `1970701290@qq.com` |

### 4. 开启 Actions 权限

仓库默认会禁止自动运行 Actions。去 **Settings** → **Actions** → **General** → 确保 "Allow all actions and reusable workflows" 已选。

### 5. 手动触发第一次

去 **Actions** 标签页 → 点击左侧 **"CN2 VPS 库存监控"** → 右侧 **"Run workflow"** → 绿色按钮运行。

第一次运行会建立初始状态（不会发邮件），之后就每小时自动检查，补货时才发邮件。

## 注意事项

- GitHub Actions 免费额度：公开仓库每月 2000 分钟，这个脚本每次运行不到 10 秒，完全够用
- 如果仓库 60 天没有任何 commit，GitHub 会暂停定时任务——但这个脚本每次运行都会 commit 状态文件，所以不会触发这个限制
- 邮件是从你的 QQ 邮箱发给自己，QQ 邮箱每天 SMTP 限额约 500 封，完全够用
