# 柒槿年 (QJinEra) 🌸

> 一个基于 AliceBot + NapCat 的拟人化赛博群友 QQBot。

**柒槿年** (QJinEra) 不仅仅是一个自动回复机器人，她拥有自己的人格，能够像真实群友一样参与话题讨论，甚至在话题冷场时主动发起聊天。

## ✨ 核心特性

- **🧠 拟人化人格**：拥有独立性格（温柔、理性、文青），拒绝 AI 味和客服腔。
- **🗣️ 自然多轮对话**：不仅仅是一问一答，通过 LLM 生成多条连贯消息，模拟人类打字延迟发送。
- **👀 智能话题识别**：
  - 自动识别新旧话题，避免上下文混乱。
  - **插话判断系统**（Judge Model）：通过小模型分析语境，决定是“插话”、“回复”还是“保持沉默”。
- **⏰ 主动交互**：
  - 群冷场监测：长时间无人发言时，主动抛出轻松话题打破沉寂。
  - 动态心跳：模拟真实用户的在线习惯。
- **💾 记忆系统**：基于 SQLite 存储话题摘要和历史消息，拥有更长久的记忆力。

## 🛠️ 技术栈

- **框架**: [AliceBot](https://github.com/AliceBotProject/alicebot) (Python) + NapCat (OneBot v11)
- **核心逻辑**: Python 3.10+
- **LLM**: OpenAI API 兼容接口 (支持 GPT-3.5/4, Claude, DeepSeek 等)
- **数据库**: SQLite
- **配置**: TOML

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

1. 确保你有一个运行中的 **NapCat** (OneBot v11) 实例，WebSocket 监听地址默认为 `ws://127.0.0.1:3001`。
2. 修改 `config.toml` 文件，填入你的 LLM API Key：

```toml
[llm]
api_base = "https://api.openai.com/v1" # 或其他中转地址
api_key = "sk-xxxxxxxx"
judge_model = "gpt-3.5-turbo" # 推荐使用便宜的小模型
chat_model = "gpt-4"          # 推荐使用高质量模型
```

### 4. 运行

```bash
python main.py
```

## 📂 目录结构

```
QJinEra/
├── config.toml           # 配置文件 (API Key, 阈值, Prompt)
├── main.py               # 启动入口
├── plugins/              # 插件目录
│   ├── core.py           # 核心逻辑 (消息处理, 调用 LLM)
│   └── scheduler.py      # 定时任务 (主动插话)
├── services/             # 服务层
│   ├── llm.py            # LLM 接口封装
│   ├── topic.py          # 话题管理与上下文构建
│   └── storage.py        # 数据库存储
└── docs/                 # 文档 (PRD 等)
```

## 📝 开发计划

- [x] 基础对话与人格设定
- [x] 话题上下文管理
- [x] 主动发起聊天
- [ ] 群友画像构建 (User Profiling)
- [ ] 多模态支持 (表情包理解)

## 📄 License

GPLv3
