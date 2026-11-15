import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { LunarThermalBin } from '../services/lunarThermal';

// Midpoints locate each supplied 15-minute bin; temperatures and nulls are copied unchanged.
export function lunarChartPoints(rows: LunarThermalBin[]) {
 return rows.map(row => ({ ...row, local_time_hour: (row.local_time_hour_start + row.local_time_hour_end) / 2 }));
}
export default function LunarThermalChart({ rows, label }: { rows: LunarThermalBin[]; label: string }) {
 const points = lunarChartPoints(rows);
 return <figure className="thermal-profile" aria-label={`${label}: mean brightness temperature by local time`}>
  <figcaption><strong>{label}</strong><span>Mean bolometric brightness temperature · K</span></figcaption>
  <div className="thermal-chart">
   <ResponsiveContainer width="100%" height="100%" minWidth={0}>
    <LineChart data={points} margin={{ top: 15, right: 24, bottom: 28, left: 8 }} accessibilityLayer>
     <CartesianGrid stroke="#303d4b" strokeDasharray="3 4" vertical={false}/>
     <XAxis dataKey="local_time_hour" type="number" domain={[0, 24]} ticks={[0, 6, 12, 18, 24]} stroke="#a8bacd" tickLine={false} label={{ value: 'Local time (hours)', position: 'bottom', offset: 8, fill: '#bdcddd' }}/>
     <YAxis stroke="#a8bacd" tickLine={false} width={60} label={{ value: 'Mean tbol (K)', angle: -90, position: 'insideLeft', fill: '#bdcddd' }}/>
     <Tooltip filterNull={false} content={({ active, payload }) => {
      const point = payload?.[0]?.payload as ReturnType<typeof lunarChartPoints>[number] | undefined;
      if (!active || !point) return null;
      return <div className="thermal-tooltip"><strong>Bin {point.local_time_index} · {point.local_time_hour_start}–{point.local_time_hour_end} h</strong><p>{point.mean_tbol_K === null ? 'Unavailable — no valid cells' : `${point.mean_tbol_K} K`}</p><p>{point.grid_cells} valid grid cells</p><small>{point.source_product}</small></div>;
     }}/>
     <Line dataKey="mean_tbol_K" name="Mean tbol" type="linear" stroke="#f18258" strokeWidth={2} dot={{ r: 2, strokeWidth: 0 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false}/>
    </LineChart>
   </ResponsiveContainer>
  </div>
  <p>Points sit at bin midpoints. Hover or use arrow keys to inspect. Lines only connect adjacent available bins; gaps indicate unavailable measurements. No values are interpolated into missing bins. Exact values and provenance are in the expandable table.</p>
 </figure>;
}
