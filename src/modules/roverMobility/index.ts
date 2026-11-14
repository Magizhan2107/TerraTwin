import type { ScientificModule, Terrain } from '../../types';
import { rankCandidates } from './scoring';
export const roverMobility: ScientificModule<Terrain> = {
 id: 'roverMobility',
 analyze: rankCandidates,
};
export { rankCandidates, scoreTerrain, FEATURES } from './scoring';
