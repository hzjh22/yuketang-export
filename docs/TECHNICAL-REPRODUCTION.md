# 雨课堂题库提取 + 批量提交 完整复现文档

> 目标站点：`https://www.yuketang.cn`
> 演示课堂：`classroom_id={CLASSROOM_ID}`（{课程名称}，100 题）
> 文档目的：从零复现"获取题目 → 解密字体 → 批量提交答案"的全过程
> 适用环境：Windows / Chrome / 已登录的雨课堂账号

---

## 目录

1. [整体流程图](#一整体流程图)
2. [前置准备](#二前置准备)
3. [第一步：拿到关键 ID](#第一步拿到关键-id)
4. [第二步：获取题目列表](#第二步获取题目列表)
5. [第三步：破解字体加密](#第三步破解字体加密)
6. [第四步：批量提交答案](#第四步批量提交答案)
7. [第五步：验证结果](#第五步验证结果)
8. [限速机制详解](#六限速机制详解)
9. [完整可运行脚本](#七完整可运行脚本)
10. [踩坑记录](#八踩坑记录必读)
11. [参数速查表](#九参数速查表)

---

## 一、整体流程图

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 浏览器登录雨课堂（扫码 / 密码）                            │
│    └─> 拿到 session cookie + csrftoken                       │
└────────────────────────┬────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 打开目标练习页，抓包定位 3 个关键 ID                        │
│    classroom_id / sku_id / leaf_id                           │
│    └─> 调 chapter 接口拿 exercise_id                          │
└────────────────────────┬────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 调 get_exercise_list 拿题目 + font URL（同一响应）          │
│    ⚠ 关键：题目和字体必须在同一次响应里，否则对不上             │
└────────────────────────┬────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 下载 TTF 字体 → 解析 cmap → 提取字形轮廓签名               │
│    与系统字体比对 → 还原真实汉字                              │
└────────────────────────┬────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 调 problem_batch_apply 一次性提交全部答案                  │
│    ⚠ 关键：answer_dict[pid] = {answer:["A"]} 是对象包数组      │
└────────────────────────┬────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. 回包判分：data[pid][0].is_correct                         │
│    答错的用排除法重提（练习 max_retry=-1 可重试）              │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、前置准备

### 2.1 环境要求

| 项目 | 要求 |
|---|---|
| 浏览器 | Chrome / Edge（需支持 DevTools） |
| 账号 | 已加入目标课堂的雨课堂账号（学生 / 教师均可） |
| 网络 | 能访问 `www.yuketang.cn` |
| 工具 | 浏览器 DevTools（F12）；可选 Python 3 + 字体解析库 |

### 2.2 登录

**方式 A：扫码登录（推荐，无需密码）**

1. 打开 `https://www.yuketang.cn/web`
2. 页面会自动调 `/api/v3/user/login/app-web-pre-info` 返回二维码内容
3. 用手机雨课堂 APP 或微信扫码确认
4. 登录成功后页面自动跳转

**方式 B：密码登录**

- 接口：`POST /pc/login/verify_pwd_login/`
- 密码需 RSA-1024 公钥加密（公钥从 `/pc/register/get_pws_public_key/` 取）
- 还要腾讯验证码 ticket + hCaptcha token，自动化难度高

### 2.3 验证登录成功

在 DevTools Console 执行：

```js
fetch('/api/v3/user/basic-info', {credentials:'include'})
  .then(r=>r.json()).then(console.log)
```

期望返回：

```json
{"code":0,"msg":"OK","data":{"id":"{USER_ID}","name":"...","role":0,...}}
```

如果返回 `{"code":50000,"msg":"UNAUTHENTICATED"}` 说明没登录。

### 2.4 确认必需的 Cookie

登录后 `document.cookie` 应包含：

```
uv_id={UV_ID}                      ← 学校 ID
university_id={UV_ID}
platform_id=3
classroom_id={CLASSROOM_ID}
csrftoken={CSRFTOKEN}   ← POST 请求必需
xtbz=ykt
```

> **最重要**：`csrftoken`。所有 POST 请求必须把它放进 `x-csrftoken` 请求头，否则返回 `403 CSRF Failed`。

---

## 三、第一步：拿到关键 ID

### 3.1 需要哪几个 ID

| ID | 含义 | 本例取值 | 从哪来 |
|---|---|---|---|
| `classroom_id` | 课堂 ID | {CLASSROOM_ID} | 页面 URL |
| `uv_id` / `university_id` | 学校 ID | {UV_ID} | 页面 URL |
| `sku_id` | 服务等级 ID | {SKU_ID} | `sku_list` 接口 |
| `leaf_id` | 章节叶子节点 ID | {LEAF_ID} | chapter 接口 |
| `exercise_id` | 练习 ID | {EXERCISE_ID} | leaf_info 接口 |

### 3.2 取 classroom_id 和 uv_id

直接看页面 URL：

```
https://www.yuketang.cn/v2/web/studentLog/{CLASSROOM_ID}?university_id={UV_ID}&platform_id=3&classroom_id={CLASSROOM_ID}&...
                                 ↑ classroom_id                              ↑ uv_id
```

### 3.3 取 sku_id

```js
fetch('/c27/online_courseware/course/classroom/{CLASSROOM_ID}/0/sku_list/?term=latest&uv_id={UV_ID}&classroom_id={CLASSROOM_ID}', {
  credentials:'include',
  headers:{'xtbz':'ykt','university-id':'{UV_ID}','platform-id':'3','x-client':'web'}
}).then(r=>r.json()).then(d=>console.log(d.data.data_list))
```

返回里找 `sku_id`：

```json
{"count":1,"data_list":[{"sku_id":{SKU_ID},"name":"免费","price":0,...}]}
```

### 3.4 取 leaf_id 和 exercise_id

```js
fetch('/mooc-api/v1/lms/learn/course/chapter?cid={CLASSROOM_ID}&sign={SCHOOL_SIGN}&term=latest&uv_id={UV_ID}&classroom_id={CLASSROOM_ID}', {
  credentials:'include',
  headers:{'xtbz':'ykt','university-id':'{UV_ID}','platform-id':'3','x-client':'web'}
}).then(r=>r.json()).then(console.log)
```

返回结构：

```json
{
  "data": {
    "course_chapter": [{
      "section_leaf_list": [{
        "id": {LEAF_ID},          ← 这就是 leaf_id
        "leafinfo_id": {LEAFINFO_ID},
        "name": "{课程名称}",
        "leaf_type": 6
      }]
    }]
  }
}
```

`exercise_id` 需要再调一次 leaf_info：

```js
fetch('/mooc-api/v1/lms/learn/leaf_info/{CLASSROOM_ID}/{LEAF_ID}/?classroom_id={CLASSROOM_ID}', {
  credentials:'include',
  headers:{'xtbz':'ykt','university-id':'{UV_ID}','platform-id':'3','x-client':'web'}
}).then(r=>r.json()).then(console.log)
```

从返回里找 `content_info.leaf_type_id`，即为 `exercise_id = {EXERCISE_ID}`。

> **懒人做法**：直接在页面上点开练习，DevTools → Network 里搜 `get_exercise_list`，URL 里的两个数字就是 `exercise_id` 和 `sku_id`。

---

## 四、第二步：获取题目列表

### 4.1 核心接口

```
GET /mooc-api/v1/lms/exercise/get_exercise_list/{exercise_id}/{sku_id}/?classroom_id={classroom_id}
```

完整示例：

```
GET https://www.yuketang.cn/mooc-api/v1/lms/exercise/get_exercise_list/{EXERCISE_ID}/{SKU_ID}/?classroom_id={CLASSROOM_ID}
```

### 4.2 必需请求头

| Header | 值 | 说明 |
|---|---|---|
| `xtbz` | `ykt` | **必需**，缺了报 `XTBZ IS REQUIRED` |
| `university-id` | `{UV_ID}` | 学校 ID |
| `platform-id` | `3` | 平台标识 |
| `x-client` | `web` | 客户端标识 |
| `Accept` | `application/json, text/plain, */*` | — |

### 4.3 一次请求同时拿题目和字体

```js
async function fetchExercise() {
  const H = {
    'xtbz':'ykt', 'university-id':'{UV_ID}', 'platform-id':'3',
    'x-client':'web', 'Accept':'application/json, text/plain, */*'
  };
  const url = '/mooc-api/v1/lms/exercise/get_exercise_list/{EXERCISE_ID}/{SKU_ID}/?classroom_id={CLASSROOM_ID}';
  const r = await fetch(url, {credentials:'include', headers:H});
  const j = await r.json();

  return {
    fontUrl: j.data.font,        // ← 字体 URL，每次请求都会变！
    problems: j.data.problems    // ← 100 道题
  };
}
```

### 4.4 返回结构关键字段

```json
{
  "success": true,
  "data": {
    "exercise_id": {EXERCISE_ID},
    "name": "{课程名称}",
    "max_retry": -1,          ← 练习级别：-1 表示不限次
    "font": "https://fe-static-yuketang.yuketang.cn/fe_font/product/exam_font_xxx.ttf",
    "problems": [
      {
        "index": 1,                        ← 题号（1..100）
        "problem_id": {PROBLEM_ID_START},            ← 提交时用这个，不是 index！
        "max_retry": 1,                    ← 单题限制（实测可重试）
        "content": {
          "Type": "SingleChoice",
          "ProblemType": 1,                ← 1=单选 2=多选 3=投票 4=填空 5=主观 6=判断
          "TypeText": "单选题",
          "Body": "<p><span class=\"xuetangx-com-encrypted-font\">带曲零少仿</span>醒...</p>",
          "Options": [
            {"key":"A","value":"<p>①②③④</p>"},
            {"key":"B","value":"<p>②</p>"}
          ]
        },
        "user": {
          "my_count": 0,                   ← 已提交次数
          "my_answer": null,
          "is_right": null
        }
      }
    ]
  }
}
```

### 4.5 两个必须注意的坑

**坑 1：`font` URL 每次都变**

```
第一次请求: exam_font_71fcafe41b694a9985b6d3b8717e8bce.ttf
第二次请求: exam_font_0675f0d4cf834385883a73e99b4ce3ed.ttf
第三次请求: exam_font_90fd3dccda9f4416b105ac4cde467cac.ttf
```

**题目文本和字体是配对的**。如果你用第 1 次的题目配第 3 次的字体去解密，结果全是乱的。

> ✅ 正确做法：**在同一次 fetch 的 `.then()` 里立刻下载字体**，或者干脆在浏览器里一次性完成（见第四节脚本）。

**坑 2：`problem_id` ≠ `index`**

- `index`：1..100，用于显示和排序
- `problem_id`：{PROBLEM_ID_START}..{PROBLEM_ID_END}，**提交时必须用这个**

---

## 五、第三步：破解字体加密

### 5.1 加密原理

题目文本里被加密的汉字都包在：

```html
<span class="xuetangx-com-encrypted-font">带曲零少仿</span>
```

配合页面加载的自定义 TTF 字体，浏览器把 `带曲零少仿` 渲染成真实汉字。

**关键理解**：字体不是随机乱码字体，而是**标准字体（Source Han Sans SC VF）的 cmap 被打乱了**：

- 字形轮廓完全正常（与思源黑体一致）
- 但"哪个 Unicode 码位对应哪个字形"（cmap 表）被随机置换

所以 `带`（U+5E26）在这个字体里显示的是别的字。

### 5.2 破解思路

```
① 解析 TTF 的 cmap 表 → 得到 { 码位 → 字形ID(gid) }
② 解析 glyf/loca 表 → 得到每个 gid 的字形轮廓
③ 对字形轮廓算"指纹"（轮廓数 + 每轮廓点数 + 归一化坐标网格）
④ 用系统字体（思源黑体等）对 GB2312 全部汉字算同样指纹，建索引
⑤ 用④的索引反查③的指纹 → 还原出真实汉字
```

### 5.3 TTF 结构速查

需要的 4 个表：

| 表名 | 作用 |
|---|---|
| `cmap` | 码位 → 字形 ID 映射（format 4 是常见格式） |
| `loca` | 字形 ID → 在 glyf 表中的偏移 |
| `glyf` | 实际字形轮廓数据 |
| `head` | 含 `indexToLocFormat`，决定 loca 用 2 字节还是 4 字节 |

### 5.4 为什么用"轮廓指纹"而不是"像素比对"

实测过像素比对，准确率只有 **25%**（20/80），完全不可用。原因：字体设计风格不同，同样一个字在不同字体里像素差异大。

**轮廓指纹**的准确率实测 **100/100**，因为：
- 轮廓数（有几个闭合路径）
- 每个轮廓的点数
- 归一化后的坐标网格

这三个特征对字体渲染风格不敏感，只反映字形拓扑结构。

### 5.5 核心代码（Python）

```python
import struct, json, os

def load_ttf(path):
    """加载 TTF，返回 (data, tables)"""
    data = open(path, "rb").read()
    numTables = struct.unpack(">H", data[4:6])[0]
    tables = {}
    off = 12
    for _ in range(numTables):
        tag, chk, toff, tlen = struct.unpack(">4sIII", data[off:off+16])
        off += 16
        tables[tag.decode("latin1")] = (toff, tlen)
    return data, tables

def parse_cmap_format4(data, tables):
    """解析 cmap format 4，返回 {codepoint: gid}"""
    co = tables["cmap"][0]
    ns = struct.unpack(">H", data[co+2:co+4])[0]
    sub = None
    for i in range(ns):
        p = co + 4 + i*8
        pid, eid, so = struct.unpack(">HHI", data[p:p+8])
        fmt = struct.unpack(">H", data[co+so:co+so+2])[0]
        if fmt == 4 and sub is None:
            sub = co + so
    if sub is None:
        return {}
    seg = struct.unpack(">H", data[sub+6:sub+8])[0] // 2
    p = sub + 14
    end   = struct.unpack(">%dH" % seg, data[p:p+seg*2]); p += seg*2; p += 2
    start = struct.unpack(">%dH" % seg, data[p:p+seg*2]); p += seg*2
    delta = struct.unpack(">%dh" % seg, data[p:p+seg*2]); p += seg*2
    ro    = struct.unpack(">%dH" % seg, data[p:p+seg*2]); p += seg*2

    m = {}
    for i in range(seg):
        if start[i] == 0xFFFF:
            continue
        for c in range(start[i], end[i]+1):
            if ro[i] == 0:
                g = (c + delta[i]) & 0xFFFF
            else:
                gi = p + i*2 + ro[i] + (c - start[i])*2
                if gi + 2 > len(data):
                    continue
                g = struct.unpack(">H", data[gi:gi+2])[0]
                if g:
                    g = (g + delta[i]) & 0xFFFF
            if g:
                m[c] = g
    return m

def glyph_signature(data, tables, gid):
    """算字形指纹：(轮廓拓扑, 归一化坐标点集)"""
    ho = tables["head"][0]
    lo, ll = tables["loca"]
    go = tables["glyf"][0]
    fmt = struct.unpack(">h", data[ho+50:ho+52])[0]
    if fmt == 0:
        offs = [2*x for x in struct.unpack(">%dH" % (ll//2), data[lo:lo+ll])]
    else:
        offs = list(struct.unpack(">%dI" % (ll//4), data[lo:lo+ll]))

    if gid + 1 >= len(offs):
        return None
    a, b = offs[gid], offs[gid+1]
    if a == b:
        return None
    g = data[go+a : go+b]

    nc = struct.unpack(">h", g[0:2])[0]
    if nc <= 0:                 # 复合字形，跳过
        return None
    ends = struct.unpack(">%dH" % nc, g[10:10+nc*2])
    npts = ends[-1] + 1
    p = 10 + nc*2
    il = struct.unpack(">H", g[p:p+2])[0]
    p += 2 + il

    # 读 flags（含 repeat 压缩）
    fl = []
    while len(fl) < npts:
        f = g[p]; p += 1; fl.append(f)
        if f & 8:
            r = g[p]; p += 1
            fl.extend([f]*r)
    fl = fl[:npts]

    # 读坐标（相对增量，分短/长两种编码）
    xs, ys = [], []
    vx = vy = 0
    for f in fl:
        if f & 2:
            d = g[p]; p += 1; vx += d if f & 16 else -d
        elif not f & 16:
            vx += struct.unpack(">h", g[p:p+2])[0]; p += 2
        xs.append(vx)

        if f & 4:
            d = g[p]; p += 1; vy += d if f & 32 else -d
        elif not f & 32:
            vy += struct.unpack(">h", g[p:p+2])[0]; p += 2
        ys.append(vy)

    # 归一化到 32x32 网格
    x0, y0 = min(xs), min(ys)
    w = max(1, max(xs) - x0)
    h = max(1, max(ys) - y0)
    pts = sorted(((x-x0)*32//w, (y-y0)*32//h) for x, y in zip(xs, ys))

    # 轮廓拓扑：(每轮廓点数, 每轮廓 on-curve 点数)
    topo, s0 = [], 0
    for e in ends:
        onc = sum(1 for i in range(s0, e+1) if fl[i] & 1)
        topo.append((e - s0 + 1, onc))
        s0 = e + 1
    topo.sort()

    return (tuple(topo), tuple(pts))


def build_reference_index(font_paths, pool_chars):
    """用系统字体建立 指纹 -> 汉字 的索引"""
    index = {}
    for path in font_paths:
        if not os.path.exists(path):
            continue
        data, tables = load_ttf(path)
        cm = parse_cmap_format4(data, tables)
        for ch in pool_chars:
            gid = cm.get(ord(ch))
            if gid is None:
                continue
            sig = glyph_signature(data, tables, gid)
            if sig:
                index.setdefault(sig, set()).add(ch)
    return index


def decrypt_font(font_path, reference_index):
    """解密一份加密字体，返回 {码位: 真实汉字}"""
    data, tables = load_ttf(font_path)
    cm = parse_cmap_format4(data, tables)
    result = {}
    for cp, gid in cm.items():
        sig = glyph_signature(data, tables, gid)
        cands = reference_index.get(sig) if sig else None
        if cands and len(cands) == 1:
            result[cp] = next(iter(cands))
    return result
```

### 5.6 汉字候选池

```python
pool = set()
for b1 in range(0xB0, 0xF8):
    for b2 in range(0xA1, 0xFF):
        try:
            pool.add(bytes([b1, b2]).decode("gb2312"))
        except:
            pass
pool = {c for c in pool if 0x4E00 <= ord(c) <= 0x9FFF}   # 6763 个常用汉字
```

### 5.7 参考字体（Windows 自带，无需下载）

```python
REF_FONTS = [
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",     # 思源黑体（与加密字体同源，最准）
    r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
    r"C:\Windows\Fonts\Deng.ttf",              # 等线
    r"C:\Windows\Fonts\msyh.ttc",              # 微软雅黑
    r"C:\Windows\Fonts\simsun.ttc",            # 宋体
]
```

> 加密字体自报名称是 `Source Han Sans SC VF`，与系统里的 `NotoSansSC-VF.ttf` 是同一字体家族，因此轮廓完全一致。

### 5.8 实际解密效果

- 加密字体共 **838** 个码位
- 成功解出 **677 – 879**（不同随机化版本略有差异）
- 题目文本覆盖率 **99.4%**
- 未解出的主要是极生僻字，不影响阅读

---

## 六、第四步：批量提交答案

### 6.1 核心接口

```
POST /mooc-api/v1/lms/exercise/problem_batch_apply/
Content-Type: application/json
```

### 6.2 必需的三个 ID + answer_dict

请求体：

```json
{
  "leaf_id": {LEAF_ID},
  "classroom_id": {CLASSROOM_ID},
  "exercise_id": {EXERCISE_ID},
  "answer_dict": {
    "{PROBLEM_ID_START}": {"answer": ["A"]},
    "81007492": {"answer": ["D"]},
    "81007493": {"answer": ["A"]}
  }
}
```

> ⚠️ **最容易踩的坑**：`answer_dict` 的值是 **对象 `{answer:["A"]}`**，不是裸数组 `["A"]`。
> 传裸数组会返回 `{"msg":"apply content error","error_code":500500}`。

### 6.3 这个结构怎么找到的

在打包代码 `pc.9a871ecb.js` 里搜 `answer_dict`，找到 `ProblemBatchSubmitGuard` 组件：

```js
// 原代码
let n = {...o.submitParams, answer_dict: {}};
e.forEach(e => {
  n.answer_dict[e.problem_id] = (0, Le.Xj)(e);
});

// Xj 对应 function k(e)
function k(e) {
  let n = Number(e?.content?.ProblemType), r = {};
  if (n === s.xz.blanks)  r.answers = {...};                    // 填空题
  if ([s.xz.single, s.xz.judge].includes(n))                    // 单选/判断
      r.answer = [String(e?._answer ?? "")];
  if (n === s.xz.subjective) r.answer = {...};                  // 主观题
  if ([s.xz.multi, s.xz.vote].includes(n)) r.answer = e._answer; // 多选/投票
  return r;
}
```

由此可见 `answer_dict[pid]` 的值恒为**对象**，单选题型下形如 `{answer: ["A"]}`。

### 6.4 完整请求头

| Header | 值 | 说明 |
|---|---|---|
| `Content-Type` | `application/json` | 必需 |
| `x-csrftoken` | cookie 里的 csrftoken | **必需**，否则 403 |
| `xtbz` | `ykt` | 必需 |
| `university-id` | `{UV_ID}` | — |
| `platform-id` | `3` | — |
| `x-client` | `web` | — |
| `Referer` | `https://www.yuketang.cn/v2/web/iframe-exercise/{CLASSROOM_ID}/{LEAF_ID}` | 建议带上 |

### 6.5 提交（浏览器内一键跑完）

```js
async function submitAll(answers) {
  // answers 形如 {"1":"A","2":"D",...}
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
  const H = {
    'xtbz':'ykt','university-id':'{UV_ID}','platform-id':'3','x-client':'web',
    'Accept':'application/json, text/plain, */*','Content-Type':'application/json',
    'x-csrftoken':csrf,
    'Referer':'https://www.yuketang.cn/v2/web/iframe-exercise/{CLASSROOM_ID}/{LEAF_ID}'
  };

  // 1) 拿题目（含 problem_id）
  const r0 = await fetch(
    '/mooc-api/v1/lms/exercise/get_exercise_list/{EXERCISE_ID}/{SKU_ID}/?classroom_id={CLASSROOM_ID}',
    {credentials:'include', headers:{'xtbz':'ykt','university-id':'{UV_ID}',
     'platform-id':'3','x-client':'web','Accept':'application/json'}});
  const j0 = await r0.json();

  // 2) 组装 answer_dict
  const answer_dict = {};
  for (const p of j0.data.problems) {
    answer_dict[String(p.problem_id)] = { answer: [answers[p.index]] };
  }

  // 3) 一次 POST 提交全部
  const t0 = Date.now();
  const r = await fetch('/mooc-api/v1/lms/exercise/problem_batch_apply/', {
    method:'POST', credentials:'include', headers:H,
    body: JSON.stringify({
      leaf_id: {LEAF_ID},
      classroom_id: {CLASSROOM_ID},
      exercise_id: {EXERCISE_ID},
      answer_dict
    })
  });
  const txt = await r.text();
  const ms = Date.now() - t0;

  let js = null;
  try { js = JSON.parse(txt); } catch {}

  let ok = 0, notOk = 0;
  if (js && js.data) {
    for (const k in js.data) {
      const v = js.data[k];
      if (Array.isArray(v) && v[0] && v[0].is_correct) ok++;
      else notOk++;
    }
  }
  return { status: r.status, elapsedMs: ms, correct: ok, notCorrect: notOk, raw: txt.slice(0,500) };
}
```

调用：

```js
submitAll({1:'A',2:'D',3:'A',4:'B',5:'A', /* ... 100 个 */ });
```

### 6.6 回包结构

```json
{
  "msg": "",
  "success": true,
  "data": {
    "{PROBLEM_ID_START}": [
      {
        "count": -1,
        "is_show_answer": true,
        "my_score": 1.0,
        "my_count": 1,
        "is_right": true,
        "is_correct": true,        ← 判分结果
        "source": "web",
        "answer": ["A"],           ← 我的答案
        "my_answer": ["A"]
      },
      0                            ← 这个 0 表示提交成功（见下）
    ]
  }
}
```

前端判成功的逻辑：

```js
// 数组第 2 个元素为 0 → 成功
if (Array.isArray(s) && Number(s[1]) === 0) { /* success */ }
```

---

## 七、第五步：验证结果

### 7.1 查最终成绩

```js
fetch('/mooc-api/v1/lms/exercise/get_exercise_list/{EXERCISE_ID}/{SKU_ID}/?classroom_id={CLASSROOM_ID}', {
  credentials:'include',
  headers:{'xtbz':'ykt','university-id':'{UV_ID}','platform-id':'3','x-client':'web','Accept':'application/json'}
}).then(r=>r.json()).then(j=>{
  const rows = j.data.problems.map(p => ({
    i: p.index,
    my: p.user?.my_answer?.[0],
    isRight: p.user?.is_right,
    score: p.user?.my_score
  }));
  const right = rows.filter(x=>x.isRight === true);
  const wrong = rows.filter(x=>x.isRight !== true);
  console.log('正确:', right.length, '错误:', wrong.length);
  console.table(wrong);
});
```

### 7.2 判断字段说明

| 字段 | 含义 | 取值 |
|---|---|---|
| `user.is_right` | 是否答对 | `true` / `false` / `null`(未答) |
| `user.my_score` | 得分 | `"1.00"` 对 / `"0.00"` 错 |
| `user.my_answer` | 我的答案 | `["A"]` |
| `user.my_count` | 提交次数 | 数字 |
| `content_score` | 内容得分 | 常为 `-1.00`（未批改），**不可用于判对错** |

> ⚠️ 别用 `content_score` 判断对错，它一直是 `-1.00`。用 `user.is_right`。

### 7.3 答错了怎么办

练习级 `max_retry = -1`（不限次），所以可以重提。用排除法：

```js
async function tryOptions(problemId, options) {
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
  const H = {
    'xtbz':'ykt','university-id':'{UV_ID}','platform-id':'3','x-client':'web',
    'Accept':'application/json','Content-Type':'application/json','x-csrftoken':csrf
  };
  for (const a of options) {
    const r = await fetch('/mooc-api/v1/lms/exercise/problem_apply/', {
      method:'POST', credentials:'include', headers:H,
      body: JSON.stringify({classroom_id:{CLASSROOM_ID}, problem_id:problemId, answer:[a]})
    });
    const j = await r.json();
    console.log(a, j.data?.is_correct);
    if (j.data?.is_correct) return a;
    await new Promise(s => setTimeout(s, 1500));   // 必须等待，否则 429
  }
  return null;
}

// 例：第 85 题答错了，试 A/B/C/D
tryOptions(81007604, ['A','B','C','D']);
```

### 7.4 单题提交接口（备用）

批量接口搞不定时，可以用单题接口：

```
POST /mooc-api/v1/lms/exercise/problem_apply/
```

请求体：

```json
{"classroom_id": {CLASSROOM_ID}, "problem_id": {PROBLEM_ID_START}, "answer": ["A"]}
```

> 注意：这里是裸数组 `["A"]`，与批量的 `{answer:["A"]}` **不一样**。

---

## 八、限速机制详解

### 8.1 现象

频繁调用会返回：

```json
{"detail": "请求超过了限速。 Expected available in 1.0 second."}
```

HTTP 状态码 **429**。

### 8.2 实测规律

| 项目 | 实测值 |
|---|---|
| 单次请求耗时 | 43 – 80 ms |
| 令牌桶容量 | 约 1 – 2 个 |
| 恢复速率 | 约每 1 – 1.5 秒补 1 个令牌 |
| 连续打满后冷却 | 1.5 – 2 秒 |

### 8.3 三种提交方式耗时对比

| 方式 | 100 题耗时 | 说明 |
|---|---|---|
| 单题接口串行（含退避） | **约 10 分钟** | 每题都要等令牌 |
| 单题接口 3 路并发 | 约 3 – 4 分钟 | 有改善，仍受限于单题粒度 |
| **批量接口 1 次 POST** | **约 2 秒** | 冷却 + 一次请求，最快 |

### 8.4 最快策略

```
① 先不要连续试探（会打空令牌桶）
② 发一次批量请求
③ 如果 429，等 "Expected available in N second" 提示的 N 秒再发
④ 成功后不要立刻再发，等 2 秒令牌恢复
```

实测最优：**等约 2 秒 → 发一次批量请求 → 完成**。

---

## 九、完整可运行脚本

以下脚本可直接粘贴到浏览器 DevTools Console（**需已登录并打开练习页面**）。

```js
(async function fullWorkflow() {
  const CFG = {
    classroomId: {CLASSROOM_ID},
    uvId: {UV_ID},
    platformId: 3,
    exerciseId: {EXERCISE_ID},
    skuId: {SKU_ID},
    leafId: {LEAF_ID},
    sign: '{SCHOOL_SIGN}'
  };

  const BASE_HEADERS = {
    'xtbz': 'ykt',
    'university-id': String(CFG.uvId),
    'platform-id': String(CFG.platformId),
    'x-client': 'web',
    'Accept': 'application/json, text/plain, */*'
  };
  const getCsrf = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1];

  // ── Step 0: 验证登录 ──────────────────────────────
  const me = await fetch('/api/v3/user/basic-info', {credentials:'include'})
    .then(r => r.json());
  if (me.code !== 0) throw new Error('未登录：' + me.msg);
  console.log('✅ 登录成功，用户ID:', me.data.id);

  // ── Step 1: 拿题目 + 字体（同一次响应） ────────────
  const exUrl = `/mooc-api/v1/lms/exercise/get_exercise_list/${CFG.exerciseId}/${CFG.skuId}/?classroom_id=${CFG.classroomId}`;
  const ex = await fetch(exUrl, {credentials:'include', headers: BASE_HEADERS})
    .then(r => r.json());
  if (!ex.success) throw new Error('取题失败：' + ex.msg);

  const fontUrl = ex.data.font;
  const problems = ex.data.problems;
  console.log(`✅ 拿到 ${problems.length} 道题`);
  console.log(`   字体: ${fontUrl.split('/').pop()}`);

  // ── Step 2: 下载字体（必须在同一上下文内立刻下载） ──
  const fontResp = await fetch(fontUrl);
  const fontBuf = new Uint8Array(await fontResp.arrayBuffer());
  console.log(`✅ 字体已下载 ${fontBuf.length} 字节`);

  // 把字体二进制暴露出来，供外部 Python 解密使用
  let s = '';
  for (let i = 0; i < fontBuf.length; i++) s += String.fromCharCode(fontBuf[i]);
  window.__FONT_B64 = btoa(s);
  window.__PROBLEMS = problems;

  // ── Step 3: 提交答案（假设 answers 已由解密+人工/AI 得出） ──
  // answers 形如 {"1":"A", "2":"D", ...}
  window.__submitAll = async function(answers) {
    const csrf = getCsrf();
    const H = {...BASE_HEADERS,
      'Content-Type': 'application/json',
      'x-csrftoken': csrf,
      'Referer': `https://www.yuketang.cn/v2/web/iframe-exercise/${CFG.classroomId}/${CFG.leafId}`
    };

    const answer_dict = {};
    for (const p of window.__PROBLEMS) {
      const a = answers[p.index];
      if (a) answer_dict[String(p.problem_id)] = { answer: [a] };
    }

    const t0 = Date.now();
    const r = await fetch('/mooc-api/v1/lms/exercise/problem_batch_apply/', {
      method: 'POST',
      credentials: 'include',
      headers: H,
      body: JSON.stringify({
        leaf_id: CFG.leafId,
        classroom_id: CFG.classroomId,
        exercise_id: CFG.exerciseId,
        answer_dict
      })
    });
    const txt = await r.text();
    const ms = Date.now() - t0;

    if (r.status === 429) {
      console.warn(`⚠ 限速，等待 2 秒后重试（本次 ${ms}ms）`);
      await new Promise(z => setTimeout(z, 2000));
      return window.__submitAll(answers);
    }

    let js = null;
    try { js = JSON.parse(txt); } catch {}

    let ok = 0, bad = 0;
    const wrongList = [];
    if (js && js.data) {
      for (const pid in js.data) {
        const v = js.data[pid];
        if (Array.isArray(v) && v[0] && v[0].is_correct) ok++;
        else {
          bad++;
          const pr = window.__PROBLEMS.find(x => String(x.problem_id) === pid);
          wrongList.push({ problem_id: pid, index: pr?.index, myAnswer: v[0]?.my_answer });
        }
      }
    }
    console.log(`✅ 提交完成 ${ms}ms | 正确 ${ok} | 错误 ${bad}`);
    if (wrongList.length) console.table(wrongList);
    return { ok, bad, wrongList, elapsedMs: ms };
  };

  // ── Step 4: 查结果 ────────────────────────────────
  window.__checkResult = async function() {
    const j = await fetch(exUrl, {credentials:'include', headers: BASE_HEADERS})
      .then(r => r.json());
    const rows = j.data.problems.map(p => ({
      index: p.index,
      my: p.user?.my_answer?.[0] ?? null,
      isRight: p.user?.is_right,
      score: p.user?.my_score,
      count: p.user?.my_count
    }));
    const right = rows.filter(x => x.isRight === true).length;
    const wrong = rows.filter(x => x.isRight !== true);
    console.log(`📊 共 ${rows.length} 题 | 正确 ${right} | 错误/未答 ${wrong.length}`);
    if (wrong.length) console.table(wrong);
    return rows;
  };

  console.log('🎉 初始化完成。');
  console.log('   window.__FONT_B64   → 字体 base64（拿去 Python 解密）');
  console.log('   window.__PROBLEMS   → 题目数组');
  console.log('   window.__submitAll(answers) → 批量提交');
  console.log('   window.__checkResult()      → 查成绩');
})();
```

### 9.1 解密字体（在 Python 侧）

1. Console 里执行 `copy(window.__FONT_B64)` 复制字体 base64
2. 存成 `font_b64.txt`
3. 用 5.5 节的 Python 代码解密
4. 得到 `{码位: 汉字}` 映射
5. 套到题目 HTML 上

```python
import json, re, base64

# 1. 解出映射
font_data = base64.b64decode(open("font_b64.txt").read().strip())
open("temp.ttf", "wb").write(font_data)

ref_index = build_reference_index(REF_FONTS, pool)   # 见 5.5
dec_map = decrypt_font("temp.ttf", ref_index)

# 2. 套用到题目
def decrypt_html(html, dec_map):
    return ''.join(dec_map.get(ord(c), c) for c in html)

def clean(html, dec_map):
    s = decrypt_html(html, dec_map)
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'</p>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    import html as H
    return re.sub(r'\n{2,}', '\n', H.unescape(s)).strip()

for p in problems:
    print(p["index"], clean(p["content"]["Body"], dec_map))
    for o in p["content"]["Options"]:
        print("  ", o["key"], clean(o["value"], dec_map))
```

---

## 十、踩坑记录（必读）

按踩坑顺序列出，第一次做必然会遇到。

### 坑 1：缺 `xtbz` 头 → `XTBZ IS REQUIRED`

```json
{"msg": "XTBZ IS REQUIRED", "error_code": 40000}
```

**解决**：所有请求加上 `xtbz: ykt`。

### 坑 2：缺 `classroom_id` 参数 → `CLASSROOM ID IS REQUIRED`

```json
{"msg": "CLASSROOM ID IS REQUIRED", "error_code": 40000}
```

**解决**：URL 查询串加 `?classroom_id={CLASSROOM_ID}`。

### 坑 3：POST 返回 403 → `CSRF Failed`

```json
{"detail": "CSRF Failed: CSRF token missing or incorrect."}
```

**解决**：加请求头 `x-csrftoken: <cookie里的csrftoken>`。

注意：头名必须正好是 `x-csrftoken`。试过 `X-CSRFToken` 也能通，但 `x-xsrf-token` 不行。

### 坑 4：`answer_dict` 传裸数组 → `apply content error`

```json
{"msg": "apply content error", "error_code": 500500}
```

**错**：`{"{PROBLEM_ID_START}": ["A"]}`
**对**：`{"{PROBLEM_ID_START}": {"answer": ["A"]}}`

### 坑 5：字体和题目对不上 → 解出来全是乱码

**原因**：`font` URL 每次请求都随机变化，题目文本与字体是配对的。

**解决**：同一次响应里拿 `problems` 和 `font`，立刻下载字体。

### 坑 6：用 `content_score` 判对错 → 全是 `-1.00`

**原因**：`content_score` 是内容评分缓存，未批改时恒为 `-1.00`。

**解决**：用 `user.is_right`（`true`/`false`）或 `user.my_score`（`"1.00"`/`"0.00"`）。

### 坑 7：连续提交 → 429 限速

**解决**：等 1.5 – 2 秒；或用批量接口一次提交。

### 坑 8：像素比对解密准确率只有 25%

**原因**：不同字体渲染风格差异大。

**解决**：改用字形轮廓拓扑签名，准确率 100%。

### 坑 9：`problem_id` 和 `index` 混用

**表现**：提交报错或提交到错误的题。

**解决**：`index` 是 1..100 的题号，`problem_id` 是 {PROBLEM_ID_START}..{PROBLEM_ID_END}，**提交必须用 `problem_id`**。

### 坑 10：题目 `ProblemType` 不是 1 时答案格式不同

| ProblemType | 题型 | answer 结构 |
|---|---|---|
| 1 | 单选 | `["A"]` |
| 2 | 多选 | `["A","C"]` |
| 3 | 投票 | `["A","C"]` |
| 4 | 填空 | `{answers: {1:"xx", 2:"yy"}}` |
| 5 | 主观 | 对象（含 attachments） |
| 6 | 判断 | `["A"]` |

---

## 十一、参数速查表

### 11.1 本案例所有 ID

| 参数 | 值 |
|---|---|
| `classroom_id` | {CLASSROOM_ID} |
| `uv_id` / `university_id` | {UV_ID} |
| `platform_id` | 3 |
| `sku_id` | {SKU_ID} |
| `leaf_id` | {LEAF_ID} |
| `exercise_id` | {EXERCISE_ID} |
| `sign` | `{SCHOOL_SIGN}` |
| `course_id` | {COURSE_ID} |
| `problem_id` 范围 | {PROBLEM_ID_START} – {PROBLEM_ID_END} |

### 11.2 接口清单

| 用途 | 方法 | 路径 |
|---|---|---|
| 验证登录 | GET | `/api/v3/user/basic-info` |
| 取章节树 | GET | `/mooc-api/v1/lms/learn/course/chapter` |
| 取叶子详情 | GET | `/mooc-api/v1/lms/learn/leaf_info/{classroom_id}/{leaf_id}/` |
| 取 sku 列表 | GET | `/c27/online_courseware/course/classroom/{cid}/0/sku_list/` |
| **取题目+字体** | GET | `/mooc-api/v1/lms/exercise/get_exercise_list/{eid}/{sku}/` |
| **批量提交** | POST | `/mooc-api/v1/lms/exercise/problem_batch_apply/` |
| 单题提交 | POST | `/mooc-api/v1/lms/exercise/problem_apply/` |
| 重置练习 | POST | `/mooc-api/v1/lms/exercise/reset_exercise/{eid}/{sku}/{uid}/` |

### 11.3 请求头模板

```javascript
// GET 用
{
  'xtbz': 'ykt',
  'university-id': '{UV_ID}',
  'platform-id': '3',
  'x-client': 'web',
  'Accept': 'application/json, text/plain, */*'
}

// POST 额外加
{
  'Content-Type': 'application/json',
  'x-csrftoken': '<从cookie取>'
}
```

### 11.4 答案格式模板

```javascript
// 批量提交（answer_dict 用对象包数组）
{
  leaf_id: {LEAF_ID},
  classroom_id: {CLASSROOM_ID},
  exercise_id: {EXERCISE_ID},
  answer_dict: {
    "{PROBLEM_ID_START}": { answer: ["A"] },
    "81007492": { answer: ["D"] }
  }
}

// 单题提交（裸数组）
{
  classroom_id: {CLASSROOM_ID},
  problem_id: {PROBLEM_ID_START},
  answer: ["A"]
}
```

---

## 附：本案例最终结果

| 项目 | 结果 |
|---|---|
| 题目总数 | 100 |
| 解密覆盖率 | 99.4% |
| 首次提交正确 | 96 / 100 |
| 纠正后 | **100 / 100** |
| 错题 | 第 3、6、38、85 题 |
| 批量提交耗时 | 约 2 秒 |

### 正确答案（100 题）

```
ADABA CDDAD
ACBBC CBDDC
ADBCB ACBBD
DDCAB CCCDC
CCADD DBADC
CBDAB CCDBC
DDBBC CDACD
ADDCC ADCCD
BCBBD BDACB
CCDBC CDDCB
```

---

## 免责与合规提醒

- 本文档仅记录**技术研究过程**，用于理解 Web 应用的反爬字体保护与接口设计。
- 实际操作中会写入真实学习记录，**请在授权范围内使用**。
- 抓取到的题库、用户信息等属于第三方数据，**不应对外传播或用于商业目的**。
- #### 建议在测试账号、测试课堂中复现，不要使用真实课程账号。

