---
name: qq-summary
description: Use when the user asks to summarize QQ messages for today (总结QQ今日消息、QQ群聊总结、查看今日QQ消息、QQ日报), or to check messages from a specific QQ group/chat (兰妈学子散作满天星等). Automatically extracts the QQNT SQLCipher key from the running QQ process, decrypts the local databases, reads today's messages, and produces a importance-ranked summary with highlights.
---

# QQ 今日消息总结

读取本机 QQNT（新版QQ）本地数据库，提取今日消息并生成按重要性高亮的总结。

## 前置条件

- QQ 正在运行（主进程 `QQ.exe`，需加载 `wrapper.node`）
- 本机 Python 3.8+，已安装 `cryptography` 库（`pip install cryptography`）
- 需要管理员权限执行密钥提取脚本（`OpenProcess` 读取进程内存）

## QQ 数据位置

```
C:\Users\<用户>\Documents\Tencent Files\<QQ号>\nt_qq\nt_db\
```

- `nt_msg.db` — 主聊天库（含 `group_msg_table` 群消息、`c2c_msg_table` 私聊）
- `group_info.db` — 群列表（`group_list` 表：`60001`=群号、`60007`=群名、`60026`=群备注）
- `group_msg_fts.db` — 群消息搜索库（部分列可能损坏，作为备选）
- 数据库均为 SQLCipher 加密（文件头 `SQLite header 3`）

## 一键入口（推荐）

用 `scripts/qq_summary.py` 全自动完成：密钥提取 → 解密 → 读取今日消息。

```powershell
cd .opencode\skills\qq-summary\scripts

# 首次（需管理员权限，会自动弹 UAC 确认）
python qq_summary.py --qq <QQ号>

# 之后（有密钥缓存，免管理员权限，快速重解密）
python qq_summary.py --qq <QQ号>

# 只总结指定群
python qq_summary.py --qq <QQ号> --group 兰妈

# 总结历史某天
python qq_summary.py --qq <QQ号> --date 2026-08-18
```

密钥缓存机制：
- 首次运行把密钥存入 `scripts/key_cache.json`，并解密全部库
- 之后运行检测到缓存，走 `fast_redecrypt`：只复制加密源库中的 `nt_msg.db` + `group_info.db`，用缓存密钥重解密，无需管理员权限
- `--fresh` 强制重新从 QQ 内存提取密钥（QQ 升级后密钥机制变化时用）
- QQ 号可自动探测（`Documents\Tencent Files` 下唯一账号目录）

## 手动流程（备选）

### 步骤 1：提取密钥并解密

使用 `scripts/dump_qq_key_auto.py`（来自 NapNeko/qq_dump_db，MIT 协议，无注入无 Hook，纯外部内存读取）：

```powershell
# 需管理员权限
python "scripts\dump_qq_key_auto.py" --qq <QQ号> --output key_map.json
```

- 自动从运行中的 QQ 主进程内存扫描 `x'<64hex_key><32hex_salt>'` 模式
- 交叉验证 HMAC 后解密所有数据库到 `output\<QQ号>\`
- 若自动找进程失败，先确认主进程 PID：`Get-CimInstance Win32_Process -Filter "Name='QQ.exe'"`（选无参数的那个），再用 `--pid <PID>`
- 数据库被 QQ 锁定无妨，脚本用外部读取，无需关闭 QQ

### 步骤 2：读取今日消息

用 `scripts/extract_messages.py` 提取今日所有群 + 私聊消息（默认 UTC 当天 0-24 点）：

```powershell
python "scripts\extract_messages.py"
```

该脚本：
- 从 `nt_msg.db` 的 `group_msg_table`（群）和 `c2c_msg_table`（私聊）读取
- 按时间戳 `40050`（unix 秒）过滤当日
- 递归解析 protobuf 消息 blob（`40800`），提取文本（`field 45101`）、图片、表情
- 输出 `messages_<日期>.txt`（UTF-8）

**若某群查询报 `database disk image is malformed`**：
- 原因：nt_msg.db 个别页损坏，`ORDER BY` 触发坏索引
- 解决：用 `rowid` 先取目标范围，再逐行 `WHERE rowid=?` 读取（参考 `extract_lanma.py` 思路）
- 群备注名匹配：目标群可能显示为备注名，用 `group_info.db` 的 `group_list` 表 `60026`（群备注）字段匹配（如"兰妈学子散作满天星"= 群993401337）

## 步骤 3：重要性排序与高亮

按以下优先级整理（对应 QQ 的消息接收设置）：

1. **群聊通知**（允许通知的群）—— @全体成员、@我、管理员公告、新群员/退群通知
2. **私人聊天**（c2c）—— 私聊内容，尤其是问询、待办、约定
3. **免打扰群聊** —— 被设为免打扰的群，仅提取要点

高亮规则：
- **🔴 最重要**：@全体/@我、通知公告、待办事项、紧急问题、含链接/文件的实操信息
- **🟡 次重要**：多人群聊讨论主题、咨询回复、日程相关
- **🔵 一般**：闲聊、刷屏玩梗、表情包、广告/拼单/引流

## 步骤 4：输出格式

```
## 📋 QQ 今日消息总结（日期）

### 🔴 [群名/私聊对象]（重点）
- 消息要点（保留关键信息、时间、发言人昵称）

### 🟡 其他消息
- 群名：主题概述（n条）

### 🔵 闲聊/低优先级
- ...

按重要程度排列，先说重点，再说次要。
```

## 缓存说明

- `scripts/output/<QQ号>/` — 解密的数据库快照，磁盘占用约 700MB（`nt_msg.db` 509MB 为主），**固定值不递增**，无自动清理
- `scripts/key_cache.json` — 账号固定的 SQLCipher 密钥缓存（几 KB）
- 每次运行 `qq_summary.py` 会用新源库**覆盖** output 下的库文件（非追加）
- 想省磁盘：手动删除 `output/<QQ号>/` 下除 `nt_msg.db`、`group_info.db` 外的文件，可省约 180MB；重跑 `--fresh` 会重新解密全部

## 群名备注说明

QQNT 支持给群设置备注名，`group_list` 表 `60026` 存备注。用户常以备注名指代群：
- 例：群 993401337 `60007`=萃英山纯良v友会，`60026`=兰妈学子散作满天星
- 匹配目标群时**同时搜 `60007` 和 `60026`**

## 关键字段速查

`group_msg_table` / `c2c_msg_table`：
- `40027` — 群号（c2c 表里为对方 uid）
- `40020` — 发送者 uid
- `40090` — 发送者昵称
- `40050` — 时间戳（unix 秒）
- `40800` — 消息内容 blob（protobuf）
- `40021` — c2c 表中对方 uid

protobuf 消息 blob 解析要点：
- `field 45101` — 纯文本消息内容
- `field 45402` — 图片文件名 → 标记 [图片]
- `field 45815` — 表情 → 标记 [动画表情]/[表情]
- `field 48214` / `48271` — 系统消息（红包、撤回等），可提取说明文字