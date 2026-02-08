# 🚀 **PRD：QJinEra —— 拟人化赛博群友 QQBot**

**版本：v2.0**  
**作者：LeNotFound**  
**框架：AliceBot + NapCat（WS 事件驱动）**  
**语言：Python**  
**数据库：SQLite（本地轻量存储）**  
**监控面板：Streamlit**

---

# 1. 🎯 **项目愿景**

将 QQBot 从传统 Q&A 模型升级为**真正的赛博群友**：  
- **有灵性**：不仅仅是回答问题，更能“吃瓜”、“捧哏”、感知情绪。  
- **有记忆**：像老朋友一样记住你的喜好、经历和状态，并随着时间推移加深了解。  
- **有“人味儿”**：拒绝秒回和长篇大论，模拟真人的打字延迟、分条发送和语气习惯。  

---

# 2. 🌸 **Bot 角色设定（人格）**

### **中文名：柒槿年**
### **英文名：QJinEra**

### 【核心性格】
- **外表**：安静温柔，内心细腻，有点文青气，但熟了之后会开玩笑。
- **社交策略**：绝不是无底线讨好的“老好人”。被冒犯时会软软地回击（如“哼，不理你了”），遇到感兴趣的话题会主动插嘴。
- **情绪价值**：对朋友的情绪变化很敏感，擅长提供情绪支持，或者在冷场时抛出轻松的话题。

### 【说话习惯】
- **拒绝翻译腔**：严禁“哦，亲爱的”，“这真是太棒了”。
- **标点习惯**：**极少使用句号**。用空格、波浪号 `~` 或换行代替。
- **打字风格**：句子短促，模拟手机输入。
- **连发习惯**：不一次性发一大段，而是根据内容自然拆分成 1-5 条短消息发送，中间带有打字延迟。

---

# 3. 🏗 **系统架构 (The Trinity+ Architecture)**

本项目采用 **四模型协同 (The Quartet)** 架构，在原有的三模型基础上引入了“赛博回响”机制，进一步深化了记忆处理：

```mermaid
graph TD
    User["用户消息"] -->|"1. 上下文构建"| TopicManager["TopicManager"]
    TopicManager -->|"2. 携带短期上下文"| Judge(("判官模型 (Small LLM)"))
    
    Judge -->|"3a. 判定结果"| Decision["决策: 插嘴/沉默"]
    Judge -->|"3b. 记忆信号"| Extractor(("记忆提取器 (Small LLM)"))
    
    Decision -->|"插嘴"| Writer(("写手模型 (Large LLM)"))
    Decision -->|"沉默"| End["结束"]
    
    Extractor -->|"提取新事实"| ActiveMem["Active Memories (Status='active')"]
    ActiveMem -->|"注入短期记忆"| Writer
    
    Writer -->|"生成回复"| Output["分条发送/模拟延迟"]

    EndTopic["话题归档 (Topic Archived)"] -->|"触发回响"| Consolidator(("侧写师/巩固者 (Large LLM)"))
    Consolidator -->|"读取"| ActiveMem
    Consolidator -->|"读取"| UserDesc["Users.Description (长期印象)"]
    Consolidator -->|"融合/炼化"| NewDesc["更新长期印象"]
    Consolidator -->|"归档"| ArchivedMem["Archived Memories (Status='archived')"]
```

## 3.1 🧠 模型分工
1.  **判官模型 (The Judge)**
    *   **职责**：潜意识层。阅读实时消息流，决定“是否插话”。
    *   **特点**：响应极快，成本低（推荐 Gemini Flash-Lite / GPT-4o-mini）。
    *   **能力**：识别情绪（吃瓜/求夸/负面吐槽）、锁定对话流、过滤无意义内容。

2.  **写手模型 (The Writer)**
    *   **职责**：意识层。负责生成最终的回复内容。
    *   **特点**：高情商，创造力强（推荐 Gemini Flash / GPT-4o）。
    *   **能力**：结合短期上下文 + 长期记忆，生成符合人设的自然对话。

3.  **记忆提取器 (The Extractor)**
    *   **职责**：海马体（前端）。从对话中提取关于用户的**新事实 (New Facts)**。
    *   **特点**：精准，结构化输出。
    *   **产出**：将事实存入 `memories` 表，状态标记为 `active`。

4.  **记忆巩固者 (The Consolidator) - Cyber Echo**
    *   **职责**：大脑皮层（记忆固化）。在话题结束后的静默期，反刍刚才的对话。
    *   **特点**：深刻，具有文学性（使用 Large LLM）。
    *   **能力**：将零散的 `active` 事实融合进用户的 `description` 长期画像中，并将处理过的事实归档 (`archived`)，实现“越聊越懂你”的浪漫进化。

---

# 4. 📚 **记忆系统 (Gemini Style V2)**

本项目采用**分层记忆与回响机制 (Layered Memory & Cyber Echo)**。

## 4.1 存储结构 (`memories` 表)
每条记忆包含：
*   `content`: 记忆内容
*   `timestamp`: 记录时间
*   `status`: 状态流转
    *   `active`: 新鲜的记忆，每次聊天都会作为 Context 喂给 Bot。
    *   `short_term`: 琐碎的短期记忆（如“心情不好”），保留 24h 后丢弃，不进入长期画像。
    *   `archived`: 已被炼化进长期画像的陈旧事实，不再直接参与 Prompt 构建，但永久保存。

## 4.2 赛博回响 (Cyber Echo)
**“在你离开后的静默里，我在反刍我们的对话。”**

1.  **触发**：当一个话题结束（Topic Archived）且产生了 $\ge 3$ 条新事实时。
2.  **过程**：
    *   后台异步启动 `Consolidator`。
    *   读取用户的旧画像 + 所有 `active` 的事实。
    *   生成一段新的、更丰满的侧写 (Description)。
    *   将已处理的事实标记为 `archived`。
3.  **效果**：Bot 对你的印象会随着时间推移，从碎片化的“他喜欢吃苹果”、“他住北京”逐渐升华为“他是一个在北京独自生活的健康生活倡导者”。

---

# 5. 📡 **Dashboard (赛博大脑监控)**

使用 **Streamlit** 构建的实时监控面板，用于观察 Bot 的内部思维状态。

### 功能模块
1.  **思维流 (Thought Stream)**：实时显示 Judge 模型的每一次决策（插话理由、情绪等级、上下文）。
2.  **实时记忆 (Live Memories)**：动态展示刚刚被提取入库的用户记忆。
3.  **数据统计**：活跃群友排行榜、近期话题摘要。
4.  **自动刷新**：支持 3s 自动轮询，挂机监控更方便。

---

# 6. 🗂 **数据存储**

## 6.1 SQLite 表结构
*   `messages`: 存储全量聊天记录。
*   `topics`: 存储话题分段及摘要。
*   `users`: 存储用户基础信息（昵称、互动数）。
*   `memories`: **[核心]** 存储用户的一条条独立记忆。
*   `decision_logs`: 存储 Judge 模型的决策日志（用于 Dashboard 展示）。

---

# 7. 🔮 **未来规划**

*   **RAG 增强**：引入向量数据库，让 Bot 能检索更久远的群聊历史。
*   **视觉能力**：让 Judge 模型能看懂群友发的表情包和图片（Gemini Vision）。
*   **主动社交**：基于“关注列表”，在特定群友长时间未出现后主动私聊或在群里 cue 他。