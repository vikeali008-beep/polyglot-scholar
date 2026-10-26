# 🌍 智译学研 (Polyglot Scholar) — 免费公网网站部署指南

本项目已完成**多用户云端隔离、账号注册/登录、移动端响应式与 Docker 容器化**封装。无需购买昂贵的云服务器，任选以下任一平台即可在 **3 分钟内获得永久免费的公网 `https://` 网址**，随时在电脑、iPad 或手机浏览器访问，或分享给同学与课题组成员共同注册使用。

---

## 方案一：Hugging Face Spaces（强烈推荐 ⭐ 零成本 · 无需绑卡 · 16GB 大内存）

Hugging Face Spaces 对 Docker Web 应用提供 **2 vCPU + 16 GB 内存** 的免费容器与自动 HTTPS 独立子域名，非常适合运行包含 `PyMuPDF`（PDF 解析）和 `pymorphy3`（俄语形态学词库）的学术网站。

### 部署步骤（纯网页操作，无需命令行）：
1. 打开 [https://huggingface.co/spaces](https://huggingface.co/spaces) 并免费注册/登录账号。
2. 点击右上角 **New Space**：
   - **Space name**：输入 `polyglot-scholar`
   - **Select the Space SDK**：选择 **Docker**（模板选 **Blank**）
   - **Space Hardware**：保持默认的 `CPU basic · 2 vCPU · 16 GB · FREE`
   - **Visibility**：选择 `Public`
   - 点击 **Create Space**。
3. 上传网站代码：
   - 点击页面上方 **Files** 标签页 → **Add file** → **Upload files**。
   - 将 `lingua_paper` 文件夹内的所有文件和子目录（`app.py`, `Dockerfile`, `requirements.txt`, `README.md`, `services/`, `static/`）拖入上传框，点击底部 **Commit changes to `main`**。
   - *(注：本项目的 `README.md` 顶部已预置 Hugging Face 所需的 `sdk: docker` 与 `app_port: 7860` 配置，无需任何修改！)*
4. 获取独立全屏网站地址：
   - 页面上方状态由 `Building` 变为绿色的 **`Running`**（约 2 分钟）后，网站即已上线！
   - 点击右上角 `⋮` 菜单 → **Embed this Space**，复制 **Direct URL**（格式为 `https://你的用户名-polyglot-scholar.hf.space`）。
   - 用该链接在电脑、平板或手机打开，即是一个**无边框、全屏独立的正式学术网站**（在手机 Safari / Chrome 点击「添加到主屏幕」还能作为独立 App 图标打开）。

---

## 方案二：Render 免费云平台部署（支持 GitHub 自动同步更新）

项目根目录已内置 `render.yaml` 蓝图配置文件：

1. 将 `lingua_paper` 目录上传到你的 GitHub 仓库。
2. 登录 [https://dashboard.render.com](https://dashboard.render.com) → 点击 **New +** → **Blueprint**（或 **Web Service**）。
3. 连接你的 GitHub 仓库，Render 会自动识别 `Dockerfile` 与 `render.yaml`（选择 **Free** 实例计划）。
4. 点击 **Deploy Web Service**，构建完成后即获得 `https://polyglot-scholar.onrender.com` 公网地址。

> 💡 **提示**：Render 免费版在 15 分钟无人访问后会自动休眠，下次打开需等待约 20 秒唤醒；若希望全天秒开，可配合免费的 [UptimeRobot](https://uptimerobot.com) 每 10 分钟访问一次 `https://你的域名/api/health`。

---

## 方案三：Railway / Koyeb / Zeabur 或自有云服务器 Docker 一键部署

如果你使用 Railway、Zeabur、Koyeb，或拥有自己的轻量应用服务器（阿里云 / 腾讯云 / Ubuntu VPS）：

```bash
# 在任意安装了 Docker 的服务器上执行：
docker build -t polyglot-scholar .

# 启动容器并将数据目录挂载到宿主机 ./scholar_data 实现永久持久化：
mkdir -p ./scholar_data
docker run -d \
  --name polyglot-scholar \
  --restart unless-stopped \
  -p 8000:7860 \
  -v "$(pwd)/scholar_data:/data" \
  polyglot-scholar
```

容器内会自动检测 `/data` 挂载卷并将所有注册用户账号、导入的 PDF 全文、个人笔记与生词本安全保存在宿主机 `./scholar_data/scholar.db` 中，后续升级代码镜像数据永不丢失。

---

## 🔐 多用户隐私与数据安全说明

- **密码安全**：用户密码通过 `PBKDF2-HMAC-SHA256`（120,000 次迭代 + 随机盐）单向加密存储，数据库不保存任何明文密码。
- **空间隔离**：每位注册用户的上传论文、DOI 导入全文、阅读笔记、生词本复习进度及个人大模型 API Key 均按 `owner_id` 严格隔离；访客模式下每个浏览器也拥有独立的随机 `guest_id` 沙盒互不干扰。
- **平滑转正**：用户在未登录访客状态下导入的论文和收藏的生词，在点击「注册账号」时会自动无缝合并迁移至新注册的个人账号下。
