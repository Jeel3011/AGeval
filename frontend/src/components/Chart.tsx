'use client';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

export function TrendChart({ dataPoints }: { dataPoints: { timestamp: string; score: number }[] }) {
  if (!dataPoints.length) {
    return <div style={{display:'flex', alignItems:'center', justifyContent:'center', height:'100%', color:'var(--text-muted)'}}>No trend data available</div>;
  }

  const data = {
    labels: dataPoints.map(d => d.timestamp.slice(0, 10)),
    datasets: [
      {
        label: 'Avg Score',
        data: dataPoints.map(d => d.score),
        borderColor: '#f97316',
        backgroundColor: 'rgba(249,115,22,0.1)',
        fill: true,
        tension: 0.4
      }
    ]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      y: { min: 0, max: 1, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#a1a1aa' } },
      x: { grid: { display: false }, ticks: { color: '#a1a1aa' } }
    }
  };

  return <Line data={data} options={options} />;
}
