# 雨课堂题库导出工具

一个用于**导出自己已选课程的练习题内容**的本地工具。

> ⚠️ **使用前请务必阅读 [免责声明](#免责声明)**。本工具仅限个人学习研究用途。

---

## 这个工具做什么

- 导出你**已加入**的课堂里的练习题题目与选项
- 处理服务端的自定义字体混淆，让题目文字可读
- 把结果保存成本地 Markdown / JSON 文件

**它不会**：绕过登录、访问你没权限的课堂、或修改任何服务端数据（除非你主动执行提交步骤）。

---

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows / macOS / Linux |
| Python | 3.8 及以上 |
| 浏览器 | Chrome / Edge（用于登录和获取 Cookie） |
| 账号 | 你**自己合法拥有**的雨课堂账号，且已加入目标课堂 |

**无需安装第三方库**，全部使用 Python 标准库。

---

## 快速开始

### 第一步：下载代码

```bash
git clone https://github.com/hzjh22/yuketang-export.git
cd yuketang-export
```

### 第二步：浏览器登录

1. 用 Chrome 打开 <https://www.yuketang.cn>
2. 正常登录（扫码或账号密码）
3. 打开你要导出题目的**课程练习页面**
4. 按 `F12` 打开开发者工具

### 第三步：获取 Cookie

在开发者工具的 **Console**（控制台）标签中输入：

```js
document.cookie
```

复制输出的整串内容（形如 `uv_id=1001; csrftoken=xxx; ...`），稍后填入配置。

> 💡 **提示**：不要让 Cookie 泄露给任何人，它等同于你的登录凭证。

### 第四步：获取必要参数

保持 Console 打开，依次执行以下代码获取参数。

**① 确认已登录**

```js
fetch('/api/v3/user/basic-info', {credentials:'include'})
  .then(r => r.json()).then(console.log)
```

看到 `{"code":0,"data":{"id":"...","name":"..."}}` 说明登录正常。

**② 获取题目接口地址中的 ID**

切换到 **Network**（网络）标签，刷新页面，在筛选框输入 `get_exercise_list`。

找到类似这样的请求：

```
https://www.yuketang.cn/mooc-api/v1/lms/exercise/get_exercise_list/24681357/13572468/?classroom_id=12345678
                                                                              ↑       ↑         ↑
                                                                        exercise_id sku_id  classroom_id
```

三个数字分别是 `exercise_id`、`sku_id`、`classroom_id`。

**③ 获取 leaf_id**

在 Network 中筛选 `leaf_info`，找到请求：

```
https://www.yuketang.cn/mooc-api/v1/lms/learn/leaf_info/12345678/87654321/
                                                                ↑ leaf_id
```

### 第五步：填写配置

打开 `src/yuketang_tool.py`，修改顶部的配置区：

```python
CFG = {
    "base_url":     "https://www.yuketang.cn",
    "classroom_id": 12345678,    # 换成你的
    "uv_id":        1001,        # 学校 ID，从 URL 或 Cookie 获取
    "platform_id":  3,
    "exercise_id":  24681357,     # 换成你的
    "sku_id":       13572468,    # 换成你的
    "leaf_id":      87654321,    # 换成你的
}

# 把第三步复制的 Cookie 粘贴到这里
COOKIE = "uv_id=1001; csrftoken=你的token; ..."
```

### 第六步：运行

```bash
python src/yuketang_tool.py
```

运行成功后，项目目录下会生成 `output/` 文件夹：

| 文件 | 内容 |
|---|---|
| `output/questions.json` | 结构化题目数据 |
| `output/questions.md` | 可直接阅读的题目文档 |
| `output/decrypt_map.json` | 字体解密映射表 |
| `output/exam_font.ttf` | 下载的字体文件 |

---

## 常见问题

### Q1：报错 `未登录：UNAUTHENTICATED`

Cookie 无效或已过期。重新登录浏览器，重新复制 Cookie。

### Q2：报错 `XTBZ IS REQUIRED`

配置里的请求头缺 `xtbz`。检查 `build_headers()` 函数是否正确保留了 `"xtbz": "ykt"`。

### Q3：报错 `CLASSROOM ID IS REQUIRED`

`classroom_id` 没填对，或接口 URL 缺少查询参数。

### Q4：解密后的文字仍然是乱码

**最常见的原因是字体和题目不匹配。**

服务端每次请求都会下发**不同的随机字体**，题目文本与字体是严格配对的。如果分开两次请求获取题目和字体，就会对不上。

本工具已处理这个问题（在同一次响应中取回题目和字体），若你自行修改代码请保留这一逻辑。

其他可能：
- 系统缺少参考字体 → 检查 `REF_FONTS` 里的字体路径是否存在
- 遇到生僻字 → 字库覆盖约 99%，少数字无法还原属正常

### Q5：报错 `429 请求超过了限速`

触发频率限制。工具内置了重试等待，若仍失败请等待 1-2 分钟后重试。

### Q6：想导出别的课程

只需更换 `classroom_id` / `exercise_id` / `sku_id` / `leaf_id` 四个参数，其余不用改。

### Q7：macOS / Linux 上找不到字体

把 `REF_FONTS` 改成你系统里的中文字体路径，例如 macOS：

```python
REF_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]
```

---

## 项目结构

```
yuketang-export/
├── README.md                          ← 本文件（使用教程 + 免责）
├── LICENSE
├── .gitignore
├── docs/
│   └── TECHNICAL-REPRODUCTION.md      ← 技术复现细节（供研究参考）
├── src/
│   └── yuketang_tool.py               ← 主程序
└── examples/
    └── answers.example.json           ← 答案文件格式示例
```

---

## 免责声明

**请在使用前完整阅读本声明。使用本工具即表示你已理解并同意以下全部条款。**

### 1. 用途限制

本工具仅供**个人学习、技术研究与教学演示**使用，用于导出用户**自己有权访问**的课程内容。

**严禁**将本工具用于：

- 商业用途或任何营利活动
- 批量抓取、爬取平台数据
- 售卖、传播、二次分发导出的题库内容
- 代替他人完成课程、作业、考试（代刷、代考）
- 破坏、干扰平台正常服务
- 任何违反当地法律法规的行为

### 2. 合规责任

- 使用者需**自行确认**其对目标课程内容拥有合法访问权限
- 使用者需**自行确认**其使用行为符合所在学校/机构的学术规范
- 使用者需**自行承担**因使用本工具产生的一切后果
- 导出内容若包含他人信息，使用者需遵守相关个人信息保护法规

### 3. 学术诚信

导出题库后用于**作弊、代考、规避考核**等行为，严重违反学术诚信，可能导致**课程成绩作废、学籍处分**等后果。**本工具作者明确反对此类行为，且不承担任何相关责任。**

### 4. 无担保

本软件按"现状"提供，不附带任何明示或暗示的担保，包括但不限于适销性、特定用途适用性和非侵权性的担保。

### 5. 责任免除

在任何情况下，作者或版权持有人均不对任何索赔、损害或其他责任负责，无论是在合同诉讼、侵权行为还是其他方面，产生于、源于或与本软件或本软件的使用或其他交易有关。

### 6. 平台条款

使用本工具可能违反目标平台的服务条款。使用者应自行评估并承担此风险。作者与目标平台无任何关联，本工具未获其授权或认可。

### 7. 内容归属

导出的题目、选项等教学内容，其著作权归**原课程教师或所属机构**所有。使用者不得主张对上述内容的任何权利，也不得未经授权对外传播。

### 8. 免责声明的变更

作者保留随时修改本免责声明的权利。继续使用本工具即视为接受修改后的条款。

---

## 许可

本项目采用 [MIT License](LICENSE)。MIT 许可仅适用于**本项目的源代码**，不适用于通过本工具获取的任何第三方内容。

---

## 反馈

如发现 Bug 或有改进建议，欢迎提交 Issue。

**再次提醒：请遵守法律法规、平台服务条款与学术诚信规范。技术本身中立，使用者的行为由其自行负责。**

