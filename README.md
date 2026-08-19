# agent-skills

本地 agent 自定义技能集合,以opencode为例。

## 技能列表

### de-ai-ify（去AI化润色）

将中文文章/文案/报告进行"去AI化"润色，让文本更像资深作者或记者亲笔所写。

触发词：去AI化、去AI味、润色、humanize、更自然

核心原则：
- 打破机械式逻辑连接词（首先/其次/总之/综上所述）
- 被动语态转主动语态
- 加入人性化细节、个人见解、场景化比喻
- 适度口语化冗余与限定词
- 替换 AI 高频词汇
- 直接输出润色后全文，不解释修改了哪里

### qq-summary（QQ 今日消息总结）

读取本机 QQNT 本地数据库，提取今日消息并生成按重要性高亮的总结。

触发词：总结QQ今日消息、QQ群聊总结、查看今日QQ消息、QQ日报

功能：
- 自动从运行中的 QQ 进程内存提取 SQLCipher 密钥（无注入、无 Hook）
- 解密本地数据库，读取今日所有群聊 + 私聊消息
- 按重要性排序：群聊通知 > 私人聊天 > 免打扰群聊
- 支持指定群/日期筛选

## 使用方法

```powershell
# QQ 今日消息总结（首次需管理员权限）
cd .opencode\skills\qq-summary\scripts
python qq_summary.py --qq <QQ号>

# 只总结指定群
python qq_summary.py --qq <QQ号> --group 群名关键词

# 总结历史某天
python qq_summary.py --qq <QQ号> --date 2026-08-18
```

## 安全说明

- `qq-summary` 会访问本地 QQ 数据库，解密密钥仅存在于进程内存
- 解密的数据库与密钥缓存（`output/`、`key_cache.json`）含个人隐私，**已排除在仓库之外**，仅存于本地
- 公开文档中不含任何真实群名/账号信息
- 群名匹配依赖本机 `group_info.db` 的备注字段，请勿将真实群名写入公开文档

## 环境要求

- Python 3.8+，`pip install cryptography`
- QQ 桌面版（NT 内核）正在运行
