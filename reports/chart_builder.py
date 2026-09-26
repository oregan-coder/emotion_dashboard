"""读取砸盘情绪历史并生成趋势图（可选模块）。"""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from config import DATA_DIR, SMASH_HISTORY_FILE


def build_smash_chart(output=None) -> None:
    if not SMASH_HISTORY_FILE.exists():
        raise FileNotFoundError("尚无 smash_history.csv；请先运行 main.py")
    df = pd.read_csv(SMASH_HISTORY_FILE, dtype={"date": str})
    if df.empty:
        raise ValueError("smash_history.csv 没有可绘制的数据")
    output = output or DATA_DIR / "smash_emotion_trend.png"
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["date"], df["smash_score"], marker="o", color="#d9534f", label="砸盘情绪分数")
    ax.set_ylim(0, 10)
    ax.set_title("砸盘情绪趋势")
    ax.set_xlabel("交易日")
    ax.set_ylabel("分数（0–10）")
    ax.grid(alpha=.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    print(f"图表已保存：{output}")


if __name__ == "__main__":
    build_smash_chart()
