import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Json } from "./types";
import type { Data, Layout } from "plotly.js";
// Plotly runs in a separate lazy chunk; the initial dashboard does not load its full bundle.
export default function Chart({
  id,
  levels,
}: {
  id: string;
  levels: { entry?: number; target?: number; stop?: number };
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    let plot: typeof import("plotly.js-dist-min") | undefined;
    const node = ref.current;
    let observer: ResizeObserver | undefined;
    (async () => {
      try {
        const [data, module] = await Promise.all([
          api<{ bars: Json[] }>("/chart/" + encodeURIComponent(id)),
          import("plotly.js-dist-min"),
        ]);
        if (!active || !node) return;
        plot = module.default;
        const rows = data.bars,
          x = rows.map((r) => r.session);
        const traces: Data[] = [
          {
            type: "candlestick",
            x,
            open: rows.map((r) => r.open),
            high: rows.map((r) => r.high),
            low: rows.map((r) => r.low),
            close: rows.map((r) => r.close),
            name: "완성 일봉",
            increasing: { line: { color: "#53d6aa" } },
            decreasing: { line: { color: "#fa8795" } },
          },
        ];
        for (const [key, color, label] of [
          ["ma5", "#e6b96a", "5일 평균"],
          ["ma20", "#72aaff", "20일 평균"],
          ["ma60", "#b59cff", "60일 평균"],
        ])
          traces.push({
            type: "scatter",
            mode: "lines",
            x,
            y: rows.map((r) => r[key]),
            name: label,
            line: { color, width: 1.6 },
          });
        traces.push({
          type: "bar",
          x,
          y: rows.map((r) => r.volume),
          yaxis: "y2",
          name: "거래량",
          marker: { color: "#536881" },
          showlegend: false,
        });
        traces.push({
          type: "scatter",
          mode: "lines",
          x,
          y: rows.map((r) => r.rsi),
          yaxis: "y3",
          name: "RSI(14)",
          line: { color: "#b59cff", width: 1.5 },
        });
        const layout: Partial<Layout> = {
          paper_bgcolor: "#191d24",
          plot_bgcolor: "#191d24",
          font: { color: "#adb6c5", size: 14, family: "system-ui" },
          margin: { l: 56, r: 20, t: 18, b: 50 },
          height: 490,
          dragmode: "pan",
          legend: { orientation: "h", y: -0.12, font: { size: 14 } },
          xaxis: {
            rangeslider: { visible: false },
            type: "category",
            nticks: 5,
            showgrid: false,
          },
          yaxis: {
            domain: [0.42, 1],
            gridcolor: "#2a323e",
            tickprefix: "$",
            fixedrange: true,
          },
          yaxis2: {
            domain: [0.23, 0.36],
            gridcolor: "#2a323e",
            title: { text: "거래량", font: { size: 14 } },
            fixedrange: true,
          },
          yaxis3: {
            domain: [0, 0.17],
            range: [0, 100],
            tickvals: [30, 70],
            gridcolor: "#2a323e",
            title: { text: "RSI", font: { size: 14 } },
            fixedrange: true,
          },
          shapes: Object.entries(levels)
            .filter(([, v]) => v != null)
            .map(([key, value]) => ({
              type: "line",
              xref: "paper",
              x0: 0,
              x1: 1,
              y0: value,
              y1: value,
              line: {
                color:
                  key === "stop"
                    ? "#fa8795"
                    : key === "target"
                      ? "#53d6aa"
                      : "#72aaff",
                dash: key === "entry" ? "dot" : "dash",
                width: 1,
              },
            })),
        };
        await plot.newPlot(node, traces, layout, {
          responsive: true,
          displayModeBar: false,
          scrollZoom: false,
        });
        observer = new ResizeObserver(() => {
          if (plot && node.isConnected) plot.Plots.resize(node);
        });
        observer.observe(node);
        if (active) setLoading(false);
      } catch (e) {
        if (active) {
          setError((e as Error).message);
          setLoading(false);
        }
      }
    })();
    return () => {
      active = false;
      observer?.disconnect();
      if (plot && node) plot.purge(node);
    };
  }, [id, levels.entry, levels.target, levels.stop]);
  return (
    <div className="chart-wrap">
      <p className="muted">
        완성 일봉 · 캔들 / 이동평균 / 거래량 / RSI · 데모 데이터
      </p>
      {loading && <p role="status">차트를 계산하고 있어요…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div ref={ref} className="chart" aria-label="합성 일봉 캔들 차트" />
      <p className="chart-prices">
        진입·매수 ${levels.entry?.toFixed(2) ?? "—"} · 목표 $
        {levels.target?.toFixed(2) ?? "—"} · 손절 기준 $
        {levels.stop?.toFixed(2) ?? "—"}
      </p>
    </div>
  );
}
