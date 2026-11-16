# 英语口语练习 · 项目交接

## 项目位置与用途

- 目录：`/Users/shazhengzhong/Downloads/diary-pronunciation-coach`
- 家庭内部使用的英语日记 / 口语练习应用，不公开注册。
- 技术栈：Django 5.2 + Python 3.14 + SQLite + 服务端模板 + 原生 JS + PWA。
- 当前应用名：**英语口语练习**；PWA 短名称：**口语练习**。
- 这个目录不是 git 仓库。不要假设有版本控制；不要删除日记、录音、`private_media`、`.env`、`.bak` 或旧的 APK，除非用户明确要求。

## 当前实际状态（2026-11-15）

### 界面

- 新主题在 `static/css/theme.css`，基础样式在 `static/css/app.css`。
- 视觉方向：近白底 + 轻蓝/轻粉/薄荷渐变，白卡片，蓝色主色，珊瑚/琥珀/薄荷/紫色点缀；按钮小而简洁，间距紧凑。
- 手机端顶部导航隐藏重复的「首页 / 邀请家人 / 成员」入口，这些入口仍在首页卡片中。
- 当前图标：方案 **08 双语气泡**（白底，蓝色大气泡 + 珊瑚色小气泡）。
- 日记详情页：上方“阅读”卡片（默认全英文、可切换全中文/全英文，可收起；全英文按原中文行/段落换行，全文正常/慢速朗读、逐词高亮、单词可点）；下方“中英对照”卡片（每句正常/慢读 + 整句录音 + 录音历史，单词可点）。
- 正文不显示音标；点击单词从底部弹出半屏单词卡，卡内显示音标、中文词性/释义、单词发音/循环、单分数录音测评 + 录音回放、居中音节播放，支持向下滑关闭。
- 旧的独立练习弹层、正文音标、中文释义朗读按钮、`view-mode` 切换均已移除。
- 单词卡不显示“播放中/播放完毕”文字；底部状态区预留高度，避免上下闪跳。
- 朗读中的当前词用蓝色高亮，已读过的词不变暗；句子 TTS 时间戳会先按词对齐，再回退到长度估算。
- 图标预览页：`static/icon-options/index.html`。
- PWA / 苹果主屏 / favicon / Android 图标都在 `static/icons/`，Android 壳图标在 `android-shell/res/mipmap-xxxhdpi/ic_launcher.png`。

### 服务

- 翻译：DeepSeek（`TRANSLATION_PROVIDER=deepseek`，Key 只在 `.env`）。
- 发音合成：阿里云 CosyVoice 3.5 Plus（`TTS_PROVIDER=cosyvoice`）；美音/英音自定义音色也在 `.env`。
- 单词/句子/全文/查词/慢速朗读都走 `get_tts_provider`，当前全部使用 CosyVoice。
- 普通单词发音使用普通文本；已知问题词 `riverside` 使用 CMU SSML 覆盖。
- 单词测评：腾讯云 SOE；拍照 OCR：腾讯云 OCR；Key 只在 `.env`。
- 单词卡释义：DeepSeek 按需生成结构化 `senses`（多词性/多释义），缓存在 `WordLookup.senses`；第一次点新词可能等待 1–2 秒。查词使用独立的每日额度 `WORD_LOOKUP_DAILY_REQUEST_LIMIT`（默认 100），不再挤占日记翻译的 20 次额度；额度不足时单词卡会显示具体提示。
- 音节播放：单词卡内逐音节和整词拼读；音频仍来自当前 TTS provider。旧“自然拼读/音素”隐藏页面仍在，但没有入口，音质不合格，不要接回 UI。
- 录音测评：单词卡只显示一个分数，录音保留并可在分数旁点击回放；低于 70 分播放警示音，70 分及以上播放正确提示音。
- 测评提示音文件在 `static/audio/assess-low.wav` / `assess-high.wav`，通过 HTML audio 播放以兼容华为 WebView；音量已调高，Web Audio 只作后备。
- 单词发音个别词有 TTS 语调问题。`riverside` 已加 CMU SSML 发音覆盖；其他词如果仍不准，优先考虑换 Microsoft/Azure 音源，不要继续硬编码单个词。

### 运行与验证

```bash
cd /Users/shazhengzhong/Downloads/diary-pronunciation-coach
source .venv/bin/activate
python manage.py test
```

- 目前测试数：225 个，全部通过。
- HTTP 开发服务：`python manage.py runserver 0.0.0.0:8000`
- HTTPS 局域网服务：`.venv/bin/python manage.py runserver_plus 0.0.0.0:8443 --cert-file var/certs/lan-cert.pem --key-file var/certs/lan-key.pem`
- 家庭手机访问地址：`https://192.168.5.4:8443/`
- Android WebView 壳 APK：`static/family-diary-1.8.apk`（版本 1.8，versionCode 9；已移除未使用的中文 TTS 桥接）。

### 文档提醒

`README.md` 和 `FEATURE_LEDGER.md` 里仍有旧的火山引擎 / 拼读功能描述，部分内容已过时。以本文件、当前代码和 `.env` 配置为准；不要只根据旧 README 推断现状。

## GitHub 备份

- GitHub 仓库：`https://github.com/shazhengzhong/my-Mac`
- 这个仓库**根目录是另一个项目**（物流打印软件）；英语项目只放在子目录：
  `english-speaking-practice/`
- 本地镜像：`~/my-Mac`（不是主要开发目录；主要开发目录仍是本项目文件夹）
- 同步脚本：`scripts/sync_github.sh`
- 用户选择的是「任务完成后提交」，不装后台定时器。**完成一个代码改动并验证通过后**，运行：
  ```bash
  ./scripts/sync_github.sh "说明这次改了什么"
  ```
- 脚本会先拉取远端、同步到镜像子目录、检查敏感/超大文件，再提交并推送。
- 不要用 `git push` 从本项目根目录直接推；它没有配置 remote。
- 不要覆盖或强推 `my-Mac` 的 `main`；仓库根目录的物流项目必须保留。
- 该仓库是公开仓库。`.env`、数据库、家庭录音、签名文件、Android 工具链、APK、测试音频都不能进入仓库；不要削弱 `scripts/sync_github.sh` 和 `.gitignore` 的排除规则。
- 纯问答、讨论和预览不提交；只有代码/资源改动并验证通过后才同步。

## 工作约定

1. **先理解需求，再改代码。** 用户明确要求先讨论时，先给方案和影响范围，得到确认后才执行。
2. **不要擅自增加功能。** 不做用户没有要求的新功能、新入口、自动恢复、自动提醒、额外页面等。
3. **不要擅自注册、购买、充值或开通付费服务。** 不引出国际信用卡方案；国内账号/支付优先。
4. **API Key / 密码 / 私密音色 ID 只放 `.env`。** 不要询问、打印、提交或在聊天中展示真实密钥；需要用户填写时，指导用户自己编辑 `.env`。
5. **隐私优先。** 日记、录音、翻译和音标仅本人可见；管理员也看不到成员内容。不要把家庭数据发到外部服务，除非是现有功能明确需要的提供商。
6. **改完要验证。** 跑测试；涉及页面就检查桌面和手机尺寸；涉及 Android 就重新打包并核对版本/名称/图标。
7. **UI 偏好：** 用户不喜欢深青绿和米色底；喜欢干净的白底、简洁的彩色点缀、小按钮和紧凑间距。改版先遵守这个方向。
8. **图标：** 当前选择是方案 08；要换图标先给预览，不要直接覆盖生产图标。

## 用户以后可以这样开场

```text
继续「英语口语练习」项目：
/Users/shazhengzhong/Downloads/diary-pronunciation-coach

先读 CLAUDE.md，检查当前代码状态。
这次我想改：……
验收标准：……

先告诉我方案和会改哪些文件，不要直接改代码。
```

如果要沿用上次对话，在同一目录运行 `claude --continue`；要重新开始新会话也可以，直接复制上面的开场白即可。新会话不需要重复项目历史，先让 Claude 读这个文件和代码。
