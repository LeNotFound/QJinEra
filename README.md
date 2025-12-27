# 🌸 柒槿年 (QJinEra)

> **“在 100 万次无状态的对话中，唯独记住了关于你的那 1KB。”**
>
> 一个基于 AliceBot + NapCat 的拟人化 QQBot，拥有记忆、情感和灵魂。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![AliceBot](https://img.shields.io/badge/Framework-AliceBot-green) ![License](https://img.shields.io/badge/License-GPLv3-orange) ![LLM Support](https://img.shields.io/badge/LLM-OpenAI%20%7C%20Gemini-blueviolet)


**柒槿年** (QJinEra) 旨在打破传统 Bot "一问一答" 的僵硬模式。她能**感知情绪**、**主动插话**、**分条回复**，并像老朋友一样**随着时间推移记住你的喜好与经历**。

---

## ✨ 核心特性 (V2.0)

### 🧠 三模型协同 (The Trinity)
抛弃单一模型，采用类似人脑的分层架构：
1.  **判官模型 (The Judge)**：潜意识层。实时分析群聊，决定是否插嘴、是否吃瓜、是否有值得记住的信息。
2.  **写手模型 (The Writer)**：意识层。负责生成高情商、符合人设的回复。
3.  **记忆提取器 (The Extractor)**：海马体。从对话中精准提取关于用户的新事实 (Facts) 并存入长期记忆。

### 💾 增量式记忆 (Gemini Style)
*   不再是一段死板的描述，而是**一条条鲜活的事实**。
*   **示例**：
    *   *2025-12-26* 记录：`用户喜欢吃菠萝披萨`
    *   *2025-12-27* 记录：`用户最近在熬夜重构代码`
*   聊天时，她会不经意地提起这些往事，给你“被记住”的浪漫感。

### 🗣️ 拟人化交互
*   **分条发送**：根据内容长度，自动拆分成 1-5 条短消息发送，像真人一样“蹦”出消息。
*   **打字延迟**：模拟人类的输入速度，拒绝秒回。
*   **主动社交**：群冷场时主动抛出话题，或者看到感兴趣的话题（如“吃瓜”、“求夸”）主动凑热闹。

### 📡 赛博大脑监控 (Dashboard)
内置 **Streamlit** 实时监控面板：
*   **思维流**：实时看到 Bot 在想什么（“这句该插嘴吗？”、“他在求夸吗？”）。
*   **记忆流**：实时目睹关于你的记忆是如何被提取和存储的。
*   **自动刷新**：支持挂机监控。

---

## 🚀 快速开始

### 1. 环境准备

确保已安装 Python 3.10+。

```bash
git clone https://github.com/YourRepo/QJinEra.git
cd QJinEra
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

1.  复制示例配置：
    ```bash
    cp example.config.toml config.toml
    ```
2.  编辑 `config.toml`，填入你的 LLM API Key (支持 OpenAI 格式，推荐 Gemini Flash 系列)：
    ```toml
    [llm]
    api_base = "..."
    api_key = "sk-..."
    # 推荐配置
    judge_model = "gemini-2.5-flash-lite"  # 判官（快且便宜）
    chat_model = "gemini-2.5-flash"        # 写手（高智商）
    ```
3.  确保 **NapCat** (OneBot v11) 正在运行，WS 地址默认为 `ws://127.0.0.1:3001`。

### 4. 运行 Bot

```bash
python main.py
```

### 5. 启动监控面板 (Dashboard)

在新的终端窗口运行：

```bash
streamlit run dashboard.py
```
打开浏览器访问 `http://localhost:8501`，开启顶部的 **Auto Refresh** 开关即可。

---

## 📂 目录结构

```
QJinEra/
├── config.toml           # 核心配置文件 (Prompt, API, 阈值)
├── main.py               # Bot 启动入口
├── dashboard.py          # Streamlit 监控面板
├── qjinera.db            # SQLite 数据库 (自动生成)
├── plugins/              # AliceBot 插件
│   ├── core.py           # [核心] 消息流处理与模型调度
│   └── scheduler.py      # [定时] 主动话题任务
├── services/             # 业务服务层
│   ├── llm.py            # LLM 接口封装 (Judge/Chat/Extract)
│   ├── topic.py          # 话题与上下文管理
│   └── storage.py        # 数据库操作 (Memories/Logs)
└── docs/                 # 文档
```

## 📝 开发计划

- [x] **三模型架构 (Judge/Chat/Extract)**
- [x] **增量记忆系统**
- [x] **Streamlit 监控面板**
- [x] **主动话题与插嘴策略**
- [ ] RAG 向量检索 (支持超长历史)
- [ ] 视觉模态 (看懂表情包)
- [ ] 语音回复 (RVC/EdgeTTS)

## 📄 License

GPLv3