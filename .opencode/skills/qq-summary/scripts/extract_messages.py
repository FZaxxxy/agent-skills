import sqlite3, sys, time, os, glob, argparse
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.expandvars(r'%USERPROFILE%\Documents\Tencent Files')

def parse_varint(buf, pos):
    result = 0; shift = 0
    while True:
        b = buf[pos]; result |= (b & 0x7F) << shift; pos += 1
        if not (b & 0x80): break
        shift += 7
    return result, pos

def parse_proto(buf):
    pos = 0; n = len(buf); out = []
    while pos < n:
        try: key, pos = parse_varint(buf, pos)
        except Exception: break
        field = key >> 3; wire = key & 7
        if wire == 0:
            val, pos = parse_varint(buf, pos); out.append((field, wire, val))
        elif wire == 1:
            if pos + 8 > n: break
            out.append((field, wire, buf[pos:pos+8])); pos += 8
        elif wire == 2:
            ln, pos = parse_varint(buf, pos)
            if pos + ln > n: break
            data = buf[pos:pos+ln]; pos += ln
            out.append((field, wire, data))
        elif wire == 5:
            if pos + 4 > n: break
            out.append((field, wire, buf[pos:pos+4])); pos += 4
        else: break
    return out

def decode_utf8(data):
    try:
        s = data.decode('utf-8')
        printable = sum(1 for c in s if c >= ' ' or c in '\r\n\t')
        if printable >= max(1, len(s)*0.7): return s
    except Exception: pass
    return None

def extract_msg_text(blob):
    if not blob: return ''
    texts = []
    def walk(buf, depth=0):
        if depth > 6 or not isinstance(buf, (bytes, bytearray)) or len(buf) == 0: return
        try: fields = parse_proto(buf)
        except Exception: return
        for f, w, v in fields:
            if w == 2 and isinstance(v, bytes):
                s = decode_utf8(v)
                if s is not None and s.strip():
                    s = s.strip()
                    if f == 45101 and len(s) < 500:
                        texts.append(s)
                    elif f == 45815 and s in ('[动画表情]', '[表情]'):
                        texts.append(s)
                    elif f == 45402 and len(s) < 200:
                        texts.append('[图片]')
                walk(v, depth + 1)
    walk(blob)
    seen = set(); out = []
    for t in texts:
        if t not in seen:
            seen.add(t); out.append(t)
    return ' '.join(out) if out else '[不可解析]'

def find_output_dir():
    env = os.environ.get('QQ_SUMMARY_OUTDIR')
    if env and os.path.isdir(env):
        return env
    pat = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', '*')
    dirs = [d for d in glob.glob(pat) if os.path.isdir(d)]
    if not dirs:
        print('ERROR: no decrypted output dir found. Run dump_qq_key_auto.py first.')
        sys.exit(1)
    return max(dirs, key=os.path.getmtime)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=time.strftime('%Y-%m-%d'), help='总结日期 YYYY-MM-DD')
    ap.add_argument('--group', default='', help='只总结群名/备注含该关键词的群')
    args = ap.parse_args()

    outdir = find_output_dir()
    print('using output dir:', outdir)
    today = args.date
    tomorrow = time.strftime('%Y-%m-%d', time.localtime(time.mktime(time.strptime(today, '%Y-%m-%d')) + 86400))
    today_start = int(time.mktime(time.strptime(today, '%Y-%m-%d')))
    tomorrow_start = int(time.mktime(time.strptime(tomorrow, '%Y-%m-%d')))

    ginfo = sqlite3.connect(os.path.join(outdir, 'group_info.db'))
    gcur = ginfo.cursor()
    gid2name = {}
    try:
        gcur.execute('SELECT "60001", "60007", "60026" FROM group_list')
        for g, n, note in gcur.fetchall():
            gid2name[str(g)] = note or n
    except Exception:
        pass
    ginfo.close()

    con = sqlite3.connect(os.path.join(outdir, 'nt_msg.db'))
    cur = con.cursor()
    out = []

    try:
        groups = cur.execute('SELECT "40027", COUNT(*), MAX("40050") FROM group_msg_table WHERE "40050" >= ? AND "40050" < ? GROUP BY "40027" ORDER BY "40050"',
                             (today_start, tomorrow_start)).fetchall()
    except Exception:
        groups = []
        try:
            cur.execute('SELECT "40027", "40050" FROM group_msg_table WHERE "40050" >= ? AND "40050" < ?', (today_start, tomorrow_start))
            agg = {}
            for gid, ts in cur:
                agg.setdefault(gid, []).append(ts)
            groups = [(g, len(v), max(v)) for g, v in agg.items()]
        except Exception as e:
            print('group query failed:', e)
            groups = []

    for (gid, cnt, mx) in groups:
        name = gid2name.get(str(gid), '?')
        if args.group and args.group not in name and args.group not in str(gid):
            continue
        out.append(f'##### 群 {gid} = {name} ({cnt}条)')
        cur2 = con.cursor()
        try:
            cur2.execute('SELECT "40050", "40090", "40800" FROM group_msg_table WHERE "40050" >= ? AND "40050" < ? AND "40027"=?',
                         (today_start, tomorrow_start, gid))
            rows = cur2.fetchall()
        except Exception:
            # fallback: rowid-based robust read
            rows = []
            try:
                cur2.execute('SELECT rowid FROM group_msg_table WHERE "40027"=? AND "40050" >= ? AND "40050" < ?',
                             (gid, today_start, tomorrow_start))
                for (rid,) in cur2.fetchall():
                    try:
                        cur2.execute('SELECT "40050", "40090", "40800" FROM group_msg_table WHERE rowid=?', (rid,))
                        r = cur2.fetchone()
                        if r: rows.append(r)
                    except Exception:
                        pass
            except Exception as e:
                out.append(f'  [查询失败: {e}]')
                out.append('')
                continue
        rows.sort(key=lambda r: r[0])
        for ts, nick, blob in rows:
            t = time.strftime('%H:%M', time.localtime(ts))
            txt = extract_msg_text(blob)
            out.append(f'  [{t}] {nick}: {txt}')
        out.append('')

    try:
        c2c_rows = cur.execute('SELECT "40021", "40020", "40090", "40050", "40800" FROM c2c_msg_table WHERE "40050" >= ? AND "40050" < ? ORDER BY "40050"',
                               (today_start, tomorrow_start)).fetchall()
    except Exception:
        c2c_rows = []
    if c2c_rows and not args.group:
        out.append('##### 私聊消息')
        for peer, sender, nick, ts, blob in c2c_rows:
            t = time.strftime('%H:%M', time.localtime(ts))
            txt = extract_msg_text(blob)
            out.append(f'  [{t}] 对方{peer} ({nick}): {txt}')
        out.append('')

    text = '\n'.join(out)
    outfile = f'messages_{today}.txt'
    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(text)
    print('written', len(out), 'lines ->', outfile)

if __name__ == '__main__':
    main()