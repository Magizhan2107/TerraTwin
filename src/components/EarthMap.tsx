import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import { useEffect, useMemo, useRef } from 'react';
import type { LatLngTuple } from 'leaflet';
import type { AnalysisResult } from '../types';
// Cut the longitude circle at its largest empty gap so Date Line neighbors stay together.
function mapCandidates(results: AnalysisResult[]) {
 const longitudes = results.map(r => r.coordinates.longitude).sort((a, b) => a - b);
 let west = longitudes[0] ?? 0;
 let largestGap = -1;
 longitudes.forEach((longitude, i) => {
  const next = longitudes[(i + 1) % longitudes.length];
  const gap = next + (i === longitudes.length - 1 ? 360 : 0) - longitude;
  if (gap > largestGap) { largestGap = gap; west = next; }
 });
 // Keep the fitted center in the conventional world while allowing unwrapped markers.
 const offset = west + (360 - largestGap) / 2 > 180 ? 360 : 0;
 return results.map(result => ({
  result,
  position: [result.coordinates.latitude, result.coordinates.longitude + (result.coordinates.longitude < west ? 360 : 0) - offset] as LatLngTuple,
 }));
}
function Focus({ candidates, selected }: { candidates: ReturnType<typeof mapCandidates>; selected?: AnalysisResult }) {
 const map = useMap();
 useEffect(() => {
  let frame = 0;
  const observer = new ResizeObserver(() => {
   cancelAnimationFrame(frame);
   frame = requestAnimationFrame(() => map.invalidateSize({ pan: false }));
  });
  observer.observe(map.getContainer());
  return () => { observer.disconnect(); cancelAnimationFrame(frame); };
 }, [map]);
 const previous = useRef<{ candidates: typeof candidates; selectedId?: string } | null>(null);
 useEffect(() => {
  if (previous.current?.candidates !== candidates) {
   if (candidates.length) map.fitBounds(candidates.map(c => c.position), { padding: [32, 48], maxZoom: 4, animate: false });
  } else if (previous.current.selectedId !== selected?.earthCandidateId) {
   const candidate = candidates.find(c => c.result.earthCandidateId === selected?.earthCandidateId);
   if (candidate) map.flyTo(candidate.position, Math.min(map.getZoom(), 4), { duration: 0.8 });
  }
  previous.current = { candidates, selectedId: selected?.earthCandidateId };
 }, [candidates, selected, map]);
 return null;
}
export default function EarthMap({ results, selected, onSelect }: { results: AnalysisResult[]; selected?: AnalysisResult; onSelect: (id: string) => void }) {
 const candidates = useMemo(() => mapCandidates(results), [results]);
 return <MapContainer center={[24, 10]} zoom={2} minZoom={0} maxZoom={19} scrollWheelZoom={false} className="earth-map" aria-label="Earth analogue candidate map"><TileLayer attribution="© OpenStreetMap contributors" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={19} /><Focus candidates={candidates} selected={selected} />{candidates.map(({ result: r, position }) => <CircleMarker key={r.earthCandidateId} center={position} radius={selected?.earthCandidateId === r.earthCandidateId ? 10 : 6} pathOptions={{ color: selected?.earthCandidateId === r.earthCandidateId ? '#ff895c' : '#56d9d0', fillOpacity: .8, weight: 2 }} eventHandlers={{ click: () => onSelect(r.earthCandidateId) }}><Popup><strong>{r.name}</strong><br/>{r.similarityScore.toFixed(1)}% preliminary terrain index</Popup></CircleMarker>)}</MapContainer>;
}
