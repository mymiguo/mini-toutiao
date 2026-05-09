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


def send_email(report, alerts):
    """Send monitoring report via 163.com SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    today = datetime.now().strftime("%Y-%m-%d")

    # Build HTML table
    buys = [r for r in report if r["signal"] == "BUY"]
    holds = [r for r in report if r["signal"] == "HOLD"]
    cashes = [r for r in report if r["signal"] == "CASH"]

    html = f"""
    <h2>📊 A股策略监控报告 — {today}</h2>
    <p>BUY: {len(buys)} | HOLD: {len(holds)} | CASH: {len(cashes)}</p>
    """

    if alerts:
        html += "<h3>⚠️ 信号异动</h3><ul>"
        for a in alerts:
            html += f"<li>{a}</li>"
        html += "</ul>"

    # Group by sector
    sectors = {}
    for r in report:
        sectors.setdefault(r["sector"], []).append(r)

    for sector, stocks in sorted(sectors.items()):
        html += f"<h4>{sector}</h4>"
        html += """<table border='1' cellpadding='4' cellspacing='0' style='border-collapse:collapse;font-size:12px'>
        <tr style='background:#333;color:#fff'><th>代码</th><th>名称</th><th>现价</th><th>MA200</th><th>强度</th><th>RSI</th><th>MACD</th><th>状态</th><th>信号</th></tr>"""
        for s in sorted(stocks, key=lambda x: x["strength"], reverse=True):
            bg = "#e8f5e9" if s["signal"] == "BUY" else ("#fff3e0" if s["signal"] == "HOLD" else "#ffebee")
            html += f"""<tr style='background:{bg}'>
            <td>{s['code']}</td><td>{s['name']}</td><td>{s['price']}</td><td>{s['ma200']}</td>
            <td>{s['strength']:+.1%}</td><td>{s['rsi']:.0f}</td><td>{s['macd']}</td>
            <td>{s['regime']}</td><td><b>{s['signal']}</b></td></tr>"""
        html += "</table><br>"

    msg = MIMEMultipart()
    msg["From"] = "gbaobao@163.com"
    msg["To"] = "gbaobao@163.com"
    msg["Subject"] = f"📊 A股策略监控报告 — {today} ({len(buys)} BUY)"
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
    print(f"=== Monitor {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    update_data()
    report, alerts = generate_report()

    if alerts:
        print("\n⚠️  ALERTS:")
        for a in alerts:
            print(f"  {a}")

    buys = [r for r in report if r["signal"] == "BUY"]
    holds = [r for r in report if r["signal"] == "HOLD"]
    cashes = [r for r in report if r["signal"] == "CASH"]
    print(f"\nBUY: {len(buys)} | HOLD: {len(holds)} | CASH: {len(cashes)}")

    send_email(report, alerts)
