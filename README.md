# 🌸 柒槿年 (QJinEra)

> **“在 100 万次无状态的对话中，唯独记住了关于你的那 1KB。”**
>
> 一个基于 AliceBot + NapCat 的拟人化 QQBot，拥有记忆、情感和灵魂。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![AliceBot](https://img.shields.io/badge/Framework-AliceBot-green) ![License](https://img.shields.io/badge/License-AGPLv3-orange) ![LLM Support](https://img.shields.io/badge/LLM-OpenAI%20%7C%20Gemini-blueviolet)

![](/docs/card.png)

**柒槿年** (QJinEra) 旨在打破传统 Bot "一问一答" 的僵硬模式。她能**感知情绪**、**主动插话**、**分条回复**，并像老朋友一样**随着时间推移记住你的喜好与经历**。

---

## ✨ 核心特性 (V4.0)

### 🧠 跨层认知架构 (The Quartet+)
抛弃单一模型，采用类似人脑的分层架构并加入世界观感知：
1.  **判官模型 (The Judge)**：潜意识层。实时分析群聊，决定是否插嘴，提取提到的专有名词和实体。
2.  **写手模型 (The Writer)**：意识层。结合长期人物传记、最新事件记忆、亲密度及当前角色心情，生成高情商回复。
3.  **记忆提取器 (The Extractor)**：海马体（前端）。从对话中精准提取关于用户的新事实 (Facts) 及相关的专有名词 (World Lore)。
4.  **记忆巩固者 (The Consolidator)**：大脑皮层（赛博回响）。在话题结束后的静默时刻，将新事实反刍并炼化为长期印象。

### 💾 V4 多维记忆机制与赛博感知
*   **实体化设定 (World Lore)**：智能捕获群聊中的专属名词与共同梗，形成 Bot 的“世界观认知”。
*   **多维度上下文注入**：利用 Jinja2 模板动态渲染状态，包含亲密度阶段、时间感知、近期动态与个人设定。
*   **赛博回响**：“在你离开后的静默里，我在反刍我们的对话。”
    *   当话题结束时，自动整理并炼化刚才的碎事，生成对你的立体画像。

### 🗣️ 拟人化交互与生命引擎雏形
*   **动态态度分配**：由于引入了 `intimacy_score`（亲密度），对陌生人与挚友展现不同的话痨程度与情感映射。
*   **多状态模拟**：具有体力（Energy）与心情（Mood）数值，后续将直接影响在线活跃度和语气。
*   **分条与延迟发送**：拒绝秒回，根据内容长度自动拆分短消息，模拟真人“蹦”字感。

### 📡 赛博大脑监控 (Dashboard)
内置 **Streamlit** 实时监控面板：
*   **思维流**：实时看到 Bot 的心理活动与插嘴判定。
*   **感知流**：查看 Bot 对各个用户的亲密关系阶段，以及刚刚提取的 World Lore（世界知识）。
*   **自动刷新**：支持全天候挂机监控。

---

## 🚀 快速开始

### 1. 环境准备

确保已安装 Python 3.10+。

```bash
git clone https://github.com/LeNotFound/QJinEra.git
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

```text
QJinEra/
├── config.toml           # 核心配置文件 (Prompt, API, 阈值)
├── main.py               # Bot 启动入口
├── dashboard.py          # Streamlit 监控面板
├── plugins/              # AliceBot 插件
│   ├── core.py           # [核心] 消息流处理与模型调度
│   └── scheduler.py      # [定时] 主动话题与记忆任务
├── prompts/              # [新] Jinja2 动态提示词系统
├── services/             # 业务服务层
│   ├── storage/          # [新] 模块化数据库操作表组件
│   │   ├── users.py      # 用户状态与亲密度
│   │   ├── world_lore.py # 专有名词感知
│   │   └── ...           # 其他存取逻辑
│   ├── llm.py            # LLM 接口封装
│   ├── topic.py          # 话题与上下文管理
│   └── memory_service.py # 记忆巩固服务
└── docs/                 # 文档
```

## 📝 开发计划

- [x] **四模型架构 (Judge/Chat/Extract/Consolidator)**
- [x] **多维度记忆 & World Lore 专有名词感知** (V4.0)
- [x] **Jinja 提示词模板与亲密度系统引擎基础** (V4.0)
- [x] **Streamlit 监控面板**
- [x] UPEX 协议适配 (Universal Personality Exchange)
- [ ] **生命引擎**：实现心情/体力的动态消耗与恢复机制
- [ ] **亲密度引擎**：实装完整的互动判断，根据亲密等级解锁特殊态度
- [ ] **主动发言强化**：Proactive 模块，真正实现在冷场时主动发散话题
- [ ] 视觉模态 (看懂表情包)
- [ ] 语音回复 (RVC/EdgeTTS)

## 📄 License

AGPLv3