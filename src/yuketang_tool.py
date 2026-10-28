"""
雨课堂题库提取 + 解密 + 批量提交 —— 完整可运行脚本

使用前提：
1. 已登录雨课堂（浏览器里能正常访问）
2. 已从浏览器导出 Cookie（重点是 csrftoken）
3. 已知 classroom_id / exercise_id / sku_id / leaf_id

依赖：仅标准库（无需 pip install）
"""

import base64
import json
import os
import re
import struct
import time
import html as HTML
import urllib.request


# ══════════════════════════════════════════════════════════════
#  配置区
# ══════════════════════════════════════════════════════════════

CFG = {
    "base_url":     "https://www.yuketang.cn",
    "classroom_id": 00000000,
    "uv_id":        0000,
    "platform_id":  3,
    "exercise_id":  0000000,
    "sku_id":       00000000,
    "leaf_id":      00000000,
}

# 从浏览器 document.cookie 复制整串过来
COOKIE = "uv_id=你的学校ID; csrftoken=你的CSRF令牌; xtbz=ykt"

# 系统字体（Windows 自带）
REF_FONTS = [
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
]

OUT_DIR = "output"


# ══════════════════════════════════════════════════════════════
#  TTF 字体解析
# ══════════════════════════════════════════════════════════════

def load_ttf(path, index=0):
    """加载 TTF 文件，返回 (data, tables)"""
    data = open(path, "rb").read()
    base = 0
    if data[:4] == b"ttcf":                       # TTC 字体集合
        n = struct.unpack(">I", data[8:12])[0]
        offs = struct.unpack(">%dI" % n, data[12:12 + 4 * n])
        base = offs[index]

    num_tables = struct.unpack(">H", data[base + 4:base + 6])[0]
    tables = {}
    off = base + 12
    for _ in range(num_tables):
        tag, chk, toff, tlen = struct.unpack(">4sIII", data[off:off + 16])
        off += 16
        tables[tag.decode("latin1")] = (toff, tlen)
    return data, tables


def parse_cmap(data, tables):
    """
    解析 cmap 表，返回 {codepoint: glyph_id}
    优先用 format 4（BMP 基本平面，足够覆盖汉字）
    """
    if "cmap" not in tables:
        return {}

    co = tables["cmap"][0]
    n_sub = struct.unpack(">H", data[co + 2:co + 4])[0]

    sub_off = None
    for i in range(n_sub):
        p = co + 4 + i * 8
        pid, eid, so = struct.unpack(">HHI", data[p:p + 8])
        fmt = struct.unpack(">H", data[co + so:co + so + 2])[0]
        if fmt == 4 and sub_off is None:
            sub_off = co + so

    if sub_off is None:
        return {}

    seg = struct.unpack(">H", data[sub_off + 6:sub_off + 8])[0] // 2
    p = sub_off + 14

    end   = struct.unpack(">%dH" % seg, data[p:p + seg * 2]); p += seg * 2
    p += 2                                                      # reservedPad
    start = struct.unpack(">%dH" % seg, data[p:p + seg * 2]); p += seg * 2
    delta = struct.unpack(">%dh" % seg, data[p:p + seg * 2]); p += seg * 2
    ro    = struct.unpack(">%dH" % seg, data[p:p + seg * 2]); p += seg * 2

    mapping = {}
    for i in range(seg):
        if start[i] == 0xFFFF:
            continue
        for c in range(start[i], end[i] + 1):
            if ro[i] == 0:
                g = (c + delta[i]) & 0xFFFF
            else:
                gi = p + i * 2 + ro[i] + (c - start[i]) * 2
                if gi + 2 > len(data):
                    continue
                g = struct.unpack(">H", data[gi:gi + 2])[0]
                if g:
                    g = (g + delta[i]) & 0xFFFF
            if g:
                mapping[c] = g
    return mapping


def glyph_signature(data, tables, gid):
    """
    计算字形指纹：(轮廓拓扑, 归一化坐标点集)
    这个指纹对字体渲染风格不敏感，只反映字形拓扑结构
    """
    if not all(k in tables for k in ("head", "loca", "glyf")):
        return None

    head_off = tables["head"][0]
    loca_off, loca_len = tables["loca"]
    glyf_off = tables["glyf"][0]

    fmt = struct.unpack(">h", data[head_off + 50:head_off + 52])[0]
    if fmt == 0:
        offs = [2 * x for x in
                struct.unpack(">%dH" % (loca_len // 2), data[loca_off:loca_off + loca_len])]
    else:
        offs = list(struct.unpack(">%dI" % (loca_len // 4),
                                  data[loca_off:loca_off + loca_len]))

    if gid + 1 >= len(offs):
        return None
    a, b = offs[gid], offs[gid + 1]
    if a == b:
        return None
    g = data[glyf_off + a: glyf_off + b]

    n_contours = struct.unpack(">h", g[0:2])[0]
    if n_contours <= 0:                 # 复合字形，跳过
        return None

    ends = struct.unpack(">%dH" % n_contours, g[10:10 + n_contours * 2])
    n_points = ends[-1] + 1

    p = 10 + n_contours * 2
    ins_len = struct.unpack(">H", g[p:p + 2])[0]
    p += 2 + ins_len

    # ---- 读 flags（有 repeat 压缩） ----
    flags = []
    while len(flags) < n_points:
        f = g[p]; p += 1
        flags.append(f)
        if f & 8:
            repeat = g[p]; p += 1
            flags.extend([f] * repeat)
    flags = flags[:n_points]

    # ---- 读坐标（增量编码，分短/长两种） ----
    xs, ys = [], []
    vx = vy = 0
    for f in flags:
        if f & 2:                                  # X 短向量
            d = g[p]; p += 1
            vx += d if f & 16 else -d
        elif not f & 16:                           # X 长向量
            vx += struct.unpack(">h", g[p:p + 2])[0]
            p += 2
        xs.append(vx)

        if f & 4:                                  # Y 短向量
            d = g[p]; p += 1
            vy += d if f & 32 else -d
        elif not f & 32:                           # Y 长向量
            vy += struct.unpack(">h", g[p:p + 2])[0]
            p += 2
        ys.append(vy)

    # ---- 归一化到 32x32 网格 ----
    x0, y0 = min(xs), min(ys)
    w = max(1, max(xs) - x0)
    h = max(1, max(ys) - y0)
    pts = sorted(((x - x0) * 32 // w, (y - y0) * 32 // h)
                 for x, y in zip(xs, ys))

    # ---- 轮廓拓扑：(每轮廓点数, 每轮廓 on-curve 点数) ----
    topo, s0 = [], 0
    for e in ends:
        on_curve = sum(1 for i in range(s0, e + 1) if flags[i] & 1)
        topo.append((e - s0 + 1, on_curve))
        s0 = e + 1
    topo.sort()

    return (tuple(topo), tuple(pts))


# ══════════════════════════════════════════════════════════════
#  构建参考索引 & 解密
# ══════════════════════════════════════════════════════════════

def build_char_pool():
    """GB2312 全部常用汉字，约 6763 个"""
    pool = set()
    for b1 in range(0xB0, 0xF8):
        for b2 in range(0xA1, 0xFF):
            try:
                pool.add(bytes([b1, b2]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return {c for c in pool if 0x4E00 <= ord(c) <= 0x9FFF}


def build_reference_index(font_paths, pool):
    """用系统字体建立 指纹 -> {汉字} 索引"""
    index = {}
    for path in font_paths:
        if not os.path.exists(path):
            print("  [跳过] 字体不存在:", path)
            continue
        try:
            data, tables = load_ttf(path)
            cm = parse_cmap(data, tables)
            cnt = 0
            for ch in pool:
                gid = cm.get(ord(ch))
                if gid is None:
                    continue
                sig = glyph_signature(data, tables, gid)
                if sig:
                    index.setdefault(sig, set()).add(ch)
                    cnt += 1
            print("  [OK] %-22s 收录 %d 字" % (os.path.basename(path), cnt))
        except Exception as e:
            print("  [失败] %s: %s" % (path, e))
    return index


def decrypt_font(font_path, ref_index):
    """解密加密字体，返回 {codepoint: 真实汉字}"""
    data, tables = load_ttf(font_path)
    cm = parse_cmap(data, tables)

    result, ambiguous, missing = {}, 0, 0
    for cp, gid in cm.items():
        sig = glyph_signature(data, tables, gid)
        cands = ref_index.get(sig) if sig else None
        if cands and len(cands) == 1:
            result[cp] = next(iter(cands))
        elif cands:
            ambiguous += 1
        else:
            missing += 1

    print("  加密字体码位: %d | 解出: %d | 歧义: %d | 未解: %d"
          % (len(cm), len(result), ambiguous, missing))
    return result


# ══════════════════════════════════════════════════════════════
#  HTTP 请求封装
# ══════════════════════════════════════════════════════════════

def build_headers(post=False):
    h = {
        "xtbz": "ykt",
        "university-id": str(CFG["uv_id"]),
        "platform-id": str(CFG["platform_id"]),
        "x-client": "web",
        "Accept": "application/json, text/plain, */*",
        "Cookie": COOKIE,
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/156.0.0.0 Safari/537.36"),
    }
    if post:
        h["Content-Type"] = "application/json"
        m = re.search(r"csrftoken=([^;]+)", COOKIE)
        if m:
            h["x-csrftoken"] = m.group(1)
    return h


def http_get(path):
    url = CFG["base_url"] + path
    req = urllib.request.Request(url, headers=build_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_json(path, payload):
    url = CFG["base_url"] + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=build_headers(post=True))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")), r.status


def download_bytes(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": build_headers()["User-Agent"],
        "Referer": CFG["base_url"] + "/",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# ══════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=" * 60)
    print(" 雨课堂题库提取工具")
    print("=" * 60)

    # ── 1. 验证登录 ──────────────────────────────
    print("\n[1/5] 验证登录状态...")
    try:
        me = http_get("/api/v3/user/basic-info")
    except Exception as e:
        print("  请求失败:", e)
        return
    if me.get("code") != 0:
        print("  未登录:", me.get("msg"))
        return
    print("  登录成功，用户:", me["data"].get("name"), "| ID:", me["data"].get("id"))

    # ── 2. 拿题目 + 字体 ─────────────────────────
    print("\n[2/5] 获取题目列表与字体...")
    ex_path = ("/mooc-api/v1/lms/exercise/get_exercise_list/"
               "%d/%d/?classroom_id=%d"
               % (CFG["exercise_id"], CFG["sku_id"], CFG["classroom_id"]))
    ex = http_get(ex_path)
    if not ex.get("success"):
        print("  取题失败:", ex.get("msg"))
        return

    font_url  = ex["data"]["font"]
    problems  = ex["data"]["problems"]
    print("  题目数量:", len(problems))
    print("  字体地址:", font_url.split("/")[-1])
    print("  练习名称:", ex["data"].get("name"))

    # ── 3. 下载并解密字体 ────────────────────────
    print("\n[3/5] 下载并解密字体...")
    font_bytes = download_bytes(font_url)
    font_path  = os.path.join(OUT_DIR, "exam_font.ttf")
    open(font_path, "wb").write(font_bytes)
    print("  字体大小:", len(font_bytes), "字节")

    print("  构建参考字体索引...")
    pool      = build_char_pool()
    ref_index = build_reference_index(REF_FONTS, pool)
    print("  指纹索引条目:", len(ref_index))

    print("  解密加密字体...")
    dec_map = decrypt_font(font_path, ref_index)
    json.dump({str(k): v for k, v in dec_map.items()},
              open(os.path.join(OUT_DIR, "decrypt_map.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    # ── 4. 还原题目文本 ──────────────────────────
    print("\n[4/5] 还原题目文本...")

    def decrypt_text(s):
        return "".join(dec_map.get(ord(c), c) for c in s)

    def clean(html_str):
        s = decrypt_text(html_str)
        s = re.sub(r"<br\s*/?>", "\n", s)
        s = re.sub(r"</p>", "\n", s)
        s = re.sub(r"<[^>]+>", "", s)
        s = HTML.unescape(s)
        return re.sub(r"\n{2,}", "\n", s).strip()

    out_items = []
    for p in problems:
        c = p["content"]
        out_items.append({
            "index":      p["index"],
            "problem_id": p["problem_id"],
            "type":       c.get("Type"),
            "type_text":  c.get("TypeText"),
            "problem_type": c.get("ProblemType"),
            "body":       clean(c.get("Body", "")),
            "options":    [{"key": o["key"], "value": clean(o["value"])}
                           for o in c.get("Options", [])],
        })

    json.dump(out_items,
              open(os.path.join(OUT_DIR, "questions.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 输出 Markdown
    lines = ["# %s" % ex["data"].get("name", "题库"), ""]
    for it in out_items:
        lines.append("## %d. %s" % (it["index"], it["body"]))
        lines.append("")
        for o in it["options"]:
            lines.append("- **%s.** %s" % (o["key"], o["value"]))
        lines.append("")
    open(os.path.join(OUT_DIR, "questions.md"), "w", encoding="utf-8") \
        .write("\n".join(lines))

    print("  已导出: %s/questions.json" % OUT_DIR)
    print("  已导出: %s/questions.md" % OUT_DIR)
    print("\n  第一题预览:")
    print("   ", out_items[0]["body"][:80])
    for o in out_items[0]["options"]:
        print("     %s. %s" % (o["key"], o["value"][:50]))

    # ── 5. 批量提交（需要你先准备好 answers） ─────
    print("\n[5/5] 批量提交")
    answers_file = os.path.join(OUT_DIR, "answers.json")
    if not os.path.exists(answers_file):
        print("  未找到 %s，跳过提交。" % answers_file)
        print("  请创建该文件，格式：")
        print('    {"1": "A", "2": "D", "3": "A", ...}')
        return

    answers = {int(k): v for k, v in
               json.load(open(answers_file, encoding="utf-8")).items()}

    answer_dict = {}
    for it in out_items:
        a = answers.get(it["index"])
        if a:
            answer_dict[str(it["problem_id"])] = {"answer": [a]}

    payload = {
        "leaf_id":      CFG["leaf_id"],
        "classroom_id": CFG["classroom_id"],
        "exercise_id":  CFG["exercise_id"],
        "answer_dict":  answer_dict,
    }

    print("  提交题数:", len(answer_dict))
    t0 = time.time()
    for attempt in range(1, 6):
        try:
            resp, status = http_post_json(
                "/mooc-api/v1/lms/exercise/problem_batch_apply/", payload)
        except Exception as e:
            print("  第%d次请求异常: %s" % (attempt, e))
            time.sleep(2)
            continue

        if status == 429:
            print("  第%d次被限速，等待 2 秒..." % attempt)
            time.sleep(2)
            continue

        elapsed = time.time() - t0
        ok, bad = 0, []
        for pid, v in (resp.get("data") or {}).items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("is_correct"):
                ok += 1
            else:
                bad.append(pid)

        print("  耗时: %.2f 秒" % elapsed)
        print("  成功: %d | 失败: %d" % (ok, len(bad)))
        if bad:
            print("  失败的 problem_id:", bad[:10])
        break

    # ── 查最终成绩 ──────────────────────────────
    print("\n[附] 最终成绩")
    j = http_get(ex_path)
    rows = []
    for p in j["data"]["problems"]:
        u = p.get("user") or {}
        rows.append({
            "index":   p["index"],
            "my":      (u.get("my_answer") or [None])[0],
            "isRight": u.get("is_right"),
            "score":   u.get("my_score"),
            "count":   u.get("my_count"),
        })
    right = sum(1 for x in rows if x["isRight"] is True)
    print("  共 %d 题 | 正确 %d | 错误/未答 %d"
          % (len(rows), right, len(rows) - right))
    for x in rows:
        if x["isRight"] is not True:
            print("    第%d题: 我的答案=%s 状态=%s" % (x["index"], x["my"], x["isRight"]))


if __name__ == "__main__":
    main()

