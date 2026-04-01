#!/usr/bin/env python3
"""
generate_visualizer.py — 根据系统分析 JSON 生成交互式可视化 HTML

用法：
    python3 generate_visualizer.py --analysis-json '{"system_name": "..."}' --output /tmp/harness-blueprint.html
    python3 generate_visualizer.py --analysis-file analysis.json --output /tmp/harness-blueprint.html
"""

import argparse
import json
import sys
import html as html_module
from pathlib import Path


def escape(text: str) -> str:
    """HTML escape"""
    return html_module.escape(str(text))


def mermaid_label(text: str) -> str:
    """清理文本使其可安全用于 Mermaid 节点标签和 edge 标签.

    Mermaid 标签中以下字符会导致解析失败:
    - 中文括号（）
    - 特殊符号 ¥ # @ 等
    - 双引号（会破坏 "..." 界定）
    """
    replacements = {
        '（': '(', '）': ')', '：': ':',
        '，': ',', '；': ';',
        '"': "'", '"': "'", '"': "'",
        '¥': 'Y', '￥': 'Y',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # 去掉可能残留的双引号
    text = text.replace('"', "'")
    return text


def mermaid_id(text: str) -> str:
    """把中文/特殊字符转成合法的 Mermaid 节点 ID."""
    import re
    import hashlib
    # 先尝试只保留字母数字下划线
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', text)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean or clean[0].isdigit():
        clean = 'n_' + clean
    # 加 hash 后缀防止不同中文映射到同一个 ID
    h = hashlib.md5(text.encode()).hexdigest()[:6]
    return f'{clean}_{h}'
    """把中文/特殊字符转成合法的 Mermaid 节点 ID."""
    import re
    import hashlib
    # 先尝试只保留字母数字下划线
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', text)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean or clean[0].isdigit():
        clean = 'n_' + clean
    # 加 hash 后缀防止不同中文映射到同一个 ID
    h = hashlib.md5(text.encode()).hexdigest()[:6]
    return f'{clean}_{h}'


def generate_cld_mermaid(data: dict) -> str:
    """生成因果回路图 Mermaid 代码"""
    lines = ["graph LR"]
    node_set: set[str] = set()

    def _ensure_node(name: str):
        nid = mermaid_id(name)
        if nid not in node_set:
            lines.append(f'    {nid}["{mermaid_label(name)}"]')
            node_set.add(nid)
        return nid

    # 增强回路
    for loop in data.get("loops", {}).get("reinforcing", []):
        path = loop.get("path", [])
        nodes = [p for p in path if p not in ("+", "-")]
        nids = [_ensure_node(n) for n in nodes]
        for i in range(len(nids) - 1):
            lines.append(f'    {nids[i]} -->|"+"| {nids[i+1]}')
        if len(nids) >= 2:
            lines.append(f'    {nids[-1]} -->|"+"| {nids[0]}')
        lid = loop.get("id", "R")
        lname = loop.get("name", "增强回路")
        status = loop.get("status", "")
        status_tag = f' [{status}]' if status else ''
        lines.append(f'    %% {lid}: {lname}{status_tag}')

    # 调节回路
    for loop in data.get("loops", {}).get("balancing", []):
        path = loop.get("path", [])
        nodes = [p for p in path if p not in ("+", "-")]
        signs = [p for p in path if p in ("+", "-")]
        nids = [_ensure_node(n) for n in nodes]
        for i in range(min(len(nids) - 1, len(signs))):
            lines.append(f'    {nids[i]} -->|"{signs[i]}"| {nids[i+1]}')
        # 闭合调节回路
        if len(nids) >= 2 and len(signs) >= len(nids) - 1:
            pass  # 最后一条边已在循环中处理
        lid = loop.get("id", "B")
        lname = loop.get("name", "调节回路")
        status = loop.get("status", "")
        status_tag = f' [{status}]' if status else ''
        lines.append(f'    %% {lid}: {lname}{status_tag}')

    return "\n".join(lines)


def generate_agent_mermaid(data: dict) -> str:
    """生成 Agent 架构图 Mermaid 代码"""
    agents = data.get("agents", [])
    feedback = data.get("feedback_loops", [])

    lines = ["graph TB"]
    lines.append(f'    {mermaid_id("用户")}["👤 用户"]')
    lines.append(f'    subgraph boundary["🔲 系统边界"]')

    for ag in agents:
        aid = mermaid_id(ag.get("id", "agent"))
        role = ag.get("role", "Agent")
        model = ag.get("model", "")
        label = f'{role}'
        if model:
            label += f' ({model})'
        lines.append(f'        {aid}["{label}"]')

    state_id = mermaid_id("共享状态")
    lines.append(f'        {state_id}[("📦 共享状态")]')
    lines.append('    end')

    uid = mermaid_id("用户")
    if agents:
        first = mermaid_id(agents[0]["id"])
        last = mermaid_id(agents[-1]["id"])
        lines.append(f'    {uid} -->|"任务输入"| {first}')
        lines.append(f'    {last} -->|"结果输出"| {uid}')

    for i in range(len(agents) - 1):
        a = mermaid_id(agents[i]["id"])
        b = mermaid_id(agents[i+1]["id"])
        lines.append(f'    {a} --> {b}')

    for ag in agents:
        aid = mermaid_id(ag["id"])
        lines.append(f'    {aid} <-.->|"读写"| {state_id}')

    for fb in feedback:
        fb_type = fb.get("type", "quality")
        fb_id = fb.get("id", "fb")
        if fb_type == "quality" and len(agents) >= 2:
            last = mermaid_id(agents[-1]["id"])
            first = mermaid_id(agents[0]["id"])
            lines.append(f'    {last} -->|"B: {fb_id}"| {first}')

    return "\n".join(lines)


def generate_stock_flow_mermaid(data: dict) -> str:
    """生成存量流量的 HTML 可视化卡片.

    Mermaid 11 flowchart 在多节点中文场景下 viewBox 计算崩溃（foreignObject 0x0），
    无法修复。改用纯 HTML/CSS 卡片布局，每个存量一张卡片，流入在左，流出在右。
    返回的是 HTML 字符串而非 Mermaid 代码。
    """
    stocks = data.get("stocks", [])
    if not stocks:
        return '<p style="color:var(--text-dim);">无存量数据</p>'

    status_colors = {
        "high": ("#1a472a", "#4ecdc4", "🟢"),
        "medium": ("#3a3a1a", "#ffd93d", "🟡"),
        "low": ("#4a1a1a", "#ff6b6b", "🔴"),
    }

    cards = []
    for s in stocks:
        name = s.get("name", "存量")
        status = s.get("status", "medium")
        bg, border, emoji = status_colors.get(status, ("#242836", "#4a4f6a", "⚪"))

        inflows_html = ""
        for inf in s.get("inflows", []):
            inf_name = inf.get("name", "")
            inf_rate = inf.get("rate", "")
            inflows_html += f'<div class="sf-flow-item sf-inflow">{inf_name}<span class="sf-rate">{inf_rate}</span></div>'

        outflows_html = ""
        for outf in s.get("outflows", []):
            outf_name = outf.get("name", "")
            outf_rate = outf.get("rate", "")
            outflows_html += f'<div class="sf-flow-item sf-outflow">{outf_name}<span class="sf-rate">{outf_rate}</span></div>'

        cards.append(f'''<div class="sf-card" style="border-color:{border};">
  <div class="sf-inflows">{inflows_html}</div>
  <div class="sf-arrow-in">→</div>
  <div class="sf-stock" style="background:{bg};border-color:{border};">{emoji} {name}</div>
  <div class="sf-arrow-out">→</div>
  <div class="sf-outflows">{outflows_html}</div>
</div>''')

    return "\n".join(cards)


def build_html(data: dict) -> str:
    """组装完整的 HTML"""

    system_name = escape(data.get("system_name", "未命名系统"))
    system_goal = escape(data.get("system_goal", ""))
    cld_mermaid = generate_cld_mermaid(data)
    agent_mermaid = generate_agent_mermaid(data)
    stock_mermaid = generate_stock_flow_mermaid(data)
    # 存量流量图现在直接返回 HTML 卡片（不用 Mermaid）
    stock_charts_html = stock_mermaid

    # Agent 列表 JSON（供编辑面板使用）
    agents_json = json.dumps(data.get("agents", []), ensure_ascii=False, indent=2)
    feedback_json = json.dumps(data.get("feedback_loops", []), ensure_ascii=False, indent=2)
    leverage_json = json.dumps(data.get("leverage_points", []), ensure_ascii=False, indent=2)
    archetypes_json = json.dumps(data.get("archetypes", []), ensure_ascii=False, indent=2)
    full_data_json = json.dumps(data, ensure_ascii=False, indent=2)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Harness Blueprint — {system_name}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242836;
    --border: #2e3348;
    --text: #e4e6f0;
    --text-dim: #8b8fa3;
    --accent: #6c8cff;
    --accent2: #4ecdc4;
    --danger: #ff6b6b;
    --warn: #ffd93d;
    --success: #4ecdc4;
    --r-color: #ff6b6b;
    --b-color: #6c8cff;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, "SF Pro Text", "Noto Sans SC", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
  }}

  /* Header */
  .header {{
    background: linear-gradient(135deg, #1a1d27 0%, #242836 100%);
    border-bottom: 1px solid var(--border);
    padding: 28px 40px;
  }}
  .header h1 {{ font-size: 24px; font-weight: 600; }}
  .header .subtitle {{ color: var(--text-dim); font-size: 14px; margin-top: 4px; }}
  .header .goal {{
    margin-top: 12px;
    padding: 10px 16px;
    background: rgba(108, 140, 255, 0.08);
    border-left: 3px solid var(--accent);
    border-radius: 0 6px 6px 0;
    font-size: 14px;
  }}

  /* Tabs */
  .tabs {{
    display: flex;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 40px;
    gap: 0;
    position: sticky;
    top: 0;
    z-index: 100;
  }}
  .tab {{
    padding: 14px 24px;
    font-size: 14px;
    color: var(--text-dim);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
    user-select: none;
  }}
  .tab:hover {{ color: var(--text); }}
  .tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}

  /* Content */
  .content {{ padding: 32px 40px; max-width: 1400px; margin: 0 auto; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}

  /* Cards */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
  }}
  .card h2 {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .card h3 {{
    font-size: 14px;
    font-weight: 600;
    margin: 16px 0 8px;
    color: var(--accent2);
  }}

  /* Mermaid */
  .mermaid-container {{
    background: var(--surface2);
    border-radius: 8px;
    padding: 20px;
    overflow-x: auto;
    margin: 12px 0;
  }}
  .mermaid {{ text-align: center; }}
  .mermaid svg {{ max-width: none !important; width: 100% !important; }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    text-align: left;
    padding: 10px 12px;
    background: var(--surface2);
    color: var(--text-dim);
    font-weight: 500;
    border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }}
  tr:hover td {{ background: rgba(108, 140, 255, 0.04); }}

  /* Badges */
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
  }}
  .badge-r {{ background: rgba(255, 107, 107, 0.15); color: var(--r-color); }}
  .badge-b {{ background: rgba(108, 140, 255, 0.15); color: var(--b-color); }}
  .badge-high {{ background: rgba(255, 107, 107, 0.15); color: var(--danger); }}
  .badge-medium {{ background: rgba(255, 217, 61, 0.15); color: var(--warn); }}
  .badge-low {{ background: rgba(78, 205, 196, 0.15); color: var(--success); }}

  /* Editable fields */
  .editable {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    color: var(--text);
    font-size: 13px;
    width: 100%;
    transition: border-color 0.2s;
  }}
  .editable:focus {{
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(108, 140, 255, 0.2);
  }}
  select.editable {{ cursor: pointer; -webkit-appearance: none; }}
  textarea.editable {{ resize: vertical; min-height: 60px; font-family: inherit; }}

  .form-group {{
    margin-bottom: 16px;
  }}
  .form-group label {{
    display: block;
    font-size: 12px;
    color: var(--text-dim);
    margin-bottom: 4px;
    font-weight: 500;
  }}

  .agent-card {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
  }}
  .agent-card .agent-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
  }}
  .agent-card .agent-title {{ font-weight: 600; font-size: 14px; }}

  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}

  /* Buttons */
  .btn {{
    padding: 10px 20px;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
  }}
  .btn-primary {{
    background: var(--accent);
    color: white;
  }}
  .btn-primary:hover {{ opacity: 0.9; transform: translateY(-1px); }}
  .btn-secondary {{
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
  }}
  .btn-secondary:hover {{ border-color: var(--accent); }}
  .btn-danger {{
    background: rgba(255, 107, 107, 0.1);
    color: var(--danger);
    border: 1px solid rgba(255, 107, 107, 0.3);
  }}
  .btn-sm {{ padding: 6px 12px; font-size: 12px; }}

  .actions-bar {{
    display: flex;
    gap: 12px;
    justify-content: flex-end;
    padding: 24px 0;
    border-top: 1px solid var(--border);
    margin-top: 24px;
  }}

  /* Toast */
  .toast {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: var(--success);
    color: var(--bg);
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    opacity: 0;
    transform: translateY(20px);
    transition: all 0.3s;
    z-index: 1000;
  }}
  .toast.show {{ opacity: 1; transform: translateY(0); }}

  /* Leverage point stars */
  .stars {{ color: var(--warn); letter-spacing: 1px; }}

  /* Responsive */
  @media (max-width: 768px) {{
    .content {{ padding: 16px; }}
    .header {{ padding: 20px 16px; }}
    .tabs {{ padding: 0 16px; overflow-x: auto; }}
    .grid-2 {{ grid-template-columns: 1fr; }}
    .sf-card {{ flex-direction: column; }}
    .sf-arrow-in, .sf-arrow-out {{ transform: rotate(90deg); }}
  }}

  /* Stock-Flow Cards */
  .sf-card {{
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-left-width: 3px;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
  }}
  .sf-inflows, .sf-outflows {{
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .sf-flow-item {{
    font-size: 13px;
    padding: 6px 10px;
    border-radius: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
  }}
  .sf-inflow {{ border-left: 2px solid var(--accent2); }}
  .sf-outflow {{ border-left: 2px solid var(--danger); }}
  .sf-rate {{
    display: block;
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 2px;
  }}
  .sf-stock {{
    flex: 0 0 auto;
    padding: 12px 20px;
    border-radius: 10px;
    border: 2px solid;
    font-size: 14px;
    font-weight: 600;
    text-align: center;
    min-width: 120px;
    white-space: nowrap;
  }}
  .sf-arrow-in, .sf-arrow-out {{
    font-size: 20px;
    color: var(--text-dim);
    flex: 0 0 auto;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>🏗️ Harness Blueprint — {system_name}</h1>
  <div class="subtitle">系统论驱动的 AI 架构规划 · 由 harness-architect 生成</div>
  <div class="goal">🎯 <strong>系统目标：</strong>{system_goal}</div>
</div>

<div class="tabs">
  <div class="tab active" data-tab="overview">📊 系统全景</div>
  <div class="tab" data-tab="agents">🤖 Agent 架构</div>
  <div class="tab" data-tab="stocks">📦 存量流量</div>
  <div class="tab" data-tab="analysis">🔍 系统分析</div>
  <div class="tab" data-tab="edit">✏️ 编辑配置</div>
</div>

<div class="content">

  <!-- Tab 1: 系统全景 -->
  <div class="panel active" id="panel-overview">
    <div class="card">
      <h2>🔄 因果回路图</h2>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:12px;">
        <span class="badge badge-r">R 增强回路</span> 放大变化 &nbsp;
        <span class="badge badge-b">B 调节回路</span> 维持稳定
      </p>
      <div class="mermaid-container">
        <pre class="mermaid">{cld_mermaid}</pre>
      </div>
    </div>

    <div class="card">
      <h2>🏗️ Agent 架构图</h2>
      <div class="mermaid-container">
        <pre class="mermaid">{agent_mermaid}</pre>
      </div>
    </div>
  </div>

  <!-- Tab 2: Agent 架构 -->
  <div class="panel" id="panel-agents">
    <div class="card">
      <h2>🤖 Agent 清单</h2>
      <table>
        <thead>
          <tr><th>ID</th><th>角色</th><th>模型</th><th>职责</th><th>工具</th></tr>
        </thead>
        <tbody id="agents-table-body"></tbody>
      </table>
    </div>

    <div class="card">
      <h2>🔄 反馈回路</h2>
      <table>
        <thead>
          <tr><th>ID</th><th>类型</th><th>触发条件</th><th>阈值</th><th>最大重试</th><th>升级目标</th></tr>
        </thead>
        <tbody id="feedback-table-body"></tbody>
      </table>
    </div>
  </div>

  <!-- Tab 3: 存量流量 -->
  <div class="panel" id="panel-stocks">
    <div class="card">
      <h2>📦 存量-流量图</h2>
      {stock_charts_html}
    </div>

    <div class="card">
      <h2>📋 存量清单</h2>
      <table>
        <thead>
          <tr><th>ID</th><th>名称</th><th>状态</th><th>流入</th><th>流出</th></tr>
        </thead>
        <tbody id="stocks-table-body"></tbody>
      </table>
    </div>
  </div>

  <!-- Tab 4: 系统分析 -->
  <div class="panel" id="panel-analysis">
    <div class="card">
      <h2>🧬 系统基模匹配</h2>
      <table>
        <thead>
          <tr><th>基模</th><th>匹配度</th><th>出现位置</th><th>证据</th><th>干预建议</th></tr>
        </thead>
        <tbody id="archetypes-table-body"></tbody>
      </table>
    </div>

    <div class="card">
      <h2>🎯 杠杆点分析</h2>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:12px;">
        按效力从高到低排列 · 层级越低数字越大效力越弱
      </p>
      <table>
        <thead>
          <tr><th>层级</th><th>杠杆点</th><th>当前实例</th><th>干预建议</th><th>难度</th><th>效力</th></tr>
        </thead>
        <tbody id="leverage-table-body"></tbody>
      </table>
    </div>
  </div>

  <!-- Tab 5: 编辑配置 -->
  <div class="panel" id="panel-edit">
    <div class="card">
      <h2>✏️ Agent 配置编辑</h2>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px;">
        编辑 Agent 角色、模型、工具等配置。修改后点击「导出配置」。
      </p>
      <div id="agent-editor"></div>
      <button class="btn btn-secondary btn-sm" onclick="addAgent()" style="margin-top:12px;">+ 添加 Agent</button>
    </div>

    <div class="card">
      <h2>⚙️ 反馈回路参数</h2>
      <div id="feedback-editor"></div>
      <button class="btn btn-secondary btn-sm" onclick="addFeedback()" style="margin-top:12px;">+ 添加回路</button>
    </div>

    <div class="card">
      <h2>🎯 系统目标</h2>
      <div class="form-group">
        <label>系统目标（可编辑）</label>
        <textarea class="editable" id="edit-goal">{system_goal}</textarea>
      </div>
    </div>

    <div class="actions-bar">
      <button class="btn btn-secondary" onclick="resetConfig()">↩️ 重置</button>
      <button class="btn btn-primary" onclick="exportConfig()">📋 复制实施计划提示词（粘贴给 AI）</button>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
// === Data ===
let analysisData = {full_data_json};
let editableAgents = JSON.parse(JSON.stringify(analysisData.agents || []));
let editableFeedback = JSON.parse(JSON.stringify(analysisData.feedback_loops || []));

// === Mermaid Init ===
mermaid.initialize({{
  startOnLoad: true,
  theme: 'dark',
  securityLevel: 'loose',
  flowchart: {{
    useMaxWidth: false,
    htmlLabels: false,
    curve: 'basis'
  }},
  themeVariables: {{
    primaryColor: '#6c8cff',
    primaryTextColor: '#e4e6f0',
    primaryBorderColor: '#2e3348',
    lineColor: '#4a4f6a',
    secondaryColor: '#242836',
    tertiaryColor: '#1a1d27',
    background: '#1a1d27',
    mainBkg: '#242836',
    nodeBorder: '#4a4f6a',
    clusterBkg: '#1a1d27',
    clusterBorder: '#2e3348'
  }}
}});

// === Tab switching ===
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
  }});
}});

// === Render tables ===
function renderAgentsTable() {{
  const tbody = document.getElementById('agents-table-body');
  tbody.innerHTML = (analysisData.agents || []).map(a => `
    <tr>
      <td><code>${{a.id}}</code></td>
      <td><strong>${{a.role}}</strong></td>
      <td>${{a.model || '-'}}</td>
      <td>${{a.responsibility || '-'}}</td>
      <td>${{(a.tools || []).join(', ') || '-'}}</td>
    </tr>
  `).join('');
}}

function renderFeedbackTable() {{
  const tbody = document.getElementById('feedback-table-body');
  tbody.innerHTML = (analysisData.feedback_loops || []).map(f => `
    <tr>
      <td><code>${{f.id}}</code></td>
      <td><span class="badge badge-${{f.type === 'quality' ? 'b' : f.type === 'resource' ? 'r' : 'b'}}">${{f.type}}</span></td>
      <td>${{f.trigger || '-'}}</td>
      <td>${{f.threshold || '-'}}</td>
      <td>${{f.max_retries || '-'}}</td>
      <td>${{f.escalation || '-'}}</td>
    </tr>
  `).join('');
}}

function renderStocksTable() {{
  const tbody = document.getElementById('stocks-table-body');
  tbody.innerHTML = (analysisData.stocks || []).map(s => `
    <tr>
      <td><code>${{s.id}}</code></td>
      <td>${{s.name}}</td>
      <td><span class="badge badge-${{s.status === 'high' ? 'high' : s.status === 'low' ? 'low' : 'medium'}}">${{s.status}}</span></td>
      <td>${{(s.inflows || []).map(i => i.name + ' (' + i.rate + ')').join(', ')}}</td>
      <td>${{(s.outflows || []).map(o => o.name + ' (' + o.rate + ')').join(', ')}}</td>
    </tr>
  `).join('');
}}

function renderArchetypesTable() {{
  const tbody = document.getElementById('archetypes-table-body');
  tbody.innerHTML = (analysisData.archetypes || []).filter(a => a.match_level !== 'none').map(a => `
    <tr>
      <td><strong>${{a.name}}</strong></td>
      <td><span class="badge badge-${{a.match_level}}">${{a.match_level}}</span></td>
      <td>${{a.location || '-'}}</td>
      <td>${{a.evidence || '-'}}</td>
      <td>${{a.intervention || '-'}}</td>
    </tr>
  `).join('');
}}

function renderLeverageTable() {{
  const tbody = document.getElementById('leverage-table-body');
  const names = {{12:'参数',11:'缓冲区',10:'物理结构',9:'延迟',8:'调节回路',7:'增强回路',6:'信息流',5:'规则',4:'自组织',3:'目标',2:'范式',1:'超越范式'}};
  tbody.innerHTML = (analysisData.leverage_points || []).sort((a,b) => a.level - b.level).map(l => `
    <tr>
      <td>#${{l.level}}</td>
      <td>${{names[l.level] || l.name}}</td>
      <td>${{l.instance || '-'}}</td>
      <td>${{l.action || '-'}}</td>
      <td><span class="badge badge-${{l.difficulty}}">${{l.difficulty}}</span></td>
      <td><span class="stars">${{Array(l.impact || 0).fill('★').join('')}}${{Array(5-(l.impact || 0)).fill('☆').join('')}}</span></td>
    </tr>
  `).join('');
}}

// === Agent Editor ===
function renderAgentEditor() {{
  const container = document.getElementById('agent-editor');
  container.innerHTML = editableAgents.map((a, i) => `
    <div class="agent-card">
      <div class="agent-header">
        <span class="agent-title">🤖 Agent ${{i+1}}</span>
        <button class="btn btn-danger btn-sm" onclick="removeAgent(${{i}})">删除</button>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>角色名称</label>
          <input class="editable" value="${{a.role || ''}}" onchange="editableAgents[${{i}}].role=this.value">
        </div>
        <div class="form-group">
          <label>模型</label>
          <select class="editable" onchange="editableAgents[${{i}}].model=this.value">
            <option ${{a.model==='opus'?'selected':''}}>opus</option>
            <option ${{a.model==='sonnet'?'selected':''}}>sonnet</option>
            <option ${{a.model==='haiku'?'selected':''}}>haiku</option>
            <option ${{a.model==='gpt-4o'?'selected':''}}>gpt-4o</option>
            <option ${{a.model==='custom'?'selected':''}}>custom</option>
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>职责描述</label>
        <textarea class="editable" onchange="editableAgents[${{i}}].responsibility=this.value">${{a.responsibility || ''}}</textarea>
      </div>
      <div class="form-group">
        <label>工具（逗号分隔）</label>
        <input class="editable" value="${{(a.tools||[]).join(', ')}}" onchange="editableAgents[${{i}}].tools=this.value.split(',').map(s=>s.trim()).filter(Boolean)">
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>输入来源（逗号分隔）</label>
          <input class="editable" value="${{(a.inputs||[]).join(', ')}}" onchange="editableAgents[${{i}}].inputs=this.value.split(',').map(s=>s.trim()).filter(Boolean)">
        </div>
        <div class="form-group">
          <label>输出目标（逗号分隔）</label>
          <input class="editable" value="${{(a.outputs||[]).join(', ')}}" onchange="editableAgents[${{i}}].outputs=this.value.split(',').map(s=>s.trim()).filter(Boolean)">
        </div>
      </div>
    </div>
  `).join('');
}}

function renderFeedbackEditor() {{
  const container = document.getElementById('feedback-editor');
  container.innerHTML = editableFeedback.map((f, i) => `
    <div class="agent-card">
      <div class="agent-header">
        <span class="agent-title">🔄 回路 ${{i+1}}: ${{f.id || ''}}</span>
        <button class="btn btn-danger btn-sm" onclick="removeFeedback(${{i}})">删除</button>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>类型</label>
          <select class="editable" onchange="editableFeedback[${{i}}].type=this.value">
            <option ${{f.type==='quality'?'selected':''}}>quality</option>
            <option ${{f.type==='resource'?'selected':''}}>resource</option>
            <option ${{f.type==='learning'?'selected':''}}>learning</option>
            <option ${{f.type==='self-heal'?'selected':''}}>self-heal</option>
          </select>
        </div>
        <div class="form-group">
          <label>最大重试次数</label>
          <input type="number" class="editable" value="${{f.max_retries || 3}}" onchange="editableFeedback[${{i}}].max_retries=parseInt(this.value)">
        </div>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>触发条件</label>
          <input class="editable" value="${{f.trigger || ''}}" onchange="editableFeedback[${{i}}].trigger=this.value">
        </div>
        <div class="form-group">
          <label>阈值</label>
          <input class="editable" value="${{f.threshold || ''}}" onchange="editableFeedback[${{i}}].threshold=this.value">
        </div>
      </div>
    </div>
  `).join('');
}}

function addAgent() {{
  editableAgents.push({{
    id: 'agent_' + (editableAgents.length + 1),
    role: '新 Agent',
    model: 'sonnet',
    responsibility: '',
    tools: [],
    inputs: [],
    outputs: [],
    constraints: []
  }});
  renderAgentEditor();
}}

function removeAgent(i) {{
  editableAgents.splice(i, 1);
  renderAgentEditor();
}}

function addFeedback() {{
  editableFeedback.push({{
    id: 'fb_' + (editableFeedback.length + 1),
    type: 'quality',
    trigger: '',
    threshold: '',
    max_retries: 3,
    escalation: 'human'
  }});
  renderFeedbackEditor();
}}

function removeFeedback(i) {{
  editableFeedback.splice(i, 1);
  renderFeedbackEditor();
}}

function resetConfig() {{
  editableAgents = JSON.parse(JSON.stringify(analysisData.agents || []));
  editableFeedback = JSON.parse(JSON.stringify(analysisData.feedback_loops || []));
  document.getElementById('edit-goal').value = analysisData.system_goal || '';
  renderAgentEditor();
  renderFeedbackEditor();
  showToast('已重置为初始配置');
}}

function exportConfig() {{
  var goal = document.getElementById('edit-goal').value;

  // 用数组拼接避免 Python f-string 和 JS 模板字面量冲突
  var lines = [];
  lines.push('# Harness 实施计划请求');
  lines.push('');
  lines.push('## 系统概览');
  lines.push('- **系统名称**: ' + analysisData.system_name);
  lines.push('- **系统目标**: ' + goal);
  lines.push('');
  lines.push('## Agent 编排方案（用户已确认）');
  lines.push('');

  editableAgents.forEach(function(a, i) {{
    lines.push('### Agent ' + (i+1) + ': ' + a.role);
    lines.push('- 模型: ' + (a.model || '-'));
    lines.push('- 职责: ' + (a.responsibility || '-'));
    lines.push('- 工具: ' + (a.tools || []).join(', '));
    lines.push('- 输入: ' + (a.inputs || []).join(', '));
    lines.push('- 输出: ' + (a.outputs || []).join(', '));
    lines.push('');
  }});

  lines.push('## 反馈回路设计');
  lines.push('');
  editableFeedback.forEach(function(f) {{
    lines.push('- **' + f.id + '**(' + f.type + '): 触发「' + f.trigger + '」阈值「' + f.threshold + '」最大重试 ' + f.max_retries + ' 次，升级到「' + f.escalation + '」');
  }});

  lines.push('');
  lines.push('## 杠杆点（按效力排序）');
  lines.push('');
  (analysisData.leverage_points || []).sort(function(a,b) {{ return a.level - b.level; }}).forEach(function(l) {{
    lines.push('- #' + l.level + ' ' + l.name + ': ' + l.action);
  }});

  lines.push('');
  lines.push('## 已识别的系统基模');
  lines.push('');
  (analysisData.archetypes || []).filter(function(a) {{ return a.match_level !== 'none'; }}).forEach(function(a) {{
    lines.push('- **' + a.name + '**(' + a.match_level + '): ' + a.evidence + ' → 干预: ' + a.intervention);
  }});

  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('请基于以上已确认的设计，生成完整的实施计划，包含：');
  lines.push('1. **周级路线图**（Week 1/2/3/4 各做什么，每周有可验证的交付物）');
  lines.push('2. **每个 Agent 的 System Prompt 设计要点**（不写完整 prompt，写核心约束和角色定义）');
  lines.push('3. **技术选型建议**（API/框架/部署方案）');
  lines.push('4. **成本估算**（按月活 1000/5000/10000 三档）');
  lines.push('5. **风险对策表**（基于上面的系统基模，每个风险的监控信号和应急方案）');
  lines.push('6. **MVP 验收标准**（什么数据证明方向对/不对）');

  var prompt = lines.join('\\n');

  navigator.clipboard.writeText(prompt).then(function() {{
    showToast('✅ 实施计划提示词已复制！直接粘贴给 AI 即可生成完整方案。');
  }}).catch(function() {{
    // file:// 协议下 clipboard API 被阻止，用 textarea fallback
    var ta = document.createElement('textarea');
    ta.value = prompt;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {{
      document.execCommand('copy');
      showToast('✅ 实施计划提示词已复制！直接粘贴给 AI 即可。');
    }} catch(e) {{
      // 最终 fallback：下载文件
      var blob = new Blob([prompt], {{ type: 'text/markdown' }});
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'harness-implementation-prompt.md';
      a.click();
      URL.revokeObjectURL(url);
      showToast('✅ 提示词已下载为 harness-implementation-prompt.md');
    }}
    document.body.removeChild(ta);
  }});
}}

function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}}

// === Init ===
renderAgentsTable();
renderFeedbackTable();
renderStocksTable();
renderArchetypesTable();
renderLeverageTable();
renderAgentEditor();
renderFeedbackEditor();
</script>
</body>
</html>'''


def main():
    parser = argparse.ArgumentParser(description="生成 Harness Blueprint 可视化 HTML")
    parser.add_argument("--analysis-json", help="分析结果 JSON 字符串")
    parser.add_argument("--analysis-file", help="分析结果 JSON 文件路径")
    parser.add_argument("--output", default="/tmp/harness-blueprint.html", help="输出 HTML 路径")
    args = parser.parse_args()

    if args.analysis_file:
        data = json.loads(Path(args.analysis_file).read_text())
    elif args.analysis_json:
        data = json.loads(args.analysis_json)
    else:
        print("请提供 --analysis-json 或 --analysis-file 参数", file=sys.stderr)
        sys.exit(1)

    html_content = build_html(data)
    output_path = Path(args.output)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"✅ 已生成可视化蓝图：{output_path}")
    print(f"   请在浏览器中打开查看")


if __name__ == "__main__":
    main()
