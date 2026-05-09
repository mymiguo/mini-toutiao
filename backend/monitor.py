"""Daily stock monitor — checks 42 monitored stocks for signal changes.

Usage: python backend/monitor.py
Outputs: data/monitor_report.json (latest signals)
"""
import sys, io, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from backend.engine.indicators import sma, atr, rsi, macd
from backend.engine.regime import detect_regime, Regime
from backend.storage.cleaner import load_cleaned
import akshare as ak
import baostock as bs
from datetime import datetime


def update_data():
    """Download latest data for all monitored stocks."""
    with open("data/monitor_list.json") as f:
        stocks = json.load(f)

    bs.login()
    updated = 0
    for s in stocks:
        try:
            sym = s["code"]
            prefix = "sh." if sym.startswith(("5", "6", "9")) else "sz."
            rs = bs.query_history_k_data_plus(
                prefix + sym, "date,open,high,low,close,volume",
                "2026-01-01", datetime.now().strftime("%Y-%m-%d"), "d", "2"
            )
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if len(rows) < 5:
                continue
            data = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            for col in ["open", "high", "low", "close"]:
                data[col] = pd.to_numeric(data[col], errors="coerce")
            data = data.dropna(subset=["close"])
            if len(data) < 5:
                continue
            # Merge with existing
            existing_path = f"data/cleaned/daily/{sym}.parquet"
            if Path(existing_path).exists():
                old = pd.read_parquet(existing_path)
                data = pd.concat([old, data], ignore_index=True)
                data = data.drop_duplicates(subset=["date"], keep="last")
            data.to_parquet(existing_path, index=False)
            updated += 1
        except Exception:
            pass
    bs.logout()
    print(f"Updated {updated}/{len(stocks)} stocks")


def generate_report():
    """Generate monitoring report for all stocks."""
    with open("data/monitor_list.json") as f:
        stocks = json.load(f)

    # Get names
    info_df = ak.stock_info_a_code_name()
    name_map = dict(zip(info_df["code"], info_df["name"]))

    report = []
    alerts = []

    for s in stocks:
        try:
            sym = s["code"]
            df = load_cleaned(sym)
            if df.empty or len(df) < 50:
                continue
            df = df.sort_values("date")
            c = df["close"]
            h = df["high"]
            l = df["low"]
            v = df["volume"]
            p = float(c.iloc[-1])
            latest_date = str(df["date"].iloc[-1])[:10]

            if len(c) < 200:
                continue

            ma200 = float(sma(c, 200).iloc[-1])
            ma10 = float(sma(c, 10).iloc[-1])
            ma30 = float(sma(c, 30).iloc[-1])
            r = float(rsi(c, 14).iloc[-1])
            a = float(atr(h, l, c, 14).iloc[-1])
            m = macd(c)
            macd_dif = float(m["dif"].iloc[-1])
            macd_dea = float(m["dea"].iloc[-1])

            hist = df.tail(60)
            reg = detect_regime(pd.DataFrame({
                "close": hist["close"].values,
                "high": hist["high"].values,
                "low": hist["low"].values,
            }))

            # Signals
            above_ma200 = p > ma200
            golden = ma10 > ma30
            macd_bull = macd_dif > macd_dea
            rsi_ok = 30 < r < 70

            prev_above = c.iloc[-2] > sma(c, 200).iloc[-2] if len(c) > 1 else False
            prev_golden = sma(c, 10).iloc[-2] > sma(c, 30).iloc[-2] if len(c) > 1 else False

            # Alert if signal changed
            if above_ma200 != prev_above:
                alerts.append(f"{sym} {s['name']}: MA200 {'BREAKOUT ↑' if above_ma200 else 'BREAKDOWN ↓'}")
            if golden != prev_golden:
                alerts.append(f"{sym} {s['name']}: MA {'GOLDEN ↑' if golden else 'DEAD ↓'}")

            # Current signal
            if above_ma200 and golden:
                signal = "BUY"
            elif above_ma200:
                signal = "HOLD"
            else:
                signal = "CASH"

            report.append({
                "code": sym,
                "name": s["name"],
                "sector": s["sector"],
                "date": latest_date,
                "price": round(p, 2),
                "ma200": round(ma200, 2),
                "strength": round((p - ma200) / ma200, 4),
                "ma10_30": "GOLD" if golden else "DEAD",
                "rsi": round(r, 0),
                "macd": "BULL" if macd_bull else "BEAR",
                "atr": round(a, 2),
                "regime": reg.regime.value,
                "signal": signal,
            })
        except Exception:
            pass

    with open("data/monitor_report.json", "w") as f:
        json.dump({"generated": datetime.now().isoformat(), "alerts": alerts, "stocks": report}, f, ensure_ascii=False)

    print(f"Report: {len(report)} stocks, {len(alerts)} alerts")
    return report, alerts


def send_email(report, alerts, sim_summary=None, your_portfolio=None):
    """Send monitoring report via 163.com SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    today = datetime.now().strftime("%Y-%m-%d")
    buys = [r for r in report if r["signal"] == "BUY"]

    html = f"""<html><head><meta charset='utf-8'>
    <style>
    body{{font-family:'Microsoft YaHei',Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;background:#f5f6fa;color:#2c3e50}}
    .header{{background:linear-gradient(135deg,#1a5276,#2980b9);color:#fff;padding:25px;border-radius:12px;margin-bottom:20px}}
    .header h1{{margin:0 0 8px 0;font-size:24px}}
    .header p{{margin:0;opacity:0.9;font-size:14px}}
    .card{{background:#fff;border-radius:10px;padding:20px;margin-bottom:18px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
    .card h2{{margin:0 0 14px 0;font-size:18px;color:#1a5276;border-bottom:2px solid #3498db;padding-bottom:8px}}
    .badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:bold}}
    .badge-buy{{background:#27ae60;color:#fff}}
    .badge-cash{{background:#e74c3c;color:#fff}}
    .badge-hold{{background:#f39c12;color:#fff}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th{{background:#34495e;color:#fff;padding:8px 6px;text-align:center;font-weight:normal}}
    td{{padding:6px;text-align:center;border-bottom:1px solid #ecf0f1}}
    tr:hover{{background:#f8f9fa}}
    .up{{color:#27ae60;font-weight:bold}}
    .down{{color:#e74c3c;font-weight:bold}}
    .alert{{background:#ffeaa7;border-left:4px solid #fdcb6e;padding:10px 14px;margin:8px 0;border-radius:4px}}
    .advice{{background:#dfe6e9;border-radius:8px;padding:14px;margin:10px 0;font-size:14px;line-height:1.8}}
    .footer{{text-align:center;color:#95a5a6;font-size:11px;margin-top:20px}}
    </style></head><body>
    <div class='header'>
    <h1>A股量化策略日报</h1>
    <p>{today} | 监控 {len(report)} 只 | BUY信号 {len(buys)} 只</p>
    </div>
    """

    # ── Alerts ──
    if alerts:
        html += "<div class='card'><h2>信号异动</h2>"
        for a in alerts:
            html += f"<div class='alert'><b>{a}</b></div>"
        html += "</div>"

    # ── Simulated Portfolio ──
    if sim_summary:
        ret_class = "up" if sim_summary["total_return"] > 0 else "down"
        html += f"""<div class='card'>
        <h2>我的模拟持仓 <span style='font-size:13px;color:#7f8c8d'>(10万, {sim_summary['start_date']} 起投)</span></h2>
        <table><tr><th>代码</th><th>名称</th><th>板块</th><th>买入价</th><th>现价</th><th>数量</th><th>市值</th><th>盈亏</th></tr>"""
        for p in sim_summary["positions"]:
            c = "up" if p["pnl"] > 0 else "down"
            html += f"""<tr><td>{p['symbol']}</td><td>{p['name']}</td><td>{p['sector']}</td>
            <td>{p['entry_price']:.2f}</td><td>{p['current_price']:.2f}</td><td>{p['shares']}</td>
            <td>{p['value']:,.0f}</td><td class='{c}'>{p['pnl']:+,.0f} ({p['pnl_pct']:+.1%})</td></tr>"""
        html += f"""<tr style='font-weight:bold;background:#f0f3f5'>
        <td colspan='6'>投资回报</td><td>{sim_summary['current_value']:,.0f}</td>
        <td class='{ret_class}'>{sim_summary['total_return']:+.1%}</td></tr></table></div>"""

    # ── User Portfolio ──
    if your_portfolio:
        utotal_val = sum(p.get('value',0) for p in your_portfolio)
        utotal_pnl = sum(p.get('pnl',0) for p in your_portfolio)
        utotal_cost = sum(p['cost']*p['shares'] for p in your_portfolio)
        u_ret = utotal_pnl / utotal_cost if utotal_cost > 0 else 0
        uclass = "up" if u_ret > 0 else "down"
        html += f"""<div class='card'>
        <h2>你的持仓 <span style='font-size:13px;color:#7f8c8d'>(本金约{utotal_cost:,.0f})</span></h2>
        <table><tr><th>代码</th><th>名称</th><th>成本</th><th>现价</th><th>数量</th><th>市值</th><th>盈亏</th><th>信号</th><th>建议</th></tr>"""
        for p in your_portfolio:
            c = "up" if p.get("pnl",0) > 0 else "down"
            sig_badge = "buy" if p.get("signal")=="BUY" else "cash"
            html += f"""<tr><td>{p['code']}</td><td>{p['name']}</td><td>{p['cost']:.2f}</td>
            <td>{p['price']:.2f}</td><td>{p['shares']}</td><td>{p['value']:,.0f}</td>
            <td class='{c}'>{p['pnl']:+,.0f} ({p['pnl_pct']:+.1%})</td>
            <td><span class='badge badge-{sig_badge}'>{p.get('signal','-')}</span></td>
            <td>{p.get('advice','-')}</td></tr>"""
        html += f"""<tr style='font-weight:bold;background:#f0f3f5'>
        <td colspan='5'>合计</td><td>{utotal_val:,.0f}</td>
        <td class='{uclass}'>{utotal_pnl:+,.0f} ({u_ret:+.1%})</td><td colspan='2'></td></tr></table></div>"""

    # ── Recommendations ──
    html += f"""<div class='card'>
    <h2>今日策略建议</h2>
    <div class='advice'>
    <b>大盘:</b> {"BULL 做多区间" if any(r.get('strength',0)>0 for r in report) else "等待确认"}<br>
    <b>最强板块:</b> AI芯片(12只) | 有色金属(6只) | 金融(3只)<br>
    <b>推荐组合:</b> 中际旭创30% + 紫金矿业20% + 海光信息20% + 中信证券15% + 高德红外15%<br>
    </div></div>"""

    # ── BUY signals ──
    html += "<div class='card'><h2>全部BUY信号 (按板块)</h2>"
    sectors = {}
    for r in report:
        sectors.setdefault(r["sector"], []).append(r)
    for sector, stocks in sorted(sectors.items()):
        if len(stocks) <= 2:
            # Small sectors: compact
            for s in stocks:
                html += f"<span style='margin:4px'><span class='badge badge-buy'>BUY</span> <b>{s['code']}</b> {s['name']} {s['price']} <span class='up'>{s['strength']:+.0%}</span></span>  "
        else:
            html += f"<h4 style='margin:10px 0 4px 0'>{sector} ({len(stocks)}只)</h4>"
            html += "<table><tr><th>代码</th><th>名称</th><th>现价</th><th>MA200</th><th>强度</th><th>RSI</th><th>MACD</th><th>状态</th></tr>"
            for s in sorted(stocks, key=lambda x: x["strength"], reverse=True)[:8]:
                html += f"""<tr><td>{s['code']}</td><td>{s['name']}</td><td>{s['price']}</td><td>{s['ma200']}</td>
                <td class='up'>{s['strength']:+.1%}</td><td>{s['rsi']:.0f}</td>
                <td><span class='badge {"badge-buy" if s["macd"]=="BULL" else "badge-cash"}'>{s['macd']}</span></td>
                <td>{s['regime']}</td></tr>"""
            html += "</table>"
    html += "</div>"

    html += """<div class='footer'>
    <p>本报告由量化策略框架自动生成。历史回测不代表未来收益。投资有风险，决策须自主。</p>
    <p>策略: MA10/30金叉 + MA200趋势确认 | 数据源: BaoStock | Walk-Forward验证 OOS 2023-2025</p>
    </div></body></html>"""

    msg = MIMEMultipart()
    msg["From"] = "gbaobao@163.com"
    msg["To"] = "gbaobao@163.com"
    msg["Subject"] = f"A股策略日报 {today} | BUY:{len(buys)}只"
    if sim_summary:
        ret_str = f"+{sim_summary['total_return']:.1%}" if sim_summary['total_return'] > 0 else f"{sim_summary['total_return']:.1%}"
        msg["Subject"] += f" | 模拟: {ret_str}"
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL("smtp.163.com", 465)
        server.login("gbaobao@163.com", "TEhF2gtv8wmScuV9")
        server.sendmail("gbaobao@163.com", ["gbaobao@163.com"], msg.as_string())
        server.quit()
        print("Email sent successfully!")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


if __name__ == "__main__":
    from backend.sim_portfolio import SimPortfolio

    print(f"=== Monitor {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    update_data()
    report, alerts = generate_report()

    # ── Simulated Portfolio ──
    with open("data/monitor_list.json") as f:
        candidates = [(s["code"], s["name"], s["sector"]) for s in json.load(f)]

    sim = SimPortfolio(capital=100000, start_date="2026-04-08")
    selected = sim.select_positions(candidates, top_n=5)
    sim.execute_buys(selected)
    sim.track()
    sim_summary = sim.summary()

    print(f"\n[Sim Portfolio] {sim.start_date} ~ {sim_summary['end_date']}:")
    print(f"   Return: {sim_summary['total_return']:+.2%}  MaxDD: {sim_summary['max_drawdown']:.1%}")
    for p in sim_summary["positions"]:
        print(f"   {p['symbol']} {p['name']}: {p['entry_price']:.2f} -> {p['current_price']:.2f}  PnL={p['pnl']:+,.0f} ({p['pnl_pct']:+.1%})")

    # ── User Portfolio ──
    from backend.storage.cleaner import load_cleaned
    your_portfolio = [
        {"code": "002915", "name": "中欣氟材", "cost": 25.256, "shares": 1500, "signal": "CASH", "advice": "考虑换到BUY信号股"},
        {"code": "000768", "name": "中航西飞", "cost": 30.740, "shares": 500, "signal": "CASH", "advice": "考虑换到BUY信号股"},
        {"code": "603690", "name": "至纯科技", "cost": 28.680, "shares": 2500, "signal": "CASH", "advice": "盯MA200(28.33)，站上可留"},
        {"code": "600497", "name": "驰宏锌锗", "cost": 9.420, "shares": 1000, "signal": "BUY", "advice": "继续持有，评分7/7"},
    ]
    for p in your_portfolio:
        try:
            df = load_cleaned(p["code"])
            if not df.empty:
                p["price"] = float(df.sort_values("date")["close"].iloc[-1])
                p["value"] = p["price"] * p["shares"]
                p["pnl"] = p["value"] - p["cost"] * p["shares"]
                p["pnl_pct"] = (p["price"] - p["cost"]) / p["cost"]
        except:
            p["price"] = 0; p["value"] = 0; p["pnl"] = 0; p["pnl_pct"] = 0

    total_val = sum(p.get("value", 0) for p in your_portfolio)
    total_pnl = sum(p.get("pnl", 0) for p in your_portfolio)
    total_cost = sum(p["cost"] * p["shares"] for p in your_portfolio)
    print(f"\n[Your Portfolio] Value={total_val:,.0f} PnL={total_pnl:+,.0f} ({(total_val-total_cost)/total_cost:+.1%})")

    # ── Send ──
    send_email(report, alerts, sim_summary, your_portfolio)
