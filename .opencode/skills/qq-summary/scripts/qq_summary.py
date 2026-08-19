"""QQ 今日消息总结 - 合并入口
用法（在 skill 的 scripts 目录下运行）：
  python qq_summary.py --qq <QQ号>
    - 首次：自动提取密钥、解密全部库、读取今日消息
    - 之后：若有缓存密钥，直接复制加密库并快速重解密（无需管理员权限）
    - 再调用 extract_messages.py 输出今日消息
选项：
  --qq <QQ号>         QQ 号（必填，即 Documents/Tencent Files 下的账号目录名）
  --fresh            忽略密钥缓存，重新从 QQ 进程内存提取密钥
  --pid <PID>         手动指定 QQ 主进程 PID（自动检测失败时用）
  --outdir <目录>      解密输出目录（默认 scripts/output/<QQ号>）
  --group <群名关键词> 只总结匹配到的群（可选，默认全部群+私聊）
  --date <YYYY-MM-DD> 指定总结日期（默认今天）
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(SCRIPTS_DIR, 'output')
KEY_CACHE = os.path.join(SCRIPTS_DIR, 'key_cache.json')

REQUIRED_DBS = ('nt_msg.db', 'group_info.db')
# 解密 nt_msg.db 足够总结消息；group_info.db 用于群名/备注。其它库非必需。


def find_qq_number_from_dbdir():
    """从 Documents/Tencent Files 猜测可能的 QQ 号目录。"""
    base = os.path.expandvars(r'%USERPROFILE%\Documents\Tencent Files')
    cands = []
    for name in os.listdir(base):
        p = os.path.join(base, name, 'nt_qq', 'nt_db')
        if os.path.isdir(p):
            cands.append(name)
    return cands


def have_cache(qq):
    """判断密钥缓存是否命中且含此账号密钥。"""
    if not os.path.exists(KEY_CACHE):
        return False
    try:
        import json
        with open(KEY_CACHE, encoding='utf-8') as f:
            data = json.load(f)
        return bool(data.get('key_map'))
    except Exception:
        return False


def run_full_dump(qq, pid, outdir):
    """完整流程：内存扫密钥 + 解密全部库。需管理员权限。"""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, 'dump_qq_key_auto.py'),
           '--qq', qq, '--output', KEY_CACHE]
    if pid:
        cmd += ['--pid', str(pid)]
    print('>>> 完整解密（首次或 --fresh），需要管理员权限...')
    r = subprocess.run(cmd, cwd=SCRIPTS_DIR)
    if r.returncode != 0:
        print('ERROR: 密钥提取/解密失败。')
        sys.exit(r.returncode)
    # dump 脚本默认输出到 output/<qq>，确认它存在
    produced = os.path.join(DEFAULT_OUT, qq)
    if os.path.isdir(produced):
        return produced
    return outdir


def fast_redecrypt(qq, outdir):
    """用缓存密钥 + 从源复制加密库 + 快速解密。不需要管理员权限。"""
    import json
    with open(KEY_CACHE, encoding='utf-8') as f:
        data = json.load(f)
    key_map = data.get('key_map', {})
    if not key_map:
        print('ERROR: key_cache.json 为空，请先完整解密一次。')
        sys.exit(1)

    src_db = os.path.join(os.path.expandvars(r'%USERPROFILE%\Documents\Tencent Files'),
                          qq, 'nt_qq', 'nt_db')
    if not os.path.isdir(src_db):
        print(f'ERROR: 源数据库目录不存在: {src_db}')
        sys.exit(1)

    # 找到对应 nt_msg.db 和 group_info.db 的密钥（按 salt 匹配）
    sys.path.insert(0, SCRIPTS_DIR)
    from dump_qq_key_auto import (collect_db_info, find_db_dirs, verify_key_hmac,
                                  derive_enc_key, decrypt_db, PRE_LOGIN_KEY)

    db_dirs = find_db_dirs(qq)
    global_dbs, pa_map = collect_db_info(db_dirs)

    # 组装密钥: salt hex -> enc key hex
    salt2key = {}
    for salt, kh in key_map.items():
        salt2key[salt] = kh

    os.makedirs(outdir, exist_ok=True)
    ok = 0
    for fn in REQUIRED_DBS:
        src = os.path.join(src_db, fn)
        if not os.path.exists(src):
            print(f'  SKIP {fn}: 源不存在')
            continue
        # 找该文件的 salt
        with open(src, 'rb') as f:
            hdr = f.read(1024 + 4096)
        page1 = hdr[1024:1024 + 4096]
        salt_hex = page1[:16].hex()
        kh = salt2key.get(salt_hex)
        if not kh:
            # 尝试全局固定密钥
            enc = derive_enc_key(PRE_LOGIN_KEY, page1[:16])
            if verify_key_hmac(page1, enc):
                kh = enc.hex()
        if not kh:
            print(f'  FAIL {fn}: 无匹配密钥')
            continue
        dst = os.path.join(outdir, fn)
        if decrypt_db(src, dst, bytes.fromhex(kh)):
            sz = os.path.getsize(dst) / 1048576
            print(f'  OK {fn} ({sz:.0f} MB)')
            ok += 1
        else:
            print(f'  FAIL {fn}: 解密校验失败')
    return outdir if ok > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qq', help='QQ 号（缺省自动探测）')
    ap.add_argument('--fresh', action='store_true', help='强制重新从内存提取密钥')
    ap.add_argument('--pid', type=int, default=0)
    ap.add_argument('--outdir', default=DEFAULT_OUT)
    ap.add_argument('--group', default='', help='只总结匹配该关键词的群')
    ap.add_argument('--date', default=time.strftime('%Y-%m-%d'), help='总结日期')
    args = ap.parse_args()

    qq = args.qq
    if not qq:
        cands = find_qq_number_from_dbdir()
        if not cands:
            print('ERROR: 未找到 QQ 账号目录，请用 --qq 指定。')
            sys.exit(1)
        if len(cands) == 1:
            qq = cands[0]
            print('自动检测 QQ 号:', qq)
        else:
            print('发现多个 QQ 账号:', cands, '请用 --qq 指定。')
            sys.exit(1)

    outdir = os.path.join(args.outdir, qq)
    cached = have_cache(qq)

    if args.fresh or not cached:
        outdir = run_full_dump(qq, args.pid, outdir)
    else:
        print('>>> 使用缓存密钥快速重解密...')
        outdir = fast_redecrypt(qq, outdir)
        if not outdir:
            print('快速解密失败，回退完整流程。')
            outdir = run_full_dump(qq, args.pid, outdir)

    # 提取今日消息
    print('>>> 提取今日消息...')
    env = os.environ.copy()
    env['QQ_SUMMARY_OUTDIR'] = outdir
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, 'extract_messages.py'),
           '--date', args.date]
    if args.group:
        cmd += ['--group', args.group]
    r = subprocess.run(cmd, cwd=SCRIPTS_DIR, env=env)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()