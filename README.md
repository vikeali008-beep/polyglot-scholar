---
title: 智译学研 Polyglot Scholar
emoji: 🎓
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 智译学研 · Polyglot Scholar Online (`v2.0` 多用户网站版)

**俄英双语学术论文精读 · 中文对照翻译 · 俄语六格/重音与英语学术词汇学习平台**

> 专为需要同时研读 **俄语 (Русский)** 与 **英语 (English)** 学术文献的研究者与学习者打造。支持多用户注册登录与独立云端空间、访客免登录即开即用、DOI 全文/摘要四源并发导入、PDF 分屏精读、俄语全文重音标注 (`ударе́ние`) 与六格变格表、英俄中三语互证词典、SM-2 间隔重复闪卡以及手机/平板自适应阅读。

---

## ✨ 网站核心特性

1. **🌐 多用户云端 SaaS 架构 + 免登录访客体验**
   - **网站门户首页 (`/`)**：学术门户落地页，支持直接粘贴 DOI 一键开启精读。
   - **个人账号隔离 (`/api/auth/*`)**：采用 `PBKDF2-HMAC-SHA256` 密码哈希与 Bearer 会话令牌；每位注册用户拥有完全隔离的**个人论文书架、精读笔记、生词本、SM-2 复习进度与私有大模型 API Key**（首次注册自动迁移当前访客体验数据）。
   - **移动端 / 平板端适配 + PWA**：手机/平板自动切换抽屉式书架与底部滑出式词法显微镜，支持「添加到主屏幕」作为独立 App 使用。

2. **🔗 四源并发 DOI 导入 + PDF 分屏 + arXiv 直连**
   - 并发查询 **Crossref + OpenAlex + Semantic Scholar + Publisher Meta (`doi.org`)**，自动抓取论文题录、英/俄摘要，并自动探测下载开放获取（Open Access）原版 PDF 全文。
   - 支持本地 PDF 拖拽上传、arXiv 编号直连与纯文本粘贴。

3. **🔬 俄语 & 英语学术语言显微镜**
   - **俄语专项**：全文一键标注重音符号（`ударе́ние`），内置 `pymorphy3` 形态学引擎生成名词/形容词 **六格单复数完整变格表**（高亮文中当前格位）、动词体/时态变位表与形动词还原。
   - **英语专项**：词形还原（Lemmatization）、音标（IPA）、学术词表（AWL）高亮、词根词缀拆解与英文原版释义。
   - **RU ↔ EN ↔ ZH 三语互证**：查俄语词同步给出英语学术同源词，查英语词同步给出俄语对应学术词，全部支持母语神经语音（`1.0x` / `0.75x`）跟读。

4. **🗂 记忆闭环：生词本 + SM-2 闪卡 + 原句语境填空 + Anki 导出**
   - 一键收藏生词并自动记录**所在论文原句与中文译文**；支持 SM-2 记忆曲线闪卡（可隐藏俄语正面重音自测）与 Anki TSV / Markdown 讲义导出。

---

## 🚀 免费公网部署指南（0 服务器成本）

本项目已内置完整的 `Dockerfile`、`render.yaml`、`railway.json` 与 Hugging Face Spaces 元数据配置。详细图文步骤请参阅 **[DEPLOY_WEBSITE.md](./DEPLOY_WEBSITE.md)**。

### 最快方式：Hugging Face Spaces 免费部署（推荐 · 16GB 内存免费 24 小时在线）
1. 注册并登录 [huggingface.co](https://huggingface.co)，点击右上角头像 → **New Space**。
2. 填写名称（如 `polyglot-scholar`），**Space SDK 选择 `Docker` → `Blank`**，Hardware 保持免费 `CPU basic (2 vCPU · 16 GB · FREE)`，点击 **Create Space**。
3. 将本目录（`lingua_paper/`）下的所有文件上传（可通过网页 `Files -> Add file -> Upload files` 或 `git push`）。
4. 等待约 2 分钟自动构建完成，即可获得永久免费 HTTPS 独立网址：
   `https://<你的用户名>-polyglot-scholar.hf.space`（在 Space 右上角 `⋮ -> Embed this Space -> Direct URL` 查看直连独立网站域名，可分享给任何人在电脑或手机打开使用！）。

---

## 💻 本地或云服务器一键运行

```bash
pip install -r requirements.txt
bash start.sh
# 默认监听 http://0.0.0.0:8000 （可通过 PORT=8080 bash start.sh 自定义端口）
```
